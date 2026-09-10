"""Transactional canonical links. Legacy proposals never enter automatically."""

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb

from klegal_gold.domain.identity import (
    CanonicalCaseIdentity,
    CaseMetadata,
    CourtCaseKey,
    DecisionKey,
    IdentityLinkEvent,
    SourceCaseIdentifier,
)
from klegal_gold.identity.allocation import canonical_id_for_request
from klegal_gold.normalize.decision import decision_keys

from .session import Database

REGISTRY_LOCK = 72834002


class Registry:
    def __init__(self, db: Database) -> None:
        self.db = db

    def apply(self, event: IdentityLinkEvent) -> None:
        with self.db.connect() as conn:
            self._apply(conn, event)

    def _apply(self, conn: Connection[dict[str, Any]], event: IdentityLinkEvent) -> None:
        payload = event.model_dump(mode="json")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (REGISTRY_LOCK,))
        prior_event = conn.execute(
            "SELECT payload FROM identity_events WHERE event_id=%s", (event.event_id,)
        ).fetchone()
        if prior_event:
            if prior_event["payload"] != payload:
                raise ValueError("IDENTITY_EVENT_CONFLICT")
            return
        for previous in event.previous:
            current = conn.execute(
                """SELECT r.payload,d.active FROM documents d JOIN document_revisions r
                   ON r.canonical_id=d.canonical_id AND r.revision=d.current_revision
                   WHERE d.canonical_id=%s""",
                (previous.canonical_id,),
            ).fetchone()
            if (
                current is None
                or not current["active"]
                or (current["payload"] != previous.model_dump(mode="json"))
            ):
                raise ValueError("STALE_IDENTITY_REVISION")
        old_ids = {p.canonical_id for p in event.previous}
        resulting_keys = [
            key
            for result in event.resulting
            for key in decision_keys(result.metadata, result.court_case_keys)
        ]
        if len(set(resulting_keys)) != len(resulting_keys):
            raise ValueError("DUPLICATE_RESULTING_DECISION_KEY")
        for key in resulting_keys:
            linked = conn.execute(
                "SELECT canonical_id FROM active_decision_keys "
                "WHERE court=%s AND case_number=%s AND decision_kind=%s",
                (key.court, key.case_number, key.decision_kind),
            ).fetchone()
            if linked and linked["canonical_id"] not in old_ids:
                raise ValueError("DECISION_KEY_ALREADY_LINKED")
        for result in event.resulting:
            if (
                result.canonical_id not in old_ids
                and conn.execute(
                    "SELECT 1 FROM documents WHERE canonical_id=%s", (result.canonical_id,)
                ).fetchone()
            ):
                raise ValueError("CANONICAL_ID_ALREADY_ALLOCATED")
        all_sources = [i for r in event.resulting for i in r.source_identifiers]
        if len(set(all_sources)) != len(all_sources):
            raise ValueError("DUPLICATE_RESULTING_SOURCE")
        conn.execute(
            "INSERT INTO identity_events(event_id,payload) VALUES(%s,%s)",
            (event.event_id, Jsonb(payload)),
        )
        for previous in event.previous:
            conn.execute(
                "DELETE FROM active_decision_keys WHERE canonical_id=%s",
                (previous.canonical_id,),
            )
            conn.execute(
                "DELETE FROM active_source_links WHERE canonical_id=%s",
                (previous.canonical_id,),
            )
            conn.execute(
                "UPDATE documents SET active=false WHERE canonical_id=%s",
                (previous.canonical_id,),
            )
        for result in event.resulting:
            conn.execute(
                """INSERT INTO documents(canonical_id,current_revision) VALUES(%s,%s)
                   ON CONFLICT(canonical_id) DO UPDATE
                   SET current_revision=EXCLUDED.current_revision,active=true""",
                (result.canonical_id, result.link_revision),
            )
            conn.execute(
                "INSERT INTO document_revisions VALUES(%s,%s,%s,%s)",
                (
                    result.canonical_id,
                    result.link_revision,
                    event.event_id,
                    Jsonb(result.model_dump(mode="json")),
                ),
            )
            for case_key in result.court_case_keys:
                conn.execute(
                    "INSERT INTO case_keys(court,case_number) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (case_key.court, case_key.case_number),
                )
                conn.execute(
                    """INSERT INTO document_case_keys
                       SELECT %s,%s,key_id FROM case_keys WHERE court=%s AND case_number=%s""",
                    (
                        result.canonical_id,
                        result.link_revision,
                        case_key.court,
                        case_key.case_number,
                    ),
                )
            for key in decision_keys(result.metadata, result.court_case_keys):
                conn.execute(
                    "INSERT INTO active_decision_keys VALUES(%s,%s,%s,%s,%s)",
                    (
                        key.court,
                        key.case_number,
                        key.decision_kind,
                        result.canonical_id,
                        result.link_revision,
                    ),
                )
            for identifier in result.source_identifiers:
                conn.execute(
                    "INSERT INTO active_source_links VALUES(%s,%s,%s,%s)",
                    (
                        identifier.source,
                        identifier.source_id,
                        result.canonical_id,
                        result.link_revision,
                    ),
                )

    def register(
        self,
        request_key: str,
        *,
        metadata: CaseMetadata,
        court_case_keys: tuple[CourtCaseKey, ...],
        source_identifiers: tuple[SourceCaseIdentifier, ...],
        actor: str,
        reason: str,
    ) -> CanonicalCaseIdentity:
        """Register an explicitly verified document; never auto-merge a matching key.

        Retries return the original registration revision, even after later relinking.
        For legacy imports request_key is the preservation_id. Missing keys remain staging.
        """
        proposed = CanonicalCaseIdentity(
            canonical_id=canonical_id_for_request(request_key),
            link_revision=1,
            metadata=metadata,
            court_case_keys=court_case_keys,
            source_identifiers=source_identifiers,
        )
        if not decision_keys(metadata, court_case_keys):
            raise ValueError("INCOMPLETE_DECISION_KEY")
        event_id = uuid5(NAMESPACE_URL, "korcounsel:registration:" + request_key)
        with self.db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (REGISTRY_LOCK,))
            previous = conn.execute(
                "SELECT payload FROM identity_events WHERE event_id=%s", (event_id,)
            ).fetchone()
            if previous:
                saved = IdentityLinkEvent.model_validate(previous["payload"])
                if saved.resulting != (proposed,) or saved.actor != actor or saved.reason != reason:
                    raise ValueError("IDENTITY_REQUEST_CONFLICT")
                return saved.resulting[0]
            self._apply(
                conn,
                IdentityLinkEvent(
                    event_id=event_id,
                    operation="CREATE",
                    resulting=(proposed,),
                    recorded_at=datetime.now(UTC),
                    actor=actor,
                    reason=reason,
                ),
            )
        return proposed

    def find_decision(self, key: DecisionKey) -> CanonicalCaseIdentity | None:
        """Find the active internal identity; a match does not authorize relinking."""
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT r.payload FROM active_decision_keys k
                   JOIN document_revisions r
                     ON (r.canonical_id,r.revision)=(k.canonical_id,k.revision)
                   WHERE k.court=%s AND k.case_number=%s AND k.decision_kind=%s""",
                (key.court, key.case_number, key.decision_kind),
            ).fetchone()
        return CanonicalCaseIdentity.model_validate(row["payload"]) if row else None

    def get(self, canonical_id: str, revision: int | None = None) -> CanonicalCaseIdentity:
        with self.db.connect() as conn:
            if revision is None:
                row = conn.execute(
                    """SELECT r.payload FROM documents d JOIN document_revisions r
                       ON r.canonical_id=d.canonical_id AND r.revision=d.current_revision
                       WHERE d.canonical_id=%s AND d.active""",
                    (canonical_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT payload FROM document_revisions WHERE canonical_id=%s AND revision=%s",
                    (canonical_id, revision),
                ).fetchone()
        if row is None:
            raise ValueError("DOCUMENT_NOT_FOUND")
        return CanonicalCaseIdentity.model_validate(row["payload"])

    def snapshot(self) -> dict[str, Any]:
        # Events are ordered by DB insertion order below using the explicit sequence in schema.
        with self.db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (REGISTRY_LOCK,))
            events = conn.execute(
                "SELECT payload FROM identity_events ORDER BY sequence"
            ).fetchall()
        return {"format": "registry-events-1", "events": [r["payload"] for r in events]}

    def restore(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("format") != "registry-events-1" or not isinstance(
            snapshot.get("events"), list
        ):
            raise ValueError("INVALID_REGISTRY_SNAPSHOT")
        events = [IdentityLinkEvent.model_validate(value) for value in snapshot["events"]]
        ids: set[UUID] = set()
        for event in events:
            if event.event_id in ids:
                raise ValueError("DUPLICATE_REGISTRY_EVENT")
            ids.add(event.event_id)
        existing = self.snapshot()["events"]
        if existing != snapshot["events"][: len(existing)]:
            raise ValueError("REGISTRY_RESTORE_PREFIX_MISMATCH")
        for event in events:
            self.apply(event)  # Restartable: already identical events are reused.
