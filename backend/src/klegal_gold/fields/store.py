"""Immutable field revisions and sixty-column Parquet; original corpus is read-only."""

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq

from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.fields.contract import NAMES, VERSION, field, validate
from klegal_gold.fields.extract import extract
from klegal_gold.ingestion.legacy_bundle import preserve_field
from klegal_gold.search.parquet import _text, legacy_snapshot

CELL = pa.struct(
    [
        ("original_type", pa.string()),
        ("encoding", pa.string()),
        ("text", pa.large_string()),
        ("integer", pa.int64()),
    ]
)


def encoded(value: Any, name: str) -> dict[str, Any]:
    item = preserve_field(name, value).model_dump(mode="json")
    return {
        "original_type": item["original_type"],
        "encoding": item["encoding"],
        "text": item["value"] if isinstance(item["value"], str) else None,
        "integer": item["value"] if type(item["value"]) is int else None,
    }


def parquet_bytes(fields: list[dict[str, Any]], revision_input: dict[str, Any]) -> bytes:
    schema = pa.schema(
        [(n, CELL) for n in NAMES],
        metadata={b"case_fields": json.dumps(revision_input, sort_keys=True).encode()},
    )
    row = {f["name"]: encoded(f["value"], f["name"]) for f in fields}
    table = pa.Table.from_pylist([row], schema=schema)
    out = pa.BufferOutputStream()
    pq.write_table(table, out)
    raw = out.getvalue().to_pybytes()
    if pq.read_table(pa.BufferReader(raw)).to_pylist() != [row]:
        raise ValueError("FIELDS_PARQUET_ROUNDTRIP_FAILED")
    return bytes(raw)


class FieldStore:
    def __init__(self, records: Records) -> None:
        self.records = records
        self.readers = ReaderStore(records)

    def build(self, document_id: str, processed_at: str) -> dict[str, Any]:
        reader = self.readers.read(document_id)
        if reader["origin"] != "CURRENT_SOURCE":
            raise ValueError("NOT_CURRENT_READER")
        key = "case-fields:" + VERSION + ":" + document_id
        try:
            return cast(dict[str, Any], json.loads(self.records.read(key)))
        except ValueError as exc:
            if str(exc) != "ARTIFACT_NOT_FOUND":
                raise
        provenance = reader["provenance"]
        metadata_id = "http:" + provenance["metadata_response_hash"]
        metadata = json.loads(self.records.read(metadata_id))["data"]["dma_jdcpctDtl"]
        if str(metadata["jisCntntsSrno"]) != reader["source_id"]:
            raise ValueError("FIELDS_SOURCE_MISMATCH")
        html = self.records.read(reader["html_artifact_id"]).decode()
        if sha256(html.encode()).hexdigest() != reader["html_sha256"]:
            raise ValueError("FIELDS_HTML_MISMATCH")
        plan_id = provenance.get("lawgo_plan_artifact_id")
        plan = json.loads(self.records.read(plan_id)) if plan_id else {}
        lawgo = None
        if plan.get("status") == "EXACT":
            lawgo = next(
                (
                    c
                    for c in plan["candidates"]
                    if str(c.get("판례일련번호")) == str(plan["source_id"])
                ),
                None,
            )
            if lawgo is None:
                raise ValueError("FIELDS_LAWGO_CANDIDATE_MISSING")
        fields = extract(
            html,
            metadata,
            title=reader["title"],
            source_id=reader["source_id"],
            html_artifact_id=reader["html_artifact_id"],
            metadata_artifact_id=metadata_id,
            processed_at=processed_at,
            lawgo=lawgo,
            lawgo_artifact_id=plan_id,
            lawgo_status=plan.get("status", "NOT_PROCESSED"),
        )
        validate(fields)
        inputs = {
            "reader_document_id": document_id,
            "source_id": reader["source_id"],
            "html_sha256": reader["html_sha256"],
            "source_artifact_id": provenance["source_artifact_id"],
            "metadata_artifact_id": metadata_id,
            "lawgo_artifact_id": plan_id,
            "rule_version": VERSION,
        }
        raw = parquet_bytes(fields, inputs)
        parquet_id = "case-fields-parquet:" + sha256(raw).hexdigest()
        self.records.put_artifact(
            parquet_id,
            raw,
            origin="DERIVED",
            metadata={"kind": "CASE_FIELDS_PARQUET"},
            parent_id=reader["html_artifact_id"],
        )
        counts = {
            status: sum(f["status"] == status for f in fields)
            for status in sorted({f["status"] for f in fields})
        }
        state = (
            "INCOMPLETE"
            if any(counts.get(x) for x in ("ERROR", "NOT_PROCESSED"))
            else "REVIEW"
            if counts.get("REVIEW")
            else "VALIDATED"
        )
        payload = {
            **inputs,
            "revision": key,
            "processed_at": processed_at,
            "state": state,
            "counts": counts,
            "parquet_artifact_id": parquet_id,
            "parquet_sha256": sha256(raw).hexdigest(),
            "fields": fields,
        }
        self.records.put_artifact(
            key,
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(),
            origin="DERIVED",
            metadata={
                "kind": "CASE_FIELDS",
                "reader_document_id": document_id,
                "source_id": reader["source_id"],
                "state": state,
                "rule_version": VERSION,
            },
            parent_id=parquet_id,
        )
        return payload

    def read(self, document_id: str) -> dict[str, Any]:
        reader = self.readers.read(document_id)
        try:
            return cast(
                dict[str, Any],
                json.loads(self.records.read("case-fields:" + VERSION + ":" + document_id)),
            )
        except ValueError as exc:
            if str(exc) != "ARTIFACT_NOT_FOUND":
                raise
        return {
            "reader_document_id": document_id,
            "source_id": reader["source_id"],
            "revision": None,
            "state": "NOT_PROCESSED",
            "fields": [
                field(n, status="NOT_PROCESSED", reason="이 reader revision의 60필드 생성 미실행")
                for n in NAMES
            ],
        }


def legacy_fields(path: Path, position: int, expected_hash: str) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    if position < 0:
        raise ValueError("INVALID_POSITION")
    index = parquet.schema.names.index("__legacy_position")
    for group in range(parquet.num_row_groups):
        stats = parquet.metadata.row_group(group).column(index).statistics
        if stats and stats.has_min_max and not stats.min <= position <= stats.max:
            continue
        for row in parquet.read_row_group(group).to_pylist():
            if row["__legacy_position"] != position:
                continue
            if (
                sha256(_text(row["case_txt_scraped_with_tags"]).encode()).hexdigest()
                != expected_hash
            ):
                raise ValueError("BODY_VERSION_CHANGED")
            fields = []
            for name in NAMES:
                value = row[name]
                fields.append(
                    field(
                        name,
                        value,
                        status="LEGACY_STORED",
                        reason="기존 저장값·타입 원형; 과거 규칙·시각·의미 검증 미확인",
                        evidence={
                            "snapshot_sha256": legacy_snapshot(path),
                            "row_position": position,
                            "column": name,
                        },
                    )
                )
                fields[-1]["rule_version"] = None
            return {
                "revision": legacy_snapshot(path),
                "state": "LEGACY_STORED",
                "fields": fields,
                "row_position": position,
                "body_hash": expected_hash,
            }
    raise ValueError("ROW_NOT_FOUND")
