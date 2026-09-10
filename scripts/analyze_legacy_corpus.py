"""Read-only whole-corpus ID/profile audit plus deterministic stratified samples.

Run with the analysis-only pandas/numpy versions documented in the report.
This script neither imports legacy code nor writes into the supplied legacy root.
"""

import argparse
import csv
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from inspect_legacy_pickle import load_data


def missing(value):
    if value is None:
        return "None"
    if isinstance(value, str):
        if not value.strip():
            return "blank"
        if value.strip().lower() in {"empty", "nan", "none", "0"}:
            return "string_" + value.strip().lower()
    if isinstance(value, (int, float)) and value == 0:
        return "numeric_zero"
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    if isinstance(value, (list, tuple, dict)) and not value:
        return "empty_container"
    return None


def official_id(value):
    if missing(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def brief(value, limit=180):
    if missing(value):
        return {"missing": missing(value), "type": type(value).__name__}
    if not isinstance(value, (str, int, float, bool, list, tuple, dict, datetime)):
        return {"type": type(value).__name__, "value_not_serialized": True}
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    return {"type": type(value).__name__, "length": len(text), "prefix": text[:limit]}


def digest_file(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def analyze(root, output):
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Report output must be outside the legacy input root")
    if Path("data/legacy-audit").resolve().is_relative_to(root.resolve()):
        raise ValueError("Metadata projection must be outside the legacy input root")
    corpus = root / "df_glaw_corpus/df_glaw_corpus_fullest_gmeta_lmeta.pickle"
    print("Loading final corpus through allowlisted data unpickler", flush=True)
    df = load_data(corpus)
    print("Loaded", df.shape, "columns", list(df.columns), flush=True)
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Expected a DataFrame")
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "source_path": str(corpus),
        "source_size": corpus.stat().st_size,
        "source_sha256": digest_file(corpus),
        "method": (
            "Full DataFrame profile plus seeded stratified samples; restricted data-class "
            "unpickler; no legacy imports, source fetch or source writes."
        ),
        "analysis_runtime": {"pandas": pd.__version__, "numpy": __import__("numpy").__version__},
        "rows": len(df),
        "columns": list(df.columns),
        "index_type": type(df.index).__name__,
        "index_unique": bool(df.index.is_unique),
        "index_min": str(df.index.min()),
        "index_max": str(df.index.max()),
        "fields": {},
        "id_columns": {},
    }
    for column in df.columns:
        values = df[column].tolist()
        report["fields"][column] = {
            "types": dict(Counter(type(v).__name__ for v in values)),
            "missing": dict(Counter(missing(v) for v in values if missing(v))),
            "present_count": sum(missing(v) is None for v in values),
        }
    id_maps = {}
    for column in [
        c
        for c in df.columns
        if re.search(r"(^id$|_id$|contId|serialno|canonical|caseId|case_id)", c, re.I)
    ]:
        groups = defaultdict(list)
        for pos, value in enumerate(df[column]):
            normalized = official_id(value)
            if normalized is not None:
                groups[normalized].append(pos)
        duplicates = {key: rows for key, rows in groups.items() if len(rows) > 1}
        id_maps[column] = groups
        report["id_columns"][column] = {
            "present_rows": sum(map(len, groups.values())),
            "unique_ids": len(groups),
            "duplicate_ids": len(duplicates),
            "rows_in_duplicate_groups": sum(map(len, duplicates.values())),
            "duplicate_examples": [
                {"id": key, "positions": rows[:12]} for key, rows in list(duplicates.items())[:20]
            ],
        }
    g = [official_id(v) for v in df.get("gmeta_contId", pd.Series([None] * len(df)))]
    lawgo_ids = [official_id(v) for v in df.get("lmeta_serialno", pd.Series([None] * len(df)))]
    report["source_id_coverage"] = dict(
        Counter(
            "both" if a and b else "scourt_only" if a else "law_go_kr_only" if b else "neither"
            for a, b in zip(g, lawgo_ids, strict=True)
        )
    )
    pair_groups = defaultdict(list)
    for pos, pair in enumerate(zip(g, lawgo_ids, strict=True)):
        if pair[0] or pair[1]:
            pair_groups[pair].append(pos)
    report["duplicate_id_pairs"] = [
        {"scourt": pair[0], "law_go_kr": pair[1], "positions": rows[:20]}
        for pair, rows in pair_groups.items()
        if len(rows) > 1
    ]
    g_to_l, l_to_g = defaultdict(set), defaultdict(set)
    for a, b in zip(g, lawgo_ids, strict=True):
        if a and b:
            g_to_l[a].add(b)
            l_to_g[b].add(a)
    report["cross_source_cardinality"] = {
        "scourt_to_multiple_lawgo": {a: sorted(bs) for a, bs in g_to_l.items() if len(bs) > 1},
        "lawgo_to_multiple_scourt": {b: sorted(aa) for b, aa in l_to_g.items() if len(aa) > 1},
        "observed_pairs": sum(map(len, g_to_l.values())),
    }
    business = defaultdict(list)
    for pos, (_, row) in enumerate(df.iterrows()):
        court, number = row.get("court_name"), row.get("case_no")
        if (
            isinstance(court, str)
            and isinstance(number, str)
            and not missing(court)
            and not missing(number)
        ):
            business[(court.strip(), number.strip())].append(pos)
    duplicate_keys = {key: rows for key, rows in business.items() if len(rows) > 1}
    report["court_case_key_raw"] = {
        "method": (
            "Persisted court_name + entire case_no, trim only; no aliases, branch collapsing "
            "or merged-docket splitting."
        ),
        "covered_rows": sum(map(len, business.values())),
        "unique_keys": len(business),
        "duplicate_keys": len(duplicate_keys),
        "rows_in_duplicate_keys": sum(map(len, duplicate_keys.values())),
        "examples": [
            {
                "court": key[0],
                "case_number": key[1],
                "positions": rows[:15],
                "citations": [str(df.iloc[pos].get("case_full_no")) for pos in rows[:15]],
            }
            for key, rows in list(duplicate_keys.items())[:30]
        ],
    }
    metadata_path = Path("data/legacy-audit/metadata-20241126.jsonl")
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", encoding="utf-8") as handle:
        for pos, (_, row) in enumerate(df.iterrows()):
            record = {
                "snapshot_sha256": report["source_sha256"],
                "position": pos,
                "legacy_index": str(df.index[pos]),
                "gmeta_contId": g[pos],
                "lmeta_serialno": lawgo_ids[pos],
            }
            for column in (
                "court_name",
                "case_no",
                "case_full_no",
                "decision_date",
                "site",
                "gmeta_saNo",
                "gmeta_bubNm",
                "gmeta_sngoDay",
                "lmeta_saNo",
                "lmeta_bubNm",
                "lmeta_sngoDay",
                "folder_file_name",
            ):
                value = row.get(column)
                record[column] = (
                    value if isinstance(value, (str, int, float)) and not missing(value) else None
                )
                record[column + "_type"] = type(value).__name__
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    report["local_metadata_extract"] = {
        "path": str(metadata_path),
        "sha256": digest_file(metadata_path),
        "rows": len(df),
        "note": "Analysis projection only; not imported operational records.",
    }
    for column in ("case_full_no", "case_no", "folder_file_name"):
        if column in df:
            counts = Counter(str(v).strip() for v in df[column] if missing(v) is None)
            report[column + "_duplicates"] = {
                "unique_values": len(counts),
                "duplicate_values": sum(n > 1 for n in counts.values()),
                "extra_rows": sum(n - 1 for n in counts.values()),
                "examples": counts.most_common(12),
            }
    for column in ("site", "court_name", "gmeta_bubNm", "case_sort", "lmeta_bubNm"):
        if column in df:
            report[column + "_distribution"] = dict(
                Counter(str(v) for v in df[column]).most_common(30)
            )
    strata = defaultdict(list)
    for pos, (_, row) in enumerate(df.iterrows()):
        key = (
            ("issue" if missing(row.get("decision_items")) is None else "no_issue")
            + "/"
            + ("summary" if missing(row.get("decision_gists")) is None else "no_summary")
        )
        strata[key].append(pos)
        if not g[pos] and not lawgo_ids[pos]:
            strata["no_official_id"].append(pos)
        if bool(g[pos]) != bool(lawgo_ids[pos]):
            strata["one_source_only"].append(pos)
    report["editorial_coverage"] = {key: len(rows) for key, rows in strata.items() if "/" in key}
    rng = random.Random(20260910)
    selected = set(rng.sample(range(len(df)), min(100, len(df))))
    sample_reasons = defaultdict(list)
    for pos in selected:
        sample_reasons[pos].append("seeded_uniform")
    for key, rows in strata.items():
        for pos in rng.sample(rows, min(12, len(rows))):
            selected.add(pos)
            sample_reasons[pos].append(key)
    for column, groups in id_maps.items():
        for rows in [rows for rows in groups.values() if len(rows) > 1][:8]:
            for pos in rows[:3]:
                selected.add(pos)
                sample_reasons[pos].append("duplicate_" + column)
    samples = []
    sampled_fields = [
        c
        for c in (
            "case_full_no",
            "case_no",
            "court_name",
            "decision_date",
            "site",
            "gmeta_contId",
            "gmeta_saNo",
            "gmeta_bubNm",
            "gmeta_sngoDay",
            "gmeta_panTypeNm",
            "lmeta_serialno",
            "lmeta_saNo",
            "lmeta_bubNm",
            "lmeta_sngoDay",
            "lmeta_deType",
            "folder_file_name",
            "file_created_time",
        )
        if c in df
    ]
    for pos in sorted(selected):
        row = df.iloc[pos]
        samples.append(
            {
                "position": pos,
                "legacy_index": str(df.index[pos]),
                "selection_reasons": sample_reasons[pos],
                "metadata": {c: brief(row[c], 220) for c in sampled_fields},
                "content": {
                    c: brief(row[c], 160 if c in {"decision_items", "decision_gists"} else 0)
                    for c in (
                        "case_txt_scraped_with_tags",
                        "case_txt_in_file",
                        "decision_items",
                        "decision_gists",
                        "main_decision",
                        "reasoning",
                        "applicable_acts",
                        "applicable_precedents",
                    )
                    if c in df
                },
                "img_tag_count_in_saved_html": len(
                    re.findall(r"<img\b", str(row.get("case_txt_scraped_with_tags", "")), re.I)
                ),
            }
        )
    report["sample_design"] = {
        "random_seed": 20260910,
        "uniform_rows": min(100, len(df)),
        "total_distinct_rows": len(samples),
        "note": (
            "Targeted oversampling of missing editorial/IDs and duplicate IDs; "
            "not a prevalence estimator."
        ),
    }
    report["samples"] = samples
    csv_path = corpus.parent / "forcheckStandardCases.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    report["csv_crosscheck"] = {
        "rows": len(csv_rows),
        "sha256": digest_file(csv_path),
        "positional_case_full_no_matches": sum(
            str(df.iloc[pos]["case_full_no"]) == row["case_full_no"]
            for pos, row in enumerate(csv_rows[: len(df)])
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "rows",
                    "id_columns",
                    "source_id_coverage",
                    "editorial_coverage",
                    "sample_design",
                    "csv_crosscheck",
                    "court_case_key_raw",
                )
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, required=True, help="A selected saved/YYYYMMDD snapshot"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.root, args.output)
