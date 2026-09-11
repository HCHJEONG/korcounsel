"""Verify reader coverage and emit an immutable sidecar; this never updates the DB."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from hashlib import file_digest, sha256
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from klegal_gold.assets.images import validate_image  # noqa: E402
from klegal_gold.config import load_settings  # noqa: E402
from klegal_gold.db.session import Database  # noqa: E402
from klegal_gold.documents.reader import STATUTE_IMAGE_VERSION, image_occurrences  # noqa: E402
from klegal_gold.storage.files import FileStore  # noqa: E402

VERSION = "legacy-reader-coverage-2"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def load_inventory(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    if summary["version"] != "legacy-enrichment-inventory-1":
        raise ValueError("UNSUPPORTED_INVENTORY_VERSION")
    path = directory / "rows.jsonl"
    expected = summary["artifacts"]["rows.jsonl"]
    if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
        raise ValueError("INVENTORY_ROWS_HASH_MISMATCH")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    positions = [r["position"] for r in rows]
    if (
        len(rows) != summary["input"]["expected_rows"]
        or any(type(p) is not int or p < 0 for p in positions)
        or len(set(positions)) != len(rows)
        or any(r["snapshot_sha256"] != summary["input"]["snapshot_sha256"] for r in rows)
    ):
        raise ValueError("INVENTORY_LOCATOR_MISMATCH")
    return summary, rows


def import_rows(db: Database, job_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        return list(
            conn.execute(
                "SELECT b.row_position,b.status,b.input_artifact,b.record_artifact,"
                "r.snapshot_hash FROM legacy_bundle_rows b LEFT JOIN legacy_records r "
                "ON r.artifact_id=b.record_artifact WHERE b.job_id=%s ORDER BY b.row_position",
                (job_id,),
            ).fetchall()
        )


def load_registry(db: Database, snapshot: str) -> dict[str, dict[str, Any]]:
    with db.connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = conn.execute(
            "SELECT a.artifact_id,a.blob_hash,a.parent_id,a.metadata,a.created_at,"
            "b.storage_key,b.size_bytes FROM artifacts a JOIN blobs b ON b.sha256=a.blob_hash "
            "WHERE (a.metadata->>'kind'='READER_DOCUMENT' "
            "AND a.metadata->>'origin'='LEGACY_CORPUS' "
            "AND a.metadata->>'legacy_snapshot'=%s) "
            "OR a.metadata->>'kind' IN "
            "('READER_SOURCE_HTML','LEGACY_LAWGO_PAYLOAD','PRESERVED_IMAGE_BYTES')",
            (snapshot,),
        ).fetchall()
    return {r["artifact_id"]: r for r in rows}


def import_fingerprint(rows: list[dict[str, Any]]) -> str:
    return sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


class Graph:
    def __init__(
        self, registry: dict[str, dict[str, Any]], data_dir: Path, *, verify_blobs: bool
    ) -> None:
        self.registry = registry
        self.store = FileStore(data_dir.resolve(strict=True))
        self.verify_blobs = verify_blobs
        self.checked: set[str] = set()
        self.hashed: set[str] = set()
        self.decoded: set[str] = set()

    def check(self, artifact_id: str, expected_hash: str, *, hash_file: bool = True) -> Path:
        row = self.registry.get(artifact_id)
        if row is None:
            raise ValueError("REFERENCED_ARTIFACT_MISSING")
        if row["blob_hash"] != expected_hash or row["storage_key"] != (
            f"blobs/{expected_hash[:2]}/{expected_hash}"
        ):
            raise ValueError("REFERENCED_ARTIFACT_HASH_MISMATCH")
        path = self.store.path(row["storage_key"])
        if artifact_id not in self.checked:
            if path.stat().st_size != row["size_bytes"]:
                raise ValueError("REFERENCED_FILE_SIZE_MISMATCH")
            self.checked.add(artifact_id)
        if self.verify_blobs and hash_file and expected_hash not in self.hashed:
            if digest(path) != expected_hash:
                raise ValueError("REFERENCED_FILE_HASH_MISMATCH")
            self.hashed.add(expected_hash)
        return path

    def manifest(self, artifact_id: str) -> dict[str, Any]:
        expected = artifact_id.removeprefix("reader:")
        path = self.check(artifact_id, expected, hash_file=False)
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise ValueError("READER_MANIFEST_HASH_MISMATCH")
        self.hashed.add(expected)
        return dict(json.loads(raw))

    def image(self, expected_hash: str) -> None:
        path = self.check("reader-image:" + expected_hash, expected_hash)
        if self.verify_blobs and expected_hash not in self.decoded:
            validate_image(path.read_bytes())
            self.decoded.add(expected_hash)


def load_statute_image_audit(
    path: Path, summary: dict[str, Any], inventory: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    raw = path.read_bytes()
    report = json.loads(raw)
    source = report.get("input", {})
    totals = report.get("totals", {})
    if (
        report.get("version") != "legacy-statute-image-audit-1"
        or source.get("parquet_sha256") != summary["input"]["parquet_sha256"]
        or source.get("parquet_after_sha256") != source.get("parquet_sha256")
        or source.get("snapshot_sha256") != summary["input"]["snapshot_sha256"]
        or source.get("unchanged") is not True
        or totals.get("rows") != len(inventory)
    ):
        raise ValueError("STATUTE_IMAGE_AUDIT_INPUT_MISMATCH")
    parents = {r["position"]: r for r in inventory}
    payloads = {r["payload_sha256"]: r for r in report["payloads"]}
    if len(payloads) != len(report["payloads"]):
        raise ValueError("DUPLICATE_STATUTE_IMAGE_AUDIT_PAYLOAD")
    expected: dict[int, list[dict[str, Any]]] = defaultdict(list)
    observed_parents = set()
    for location in report["parent_locations"]:
        position = location["position"]
        parent = parents.get(position)
        parent_key = (position, location["statute_order"])
        if (
            parent is None
            or location["parent_html_sha256"] != parent["body_hash"]
            or parent_key in observed_parents
            or type(location["statute_order"]) is not int
            or not 0 <= location["statute_order"] < parent["statute_occurrences"]
        ):
            raise ValueError("STATUTE_IMAGE_AUDIT_PARENT_MISMATCH")
        observed_parents.add(parent_key)
        key = location["payload_sha256"]
        payload = payloads[key]
        for image in payload["images"]:
            if image["parent_html_sha256"] != key:
                raise ValueError("STATUTE_IMAGE_AUDIT_PAYLOAD_MISMATCH")
            expected[position].append(
                {
                    **image,
                    "article_order": location["statute_order"],
                    "article_reference_id": location["statute_reference_id"],
                    "payload_sha256": key,
                    "parent_body_sha256": parent["body_hash"],
                }
            )
    for refs in expected.values():
        refs.sort(key=lambda r: (r["article_order"], r["order"]))
    if (
        totals.get("unique_visual_payloads") != len(payloads)
        or totals.get("unique_payload_img_tags") != sum(len(r["images"]) for r in payloads.values())
        or totals.get("payload_parent_locations") != len(observed_parents)
        or totals.get("img_parent_occurrences") != sum(len(refs) for refs in expected.values())
    ):
        raise ValueError("STATUTE_IMAGE_AUDIT_COUNT_MISMATCH")
    return {
        "path": str(path.resolve()),
        "sha256": sha256(raw).hexdigest(),
        "rows_with_images": sum(bool(refs) for refs in expected.values()),
        "image_occurrences": sum(len(refs) for refs in expected.values()),
    }, dict(expected)


def statute_image_counts(
    manifest: dict[str, Any],
    meta: dict[str, Any],
    graph: Graph,
    audited: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    expected = []
    for article in manifest["statutes"]:
        if not article["payload"]:
            continue
        for image in image_occurrences(
            article["payload"], source_id="", base_url="https://www.law.go.kr/"
        ):
            expected.append(
                {
                    **image,
                    "html_line_column": list(image["html_line_column"]),
                    "article_order": article["order"],
                    "article_reference_id": article["reference_id"],
                    "payload_sha256": article["payload_sha256"],
                    "parent_body_sha256": manifest["html_sha256"],
                }
            )
    if audited is not None and expected != audited:
        raise ValueError("STATUTE_IMAGE_AUDIT_MANIFEST_MISMATCH")
    refs = manifest.get("statute_images")
    present = "statute_images" in manifest
    if not present and manifest.get("version") != STATUTE_IMAGE_VERSION:
        return {
            "statute_image_occurrences": len(expected),
            "acquired_statute_images": 0,
            "unacquired_statute_images": len(expected),
            "missing_statute_image_references": len(expected),
            "statute_image_coverage_status": "MISSING_REFERENCES" if expected else "NO_IMAGES",
        }
    if manifest.get("version") != STATUTE_IMAGE_VERSION or not isinstance(refs, list):
        raise ValueError("INVALID_STATUTE_IMAGE_MANIFEST")
    if len(refs) != len(expected):
        raise ValueError("STATUTE_IMAGE_COUNT_MISMATCH")
    acquired = 0
    for original, linked in zip(expected, refs, strict=True):
        if not isinstance(linked, dict) or any(
            key not in linked or linked[key] != value for key, value in original.items()
        ):
            raise ValueError("STATUTE_IMAGE_POSITION_MISMATCH")
        acquisition = linked.get("acquisition", {})
        if not isinstance(acquisition, dict):
            raise ValueError("INVALID_STATUTE_IMAGE_ACQUISITION")
        if linked.get("blob_hash"):
            digest = linked["blob_hash"]
            if (
                not isinstance(digest, str)
                or re.fullmatch("[0-9a-f]{64}", digest) is None
                or linked.get("status") != "ACQUIRED"
                or acquisition.get("status") != "ACQUIRED"
                or acquisition.get("sha256") != digest
                or acquisition.get("url") != linked.get("resolved_url")
            ):
                raise ValueError("INVALID_STATUTE_IMAGE_ACQUISITION")
            graph.image(digest)
            acquired += 1
        elif linked.get("status") == "ACQUIRED" or acquisition.get("status") == "ACQUIRED":
            raise ValueError("STATUTE_IMAGE_BLOB_MISSING")
    if (
        meta.get("statute_image_count") != len(refs)
        or meta.get("statute_image_acquired_count") != acquired
    ):
        raise ValueError("STATUTE_IMAGE_METADATA_COUNT_MISMATCH")
    return {
        "statute_image_occurrences": len(refs),
        "acquired_statute_images": acquired,
        "unacquired_statute_images": len(refs) - acquired,
        "missing_statute_image_references": 0,
        "statute_image_coverage_status": "REFERENCES_VERIFIED" if refs else "NO_IMAGES",
    }


def inspect_manifest(
    inventory: dict[str, Any],
    artifact_id: str,
    graph: Graph,
    audited_statute_images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest = graph.manifest(artifact_id)
    meta = graph.registry[artifact_id]["metadata"]
    provenance = manifest["provenance"]
    body_hash = inventory["body_hash"]
    if (
        manifest["origin"] != "LEGACY_CORPUS"
        or manifest["html_sha256"] != body_hash
        or provenance["row_position"] != inventory["position"]
        or provenance["snapshot_sha256"] != inventory["snapshot_sha256"]
        or provenance["original_index"] != inventory["original_index"]
        or provenance["field"] != inventory["body_field"]
        or manifest["source_id"] != inventory["source_id"]
    ):
        raise ValueError("MANIFEST_LOCATOR_MISMATCH")
    if graph.registry[artifact_id]["parent_id"] != manifest["html_artifact_id"]:
        raise ValueError("MANIFEST_PARENT_MISMATCH")
    body_path = graph.check(manifest["html_artifact_id"], body_hash)
    html = body_path.read_bytes().decode("utf-8") if graph.verify_blobs else None
    images, statutes = manifest["images"], manifest["statutes"]
    if (
        len(images) != inventory["image_occurrences"]
        or len(statutes) != inventory["statute_occurrences"]
    ):
        raise ValueError("OCCURRENCE_COUNT_MISMATCH")
    for refs in (images, statutes):
        for order, ref in enumerate(refs):
            if (
                ref["order"] != order
                or ref["parent_html_sha256"] != body_hash
                or not 0 <= ref["html_start"] < ref["html_end"] <= inventory["body_characters"]
            ):
                raise ValueError("OCCURRENCE_LOCATOR_MISMATCH")
            if html is not None and html[ref["html_start"] : ref["html_end"]] != ref["html_tag"]:
                raise ValueError("OCCURRENCE_TAG_MISMATCH")
    counts = Counter(str(item["status"]) for item in statutes)
    if any(
        counts[state] != inventory[key]
        for state, key in (
            ("PRESERVED", "preserved_statutes"),
            ("LEGACY_FAILURE", "failed_statutes"),
            ("UNLINKED", "unlinked_statutes"),
        )
    ):
        raise ValueError("STATUTE_STATE_COUNT_MISMATCH")
    for article in statutes:
        payload = article["payload"]
        if sha256(payload.encode()).hexdigest() != article["payload_sha256"]:
            raise ValueError("STATUTE_PAYLOAD_HASH_MISMATCH")
        if payload:
            graph.check(article["payload_artifact_id"], article["payload_sha256"])
    image_states: Counter[str] = Counter()
    acquired = 0
    for image in images:
        image_states[str(image.get("status", "UNKNOWN"))] += 1
        if image.get("blob_hash"):
            graph.image(image["blob_hash"])
            acquired += 1
            if not image.get("link_evidence"):
                raise ValueError("IMAGE_LINK_EVIDENCE_MISSING")
        elif image.get("status") == "ACQUIRED":
            raise ValueError("ACQUIRED_IMAGE_BYTES_MISSING")
    if meta["image_count"] != len(images) or meta["acquired_count"] != acquired:
        raise ValueError("READER_METADATA_COUNT_MISMATCH")
    return {
        "image_occurrences": len(images),
        "acquired_images": acquired,
        "unacquired_images": len(images) - acquired,
        "statute_occurrences": len(statutes),
        "preserved_statutes": counts["PRESERVED"],
        "failed_statutes": counts["LEGACY_FAILURE"],
        "unlinked_statutes": counts["UNLINKED"],
        "image_states": dict(image_states),
        **statute_image_counts(manifest, meta, graph, audited_statute_images),
    }


SIDECAR_SCHEMA = pa.schema(
    [
        ("snapshot_sha256", pa.string()),
        ("position", pa.int64()),
        ("original_index", pa.string()),
        ("body_hash", pa.string()),
        ("reader_revision", pa.string()),
        ("status", pa.string()),
        ("revision_count", pa.int64()),
        ("other_body_revision_count", pa.int64()),
        ("image_occurrences", pa.int64()),
        ("acquired_images", pa.int64()),
        ("unacquired_images", pa.int64()),
        ("statute_occurrences", pa.int64()),
        ("preserved_statutes", pa.int64()),
        ("failed_statutes", pa.int64()),
        ("unlinked_statutes", pa.int64()),
        ("statute_image_occurrences", pa.int64()),
        ("acquired_statute_images", pa.int64()),
        ("unacquired_statute_images", pa.int64()),
        ("missing_statute_image_references", pa.int64()),
        ("statute_image_coverage_status", pa.string()),
        ("error_codes", pa.list_(pa.string())),
    ]
)


def verify_coverage(
    inventory_dir: Path,
    output_dir: Path,
    data_dir: Path,
    registry: dict[str, dict[str, Any]],
    original_import: list[dict[str, Any]],
    *,
    verify_blobs: bool = False,
    statute_image_audit: Path | None = None,
    import_after: Callable[[], list[dict[str, Any]]] | None = None,
    progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, Any]:
    summary, inventory = load_inventory(inventory_dir)
    audit_meta = None
    audited_images = None
    if statute_image_audit is not None:
        audit_meta, audited_images = load_statute_image_audit(
            statute_image_audit, summary, inventory
        )
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    source = Path(summary["input"]["parquet_path"])
    source_hash = digest(source)
    if source_hash != summary["input"]["parquet_sha256"]:
        raise ValueError("SOURCE_PARQUET_HASH_MISMATCH")
    snapshot = summary["input"]["snapshot_sha256"]
    expected_positions = {r["position"] for r in inventory}
    original_positions = [r["row_position"] for r in original_import]
    import_matches = (
        len(original_import) == len(inventory)
        and set(original_positions) == expected_positions
        and all(
            r["status"] == "PRESERVED" and r["snapshot_hash"] == snapshot for r in original_import
        )
    )
    by_position: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in registry.values():
        meta = record["metadata"]
        if meta.get("kind") != "READER_DOCUMENT" or meta.get("origin") != "LEGACY_CORPUS":
            continue
        if meta.get("legacy_snapshot") != snapshot:
            continue
        by_position[int(meta["legacy_position"])].append(record)
    graph = Graph(registry, data_dir, verify_blobs=verify_blobs)
    rows = []
    totals: Counter[str] = Counter()
    image_states: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    for original in inventory:
        candidates = by_position.get(original["position"], [])
        matching = [
            r for r in candidates if r["metadata"]["legacy_body_hash"] == original["body_hash"]
        ]
        matching.sort(key=lambda r: (str(r["created_at"]), r["artifact_id"]), reverse=True)
        record = {
            **{
                k: original[k]
                for k in ("snapshot_sha256", "position", "original_index", "body_hash")
            },
            "reader_revision": None,
            "status": "MISSING",
            "revision_count": len(matching),
            "other_body_revision_count": len(candidates) - len(matching),
            "error_codes": [],
        }
        row_audit = (
            audited_images.get(original["position"], []) if audited_images is not None else None
        )
        if row_audit is not None:
            record.update(
                statute_image_occurrences=len(row_audit),
                acquired_statute_images=0,
                unacquired_statute_images=len(row_audit),
                missing_statute_image_references=len(row_audit),
                statute_image_coverage_status="READER_MISSING",
            )
        if matching:
            record["reader_revision"] = matching[0]["artifact_id"].removeprefix("reader:")
            try:
                observed = inspect_manifest(original, matching[0]["artifact_id"], graph, row_audit)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                record.update(
                    status="ERROR", error_codes=[code], statute_image_coverage_status="ERROR"
                )
                errors[code] += 1
            else:
                image_states.update(observed.pop("image_states"))
                record.update(status="STAGED_VERIFIED", **observed)
        rows.append(record)
        totals["rows"] += 1
        totals["rows_" + record["status"].lower()] += 1
        totals["rows_with_multiple_revisions"] += int(len(matching) > 1)
        totals["historical_revisions"] += max(0, len(matching) - 1)
        totals["rows_missing_statute_image_references"] += int(
            record.get("missing_statute_image_references", 0) > 0
        )
        for key in (
            "image_occurrences",
            "acquired_images",
            "unacquired_images",
            "statute_occurrences",
            "preserved_statutes",
            "failed_statutes",
            "unlinked_statutes",
            "statute_image_occurrences",
            "acquired_statute_images",
            "unacquired_statute_images",
            "missing_statute_image_references",
        ):
            if key in record:
                totals[key] += record[key]
        if progress and len(rows) % 1024 == 0:
            progress({"rows": len(rows), "expected_rows": len(inventory)})
    after = import_after() if import_after is not None else original_import
    input_unchanged = digest(source) == source_hash
    import_unchanged = import_fingerprint(original_import) == import_fingerprint(after)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_dir.with_name(output_dir.name + ".partial-" + uuid.uuid4().hex)
    temporary.mkdir()
    with (temporary / "reader-coverage.jsonl").open("w", encoding="utf-8") as stream:
        for record in rows:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    metadata = {
        b"coverage": json.dumps(
            {
                "version": VERSION,
                "snapshot_sha256": snapshot,
                "parquet_sha256": source_hash,
                "inventory_rows_sha256": summary["artifacts"]["rows.jsonl"]["sha256"],
                "statute_image_audit": audit_meta,
            },
            sort_keys=True,
        ).encode(),
    }
    table = pa.Table.from_pylist(rows, schema=SIDECAR_SCHEMA).replace_schema_metadata(metadata)
    sidecar = temporary / "reader-coverage.parquet"
    pq.write_table(table, sidecar, compression="zstd", row_group_size=1024)
    if pq.read_table(sidecar).to_pylist() != table.to_pylist():
        raise ValueError("COVERAGE_PARQUET_ROUND_TRIP_MISMATCH")
    complete = (
        totals["rows_staged_verified"] == len(inventory)
        and import_matches
        and import_unchanged
        and input_unchanged
    )
    report = {
        "version": VERSION,
        "inventory_summary_sha256": digest(inventory_dir / "summary.json"),
        "inventory_rows_sha256": summary["artifacts"]["rows.jsonl"]["sha256"],
        "parquet_sha256": source_hash,
        "snapshot_sha256": snapshot,
        "source_parquet_unchanged": input_unchanged,
        "import_rows": len(original_import),
        "import_matches_inventory": import_matches,
        "import_unchanged": import_unchanged,
        "import_fingerprint": import_fingerprint(original_import),
        "totals": dict(sorted(totals.items())),
        "image_states": dict(sorted(image_states.items())),
        "error_codes": dict(sorted(errors.items())),
        "complete_reader_registration": complete,
        "all_observed_images_acquired": (
            complete
            and totals["unacquired_images"] == 0
            and totals["unacquired_statute_images"] == 0
            and totals["missing_statute_image_references"] == 0
        ),
        "complete_statute_image_reference_coverage": (
            complete and totals["missing_statute_image_references"] == 0
        ),
        "statute_image_audit": audit_meta,
        "verify_blobs": verify_blobs,
        "unique_artifacts_checked": len(graph.checked),
        "unique_blobs_hashed": len(graph.hashed),
        "unique_images_decoded": len(graph.decoded),
        "unexpected_reader_positions": sorted(set(by_position) - expected_positions),
        "scope": (
            "Registration coverage and original counts are separate from image acquisition, "
            "statute version confirmation and browser verification. Multiple revisions are history."
        ),
        "artifacts": {
            name: {"sha256": digest(temporary / name), "bytes": (temporary / name).stat().st_size}
            for name in ("reader-coverage.jsonl", "reader-coverage.parquet")
        },
    }
    (temporary / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.rename(output_dir)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--import-job-id", type=uuid.UUID, required=True)
    parser.add_argument("--verify-blobs", action="store_true")
    parser.add_argument("--statute-image-audit", type=Path)
    args = parser.parse_args()
    summary, _ = load_inventory(args.inventory)
    settings = load_settings()
    db = Database.from_settings(settings)
    before = import_rows(db, str(args.import_job_id))
    registry = load_registry(db, summary["input"]["snapshot_sha256"])
    report = verify_coverage(
        args.inventory,
        args.output_dir,
        settings.data_dir,
        registry,
        before,
        verify_blobs=args.verify_blobs,
        statute_image_audit=args.statute_image_audit,
        import_after=lambda: import_rows(db, str(args.import_job_id)),
        progress=lambda value: print(json.dumps(value), flush=True),
    )
    print(json.dumps({"output_dir": str(args.output_dir), **report}, ensure_ascii=False))
    if not report["complete_reader_registration"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
