"""Read-only text-vs-DataFrame audit; source IDs are historical links."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath


def legacy_newlines(text):
    """Match Python text-mode reading without modifying preserved source bytes."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def source_ids(path):
    if path.parent.name == "glaw_updated_panre_txt" and re.fullmatch(r"[0-9]+", path.stem):
        return {"scourt": path.stem}, None
    if path.parent.name == "lawgo_jomunupdated_panre_txt":
        match = re.fullmatch(r"([0-9]+)-([0-9]+|empty)-([0-9]+|empty)", path.stem)
        if match:
            ids = {
                source: value
                for source, value in zip(("scourt", "law_go_kr"), (match[2], match[3]), strict=True)
                if value not in {"empty", "0"}
            }
            return ids, int(match[1])
    return {}, None


def classify(exact_positions, ids, source_index):
    if exact_positions:
        return "EXACT_STORED_FIELD_MATCH", sorted(exact_positions)
    groups = [set(source_index[source].get(value, [])) for source, value in ids.items()]
    if groups:
        intersection = set.intersection(*groups)
        if intersection:
            return "SOURCE_ID_LINK_CONTENT_DIFFERS", sorted(intersection)
        union = set.union(*groups)
        if union:
            return "SOURCE_ID_PARTIAL_OR_PAIR_CONFLICT", sorted(union)
        return "SOURCE_IDS_NOT_IN_CORPUS", []
    return "NO_USABLE_FILENAME_SOURCE_ID", []


def content_crosschecks(items):
    enriched = defaultdict(list)
    conflicts = []
    for item in items:
        matches = {match["position"] for match in item.get("newline_fields", [])}
        groups = [set(positions) for positions in item.get("source_membership", {}).values()]
        linked = set.intersection(*groups) if groups else set()
        if matches and groups and not (matches & linked):
            conflicts.append(
                {
                    "path": item["path"],
                    "content_positions": sorted(matches),
                    "source_positions": sorted(linked),
                }
            )
        if (
            "lawgo_jomunupdated_panre_txt" in item["path"]
            and item["status"] == "LEGACY_NEWLINE_FIELD_MATCH"
        ):
            enriched[item["filename_source_ids"].get("scourt")].append(item)
    covered = 0
    remaining = []
    for item in items:
        if item["status"] != "SOURCE_ID_LINK_CONTENT_DIFFERS":
            continue
        counterparts = [
            other["path"]
            for other in enriched.get(item["filename_source_ids"].get("scourt"), [])
            if {match["position"] for match in other["newline_fields"]}
            & set(item["candidate_positions"])
        ]
        if counterparts:
            covered += 1
        else:
            remaining.append({"file": item["path"], "matched_enriched_files": []})
    return {
        "newline_content_source_assignment_conflicts": conflicts,
        "basic_variants_with_exact_enriched_counterpart": covered,
        "basic_variants_without_exact_enriched_counterpart": remaining,
    }


