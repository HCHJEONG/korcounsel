"""Verify observed Step 2 samples, optionally including existing saved HTML files.

Run from backend with uv. This never reads the large pickle or writes an import DB.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from klegal_gold.domain.common import content_hash
from klegal_gold.domain.legacy import LegacyCaseRecord, LegacyRow, LegacyStoredText
from klegal_gold.ingestion.legacy import (
    identity_conflicts,
    legacy_content_revision,
    map_legacy_row,
    row_from_metadata_projection,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    fixture = root / "backend/tests/fixtures/legacy/bootstrap-metadata.json"
    rows = {
        value["position"]: row_from_metadata_projection(value)
        for value in json.loads(fixture.read_text())["rows"]
    }
    checked_at = datetime.now(UTC)
    files = []
    if args.archive_root:
        manifest = json.loads((root / "docs/step0/legacy-enrichment-samples.json").read_text())
        for entry in manifest:
            relative = entry["file"]
            path = args.archive_root / relative
            raw = path.read_bytes()
            digest = content_hash(raw)
            if digest != entry["sha256"]:
                raise ValueError("LEGACY_SAMPLE_FILE_CHANGED")
            stem = path.stem.split("-")
            position = int(stem[0]) if len(stem) == 3 else 88590
            row = rows[position]
            fields = {field.name: field.value for field in row.fields}
            if len(stem) == 3:
                expected = [
                    str(fields.get(k) or "empty") for k in ("gmeta_contId", "lmeta_serialno")
                ]
                if stem[1:] != expected:
                    raise ValueError("LEGACY_SAMPLE_SOURCE_ID_MISMATCH")
            elif stem[0] != fields["gmeta_contId"]:
                raise ValueError("LEGACY_SAMPLE_SOURCE_ID_MISMATCH")
            text = raw.decode("utf-8")  # No replacement, stripping, or newline conversion.
            stored = LegacyStoredText(
                role="ENRICHED_HTML" if len(stem) == 3 else "SAVED_HTML",
                original_locator=relative,
                text=text,
                utf8_sha256=content_hash(text.encode("utf-8")),
                file_sha256=digest,
            )
            rows[position] = LegacyRow.model_validate(
                row.model_dump() | {"stored_texts": [*row.stored_texts, stored]}
            )
            files.append({"file": relative, "sha256": digest, "size_bytes": len(raw)})
    records = tuple(map_legacy_row(row, imported_at=checked_at) for row in rows.values())
    jsonl = "\n".join(record.model_dump_json() for record in records)
    restored = tuple(LegacyCaseRecord.model_validate_json(line) for line in jsonl.splitlines())
    if restored != records:
        raise ValueError("LEGACY_JSONL_ROUND_TRIP_FAILED")
    rerun = tuple(
        map_legacy_row(row, imported_at=checked_at.replace(microsecond=0)) for row in rows.values()
    )
    if [legacy_content_revision(r) for r in records] != [legacy_content_revision(r) for r in rerun]:
        raise ValueError("LEGACY_REEXECUTION_CHANGED_CONTENT")
    report = {
        "checked_at": checked_at.isoformat(),
        "scope": "15 observed metadata projections and optional saved UTF-8 HTML files",
        "fixture_sha256": content_hash(fixture.read_bytes()),
        "rows_checked": len(records),
        "files_checked": files,
        "jsonl_round_trip": "PASS",
        "content_revision_reexecution": "PASS",
        "conflicting_source_rows": identity_conflicts(records),
        "results": [
            {
                "position": r.original.locator.position,
                "preservation_id": r.preservation_id,
                "document_id_proposal": r.document_id_proposal,
                "body_state": r.body_state,
                "enrichment_state": r.enrichment_state,
                "reasons": r.reasons,
                "content_revision": legacy_content_revision(r),
            }
            for r in records
        ],
        "not_performed": [
            "full pickle conversion",
            "DB import",
            "canonical link confirmation",
            "live scourt/lawgo verification",
            "Parquet export",
            "asset download",
            "historical statute version validation",
        ],
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Verified {len(records)} metadata rows and {len(files)} saved files; no DB import.")


if __name__ == "__main__":
    main()
