"""Full offline repair audit and image inventory; immutable source, no DB writes."""

import argparse
import hashlib
import json
import resource
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from inspect_legacy_pickle import load_data
from legacy_repair_rules import VERSION, propose_closing, propose_decision

from klegal_gold.documents.observe import Observer


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def count_lines(path: Path) -> int:
    with path.open() as handle:
        return sum(1 for _ in handle)


def write_line(handle: Any, row: Any) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def run(snapshot: Path, expected: str, output: Path, report: Path) -> None:
    start = time.monotonic()
    before = snapshot.stat()
    if digest(snapshot) != expected:
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    output.mkdir(parents=True, exist_ok=False)
    print("Verified snapshot; loading existing DataFrame", flush=True)
    frame = load_data(snapshot)
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique:
        raise ValueError("INVALID_FRAME")
    date_counts: Counter[str] = Counter()
    closing_counts: Counter[str] = Counter()
    image_counts: Counter[str] = Counter()
    unique_urls: set[str] = set()
    overlay = []
    with (
        (output / "dates.jsonl").open("w") as dates,
        (output / "images.jsonl").open("w") as images,
        (output / "quarantine.jsonl").open("w") as quarantine,
    ):
        for position in range(len(frame)):
            html = frame["case_txt_scraped_with_tags"].iloc[position]
            text = frame["case_txt_in_file"].iloc[position]
            title = frame["case_full_no"].iloc[position]
            locator = {"position": position, "original_index": str(frame.index[position])}
            if not all(isinstance(item, str) for item in (html, text, title)):
                write_line(quarantine, {**locator, "error": "INVALID_SOURCE_FIELDS"})
                continue
            html_hash = hashlib.sha256(html.encode()).hexdigest()
            try:
                # Use the same reviewed HTML parser for visible text; not a raw-byte offset.

                viewer = Observer("https://glaw.scourt.go.kr/")
                viewer.feed(html)
                visible = " ".join(viewer.text)
                decision = propose_decision(
                    title,
                    visible,
                    {
                        name: frame[name].iloc[position]
                        for name in ("gmeta_sngoDay", "lmeta_sngoDay")
                    },
                )
                closing = propose_closing(text, visible, frame["closing_argument"].iloc[position])
                for item in decision["evidence"]:
                    assert title[item["start"] : item["end"]] == item["text"]
                for item in closing["evidence"]:
                    assert text[item["start"] : item["end"]] == item["text"]
                previous = frame["decision_date"].iloc[position]
                previous_value = previous.isoformat() if isinstance(previous, date) else None
                record = {
                    **locator,
                    "html_sha256": html_hash,
                    "title": title,
                    "title_sha256": hashlib.sha256(title.encode()).hexdigest(),
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "decision_previous": {
                        "type": type(previous).__module__ + "." + type(previous).__qualname__,
                        "value": previous_value,
                        "archive_position": position,
                    },
                    "decision": decision,
                    "closing": closing,
                }
                refs = viewer.images
                image_counts["rows_with_images" if refs else "rows_without_images"] += 1
                for ref in refs:
                    ref["provider_mapping_values"] = viewer.image_mappings.get(ref["name"], [])
                    raw_url = ref["resolved_url"]
                    parsed = urlsplit(raw_url) if raw_url else None
                    query = parse_qs(parsed.query) if parsed else {}
                    ref.update(
                        {
                            "host": parsed.hostname if parsed else None,
                            "path": parsed.path if parsed else None,
                            "legacy_contId": query.get("contId", []),
                            "legacy_filename": query.get("attachImgNm", []),
                            "suspected_ui": bool(raw_url and "alert_img" in raw_url),
                        }
                    )
                    if raw_url:
                        unique_urls.add(raw_url)
                    image_counts["occurrences"] += 1
                    image_counts["suspected_ui" if ref["suspected_ui"] else "other_or_unknown"] += 1
                write_line(dates, record)
                date_counts[decision["status"]] += 1
                closing_counts[closing["status"]] += 1
                overlay.append(
                    {
                        **locator,
                        "html_sha256": html_hash,
                        "decision_apply": decision["status"] == "READY",
                        "decision_date": date.fromisoformat(decision["candidate"])
                        if decision["status"] == "READY"
                        else None,
                        "decision_status": decision["status"],
                        "closing_apply": closing["status"] == "READY",
                        "closing_argument": date.fromisoformat(closing["candidate"])
                        if closing["status"] == "READY"
                        else None,
                        "closing_status": closing["status"],
                    }
                )
                write_line(
                    images,
                    {
                        **locator,
                        "html_sha256": html_hash,
                        "scourt_id": str(frame["gmeta_contId"].iloc[position]),
                        "lawgo_id": str(frame["lmeta_serialno"].iloc[position]),
                        "images": refs,
                        "acquisition_status": "NOT_ATTEMPTED",
                    },
                )
            except (ValueError, TypeError, AssertionError, RecursionError) as error:
                write_line(
                    quarantine,
                    {
                        **locator,
                        "html_sha256": html_hash,
                        "error": type(error).__name__,
                        "detail": str(error)[:300],
                    },
                )
            if (position + 1) % 5000 == 0:
                print(f"Audited {position + 1}/{len(frame)}", flush=True)
    schema = pa.schema(
        [
            ("position", pa.int64()),
            ("original_index", pa.string()),
            ("html_sha256", pa.string()),
            ("decision_apply", pa.bool_()),
            ("decision_date", pa.date32()),
            ("decision_status", pa.string()),
            ("closing_apply", pa.bool_()),
            ("closing_argument", pa.date32()),
            ("closing_status", pa.string()),
        ],
        metadata={
            b"snapshot_sha256": expected.encode(),
            b"rules_version": VERSION.encode(),
            b"scope": b"REPAIR_OVERLAY_NOT_FULL_CORPUS",
        },
    )
    table = pa.Table.from_pylist(overlay, schema=schema)
    pq.write_table(
        table, output / "repair-overlay.parquet", compression="zstd", row_group_size=2048
    )
    assert pq.read_table(output / "repair-overlay.parquet").equals(table, check_metadata=True)
    after = snapshot.stat()
    assert (before.st_size, before.st_mtime_ns, before.st_ino) == (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    )
    files = {
        path.name: {"sha256": digest(path), "bytes": path.stat().st_size}
        for path in output.iterdir()
        if path.is_file()
    }
    counts = {
        name: count_lines(output / name)
        for name in ("dates.jsonl", "images.jsonl", "quarantine.jsonl")
    }
    assert counts["dates.jsonl"] + counts["quarantine.jsonl"] == len(frame)
    assert counts["images.jsonl"] == counts["dates.jsonl"]
    result = {
        "scope": "FULL_OFFLINE_REPAIR_AUDIT_AND_IMAGE_INVENTORY",
        "snapshot_sha256": expected,
        "rows": len(frame),
        "columns": len(frame.columns),
        "rules_version": VERSION,
        "decision": dict(date_counts),
        "closing": dict(closing_counts),
        "images": dict(image_counts),
        "unique_resolved_urls": len(unique_urls),
        "counts": counts,
        "files": files,
        "output": str(output.resolve()),
        "overlay_roundtrip": True,
        "source_stat_unchanged": True,
        "elapsed_seconds": time.monotonic() - start,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "applied_to_original": False,
        "canonical_registered": False,
    }
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args.snapshot, args.expected_sha256, args.output, args.report)
