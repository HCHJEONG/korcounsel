"""Read-only identity candidate audit; never merges records or changes links."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pyarrow.parquet as pq
from klegal_gold.config import load_settings
from klegal_gold.db.session import Database
from klegal_gold.documents.image_links import TITLE_VERSION, _parse_display_title
from klegal_gold.fields.extract import visible
from klegal_gold.normalize.decision import court_comparison_key, decision_kind


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--saved-audit",
        type=Path,
        help="Reuse a hash-verified prior DB observation without connecting to PostgreSQL",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    baseline_path = (
        data
        / "quality-baseline-20260915/baseline-980f34cfe2dcd48eb4596fee2a8f32dc6a30b5b70640d4b227914d163a6da818.json"
    )
    baseline = json.loads(baseline_path.read_bytes())
    verified = {}

    def blob(digest):
        raw = (data / "blobs" / digest[:2] / digest).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        verified[digest] = len(raw)
        return json.loads(raw)

    legacy_path = data / "corrected-parquet-20260911-v1/legacy-corrected-full.parquet"
    columns = [
        "gmeta_contId",
        "gmeta_saNo",
        "gmeta_bubNm",
        "gmeta_panTypeNm",
        "gmeta_sngoDay",
        "lmeta_serialno",
        "__legacy_position",
    ]
    legacy = []
    for batch in pq.ParquetFile(legacy_path).iter_batches(columns=columns):
        for row in batch.to_pylist():
            legacy.append(
                {
                    "origin": "LEGACY",
                    "source_id": row["gmeta_contId"],
                    "docket": row["gmeta_saNo"],
                    "court": row["gmeta_bubNm"],
                    "kind": row["gmeta_panTypeNm"],
                    "date": row["gmeta_sngoDay"],
                    "lawgo_id": row["lmeta_serialno"],
                    "position": row["__legacy_position"],
                }
            )
    if args.saved_audit:
        saved_raw = args.saved_audit.read_bytes()
        assert args.saved_audit.stem == "audit-" + hashlib.sha256(saved_raw).hexdigest()
        saved = json.loads(saved_raw)
        observation, registry = saved["observation"], saved["registry"]
        latest = []
        for digest in saved["verified_blobs"]:
            document = blob(digest)
            if (
                document.get("origin") == "CURRENT_SOURCE"
                and "html_artifact_id" in document
            ):
                latest.append(
                    {
                        "source_id": document["source_id"],
                        "artifact_id": "reader:" + digest,
                        "blob_hash": digest,
                    }
                )
        assert len(latest) == saved["counts"]["current_ids"]
        assert len({x["source_id"] for x in latest}) == len(latest)
    else:
        db = Database.from_settings(load_settings())
        with db.connect() as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            observation = conn.execute(
                "SELECT transaction_timestamp() AS time, txid_current_snapshot()::text AS snapshot"
            ).fetchone()
            sql = baseline["queries"]["latest_current"]["sql"]
            latest = conn.execute(
                "SELECT latest.*,a.blob_hash FROM ("
                + sql
                + ") latest JOIN artifacts a ON a.artifact_id=latest.artifact_id"
            ).fetchall()
            registry = conn.execute(
                "SELECT (SELECT count(*) FROM documents) AS documents,(SELECT count(*) FROM active_source_links) AS active_source_links"
            ).fetchone()
    current = []
    for row in latest:
        reader = blob(row["blob_hash"])
        p = reader["provenance"]
        if not p.get("court"):
            response = next(
                (
                    x
                    for x in p.get("source_responses", [])
                    if x["url"].endswith("selectJdcpctDtl.on")
                ),
                None,
            )
            if response:
                metadata = blob(response["sha256"])["data"]["dma_jdcpctDtl"]
                p = {
                    **p,
                    "court": metadata.get("cortNm"),
                    "case_number": metadata.get("csNoLstCtt"),
                    "decision_type": metadata.get("adjdTypNm"),
                    "decision_date": metadata.get("prnjdgYmd"),
                    "metadata_response_hash": response["sha256"],
                }
        title_evidence = None
        if not p.get("court"):
            parsed = _parse_display_title(reader["title"])
            if parsed:
                year, month, day = parsed["date"].rstrip(".").split(".")
                p = {
                    **p,
                    "court": parsed["court"],
                    "case_number": parsed["docket"],
                    "decision_type": parsed["kind"],
                    "decision_date": f"{int(year):04d}{int(month):02d}{int(day):02d}",
                }
                title_evidence = {
                    "title": reader["title"],
                    "parser": TITLE_VERSION,
                    "spans": parsed["raw_spans"],
                }
        current.append(
            {
                "origin": "CURRENT",
                "source_id": row["source_id"],
                "docket": p.get("case_number"),
                "court": p.get("court"),
                "kind": p.get("decision_type"),
                "date": p.get("decision_date"),
                "reader_artifact": row["artifact_id"],
                "metadata_hash": p.get("metadata_response_hash"),
            }
        )
        if title_evidence:
            current[-1]["title_evidence"] = title_evidence
    groups = defaultdict(list)
    incomplete = []
    for row in legacy + current:
        kind = decision_kind(row["kind"])
        court = court_comparison_key(row["court"])
        docket = (row["docket"] or "").strip()
        if not kind or not court or not docket:
            incomplete.append(row)
        else:
            groups[(court, docket, kind.value)].append(row)
    candidates = []
    for key, rows in sorted(groups.items()):
        ids = {r["source_id"] for r in rows}
        if len(ids) > 1:
            candidates.append(
                {
                    "key": key,
                    "rows": rows,
                    "date_consistent": len({r["date"] for r in rows}) == 1,
                    "status": "REVIEW_REQUIRED",
                }
            )
    conflicts = []
    for c in baseline["conflicts"]:
        p = c["provenance"]
        metadata = blob(p["metadata_response_hash"])["data"]["dma_jdcpctDtl"]
        response = next(x for x in c["responses"] if "PrecService" in x["body"])
        digest = baseline["verified_artifacts"][response["artifact_id"]]
        detail = blob(digest)["PrecService"]
        full = metadata.get("mrgCsNoCtt")
        checks = {
            "full_docket_literal": bool(full) and full == detail["사건번호"],
            "court": court_comparison_key(p["court"])
            == court_comparison_key(detail["법원명"]),
            "kind": decision_kind(p["decision_type"]) is not None
            and decision_kind(p["decision_type"]) == decision_kind(detail["판결유형"]),
            "date": p["decision_date"] == detail["선고일자"],
        }
        conflicts.append(
            {
                "source_id": c["source_id"],
                "representative": p["case_number"],
                "scourt_full_docket": full,
                "lawgo_full_docket": detail["사건번호"],
                "scourt_metadata_hash": p["metadata_response_hash"],
                "lawgo_detail_artifact": response["artifact_id"],
                "checks": checks,
                "assessment": "FULL_METADATA_AGREEMENT"
                if all(checks.values())
                else "REVIEW_REQUIRED",
                "operational_status": "CONFLICT",
            }
        )
    legacy_ids = {
        r["source_id"]
        for r in legacy
        if r["source_id"] and str(r["source_id"]).isdigit()
    }
    current_ids = {r["source_id"] for r in current}
    source_duplicates = {
        str(k): v
        for k, v in Counter(
            r["source_id"] for r in legacy if r["source_id"] in legacy_ids
        ).items()
        if v > 1
    }
    positions = {
        r["position"] for c in candidates for r in c["rows"] if r["origin"] == "LEGACY"
    }
    positions.update(
        r["position"] for r in legacy if str(r["source_id"]) in source_duplicates
    )
    old_audit = json.loads((root / "docs/step3a-validation.json").read_bytes())
    replacements = []
    replacement_positions = set()
    for candidate in old_audit["replacement_candidates"]:
        digest = candidate["sha256"]
        raw = (data / "source-audit/blobs" / digest[:2] / digest).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        detail = json.loads(raw)
        text = visible(
            detail["PrecService"]["판례내용"]
            if candidate["source"] == "law_go_kr"
            else detail["data"]["dma_jdcpctCtxt"]["orgdocXmlCtt"]
        )
        rows = [
            r
            for r in legacy
            if str(
                r["lawgo_id"] if candidate["source"] == "law_go_kr" else r["source_id"]
            )
            == candidate["legacy_id"]
        ]
        replacement_positions.update(r["position"] for r in rows)
        replacements.append(
            {
                "source": candidate["source"],
                "old_id": candidate["legacy_id"],
                "candidate_id": candidate["candidate_id"],
                "candidate_sha256": digest,
                "candidate_metadata": candidate["metadata"],
                "legacy_rows": rows,
                "candidate_text": text,
                "observation": "2026-09-10 preserved response; no new provider fetch",
                "status": "REVIEW_REQUIRED",
            }
        )
    positions.update(replacement_positions)
    bodies = {}
    replacement_texts = {}
    for batch in pq.ParquetFile(legacy_path).iter_batches(
        batch_size=512, columns=["__legacy_position", "case_txt_scraped_with_tags"]
    ):
        for row in batch.to_pylist():
            position = row["__legacy_position"]
            if position in positions:
                html = row["case_txt_scraped_with_tags"]
                valid = isinstance(html, str) and html.strip() not in {
                    "",
                    "empty",
                    "None",
                }
                bodies[position] = {
                    "present": valid,
                    "html_sha256": hashlib.sha256(html.encode()).hexdigest()
                    if valid
                    else None,
                    "visible_compact_sha256": hashlib.sha256(
                        "".join(visible(html).split()).encode()
                    ).hexdigest()
                    if valid
                    else None,
                }
                if position in replacement_positions and valid:
                    replacement_texts[position] = visible(html)
    for candidate in replacements:
        text = candidate.pop("candidate_text")
        compact = "".join(text.split())
        evidence = []
        for row in candidate["legacy_rows"]:
            old = "".join(replacement_texts.get(row["position"], "").split())
            match = SequenceMatcher(
                None, old, compact, autojunk=False
            ).find_longest_match()
            evidence.append(
                {
                    "position": row["position"],
                    "legacy_body": bodies[row["position"]],
                    "candidate_visible_prefix": text[:100],
                    "compact_equal": bool(old) and old == compact,
                    "longest_exact_compact_characters": match.size,
                    "legacy_compact_start": match.a,
                    "candidate_compact_start": match.b,
                    "interpretation": "Exact common text is supporting evidence only; provider replacement and full document identity remain unconfirmed",
                }
            )
        candidate["body_comparison"] = evidence
    for c in candidates:
        evidence = {
            str(r["position"]): bodies[r["position"]]
            for r in c["rows"]
            if r["origin"] == "LEGACY"
        }
        c["legacy_body_evidence"] = evidence
        c["legacy_html_equal"] = (
            all(x["present"] for x in evidence.values())
            and len({x["html_sha256"] for x in evidence.values()}) == 1
        )
        c["legacy_visible_compact_equal"] = (
            all(x["present"] for x in evidence.values())
            and len({x["visible_compact_sha256"] for x in evidence.values()}) == 1
        )
    repeated = []
    for sid in source_duplicates:
        rows = [r for r in legacy if str(r["source_id"]) == sid]
        repeated.append(
            {
                "source_id": sid,
                "rows": rows,
                "bodies": {str(r["position"]): bodies[r["position"]] for r in rows},
            }
        )
    report = {
        "version": "identity-candidate-audit-1",
        "observation": observation,
        "registry": registry,
        "baseline_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        "legacy_sha256": hashlib.sha256(legacy_path.read_bytes()).hexdigest(),
        "counts": {
            "legacy_rows": len(legacy),
            "legacy_unique_ids": len(legacy_ids),
            "current_ids": len(current_ids),
            "same_source_ids": len(legacy_ids & current_ids),
            "outside_legacy_ids": len(current_ids - legacy_ids),
            "different_source_candidate_groups": len(candidates),
            "candidate_groups_date_disagreement": sum(
                not c["date_consistent"] for c in candidates
            ),
            "incomplete_metadata_rows": len(incomplete),
            "full_metadata_agreement": sum(
                c["assessment"] == "FULL_METADATA_AGREEMENT" for c in conflicts
            ),
        },
        "different_source_candidates": candidates,
        "legacy_duplicate_source_ids": source_duplicates,
        "incomplete_metadata": incomplete,
        "lawgo_conflicts": conflicts,
        "outside_legacy_sources": sorted(current_ids - legacy_ids),
        "verified_blobs": verified,
        "limits": [
            "Representative docket equality is candidate generation, not full merged docket or body identity.",
            "Dates are comparison evidence, never part of the decision key.",
            "No network fetch, registry mutation, reader revision or automatic merge performed.",
            "No candidate does not establish uniqueness; spelling variations and missing metadata remain outside exact matching.",
        ],
    }
    report["current_observations"] = current
    report["legacy_repeated_source_rows"] = repeated
    report["provider_number_change_candidates"] = replacements
    report["saved_audit"] = str(args.saved_audit) if args.saved_audit else None
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    legacy_by_id = defaultdict(list)
    for row in legacy:
        legacy_by_id[row["source_id"]].append(row)
    same_source = []
    for row in current:
        if row["source_id"] not in legacy_ids:
            continue
        comparisons = []
        for old in legacy_by_id[row["source_id"]]:
            known = bool(row["court"] and row["docket"] and decision_kind(row["kind"]))
            equal = (
                known
                and court_comparison_key(row["court"])
                == court_comparison_key(old["court"])
                and row["docket"] == old["docket"]
                and decision_kind(row["kind"]) == decision_kind(old["kind"])
                and row["date"] == old["date"]
            )
            comparisons.append(
                {
                    "legacy_position": old["position"],
                    "status": "METADATA_AGREEMENT"
                    if equal
                    else "METADATA_DIFFERENCE"
                    if known
                    else "CURRENT_METADATA_UNRESOLVED",
                }
            )
        same_source.append({"source_id": row["source_id"], "comparisons": comparisons})
    report["same_source_comparisons"] = same_source
    report["counts"]["same_source_comparison_rows"] = dict(
        Counter(x["status"] for item in same_source for x in item["comparisons"])
    )
    raw = json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2, default=str
    ).encode()
    out = data / "identity-audit-20260915"
    out.mkdir(exist_ok=True)
    path = out / ("audit-" + hashlib.sha256(raw).hexdigest() + ".json")
    if path.exists():
        assert path.read_bytes() == raw
    else:
        path.write_bytes(raw)
    print(
        json.dumps({"path": str(path), "counts": report["counts"]}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
