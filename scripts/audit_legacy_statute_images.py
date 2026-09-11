"""Audit preserved lawgo payload images; read-only Parquet scan, never download."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import re
from concurrent.futures import ProcessPoolExecutor
from hashlib import file_digest, sha256
from html.parser import HTMLParser
from pathlib import Path
from time import monotonic
from typing import Any

import pyarrow.parquet as pq

from klegal_gold.documents.reader import image_occurrences
from klegal_gold.enrichment.legacy_statutes import statute_occurrences
from klegal_gold.search.parquet import _text, legacy_snapshot

VERSION = "legacy-statute-image-audit-1"
# Deliberately broad substring guards. Any HTML img tag recognized by HTMLParser,
# SVG image, srcset, CSS url(), background or embedded visual element includes one.
GUARDS = (
    "img",
    "image",
    "picture",
    "source",
    "srcset",
    "url",
    "background",
    "svg",
    "object",
    "embed",
    "iframe",
)
VISUAL_TAGS = {"img", "image", "picture", "source", "object", "embed", "iframe", "svg"}
CACHE: dict[str, dict[str, Any] | None] = {}


def json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Caller selects a new output path. Never silently overwrite an audit.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


class VisualReferences(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.html = html
        self.lines = [0] + [i + 1 for i, char in enumerate(html) if char == "\n"]
        self.references: list[dict[str, Any]] = []
        self.style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "style":
            self.style = True
        reasons = []
        if tag.rsplit(":", 1)[-1] in VISUAL_TAGS:
            reasons.append("VISUAL_ELEMENT")
        if "srcset" in values:
            reasons.append("SRCSET_ATTRIBUTE")
        if "background" in values:
            reasons.append("BACKGROUND_ATTRIBUTE")
        if re.search(r"url\s*\(", values.get("style") or "", flags=re.I):
            reasons.append("CSS_URL_ATTRIBUTE")
        if any("data:image/" in (value or "").lower() for value in values.values()):
            reasons.append("DATA_IMAGE_ATTRIBUTE")
        if not reasons:
            return
        line, column = self.getpos()
        start = self.lines[line - 1] + column
        text = self.get_starttag_text() or ""
        self.references.append(
            {
                "tag": tag,
                "attributes": values,
                "reasons": reasons,
                "html_start": start,
                "html_end": start + len(text),
                "html_tag": text,
                "before": self.html[max(0, start - 160) : start],
                "after": self.html[start + len(text) : start + len(text) + 160],
            }
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.style = False

    def handle_data(self, data: str) -> None:
        if self.style and re.search(r"url\s*\(", data, flags=re.I):
            self.references.append({"tag": "style-data", "reasons": ["CSS_URL_TEXT"], "text": data})


def payload_observation(payload: str, payload_hash: str) -> dict[str, Any] | None:
    if payload_hash in CACHE:
        return CACHE[payload_hash]
    lower = payload.lower()
    if not any(token in lower for token in GUARDS):
        CACHE[payload_hash] = None
        return None
    parser = VisualReferences(payload)
    parser.feed(payload)
    images = image_occurrences(payload, source_id="", base_url="https://www.law.go.kr/")
    if images or parser.references:
        result: dict[str, Any] | None = {
            "payload_sha256": payload_hash,
            "payload_characters": len(payload),
            "images": images,
            "visual_references": parser.references,
        }
    else:
        result = None
    CACHE[payload_hash] = result
    return result


def inspect_batch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hashes: set[str] = set()
    found: dict[str, dict[str, Any]] = {}
    locations: list[dict[str, Any]] = []
    nonempty = 0
    total = 0
    status_counts: dict[str, int] = {}
    for row in rows:
        position = row["__legacy_position"]
        html = _text(row["case_txt_scraped_with_tags"])
        articles = statute_occurrences(html)
        total += len(articles)
        for item in articles:
            status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
            if not item["payload"]:
                continue
            nonempty += 1
            key = item["payload_sha256"]
            hashes.add(key)
            observation = payload_observation(item["payload"], key)
            if observation is None:
                continue
            found[key] = observation
            locations.append(
                {
                    "position": position,
                    "parent_html_sha256": item["parent_html_sha256"],
                    "statute_reference_id": item["reference_id"],
                    "statute_order": item["order"],
                    "statute_html_start": item["html_start"],
                    "statute_html_end": item["html_end"],
                    "statute_text": item["text"],
                    "status": item["status"],
                    "payload_sha256": key,
                }
            )
    return {
        "rows": len(rows),
        "statute_occurrences": total,
        "nonempty_occurrences": nonempty,
        "payload_hashes": sorted(hashes),
        "payloads": found,
        "locations": locations,
        "status_counts": status_counts,
    }


def ui_samples(inventory: Path) -> dict[int, dict[str, Any]]:
    samples: dict[int, dict[str, Any]] = {}
    with inventory.open() as stream:
        for line in stream:
            item = json.loads(line)
            if item.get("category") == "PROVIDER_UI" and item["position"] not in samples:
                samples[item["position"]] = item
                if len(samples) == 3:
                    return samples
    return samples


def run(
    path: Path, output: Path, expected_hash: str, inventory: Path, processes: int
) -> dict[str, Any]:
    start = monotonic()
    if output.exists():
        raise FileExistsError("AUDIT_OUTPUT_ALREADY_EXISTS")
    before = path.stat()
    actual = digest(path)
    if actual != expected_hash:
        raise ValueError("PARQUET_HASH_MISMATCH")
    chosen_ui = ui_samples(inventory)
    ui_evidence = []
    parquet = pq.ParquetFile(path)
    unique: set[str] = set()
    payloads: dict[str, dict[str, Any]] = {}
    locations = []
    totals = {"rows": 0, "statute_occurrences": 0, "nonempty_occurrences": 0}
    statuses: dict[str, int] = {}

    def batches():
        for batch in parquet.iter_batches(
            batch_size=128,
            columns=["__legacy_position", "case_txt_scraped_with_tags"],
            use_threads=False,
        ):
            rows = batch.to_pylist()
            for row in rows:
                sample = chosen_ui.get(row["__legacy_position"])
                if sample is not None:
                    html = _text(row["case_txt_scraped_with_tags"])
                    a, b = sample["html_start"], sample["html_end"]
                    if sha256(html.encode()).hexdigest() != sample["parent_html_sha256"]:
                        raise ValueError("UI_PARENT_HASH_MISMATCH")
                    ui_evidence.append(
                        {
                            "position": row["__legacy_position"],
                            "original_src": sample["original_src"],
                            "image_name": sample.get("name"),
                            "category": sample["category"],
                            "classification_basis": (
                                "Known historical provider filename alert_img_01.png"
                            ),
                            "parent_html_sha256": sample["parent_html_sha256"],
                            "html_start": a,
                            "html_end": b,
                            "html_tag": html[a:b],
                            "before": html[max(0, a - 300) : a],
                            "after": html[b : b + 300],
                        }
                    )
            yield rows

    # map buffersize bounds pending Parquet batches under Python 3.12 through an
    # explicit small rolling queue; a 4-process scan never queues the full corpus.
    with ProcessPoolExecutor(
        max_workers=processes, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        iterator = iter(batches())
        pending = []
        exhausted = False
        while pending or not exhausted:
            while not exhausted and len(pending) < processes * 2:
                try:
                    pending.append(pool.submit(inspect_batch, next(iterator)))
                except StopIteration:
                    exhausted = True
            if not pending:
                break
            result = pending.pop(0).result()
            for key in totals:
                totals[key] += result[key]
            unique.update(result["payload_hashes"])
            payloads.update(result["payloads"])
            locations.extend(result["locations"])
            for key, count in result["status_counts"].items():
                statuses[key] = statuses.get(key, 0) + count
            if totals["rows"] % 4096 == 0:
                print(
                    json.dumps(
                        {
                            "rows": totals["rows"],
                            "unique_payloads": len(unique),
                            "visual_payloads": len(payloads),
                        }
                    ),
                    flush=True,
                )
    after_hash = digest(path)
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or actual != after_hash
    ):
        raise ValueError("PARQUET_CHANGED_DURING_AUDIT")
    if totals["rows"] != parquet.metadata.num_rows:
        raise ValueError("AUDIT_ROW_RECONCILIATION_FAILED")
    report = {
        "version": VERSION,
        "input": {
            "parquet_path": str(path.resolve()),
            "parquet_sha256": actual,
            "parquet_after_sha256": after_hash,
            "snapshot_sha256": legacy_snapshot(path),
            "size_bytes": before.st_size,
            "unchanged": True,
        },
        "scope": (
            "All nonempty preserved legacy lawgo jtable payloads; static visual references only."
        ),
        "totals": {
            **totals,
            "unique_nonempty_payloads": len(unique),
            "unique_visual_payloads": len(payloads),
            "unique_payload_img_tags": sum(len(p["images"]) for p in payloads.values()),
            "payload_parent_locations": len(locations),
            "img_parent_occurrences": sum(
                len(payloads[p["payload_sha256"]]["images"]) for p in locations
            ),
        },
        "statute_statuses": statuses,
        "payloads": list(payloads.values()),
        "parent_locations": locations,
        "provider_ui_samples": ui_evidence,
        "limitations": [
            "No download, OCR, JavaScript execution or source recrawl.",
            "CSS URL and embedded element candidates are observations, not verified image content.",
            "Original strings and files were not modified.",
        ],
        "processes": processes,
        "elapsed_seconds": monotonic() - start,
    }
    json_write(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--images-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--processes", type=int, choices=range(1, 5), default=4)
    args = parser.parse_args()
    report = run(
        args.parquet, args.output, args.expected_sha256, args.images_inventory, args.processes
    )
    print(
        json.dumps({"totals": report["totals"], "elapsed_seconds": report["elapsed_seconds"]}),
        flush=True,
    )
