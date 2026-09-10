"""Resumable full-row preservation; identity registration is deliberately a separate decision."""

from collections.abc import Callable
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from klegal_gold.db.records import Records
from klegal_gold.domain.common import content_hash
from klegal_gold.domain.legacy import LegacyRow
from klegal_gold.ingestion.legacy import IMPORT_RULES_VERSION, map_legacy_row
from klegal_gold.ingestion.legacy_bundle import MAX_MANIFEST_BYTES, LegacyBundle
from klegal_gold.jobs.queue import Job


class LegacyImporter:
    def __init__(self, records: Records) -> None:
        self.records = records

    def _input(self, digest: str, limit: int, progress: Callable[[], None]) -> bytes:
        path = self.records.store.path(f"blobs/{digest[:2]}/{digest}")
        parts: list[bytes] = []
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("IMPORT_INPUT_SIZE_LIMIT")
                parts.append(chunk)
                progress()
        raw = b"".join(parts)
        if content_hash(raw) != digest:
            raise ValueError("IMPORT_INPUT_HASH_MISMATCH")
        return raw

    def run(self, job: Job, progress: Callable[[], None]) -> str:
        progress()
        digest = job.payload["manifest_hash"]
        raw = self._input(digest, MAX_MANIFEST_BYTES, progress)
        bundle = LegacyBundle.model_validate_json(raw)
        bundle_id = "legacy-bundle:" + digest
        self.records.put_artifact(
            bundle_id, raw, origin="MANIFEST", metadata={"kind": "LEGACY_IMPORT_INPUT"}
        )
        for entry in bundle.entries:
            progress()
            # Recheck even completed inputs; checkpoint never blesses missing/corrupt files.
            raw = self._input(entry.sha256, entry.size_bytes, progress)
            if len(raw) != entry.size_bytes:
                raise ValueError("IMPORT_INPUT_SIZE_MISMATCH")
            input_id = "legacy-input:" + entry.sha256
            with self.records.db.connect() as conn:
                prior = conn.execute(
                    "SELECT * FROM legacy_bundle_rows WHERE job_id=%s AND row_position=%s",
                    (job.job_id, entry.position),
                ).fetchone()
            if prior:
                if prior["input_artifact"] != input_id:
                    raise ValueError("IMPORT_LEDGER_INPUT_CONFLICT")
                self.records.read(input_id)
                if prior["record_artifact"]:
                    self.records.read(prior["record_artifact"])
                continue
            self.records.put_artifact(
                input_id, raw, origin="LEGACY_ARCHIVE", metadata={"kind": "FULL_ROW_INPUT"}
            )
            record_id = None
            reasons: list[str] = []
            try:
                row = LegacyRow.model_validate_json(raw)
                if (
                    row.coverage != "FULL_ROW"
                    or row.locator.snapshot_sha256 != bundle.snapshot_sha256
                    or row.locator.position != entry.position
                    or tuple(field.name for field in row.fields) != bundle.columns
                ):
                    raise ValueError("LEGACY_ROW_CONTRACT_MISMATCH")
                record = map_legacy_row(row, imported_at=datetime.now(UTC))
            except ValueError:
                # The original raw row is retained even when it cannot satisfy LegacyRow.
                status = "QUARANTINED"
                reasons = ["LEGACY_ROW_INVALID"]
            else:
                status = "PRESERVED"
                record_id = self.records.save_legacy(record, run_id=str(job.job_id))
                reasons = list(record.reasons)
                if any(field.encoding == "OPAQUE" for field in row.fields):
                    reasons.append("OPAQUE_FIELDS_REFERENCE_SOURCE_ARCHIVE")
            progress()
            # Stale workers may leave immutable artifacts, but cannot commit a row checkpoint.
            with self.records.db.connect() as conn:
                owner = conn.execute(
                    "SELECT 1 FROM jobs WHERE job_id=%s AND lease_token=%s "
                    "AND status='RUNNING' AND lease_until>clock_timestamp() FOR UPDATE",
                    (job.job_id, job.lease_token),
                ).fetchone()
                if owner is None:
                    raise ValueError("IMPORT_LEASE_LOST")
                conn.execute(
                    "INSERT INTO legacy_bundle_rows VALUES(%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    (job.job_id, entry.position, input_id, record_id, status, Jsonb(reasons)),
                )
                saved = conn.execute(
                    "SELECT input_artifact,record_artifact,status,reasons FROM legacy_bundle_rows "
                    "WHERE job_id=%s AND row_position=%s",
                    (job.job_id, entry.position),
                ).fetchone()
                if saved != dict(
                    input_artifact=input_id,
                    record_artifact=record_id,
                    status=status,
                    reasons=reasons,
                ):
                    raise ValueError("IMPORT_LEDGER_CONFLICT")
            progress()
        with self.records.db.connect() as conn:
            rows = conn.execute(
                "SELECT row_position,input_artifact,record_artifact,status,reasons "
                "FROM legacy_bundle_rows WHERE job_id=%s ORDER BY row_position",
                (job.job_id,),
            ).fetchall()
        if [row["row_position"] for row in rows] != [entry.position for entry in bundle.entries]:
            raise ValueError("IMPORT_RECONCILIATION_FAILED")
        preserved = sum(row["status"] == "PRESERVED" for row in rows)
        quarantined = len(rows) - preserved
        progress()
        return self.records.save_manifest(
            "legacy-import-result:" + str(job.job_id),
            "IMPORT",
            {
                "format": "legacy-import-result-1",
                "job_id": str(job.job_id),
                "input_manifest": bundle_id,
                "snapshot_sha256": bundle.snapshot_sha256,
                "scope": bundle.scope,
                "source_total_rows": bundle.total_rows,
                "selected_rows": len(bundle.entries),
                "preserved": preserved,
                "quarantined": quarantined,
                "pending": 0,
                "corpus_import_complete": bundle.scope == "FULL" and quarantined == 0,
                "mapper_version": IMPORT_RULES_VERSION,
                "rows": rows,
                "identity_registration": "NOT_PERFORMED",
            },
        )
