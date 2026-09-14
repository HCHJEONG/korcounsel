"""Rebuildable, complete-snapshot substring projection of every legacy column."""

import json
from collections.abc import Callable
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from psycopg.types.json import Jsonb

from klegal_gold.db.session import Database
from klegal_gold.search.parquet import (
    ParquetCaseSearchResult,
    _case_numbers,
    _date,
    _original_index,
    _text,
)

VERSION = "legacy-substring-1"


def snapshot_key(path: Path) -> str:
    st = path.stat()
    return sha256(
        json.dumps(
            [
                VERSION,
                str(path.resolve()),
                st.st_dev,
                st.st_ino,
                st.st_size,
                st.st_mtime_ns,
                st.st_ctime_ns,
            ]
        ).encode()
    ).hexdigest()


class LegacySearchIndex:
    def __init__(self, db: Database):
        self.db = db

    def build(self, path: Path, expected: str, progress: Callable[[dict[str, Any]], None]) -> None:
        if snapshot_key(path) != expected:
            raise ValueError("SEARCH_SOURCE_CHANGED")
        parquet = pq.ParquetFile(path)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO legacy_search_snapshots(snapshot_key) VALUES(%s) ON "
                "CONFLICT DO NOTHING",
                (expected,),
            )
            state = conn.execute(
                "SELECT * FROM legacy_search_snapshots WHERE snapshot_key=%s", (expected,)
            ).fetchone()
        assert state is not None
        if state["ready"]:
            progress({"phase": "READY", "rows": state["row_count"]})
            return
        ordinal = state["row_count"]
        for group in range(state["next_group"], parquet.num_row_groups):
            progress({"phase": "BUILDING", "next_group": group, "rows": ordinal})
            # Group boundaries are committed with their row count; replay never duplicates rows.
            with self.db.connect() as conn:
                for batch in parquet.iter_batches(batch_size=128, row_groups=[group]):
                    values = []
                    for row in batch.to_pylist():
                        parts = []
                        fields = []
                        offset = 0
                        for name, value in row.items():
                            text = _text(value).casefold()
                            parts.append(text)
                            fields.append([name, offset, offset + len(text)])
                            offset += len(text) + 1
                        body = _text(row.get("case_txt_scraped_with_tags"))
                        decision_date = _date(row.get("decision_date"))
                        payload = {
                            "court": _text(row.get("court_name") or row.get("court")).strip()
                            or None,
                            "case_numbers": _case_numbers(row),
                            "decision_date": decision_date.isoformat() if decision_date else None,
                            "row_position": row.get("__legacy_position"),
                            "original_index": _original_index(row.get("__legacy_index")),
                            "body_hash": sha256(body.encode()).hexdigest(),
                        }
                        values.append(
                            (expected, ordinal, "\n".join(parts), Jsonb(fields), Jsonb(payload))
                        )
                        ordinal += 1
                    with conn.cursor() as cursor:
                        cursor.executemany(
                            "INSERT INTO legacy_search_rows VALUES(%s,%s,%s,%s,%s) ON "
                            "CONFLICT(snapshot_key,ordinal) DO NOTHING",
                            values,
                        )
                    progress({"phase": "BUILDING", "next_group": group, "rows": ordinal})
                conn.execute(
                    "UPDATE legacy_search_snapshots SET next_group=%s,row_count=%s "
                    "WHERE snapshot_key=%s",
                    (group + 1, ordinal, expected),
                )
        digest = sha256()
        with path.open("rb") as source:
            while chunk := source.read(8 * 1024 * 1024):
                digest.update(chunk)
                progress({"phase": "VERIFYING_SOURCE", "rows": ordinal})
        if snapshot_key(path) != expected or ordinal != parquet.metadata.num_rows:
            raise ValueError("SEARCH_SOURCE_CHANGED")
        with self.db.connect() as conn:
            count = conn.execute(
                "SELECT count(*) n FROM legacy_search_rows WHERE snapshot_key=%s", (expected,)
            ).fetchone()
            if count is None or count["n"] != ordinal:
                raise ValueError("SEARCH_ROW_COUNT_MISMATCH")
            conn.execute(
                "UPDATE legacy_search_snapshots SET ready=true,source_sha256=%s "
                "WHERE snapshot_key=%s",
                (digest.hexdigest(), expected),
            )
        progress({"phase": "READY", "rows": ordinal, "source_sha256": digest.hexdigest()})

    def search(
        self, path: Path, query: str, limit: int = 30
    ) -> list[ParquetCaseSearchResult] | None:
        key = snapshot_key(path)
        normalized = query.strip().casefold()
        if not normalized:
            return []
        if "\x00" in normalized:
            return None
        with self.db.connect() as conn:
            ready = conn.execute(
                "SELECT ready FROM legacy_search_snapshots WHERE snapshot_key=%s", (key,)
            ).fetchone()
            if ready is None or not ready["ready"]:
                return None
            pattern = (
                "%" + normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            results: list[ParquetCaseSearchResult] = []
            after = -1
            while len(results) < max(1, min(limit, 100)):
                # Common terms often fill the result limit in the first 256 rows.
                # Bound that prefix by the primary key before the full trigram query,
                # avoiding a large bitmap recheck/sort of a very common term.
                prefix = after < 255
                rows = conn.execute(
                    "SELECT ordinal,search_text,fields,result FROM legacy_search_rows "
                    "WHERE snapshot_key=%s AND ordinal>%s AND search_text LIKE %s "
                    + ("AND ordinal<256 " if prefix else "")
                    + "ORDER BY ordinal LIMIT %s",
                    (key, after, pattern, max(1, min(limit, 100)) - len(results)),
                ).fetchall()
                if not rows:
                    if prefix:
                        after = 255
                        continue
                    break
                for row in rows:
                    after = row["ordinal"]
                    # A match spanning two columns is only a candidate, never a result.
                    matched = tuple(
                        name
                        for name, start, end in row["fields"]
                        if normalized in row["search_text"][start:end]
                    )
                    if not matched:
                        continue
                    payload = row["result"]
                    results.append(
                        ParquetCaseSearchResult(
                            court=payload["court"],
                            case_numbers=tuple(payload["case_numbers"]),
                            decision_date=date.fromisoformat(payload["decision_date"])
                            if payload["decision_date"]
                            else None,
                            row_position=payload["row_position"]
                            if isinstance(payload["row_position"], int)
                            else len(results),
                            original_index=payload["original_index"],
                            matched_columns=matched[:8],
                            body_hash=payload["body_hash"],
                        )
                    )
                    if len(results) >= max(1, min(limit, 100)):
                        break
        return results
