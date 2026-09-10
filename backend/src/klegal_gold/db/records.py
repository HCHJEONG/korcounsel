"""Persistence of immutable records and rebuildable projections."""

import json
from collections.abc import Callable
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg.types.json import Jsonb

from klegal_gold.domain.cases import RawLegalCase
from klegal_gold.domain.common import content_hash
from klegal_gold.domain.inventory import InventorySnapshot
from klegal_gold.domain.legacy import LegacyCaseRecord
from klegal_gold.ingestion.legacy import legacy_content_revision
from klegal_gold.storage.files import Blob, FileStore

from .session import Connection, Database


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


class Records:
    def __init__(self, db: Database, store: FileStore) -> None:
        self.db, self.store = db, store

    def _artifact(
        self,
        conn: Connection,
        artifact_id: str,
        raw: bytes,
        origin: str,
        metadata: dict[str, Any],
        parent_id: str | None = None,
    ) -> Blob:
        blob = self.store.put(raw)
        conn.execute(
            """INSERT INTO blobs(sha256,storage_key,size_bytes) VALUES(%s,%s,%s)
               ON CONFLICT DO NOTHING""",
            (blob.sha256, blob.storage_key, blob.size_bytes),
        )
        saved = conn.execute("SELECT * FROM blobs WHERE sha256=%s", (blob.sha256,)).fetchone()
        if saved is None or (saved["storage_key"], saved["size_bytes"]) != (
            blob.storage_key,
            blob.size_bytes,
        ):
            raise ValueError("BLOB_REGISTRY_CONFLICT")
        conn.execute(
            """INSERT INTO artifacts(artifact_id,blob_hash,origin,parent_id,metadata)
               VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (artifact_id, blob.sha256, origin, parent_id, Jsonb(metadata)),
        )
        existing = conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id=%s", (artifact_id,)
        ).fetchone()
        if existing is None or (
            existing["blob_hash"],
            existing["origin"],
            existing["parent_id"],
            existing["metadata"],
        ) != (blob.sha256, origin, parent_id, metadata):
            raise ValueError("IMMUTABLE_ARTIFACT_CONFLICT")
        return blob

    def put_artifact(
        self,
        artifact_id: str,
        raw: bytes,
        *,
        origin: str,
        metadata: dict[str, Any],
        parent_id: str | None = None,
    ) -> Blob:
        with self.db.connect() as conn:
            return self._artifact(conn, artifact_id, raw, origin, metadata, parent_id)

    def blob(self, artifact_id: str) -> Blob:
        with self.db.connect() as conn:
            result = conn.execute(
                """SELECT b.* FROM blobs b JOIN artifacts a ON a.blob_hash=b.sha256
                   WHERE a.artifact_id=%s""",
                (artifact_id,),
            ).fetchone()
        if result is None:
            raise ValueError("ARTIFACT_NOT_FOUND")
        return Blob(result["sha256"], result["storage_key"], result["size_bytes"])

    def read(self, artifact_id: str) -> bytes:
        blob = self.blob(artifact_id)
        self.store.verify(blob)
        raw = self.store.path(blob.storage_key).read_bytes()
        if content_hash(raw) != blob.sha256:
            raise ValueError("BLOB_INTEGRITY_FAILED")
        return raw

    @staticmethod
    def _project(conn: Connection, record: LegacyCaseRecord, revision: str) -> None:
        conn.execute(
            """INSERT INTO case_projection
               (preservation_id,content_revision,court,case_numbers,decision_date,body_state)
               VALUES(%s,%s,%s,%s,%s,%s)
               ON CONFLICT(preservation_id,content_revision) DO UPDATE SET
               court=EXCLUDED.court,case_numbers=EXCLUDED.case_numbers,
               decision_date=EXCLUDED.decision_date,body_state=EXCLUDED.body_state""",
            (
                record.preservation_id,
                revision,
                record.metadata.court,
                Jsonb(list(record.metadata.case_numbers)),
                record.metadata.decision_date,
                record.body_state,
            ),
        )

    def save_legacy(
        self,
        record: LegacyCaseRecord,
        *,
        run_id: str,
        status: Literal["PRESERVED", "QUARANTINED"] = "PRESERVED",
    ) -> str:
        revision = legacy_content_revision(record)
        artifact_id = f"legacy:{revision}"
        locator = record.original.locator
        attempt_id = uuid5(
            NAMESPACE_URL, _json([run_id, record.preservation_id, revision]).decode()
        )
        with self.db.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (record.preservation_id,)
            )
            existing = conn.execute(
                """SELECT artifact_id FROM legacy_records
                   WHERE preservation_id=%s AND content_revision=%s""",
                (record.preservation_id, revision),
            ).fetchone()
            if existing is None:
                self._artifact(
                    conn,
                    artifact_id,
                    record.model_dump_json().encode(),
                    "LEGACY_ARCHIVE",
                    {"content_revision": revision},
                )
                conn.execute(
                    """INSERT INTO legacy_records VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        record.preservation_id,
                        revision,
                        locator.snapshot_sha256,
                        locator.position,
                        locator.original_index,
                        record.original.coverage,
                        artifact_id,
                    ),
                )
            else:
                artifact_id = existing["artifact_id"]
                self.store.verify(self.blob(artifact_id))
            conn.execute(
                """INSERT INTO legacy_import_attempts
                   (attempt_id,run_id,preservation_id,content_revision,status,reasons)
                   VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    attempt_id,
                    run_id,
                    record.preservation_id,
                    revision,
                    status,
                    Jsonb(list(record.reasons)),
                ),
            )
            attempt = conn.execute(
                "SELECT status,reasons FROM legacy_import_attempts WHERE attempt_id=%s",
                (attempt_id,),
            ).fetchone()
            if attempt is None or (attempt["status"], attempt["reasons"]) != (
                status,
                list(record.reasons),
            ):
                raise ValueError("IMPORT_REQUEST_CONFLICT")
            self._project(conn, record, revision)
        # Also check reused artifacts; absence/corruption must never be called success.
        self.store.verify(self.blob(artifact_id))
        return artifact_id

    def rebuild_projection(
        self,
        *,
        job_id: UUID | None = None,
        after_key: str = "",
        progress: Callable[[str, int], None] | None = None,
    ) -> int:
        # Bounded keyset scan; every row reads and validates its immutable artifact.
        last = after_key
        count = 0
        while True:
            with self.db.connect() as conn:
                if job_id is None:
                    rows = conn.execute(
                        """SELECT artifact_id,content_revision FROM legacy_records
                           WHERE artifact_id>%s ORDER BY artifact_id LIMIT 100""",
                        (last,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT artifact_id,content_revision FROM projection_rebuild_inputs
                           WHERE job_id=%s AND artifact_id>%s
                           ORDER BY artifact_id LIMIT 100""",
                        (job_id, last),
                    ).fetchall()
            if not rows:
                return count
            for item in rows:
                record = LegacyCaseRecord.model_validate_json(self.read(item["artifact_id"]))
                if legacy_content_revision(record) != item["content_revision"]:
                    raise ValueError("LEGACY_REVISION_MISMATCH")
                with self.db.connect() as conn:
                    self._project(conn, record, item["content_revision"])
                last = item["artifact_id"]
                count += 1
                if progress is not None:
                    progress(last, count)

    def save_inventory(self, snapshot: InventorySnapshot) -> str:
        artifact_id = "inventory:" + snapshot.snapshot_id
        with self.db.connect() as conn:
            self._artifact(conn, artifact_id, snapshot.model_dump_json().encode(), "MANIFEST", {})
            conn.execute(
                "INSERT INTO inventories VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    snapshot.snapshot_id,
                    snapshot.source,
                    snapshot.scope_hash,
                    snapshot.completeness,
                    artifact_id,
                ),
            )
        return artifact_id

    def save_manifest(self, manifest_id: str, kind: str, payload: dict[str, Any]) -> str:
        artifact_id = "manifest:" + manifest_id
        with self.db.connect() as conn:
            self._artifact(conn, artifact_id, _json(payload), "MANIFEST", {"kind": kind})
            conn.execute(
                "INSERT INTO manifests(manifest_id,kind,artifact_id) VALUES(%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                (manifest_id, kind, artifact_id),
            )
        return artifact_id

    def save_raw(self, model: RawLegalCase, raw: bytes, *, receipt_id: UUID) -> str:
        """Preserve one HTTP content version and a separate acquisition receipt."""
        artifact = model.raw_artifact
        digest = content_hash(raw)
        expected_key = f"blobs/{digest[:2]}/{digest}"
        if (artifact.sha256, artifact.file_size, artifact.storage_path) != (
            digest,
            len(raw),
            expected_key,
        ):
            raise ValueError("RAW_BYTES_MISMATCH")
        version = model.source_version
        if artifact.parent_artifact_id is not None:
            raise ValueError("RAW_RESPONSE_HAS_PARENT")
        if (model.provenance.source_url, model.provenance.retrieved_at) != (
            artifact.source_url,
            artifact.retrieved_at,
        ):
            raise ValueError("RAW_RECEIPT_MISMATCH")
        receipt_artifact = f"receipt:{receipt_id}"
        with self.db.connect() as conn:
            self._artifact(
                conn,
                artifact.artifact_id,
                raw,
                "HTTP_RESPONSE",
                {"source_version": version.model_dump(mode="json")},
            )
            conn.execute(
                """INSERT INTO source_versions(source,source_id,raw_content_hash,artifact_id)
                   VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    version.identifier.source,
                    version.identifier.source_id,
                    digest,
                    artifact.artifact_id,
                ),
            )
            existing = conn.execute(
                """SELECT artifact_id FROM source_versions
                   WHERE source=%s AND source_id=%s AND raw_content_hash=%s""",
                (version.identifier.source, version.identifier.source_id, digest),
            ).fetchone()
            if existing is None or existing["artifact_id"] != artifact.artifact_id:
                raise ValueError("SOURCE_VERSION_ARTIFACT_CONFLICT")
            self._artifact(
                conn,
                receipt_artifact,
                model.model_dump_json().encode(),
                "DERIVED",
                {"kind": "ACQUISITION_RECEIPT"},
                artifact.artifact_id,
            )
            conn.execute(
                """INSERT INTO source_receipts(receipt_id,artifact_id,receipt_artifact_id)
                   VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",
                (receipt_id, artifact.artifact_id, receipt_artifact),
            )
        return receipt_artifact
