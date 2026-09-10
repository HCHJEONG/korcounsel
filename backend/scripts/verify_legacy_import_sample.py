"""Verify an actual staged FULL_ROW sample in a disposable local PostgreSQL schema."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from klegal_gold.db.migrate import migrate
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.domain.legacy import LegacyCaseRecord, LegacyRow
from klegal_gold.ingestion.legacy_bundle import LegacyBundle
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore


def verify(data_dir: Path, manifest_hash: str, report_path: Path) -> None:
    dsn = os.environ["KLEGAL_TEST_DATABASE_URL"]
    info = conninfo_to_dict(dsn)
    if (
        info.get("host") not in {"127.0.0.1", "localhost"}
        or info.get("port") != "55432"
        or (info.get("dbname") not in {"korcounsel_dev", "korcounsel_test"})
    ):
        raise ValueError("LOCAL_TEST_DATABASE_REQUIRED")
    schema = "klegal_test_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        db = Database(dsn, schema=schema)
        migrate(db)
        records = Records(db, FileStore(data_dir.resolve()))
        bundle = LegacyBundle.model_validate_json(
            records.store.path(f"blobs/{manifest_hash[:2]}/{manifest_hash}").read_bytes()
        )
        if bundle.scope != "SAMPLE":
            raise ValueError("SAMPLE_BUNDLE_REQUIRED")
        queue = Queue(db)
        worker = Worker(queue, records)
        outputs = []
        for key in ("sample-first", "sample-repeat"):
            job = queue.submit_legacy_import(key, manifest_hash)
            worker.run_once()
            final = queue.get(job.job_id)
            if final.status != "SUCCEEDED":
                raise ValueError("SAMPLE_IMPORT_FAILED")
            outputs.append(json.loads(records.read(final.checkpoint["result_manifest"])))
        first = outputs[0]
        if first["quarantined"] or first["preserved"] != len(bundle.entries):
            raise ValueError("SAMPLE_RECONCILIATION_FAILED")
        if [r["record_artifact"] for r in first["rows"]] != [
            r["record_artifact"] for r in outputs[1]["rows"]
        ]:
            raise ValueError("SAMPLE_RETRY_CHANGED_ARTIFACT")
        opaque_fields = 0
        text_fields = 0
        body_fields = 0
        for entry, saved in zip(bundle.entries, first["rows"], strict=True):
            original = LegacyRow.model_validate_json(records.read(saved["input_artifact"]))
            restored = LegacyCaseRecord.model_validate_json(records.read(saved["record_artifact"]))
            if restored.original != original or len(original.fields) != len(bundle.columns):
                raise ValueError("SAMPLE_FULL_ROW_CHANGED")
            if original.locator.position != entry.position:
                raise ValueError("SAMPLE_POSITION_CHANGED")
            opaque_fields += sum(f.encoding == "OPAQUE" for f in original.fields)
            text_fields += sum(f.encoding == "STRING" for f in original.fields)
            body_fields += sum(
                f.encoding == "STRING"
                and f.name in {"case_txt_scraped_with_tags", "case_txt_in_file"}
                for f in original.fields
            )
        with db.connect() as conn:
            count = conn.execute("SELECT count(*) AS n FROM legacy_records").fetchone()["n"]
            ledger = conn.execute("SELECT count(*) AS n FROM legacy_bundle_rows").fetchone()["n"]
            identities = conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
        if (count, ledger, identities) != (len(bundle.entries), 2 * len(bundle.entries), 0):
            raise ValueError("SAMPLE_DB_COUNTS_MISMATCH")
        report_path.write_text(
            json.dumps(
                {
                    "verified_at": datetime.now(UTC).isoformat(),
                    "manifest_hash": manifest_hash,
                    "snapshot_sha256": bundle.snapshot_sha256,
                    "source_rows": bundle.total_rows,
                    "selected_rows": len(bundle.entries),
                    "columns": len(bundle.columns),
                    "preserved_field_cells": len(bundle.entries) * len(bundle.columns),
                    "opaque_fields_referencing_archive": opaque_fields,
                    "string_fields": text_fields,
                    "body_string_fields": body_fields,
                    "quarantined": 0,
                    "records_after_two_runs": count,
                    "ledger_after_two_runs": ledger,
                    "exact_original_roundtrip": True,
                    "identities_registered": identities,
                    "scope": "SAMPLE",
                    "public_schema_modified": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(f"Verified {count} FULL_ROW records; {ledger} ledger rows; exact original round-trip")
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--manifest-hash", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    verify(args.data_dir, args.manifest_hash, args.report)
