"""Transactional canonical links. Legacy proposals never enter automatically."""

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from klegal_gold.domain.identity import CanonicalCaseIdentity, IdentityLinkEvent

from .session import Database

REGISTRY_LOCK = 72834002


class Registry:
    def __init__(self, db: Database) -> None:
        self.db = db

    def apply(self, event: IdentityLinkEvent) -> None:
        payload = event.model_dump(mode="json")
        with self.db.connect() as conn:
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
                for key in result.court_case_keys:
                    conn.execute(
                        "INSERT INTO case_keys(court,case_number) VALUES(%s,%s)"
                        " ON CONFLICT DO NOTHING",
                        (key.court, key.case_number),
                    )
                    conn.execute(
                        """INSERT INTO document_case_keys
                           SELECT %s,%s,key_id FROM case_keys WHERE court=%s AND case_number=%s""",
                        (result.canonical_id, result.link_revision, key.court, key.case_number),
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
