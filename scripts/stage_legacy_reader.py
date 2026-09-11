"""Publish a bounded legacy reader revision; queue downloads separately from publication.

The current reader is evidence, never a replacement for the legacy body. Re-running
with the same evidence reuses artifacts. New acquisitions create new reader revisions.
"""

import argparse
import json
from hashlib import sha256
from pathlib import Path

import pyarrow.parquet as pq

from klegal_gold.assets.images import validate_image
from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.image_links import link_legacy_images
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.search.parquet import _original_index, _text, legacy_snapshot
from klegal_gold.storage.files import FileStore


def stage(path, positions, current_ids, records):
    store = ReaderStore(records)
    selected = {}
    parquet = pq.ParquetFile(path)
    columns = [
        "__legacy_position",
        "__legacy_index",
        "case_txt_scraped_with_tags",
        "case_full_no",
        "gmeta_contId",
        "lmeta_serialno",
    ]
    locator_column = parquet.schema.names.index("__legacy_position")
    for group in range(parquet.num_row_groups):
        stats = parquet.metadata.row_group(group).column(locator_column).statistics
        if stats and stats.has_min_max and not any(stats.min <= p <= stats.max for p in positions):
            continue
        for row in parquet.read_row_group(group, columns=columns).to_pylist():
            if row["__legacy_position"] in positions:
                selected[row["__legacy_position"]] = row
    if set(selected) != set(positions):
        raise ValueError("MISSING_LEGACY_ROWS")
    result = []
    pending = []
    for position in positions:
        row = selected[position]
        html = _text(row["case_txt_scraped_with_tags"])
        title = _text(row["case_full_no"]).strip()
        source = _text(row["gmeta_contId"])
        provenance = {
            "snapshot_sha256": legacy_snapshot(path),
            "row_position": position,
            "original_index": _original_index(row["__legacy_index"]),
            "field": "case_txt_scraped_with_tags",
            "lawgo_serialno": _text(row["lmeta_serialno"]),
            "historical_binary_identity_verified": False,
        }
        linked = None
        if position in current_ids:
            current_id = current_ids[position]
            current = store.read(current_id)
            current_html = records.read(current["html_artifact_id"]).decode()
            if sha256(current_html.encode()).hexdigest() != current["html_sha256"]:
                raise ValueError("CURRENT_BODY_HASH_MISMATCH")
            linked = link_legacy_images(html, current_html, current, source_id=source, title=title)
            provenance["current_reader_id"] = current_id
            for ref in linked:
                evidence = ref.get("link_evidence")
                if not evidence:
                    continue
                url = evidence["resolved_url"]
                with records.db.connect() as conn:
                    acquired = conn.execute(
                        "SELECT * FROM image_acquisitions WHERE url=%s", (url,)
                    ).fetchone()
                    attempt = conn.execute(
                        "SELECT attempt_id,recorded_at,job_id FROM image_acquisition_attempts "
                        "WHERE url=%s ORDER BY recorded_at DESC LIMIT 1",
                        (url,),
                    ).fetchone()
                if acquired and acquired["status"] == "ACQUIRED":
                    digest = acquired["blob_hash"]
                    raw = records.store.path(f"blobs/{digest[:2]}/{digest}").read_bytes()
                    if sha256(raw).hexdigest() != digest:
                        raise ValueError("IMAGE_HASH_MISMATCH")
                    metadata = validate_image(raw)
                    records.put_artifact(
                        "reader-image:" + digest,
                        raw,
                        origin="DERIVED",
                        metadata={"kind": "PRESERVED_IMAGE_BYTES"},
                    )
                    ref.update(
                        blob_hash=digest,
                        status="ACQUIRED",
                        decode=metadata,
                        acquisition={"url": url, "attempt": attempt},
                    )
                elif acquired and not ref.get("blob_hash"):
                    ref.update(
                        status=acquired["status"],
                        acquisition={
                            "url": url,
                            "attempt": attempt,
                            "error": acquired["last_error_code"],
                        },
                    )
                if ref.get("blob_hash"):
                    ref["decode"] = validate_image(records.read("reader-image:" + ref["blob_hash"]))
                else:
                    pending.append(
                        {
                            **ref,
                            "reference_id": sha256(
                                (ref["reference_id"] + current_id).encode()
                            ).hexdigest(),
                            "row_position": position,
                            "source_id": source,
                            "source_system": "scourt",
                            "resolved_url": url,
                            "reference_status": "RESOLVED",
                            "reason": ref["link_reason"],
                            "current_reader_id": current_id,
                        }
                    )
        # DB timestamps and UUIDs become explicit provenance strings, not guessed historic times.
        if linked is not None:
            linked = json.loads(json.dumps(linked, default=str))
        document_id = store.preserve(
            html,
            title=title,
            source_id=source,
            origin="LEGACY_CORPUS",
            provenance=provenance,
            acquisitions={},
            linked_images=linked,
        )
        manifest = store.read(document_id)
        result.append(
            {
                "position": position,
                "title": title,
                "body_hash": manifest["html_sha256"],
                "document_id": document_id,
                "images": len(manifest["images"]),
                "linked": sum(bool(x.get("blob_hash")) for x in manifest["images"]),
                "statutes": len(manifest["statutes"]),
                "preserved_statutes": sum(x["status"] == "PRESERVED" for x in manifest["statutes"]),
            }
        )
    download_raw = json.dumps(
        {"references": pending}, ensure_ascii=False, sort_keys=True, default=str
    ).encode()
    download_id = "image-manifest:legacy-reader-" + sha256(download_raw).hexdigest()
    records.put_artifact(
        download_id, download_raw, origin="MANIFEST", metadata={"kind": "IMAGE_REFERENCE_MANIFEST"}
    )
    return {"rows": result, "download_manifest": download_id, "download_references": len(pending)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", required=True)
    parser.add_argument("--current", action="append", default=[], help="POSITION:CURRENT_READER_ID")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    positions = [int(x) for x in args.positions.split(",")]
    if not 1 <= len(positions) <= 50 or len(set(positions)) != len(positions):
        parser.error("Choose 1..50 distinct positions per batch")
    current_ids = {int(x.split(":", 1)[0]): x.split(":", 1)[1] for x in args.current}
    settings = load_settings()
    if settings.legacy_parquet_path is None:
        parser.error("LEGACY_PARQUET_PATH is required")
    records = Records(Database.from_settings(settings), FileStore(settings.data_dir))
    result = stage(settings.legacy_parquet_path, positions, current_ids, records)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
