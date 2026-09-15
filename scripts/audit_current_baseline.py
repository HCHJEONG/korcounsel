"""Read-only PostgreSQL and immutable-file baseline for a fixed field snapshot.

Run with the backend environment and an explicit KLEGAL_ENV_FILE. This script
does not submit jobs, fetch providers, or write to the application database.
"""

import argparse
import hashlib
import io
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from psycopg.conninfo import make_conninfo

from klegal_gold.config import load_settings
from klegal_gold.enrichment.current_lawgo import article_table, provider_article_params
from klegal_gold.fields.extract import visible
from klegal_gold.fields.store import encoded
from klegal_gold.ingestion.legacy_catalog import scourt_catalog
from klegal_gold.quality.checks import inspect


def comparable_cell(cell: dict[str, Any]) -> dict[str, Any]:
    """Compare typed JSON dictionaries without treating key order as a value change."""

    def canonical(node: Any) -> Any:
        if isinstance(node, dict):
            result = {key: canonical(value) for key, value in node.items()}
            if node.get("type") == "builtins.dict":
                result["value"] = sorted(
                    result["value"], key=lambda pair: json.dumps(pair[0], sort_keys=True)
                )
            return result
        if isinstance(node, list):
            return [canonical(value) for value in node]
        return node

    if cell["encoding"] == "JSON":
        return {**cell, "text": canonical(json.loads(cell["text"]))}
    return cell


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    from klegal_gold.db.session import Database

    settings = load_settings()
    if settings.database_url is None:
        raise ValueError("DATABASE_URL is required")
    dsn = settings.database_url.get_secret_value()
    if args.host:
        dsn = make_conninfo(dsn, host=args.host, port=args.port or 5432)
    db = Database(dsn)
    manifest_raw = args.cohort.read_bytes()
    cohort = json.loads(manifest_raw)
    ids = sorted({r["source_id"] for r in cohort["cases"]})
    assert len(ids) == len(cohort["cases"])
    legacy = scourt_catalog(args.legacy)
    queries = {}
    results = {}
    verified = {}
    verified_blobs = {}
    evidence_ranges = 0
    with db.connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")

        def query(name, sql, params=()):
            queries[name] = {"sql": sql, "parameters": params}
            rows = conn.execute(sql, params).fetchall()
            results[name] = rows
            return rows

        def raw(key):
            row = conn.execute(
                "SELECT a.blob_hash,b.storage_key,b.size_bytes FROM artifacts a "
                "JOIN blobs b ON b.sha256=a.blob_hash WHERE artifact_id=%s",
                (key,),
            ).fetchone()
            assert row is not None, key
            value = (args.data / row["storage_key"]).read_bytes()
            assert hashlib.sha256(value).hexdigest() == row["blob_hash"], key
            assert len(value) == row["size_bytes"], key
            verified[key] = row["blob_hash"]
            return value

        def read(key):
            return json.loads(raw(key))

        query(
            "database",
            "SELECT current_database() AS database, transaction_timestamp() AS "
            "observed_at, txid_current_snapshot()::text AS transaction_snapshot",
        )
        query(
            "legacy_records",
            "SELECT snapshot_hash,coverage,count(*) AS revisions,count(DISTINCT "
            "row_position) AS positions FROM legacy_records GROUP BY 1,2 ORDER BY "
            "1,2",
        )
        query(
            "legacy_readers",
            "SELECT metadata->>'legacy_snapshot' AS snapshot,count(*) AS "
            "revisions,count(DISTINCT metadata->>'legacy_position') AS positions "
            "FROM artifacts WHERE metadata->>'kind'='READER_DOCUMENT' AND "
            "metadata->>'origin'='LEGACY_CORPUS' GROUP BY 1",
        )
        query(
            "source_versions",
            "SELECT source,count(*) AS versions,count(DISTINCT source_id) AS "
            "source_ids FROM source_versions GROUP BY 1",
        )
        query("source_receipts", "SELECT count(*) AS receipts FROM source_receipts")
        query(
            "canonical",
            "SELECT (SELECT count(*) FROM documents) AS documents,(SELECT count(*) "
            "FROM active_source_links) AS active_source_links",
        )
        query("jobs", "SELECT kind,status,count(*) AS jobs FROM jobs GROUP BY 1,2 ORDER BY 1,2")
        jobs = query(
            "cohort_jobs",
            "SELECT job_id,kind,status,payload,checkpoint FROM jobs WHERE "
            "payload->>'source_id'=ANY(%s) OR payload->>'document_id' IN (SELECT "
            "replace(artifact_id,'reader:','') FROM artifacts WHERE "
            "metadata->>'kind'='READER_DOCUMENT' AND "
            "metadata->>'source_id'=ANY(%s)) ORDER BY created_at,job_id",
            (ids, ids),
        )
        query(
            "field_revisions",
            "SELECT metadata->>'rule_version' AS rule,count(*) AS "
            "revisions,count(DISTINCT metadata->>'source_id') AS source_ids FROM "
            "artifacts WHERE metadata->>'kind'='CASE_FIELDS' GROUP BY 1 ORDER BY 1",
        )
        latest = query(
            "latest_current",
            "SELECT DISTINCT ON(a.metadata->>'source_id') a.metadata->>'source_id' "
            "AS source_id,a.artifact_id FROM artifacts a LEFT JOIN artifacts root "
            "ON "
            "root.artifact_id='reader:'||(a.metadata->>'current_root_document_id') "
            "WHERE a.metadata->>'kind'='READER_DOCUMENT' AND "
            "a.metadata->>'origin'='CURRENT_SOURCE' ORDER BY "
            "a.metadata->>'source_id',COALESCE(root.created_at,a.created_at) "
            "DESC,a.created_at DESC,a.artifact_id DESC",
        )
        query(
            "current_revisions",
            "SELECT count(*) AS revisions,count(DISTINCT metadata->>'source_id') AS"
            " source_ids FROM artifacts WHERE metadata->>'kind'='READER_DOCUMENT' "
            "AND metadata->>'origin'='CURRENT_SOURCE'",
        )
        query(
            "cohort_revisions",
            "SELECT count(*) AS revisions,count(DISTINCT metadata->>'source_id') AS"
            " source_ids FROM artifacts WHERE metadata->>'kind'='READER_DOCUMENT' "
            "AND metadata->>'origin'='CURRENT_SOURCE' AND "
            "metadata->>'source_id'=ANY(%s)",
            (ids,),
        )
        query(
            "cohort_source_versions",
            "SELECT count(*) AS versions,count(DISTINCT source_id) AS source_ids "
            "FROM source_versions WHERE source='scourt' AND source_id=ANY(%s)",
            (ids,),
        )
        query(
            "cohort_observations",
            "SELECT count(*) AS observations FROM artifacts a JOIN source_versions "
            "sv ON sv.artifact_id=a.parent_id WHERE "
            "a.metadata->>'kind'='SCOURT_ACQUISITION' AND sv.source='scourt' AND "
            "sv.source_id=ANY(%s)",
            (ids,),
        )
        current = {r["source_id"]: r["artifact_id"] for r in latest}
        query(
            "latest_current_fields",
            "SELECT COALESCE(f.metadata->>'rule_version','NOT_PROCESSED') AS "
            "rule,count(*) AS readers FROM unnest(%s::text[]) AS r(id) LEFT JOIN "
            "artifacts f ON "
            "f.artifact_id='case-fields:case-fields-6:'||replace(r.id,'reader:','')"
            " GROUP BY 1",
            (list(current.values()),),
        )
        catalog_ids = set(legacy.source_ids)
        baseline = {
            "legacy": legacy.payload(),
            "cohort_source_ids": len(ids),
            "current_source_ids": len(current),
            "current_in_legacy_catalog": len(set(current) & catalog_ids),
            "current_outside_legacy_catalog": len(set(current) - catalog_ids),
            "outside_catalog_and_cohort": sorted(set(current) - catalog_ids - set(ids)),
            "cohort_in_legacy_catalog": sorted(set(ids) & catalog_ids),
        }
        items = []
        conflicts = []
        failures = []
        all_statuses = {
            key: Counter()
            for key in (
                "fields",
                "lawgo",
                "images",
                "statute_images",
                "statutes",
                "months",
                "field_review",
                "field_statuses",
                "issue_codes",
            )
        }
        snapshot_rows = pq.read_table(args.cohort.with_suffix(".parquet")).to_pylist()
        assert (
            hashlib.sha256(args.cohort.with_suffix(".parquet").read_bytes()).hexdigest()
            == cohort["sha256"]
        )
        assert len(snapshot_rows) == len(ids)
        for saved, snapshot_row in zip(cohort["cases"], snapshot_rows, strict=True):
            sid = saved["source_id"]
            saved_fields = read(saved["fields_revision"])
            assert {
                f["name"]: encoded(f["value"], f["name"]) for f in saved_fields["fields"]
            } == snapshot_row
            assert saved_fields["reader_document_id"] == saved["reader_document_id"]
            reader = read(current[sid])
            document = current[sid].removeprefix("reader:")
            fields = read("case-fields:case-fields-6:" + document)
            html = raw(reader["html_artifact_id"])
            assert hashlib.sha256(html).hexdigest() == reader["html_sha256"] == saved["html_sha256"]
            assert fields["reader_document_id"] == document
            field_parquet = raw(fields["parquet_artifact_id"])
            parquet_rows = pq.read_table(io.BytesIO(field_parquet)).to_pylist()
            assert len(parquet_rows) == 1
            assert {name: comparable_cell(cell) for name, cell in parquet_rows[0].items()} == {
                f["name"]: comparable_cell(encoded(f["value"], f["name"])) for f in fields["fields"]
            }
            provenance = reader["provenance"]
            raw(provenance["source_artifact_id"])
            raw(fields["metadata_artifact_id"])
            plan = read(provenance["lawgo_plan_artifact_id"])
            row = {
                "document_id": document,
                "provenance": provenance,
                **inspect(reader, fields, html.decode()),
            }
            items.append(row)
            for name, value in (
                ("fields", fields["state"]),
                ("lawgo", plan["status"]),
                ("months", str(provenance.get("decision_date", ""))[:6]),
            ):
                all_statuses[name][value] += 1
            for field in fields["fields"]:
                all_statuses["field_statuses"][field["status"]] += 1
                spans = field.get("evidence", {}).get("ranges", [])
                text = visible(html.decode()) if spans else ""
                for start, end in spans:
                    assert 0 <= start < end <= len(text)
                    evidence_ranges += 1
                if spans and isinstance(field["value"], str):
                    assert (
                        "\n".join(text[start:end].strip() for start, end in spans) == field["value"]
                    )
                if field["status"] == "REVIEW":
                    all_statuses["field_review"][field["name"]] += 1
            all_statuses["issue_codes"].update(issue["code"] for issue in row["issues"])
            for name in ("images", "statute_images", "statutes"):
                for ref in reader.get(name, []):
                    all_statuses[name][ref.get("provider_status", ref["status"])] += 1
                    if ref.get("blob_hash") and ref["status"] == "ACQUIRED":
                        digest = ref["blob_hash"]
                        blob = conn.execute(
                            "SELECT storage_key,size_bytes FROM blobs WHERE sha256=%s", (digest,)
                        ).fetchone()
                        content = (args.data / blob["storage_key"]).read_bytes()
                        assert hashlib.sha256(content).hexdigest() == digest
                        assert len(content) == blob["size_bytes"]
                        verified_blobs[digest] = len(content)
                    if name == "images":
                        assert html.decode()[ref["html_start"] : ref["html_end"]] == ref["html_tag"]
                    if name == "statutes" and ref.get("payload"):
                        assert (
                            hashlib.sha256(ref["payload"].encode()).hexdigest()
                            == ref["payload_sha256"]
                        )
                        if ref.get("payload_artifact_id"):
                            assert (
                                article_table(raw(ref["payload_artifact_id"]).decode())
                                == ref["payload"]
                            )
            if plan["status"] == "CONFLICT":
                run_id = provenance["lawgo_plan_artifact_id"].split(":")[1]
                responses = conn.execute(
                    "SELECT artifact_id,parent_id FROM artifacts WHERE "
                    "metadata->>'kind'='HTTP_ATTEMPT' AND metadata->>'run_id'=%s ORDER BY "
                    "created_at",
                    (run_id,),
                ).fetchall()
                details = []
                for response in responses:
                    body = read(response["parent_id"])
                    details.append({"artifact_id": response["parent_id"], "body": body})
                conflicts.append(
                    {"source_id": sid, "provenance": provenance, "plan": plan, "responses": details}
                )
            for article in reader["statutes"]:
                if article.get("provider_status") == "FAILED":
                    links = [link for link in plan["links"] if link["text"] == article["text"]]
                    failure = {
                        "source_id": sid,
                        "document_id": document,
                        "plan_artifact_id": provenance["lawgo_plan_artifact_id"],
                        "article": article,
                    }
                    if links:
                        key = (
                            provenance["lawgo_plan_artifact_id"].removesuffix(":plan")
                            + ":article:"
                            + hashlib.sha256(
                                json.dumps(links[0], sort_keys=True).encode()
                            ).hexdigest()
                        )
                        response = raw(key).decode()
                        failure["response_artifact_id"] = key
                        failure["provider_parameters"] = provider_article_params(
                            links[0], plan["day"]
                        )
                        failure["disposition"] = (
                            "PROVIDER_SERVICE_ERROR"
                            if 'id="error500"' in response
                            else "POPUP_REDIRECT_WITHOUT_ARTICLE_TEXT"
                            if 'id="lnkLsId"' in response
                            else "UNCLASSIFIED_STRUCTURE"
                        )
                    failures.append(failure)
        query(
            "lawgo_responses",
            "SELECT artifact_id,blob_hash,metadata FROM artifacts WHERE "
            "metadata->>'kind'='LAWGO_PROVIDER_RESPONSE' AND "
            "metadata->>'endpoint'='lsLinkProc.do'",
        )
    report = {
        "version": "current-baseline-2",
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "cohort_manifest": str(args.cohort),
        "cohort_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "baseline": baseline,
        "counts": all_statuses,
        "queries": queries,
        "sql_results": results,
        "cohort_job_counts": dict(Counter(j["kind"] + ":" + j["status"] for j in jobs)),
        "items": items,
        "conflicts": conflicts,
        "failures": failures,
        "verified_artifacts": verified,
        "verified_image_blobs": verified_blobs,
        "verified_field_evidence_ranges": evidence_ranges,
        "limits": [
            "Source IDs and legacy rows are not deduplicated canonical decisions.",
            "Field semantic correctness and historical law versions remain reviewable.",
            "No provider request, job submission or database mutation was performed.",
        ],
    }
    content = json.dumps(report, ensure_ascii=False, sort_keys=True, default=str).encode()
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / ("baseline-" + hashlib.sha256(content).hexdigest() + ".json")
    with target.open("xb") as stream:
        stream.write(content)
    print(target)
    print(
        json.dumps(
            {
                "baseline": {k: v for k, v in baseline.items() if k != "legacy"},
                "counts": all_statuses,
                "job_counts": report["cohort_job_counts"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
