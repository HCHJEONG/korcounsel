"""Read-only inventory of preserved legacy HTML, with no acquisition or DB effects."""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import file_digest, sha256
from html.parser import HTMLParser
from itertools import repeat
from multiprocessing import get_context
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pyarrow.parquet as pq

from klegal_gold.documents.reader import HIDDEN, image_occurrences
from klegal_gold.documents.reader import VERSION as READER_VERSION
from klegal_gold.enrichment.legacy_statutes import VERSION as STATUTE_VERSION
from klegal_gold.enrichment.legacy_statutes import statute_occurrences
from klegal_gold.search.parquet import _cell_value, _original_index, _text, legacy_snapshot

VERSION = "legacy-enrichment-inventory-1"
COLUMNS = (
    "__legacy_position",
    "__legacy_index",
    "case_txt_scraped_with_tags",
    "case_full_no",
    "gmeta_contId",
    "lmeta_serialno",
)
UI_IMAGE_FILENAMES = frozenset({"alert_img_01.png"})


class Structure(HTMLParser):
    """Classify image positions without claiming semantic image content."""

    def __init__(self) -> None:
        super().__init__()
        self.tables = 0
        self.table_depth = 0
        self.hidden: list[str] = []
        self.images: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.images.append({"in_table": self.table_depth > 0, "hidden": bool(self.hidden)})
        if tag in HIDDEN and tag != "embed":
            self.hidden.append(tag)
        if tag == "table":
            self.table_depth += 1
            if not self.hidden:
                self.tables += 1

    def handle_endtag(self, tag: str) -> None:
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if tag == "table":
            self.table_depth = max(0, self.table_depth - 1)


@dataclass
class RowInventory:
    row: dict[str, Any]
    images: list[dict[str, Any]]
    statutes: list[dict[str, Any]]
    errors: list[dict[str, Any]]


def _source_id(value: str) -> bool:
    return value.isascii() and value.isdigit() and int(value) > 0