def audit(snapshot, expected_hash, roots, report_path, inventory_path):
    from inspect_legacy_pickle import load_data

    for output in (report_path, inventory_path):
        if any(output.resolve().is_relative_to(root.resolve()) for root in roots):
            raise ValueError("OUTPUT_INSIDE_LEGACY_ROOT")
    stat_before = snapshot.stat()
    with snapshot.open("rb") as handle:
        snapshot_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    if snapshot_hash != expected_hash:
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    print("Snapshot verified; loading preserved DataFrame", flush=True)
    frame = load_data(snapshot)
    source_index = {"scourt": defaultdict(list), "law_go_kr": defaultdict(list)}
    field_hashes = defaultdict(list)
    path_roots = Counter()
    for position in range(len(frame)):
        for source, column in (("scourt", "gmeta_contId"), ("law_go_kr", "lmeta_serialno")):
            value = frame[column].iloc[position]
            if isinstance(value, str) and value.strip() not in {"", "0", "empty"}:
                source_index[source][value.strip()].append(position)
        for column in ("case_txt_scraped_with_tags", "case_txt_in_file"):
            value = frame[column].iloc[position]
            if isinstance(value, str):
                digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
                field_hashes[digest].append((position, column))
        locator = frame["folder_file_name"].iloc[position]
        if isinstance(locator, str):
            parts = PureWindowsPath(locator.replace("/", "\\")).parts
            if len(parts) > 1 and parts[0].endswith("\\"):
                path_roots[str(PureWindowsPath(parts[0], parts[1]))] += 1
        if (position + 1) % 10000 == 0:
            print(f"Indexed {position + 1} DataFrame rows", flush=True)
    hash_cache = inventory_path.parent / "corpus-body-field-hashes.json"
    hash_cache.parent.mkdir(parents=True, exist_ok=True)
    hash_cache.write_text(
        json.dumps(
            {"snapshot_sha256": snapshot_hash, "fields": dict(field_hashes)}, ensure_ascii=False
        )
        + "\n"
    )
    items = []
    scan_errors = []
    skipped_symlinks = []
    for root in roots:

        def on_error(error):
            scan_errors.append({"path": error.filename, "error": type(error).__name__})

        for directory, dirs, files in os.walk(root, onerror=on_error):
            kept = []
            for name in dirs:
                path = Path(directory) / name
                if path.is_symlink():
                    skipped_symlinks.append(str(path))
                elif name not in {".git", ".venv", "__pycache__", "node_modules"}:
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(files):
                path = Path(directory) / name
                if path.suffix.lower() not in {".txt", ".html", ".htm"}:
                    continue
                item = {"root": str(root), "path": str(path.relative_to(root))}
                if path.is_symlink():
                    item["status"] = "SYMLINK_NOT_READ"
                    items.append(item)
                    continue
                try:
                    before = path.stat()
                    raw = path.read_bytes()
                    digest = hashlib.sha256(raw).hexdigest()
                    text = raw.decode("utf-8")
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError("TEXT_CHANGED_DURING_AUDIT")
                except (OSError, UnicodeError, ValueError) as error:
                    item.update(status="READ_OR_ENCODING_FAILURE", error=type(error).__name__)
                    items.append(item)
                    continue
                ids, row_hint = source_ids(path)
                exact = field_hashes.get(digest, [])
                status, candidates = classify({p for p, _ in exact}, ids, source_index)
                newline_hash = hashlib.sha256(legacy_newlines(text).encode("utf-8")).hexdigest()
                newline_matches = field_hashes.get(newline_hash, [])
                if not exact and newline_matches:
                    status = "LEGACY_NEWLINE_FIELD_MATCH"
                    candidates = sorted({position for position, _ in newline_matches})
                item.update(
                    size_bytes=len(raw),
                    sha256=digest,
                    filename_source_ids=ids,
                    filename_row_hint=row_hint,
                    status=status,
                    candidate_positions=candidates,
                    exact_fields=[{"position": p, "field": field} for p, field in exact],
                    newline_fields=[
                        {"position": p, "field": field} for p, field in newline_matches
                    ],
                    newline_rules="Python text-mode universal newlines; original bytes unchanged",
                    empty_file=not raw,
                    source_membership={
                        source: source_index[source].get(value, []) for source, value in ids.items()
                    },
                )
                if status in {
                    "SOURCE_IDS_NOT_IN_CORPUS",
                    "NO_USABLE_FILENAME_SOURCE_ID",
                    "SOURCE_ID_PARTIAL_OR_PAIR_CONFLICT",
                }:
                    # Diagnostic text only; it is not an identity resolver or body normalization.
                    item["diagnostic_prefix"] = re.sub(r"<[^>]*>", " ", text[:12000])[:2500]
                    item["candidate_metadata"] = [
                        {
                            column: str(frame[column].iloc[p])
                            for column in (
                                "court_name",
                                "case_no",
                                "case_full_no",
                                "gmeta_contId",
                                "lmeta_serialno",
                            )
                        }
                        | {"position": p}
                        for p in candidates[:10]
                    ]
                items.append(item)
    after = snapshot.stat()
    if (stat_before.st_size, stat_before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("SNAPSHOT_CHANGED_DURING_AUDIT")
    groups = defaultdict(list)
    exact_rows = set()
    linked_rows = set()
    by_directory = defaultdict(Counter)
    for item in items:
        if "sha256" in item:
            groups[item["sha256"]].append(item["path"])
        exact_rows.update(match["position"] for match in item.get("exact_fields", []))
        for positions in item.get("source_membership", {}).values():
            linked_rows.update(positions)
        by_directory[str(Path(item["path"]).parent)][item["status"]] += 1
    old_roots = []
    for original, count in path_roots.items():
        parsed = PureWindowsPath(original)
        local = Path("/mnt") / parsed.drive[0].lower() / parsed.parts[1]
        old_roots.append(
            {
                "original": original,
                "corpus_rows": count,
                "current_literal_path": str(local),
                "exists": local.exists(),
            }
        )
    summary = {
        "checked_at": datetime.now(UTC).isoformat(),
        "method": "Exact UTF-8 field hashes over all rows and filename source-ID membership",
        "snapshot": str(snapshot),
        "snapshot_sha256": snapshot_hash,
        "rows": len(frame),
        "columns": len(frame.columns),
        "roots": [str(root) for root in roots],
        "files": len(items),
        "status_counts": dict(Counter(item["status"] for item in items)),
        "by_directory": {name: dict(counts) for name, counts in by_directory.items()},
        "unique_file_hashes": len(groups),
        "duplicate_hash_groups": sum(len(v) > 1 for v in groups.values()),
        "duplicate_file_copies_beyond_first": sum(len(v) - 1 for v in groups.values()),
        "corpus_rows_with_exact_file_content": len(exact_rows),
        "corpus_rows_with_filename_source_link": len(linked_rows),
        "historical_locator_roots": old_roots,
        "scan_errors": scan_errors,
        "skipped_symlink_directories": skipped_symlinks,
        "unmatched_files": [
            item
            for item in items
            if item["status"]
            not in {
                "EXACT_STORED_FIELD_MATCH",
                "LEGACY_NEWLINE_FIELD_MATCH",
                "SOURCE_ID_LINK_CONTENT_DIFFERS",
            }
        ],
        "limits": [
            "Content difference is not a new case or missing legal text verdict.",
            "Filename IDs are historical links, not permanent canonical IDs.",
            "No filesystem-wide scan outside the listed roots.",
            "No DB import, identity relink, source mutation or live retrieval.",
        ],
    }
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    )
    summary.update(content_crosschecks(items))
    summary["inventory_path"] = str(inventory_path)
    summary["inventory_sha256"] = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    targeted = []
    for position in range(len(frame)):
        if str(frame["court_name"].iloc[position]).strip() == "중앙해양안전심판원":
            value = frame["case_txt_scraped_with_tags"].iloc[position]
            targeted.append(
                {
                    "position": position,
                    "metadata": {
                        name: str(frame[name].iloc[position])
                        for name in (
                            "court_name",
                            "case_no",
                            "case_full_no",
                            "gmeta_contId",
                            "lmeta_serialno",
                        )
                    },
                    "html_characters": len(value) if isinstance(value, str) else None,
                    "html_prefix": value[:500] if isinstance(value, str) else None,
                    "image_tags": len(re.findall(r"<img\b", value, re.I))
                    if isinstance(value, str)
                    else None,
                }
            )
    summary["central_maritime_metadata_candidates"] = targeted
    summary["newline_match_files"] = sum(bool(item.get("newline_fields")) for item in items)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "files",
                    "status_counts",
                    "unique_file_hashes",
                    "corpus_rows_with_exact_file_content",
                    "corpus_rows_with_filename_source_link",
                    "historical_locator_roots",
                )
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    audit(args.snapshot, args.expected_sha256, args.root, args.report, args.inventory)
