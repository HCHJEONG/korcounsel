"""Audit ID links and court/docket duplicate representations from the local projection."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from inspect_legacy_pickle import load_data


def normalized_date(value):
    digits = re.sub(r"[^0-9]", "", value or "")
    return digits if len(digits) == 8 else None


def citation_date(text):
    match = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", text or "")
    if match is None:
        return None
    year, month, day = map(int, match.groups())
    return f"{year:04d}{month:02d}{day:02d}"


def compact(row):
    return {
        k: row.get(k)
        for k in (
            "position",
            "court_name",
            "case_no",
            "case_full_no",
            "gmeta_contId",
            "gmeta_saNo",
            "gmeta_bubNm",
            "gmeta_sngoDay",
            "lmeta_serialno",
            "lmeta_saNo",
            "lmeta_bubNm",
            "lmeta_sngoDay",
        )
    }


def analyze(root, projection, output):
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Report output must be outside the legacy input root")
    rows = [json.loads(line) for line in projection.read_text().splitlines()]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["court_name"].strip(), row["case_no"].strip())].append(row)
    duplicate_groups = [group for group in groups.values() if len(group) > 1]
    categories, examples = Counter(), defaultdict(list)
    for group in duplicate_groups:
        dates = {citation_date(row["case_full_no"]) for row in group}
        citations = {row["case_full_no"].strip() for row in group}
        category = (
            "same_trimmed_citation"
            if len(citations) == 1
            else "same_citation_date"
            if len(dates) == 1
            else "different_citation_dates"
        )
        categories[category] += 1
        if len(examples[category]) < 8:
            examples[category].append([compact(row) for row in group])
    result = {
        "method": (
            "Full local metadata projection; dates are diagnostic extracted values, "
            "not corrected operational values."
        ),
        "rows": len(rows),
        "duplicate_business_key_groups": dict(categories),
        "examples": dict(examples),
    }
    cross = Counter()
    for row in rows:
        a, b = normalized_date(row.get("gmeta_sngoDay")), normalized_date(row.get("lmeta_sngoDay"))
        if a and b:
            cross["same_source_dates" if a == b else "different_source_dates"] += 1
        else:
            cross["missing_source_date"] += 1
    result["stored_source_date_comparison"] = dict(cross)
    result["no_government_id_examples"] = [
        compact(row) for row in rows if not row["gmeta_contId"] and not row["lmeta_serialno"]
    ][:12]
    result["catalogs"] = {}
    for source, relative, id_field, row_field in [
        (
            "law_go_kr",
            "lawgo_panre_metadata/lawgo_panre_metadata_list.pickle",
            "판례일련번호",
            "lmeta_serialno",
        ),
        ("scourt", "glaw_panre_metadata/glaw_panre_metadata_list.pickle", "contId", "gmeta_contId"),
    ]:
        path = root / relative
        catalog = load_data(path)
        print(
            source,
            "catalog",
            type(catalog).__name__,
            len(catalog),
            "keys",
            list(catalog[0]),
            flush=True,
        )
        mapping = defaultdict(list)
        for item in catalog:
            if id_field not in item and "gmeta" in item:
                item = item["gmeta"]
            mapping[str(item[id_field]).strip()].append(item)
        found = sum(bool(row[row_field]) and row[row_field] in mapping for row in rows)
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        result["catalogs"][source] = {
            "path": str(path),
            "sha256": digest,
            "rows": len(catalog),
            "unique_ids": len(mapping),
            "duplicate_ids": sum(len(items) > 1 for items in mapping.values()),
            "corpus_rows_found_by_id": found,
            "corpus_rows_with_id_not_in_catalog": sum(
                bool(row[row_field]) and row[row_field] not in mapping for row in rows
            ),
            "note": (
                "Historical catalog membership only; not current source completeness "
                "or deletion evidence."
            ),
        }
        examples_to_check = [325, 952, 331, 338, 1884, 8499, 2811, 6213, 86623, 190, 232, 86671]
        sample_matches = []
        for position in examples_to_check:
            row = rows[position]
            items = mapping.get(row[row_field], [])
            wanted = (
                ("contId", "bubNm", "saNo", "sngoDay", "panTypeNm")
                if source == "scourt"
                else ("판례일련번호", "법원명", "사건번호", "선고일자", "판결유형")
            )
            sample_matches.append(
                {
                    "position": position,
                    "catalog_matches": [{k: item.get(k) for k in wanted} for item in items],
                }
            )
        result["catalogs"][source]["targeted_matches"] = sample_matches
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "duplicate_groups": result["duplicate_business_key_groups"],
                "source_dates": cross,
                "catalogs": {
                    source: {k: v for k, v in value.items() if k != "targeted_matches"}
                    for source, value in result["catalogs"].items()
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.root, args.projection, args.output)