def inspect_row(row: dict[str, Any], snapshot: str, ordinal: int) -> RowInventory:
    """Inspect one preserved row; errors remain attached to its physical ordinal."""
    position = row.get("__legacy_position")
    source_id = _text(row.get("gmeta_contId"))
    locator = {
        "row_ordinal": ordinal,
        "position": position,
        "original_index": _original_index(row.get("__legacy_index")),
        "snapshot_sha256": snapshot,
    }
    result: dict[str, Any] = {
        **locator,
        "title": _text(row.get("case_full_no")).strip(),
        "source_id": source_id,
        "lawgo_serialno": _text(row.get("lmeta_serialno")),
        "source_id_usable": _source_id(source_id),
        "body_field": "case_txt_scraped_with_tags",
        "status": "OBSERVED",
    }
    errors: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    statutes: list[dict[str, Any]] = []
    if not isinstance(position, int) or isinstance(position, bool) or position < 0:
        errors.append({**locator, "code": "INVALID_ROW_POSITION"})
    body = _cell_value(row.get("case_txt_scraped_with_tags"))
    if not isinstance(body, str):
        result.update(status="ERROR", body_hash=None)
        errors.append({**locator, "code": "BODY_NOT_STRING", "type": type(body).__name__})
        return RowInventory(result, [], [], errors)
    body_hash = sha256(body.encode()).hexdigest()
    result.update(body_hash=body_hash, body_characters=len(body))
    if body.strip().lower() in {"", "empty", "no_info", "none"}:
        result["status"] = "EMPTY_OR_SENTINEL"
    occurrence_locator = {**locator, "parent_html_sha256": body_hash}
    try:
        structure = Structure()
        structure.feed(body)
        refs = image_occurrences(body, source_id=source_id, base_url="https://glaw.scourt.go.kr/")
        for ref, flags in zip(refs, structure.images, strict=True):
            src = ref.get("original_src")
            parsed = urlsplit(src or "")
            query = parse_qs(parsed.query)
            filename = parsed.path.rsplit("/", 1)[-1].lower()
            is_ui = filename in UI_IMAGE_FILENAMES
            category = "HIDDEN" if flags["hidden"] else ("PROVIDER_UI" if is_ui else "BODY")
            if not src:
                reference_status = "MISSING_SRC"
            elif parsed.scheme and parsed.scheme not in {"http", "https"}:
                reference_status = "UNSUPPORTED_SCHEME"
            elif parsed.hostname == "glaw.scourt.go.kr" or not parsed.hostname:
                reference_status = "LEGACY_REFERENCE_REQUIRES_MAPPING"
            else:
                reference_status = "UNVERIFIED_EXTERNAL_REFERENCE"
            images.append(
                {
                    **occurrence_locator,
                    **{
                        key: ref.get(key)
                        for key in (
                            "reference_id",
                            "order",
                            "html_start",
                            "html_end",
                            "original_src",
                            "name",
                            "resolved_url",
                            "alt",
                            "srcset_original",
                            "provider_mapping_values",
                        )
                    },
                    **flags,
                    "category": category,
                    "known_provider_ui_filename": is_ui,
                    "reference_status": reference_status,
                    "legacy_cont_ids": query.get("contId", []),
                    "legacy_filenames": query.get("attachImgNm", []),
                    "acquisition_status": "NOT_CHECKED",
                }
            )
        result["body_tables"] = structure.tables
    except Exception as exc:
        errors.append(
            {**locator, "code": "IMAGE_OBSERVATION_FAILED", "error_type": type(exc).__name__}
        )
    try:
        for item in statute_occurrences(body):
            if body[item["html_start"] : item["html_end"]] != item["html_tag"]:
                raise ValueError("STATUTE_TAG_POSITION_MISMATCH")
            statutes.append(
                {
                    **occurrence_locator,
                    **{
                        key: item[key]
                        for key in (
                            "reference_id",
                            "order",
                            "html_start",
                            "html_end",
                            "payload_sha256",
                            "status",
                            "version_status",
                            "text",
                        )
                    },
                    "payload_characters": len(item["payload"]),
                }
            )
    except Exception as exc:
        errors.append(
            {**locator, "code": "STATUTE_OBSERVATION_FAILED", "error_type": type(exc).__name__}
        )
    # A failed parse has unknown counts, not a misleading zero.
    image_failed = any(e["code"] == "IMAGE_OBSERVATION_FAILED" for e in errors)
    statute_failed = any(e["code"] == "STATUTE_OBSERVATION_FAILED" for e in errors)
    image_counts = Counter(str(image["category"]) for image in images)
    statute_counts = Counter(str(item["status"]) for item in statutes)
    result.update(
        image_occurrences=None if image_failed else len(images),
        body_images=None if image_failed else image_counts["BODY"],
        provider_ui_images=None if image_failed else image_counts["PROVIDER_UI"],
        hidden_images=None if image_failed else image_counts["HIDDEN"],
        table_body_images=None
        if image_failed
        else sum(image["in_table"] and image["category"] == "BODY" for image in images),
        missing_src_body_images=None
        if image_failed
        else sum(image["category"] == "BODY" and not image["original_src"] for image in images),
        statute_occurrences=None if statute_failed else len(statutes),
        preserved_statutes=None if statute_failed else statute_counts["PRESERVED"],
        failed_statutes=None if statute_failed else statute_counts["LEGACY_FAILURE"],
        unlinked_statutes=None if statute_failed else statute_counts["UNLINKED"],
    )
    if errors:
        result["status"] = "ERROR"
        result["error_codes"] = [e["code"] for e in errors]
    return RowInventory(result, images, statutes, errors)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def run_inventory(
    parquet_path: Path,
    output_dir: Path,
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
    processes: int = 1,
) -> dict[str, Any]:
    """Write a complete, hash-bound inventory atomically into a new directory."""
    if not 1 <= processes <= 4:
        raise ValueError("INVENTORY_PROCESSES_MUST_BE_1_TO_4")
    parquet_path = parquet_path.resolve(strict=True)
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    parquet = pq.ParquetFile(parquet_path)
    missing = set(COLUMNS) - set(parquet.schema_arrow.names)
    if missing:
        raise ValueError("MISSING_INVENTORY_COLUMNS:" + ",".join(sorted(missing)))
    snapshot = legacy_snapshot(parquet_path)
    if len(snapshot) != 64 or any(c not in "0123456789abcdef" for c in snapshot):
        raise ValueError("MISSING_LEGACY_SNAPSHOT_HASH")
    initial_hash = _sha256(parquet_path)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.with_name(output_dir.name + ".partial-" + uuid.uuid4().hex)
    staging.mkdir()
    filenames = ("rows", "images", "statutes", "image-targets", "errors")
    totals: Counter[str] = Counter()
    image_statuses: Counter[str] = Counter()
    statute_statuses: Counter[str] = Counter()
    error_codes: Counter[str] = Counter()
    positions: set[int] = set()
    original_urls: set[str] = set()
    body_urls: set[str] = set()
    payload_hashes: set[str] = set()
    samples: dict[str, list[dict[str, Any]]] = {}
    counters = (
        "image_occurrences",
        "body_images",
        "provider_ui_images",
        "hidden_images",
        "table_body_images",
        "missing_src_body_images",
        "statute_occurrences",
        "preserved_statutes",
        "failed_statutes",
        "unlinked_statutes",
        "body_tables",
    )
    with ExitStack() as stack:
        pool = (
            stack.enter_context(
                ProcessPoolExecutor(max_workers=processes, mp_context=get_context("spawn"))
            )
            if processes > 1
            else None
        )
        streams = {
            name: stack.enter_context((staging / (name + ".jsonl")).open("w", encoding="utf-8"))
            for name in filenames
        }

        def write(name: str, record: dict[str, Any]) -> None:
            streams[name].write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

        for batch in parquet.iter_batches(batch_size=256, columns=list(COLUMNS)):
            raw_rows = batch.to_pylist()
            ordinals = range(totals["rows"], totals["rows"] + len(raw_rows))
            inspected_rows = (
                pool.map(inspect_row, raw_rows, repeat(snapshot), ordinals, chunksize=8)
                if pool is not None
                else (
                    inspect_row(raw, snapshot, ordinal)
                    for raw, ordinal in zip(raw_rows, ordinals, strict=True)
                )
            )
            for inspected in inspected_rows:
                row = inspected.row
                position = row["position"]
                if isinstance(position, int):
                    if position in positions:
                        row["status"] = "ERROR"
                        inspected.errors.append(
                            {
                                "position": position,
                                "row_ordinal": row["row_ordinal"],
                                "snapshot_sha256": snapshot,
                                "code": "DUPLICATE_ROW_POSITION",
                            }
                        )
                    positions.add(position)
                totals["rows"] += 1
                totals["rows_" + row["status"].lower()] += 1
                for key in counters:
                    value = row.get(key)
                    if isinstance(value, int):
                        totals[key] += value
                        if value > 0:
                            totals["rows_with_" + key] += 1
                write("rows", row)
                if row.get("body_images") or row.get("image_occurrences") is None:
                    write("image-targets", row)
                    totals["image_target_rows"] += 1
                    if not row["source_id_usable"]:
                        totals["image_target_rows_without_source_id"] += 1
                for item in inspected.images:
                    write("images", item)
                    image_statuses[item["reference_status"]] += 1
                    if item["original_src"]:
                        original_urls.add(item["original_src"])
                        if item["category"] == "BODY":
                            body_urls.add(item["original_src"])
                for item in inspected.statutes:
                    write("statutes", item)
                    statute_statuses[item["status"]] += 1
                    if item["status"] == "PRESERVED":
                        payload_hashes.add(item["payload_sha256"])
                for error in inspected.errors:
                    write("errors", error)
                    error_codes[error["code"]] += 1
                for category, selected in (
                    ("table_body_images", bool(row.get("table_body_images"))),
                    ("body_images", bool(row.get("body_images"))),
                    ("failed_statutes", bool(row.get("failed_statutes"))),
                    ("preserved_statutes", bool(row.get("preserved_statutes"))),
                    ("unlinked_statutes", bool(row.get("unlinked_statutes"))),
                    ("errors", bool(inspected.errors)),
                ):
                    if selected and len(samples.setdefault(category, [])) < 10:
                        samples[category].append(row)
            if progress:
                progress({"rows": totals["rows"], "expected_rows": parquet.metadata.num_rows})
        for stream in streams.values():
            stream.flush()
            os.fsync(stream.fileno())
    final_hash = _sha256(parquet_path)
    if final_hash != initial_hash:
        raise ValueError("INPUT_PARQUET_CHANGED_DURING_INVENTORY")
    if totals["rows"] != parquet.metadata.num_rows:
        raise ValueError("INVENTORY_ROW_COUNT_MISMATCH")
    artifacts = {
        name + ".jsonl": {
            "sha256": _sha256(staging / (name + ".jsonl")),
            "bytes": (staging / (name + ".jsonl")).stat().st_size,
        }
        for name in filenames
    }
    summary: dict[str, Any] = {
        "version": VERSION,
        "reader_version": READER_VERSION,
        "statute_parser_version": STATUTE_VERSION,
        "input": {
            "parquet_path": str(parquet_path),
            "parquet_sha256": initial_hash,
            "parquet_bytes": parquet_path.stat().st_size,
            "snapshot_sha256": snapshot,
            "expected_rows": parquet.metadata.num_rows,
            "unchanged_after_scan": True,
        },
        "totals": dict(sorted(totals.items())),
        "distinct_positions": len(positions),
        "distinct_original_image_urls": len(original_urls),
        "distinct_body_image_urls": len(body_urls),
        "distinct_preserved_statute_payloads": len(payload_hashes),
        "image_reference_statuses": dict(sorted(image_statuses.items())),
        "statute_statuses": dict(sorted(statute_statuses.items())),
        "error_codes": dict(sorted(error_codes.items())),
        "samples": samples,
        "artifacts": artifacts,
        "scope": "Preserved HTML observations only; no current-provider, binary or DB verification",
        "ui_classification": {
            "rule": "exact filename allowlist",
            "filenames": sorted(UI_IMAGE_FILENAMES),
        },
    }
    (staging / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    staging.rename(output_dir)
    return summary
