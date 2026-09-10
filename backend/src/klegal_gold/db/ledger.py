"""Version-scoped item attempts, separate from jobs and source content versions."""

import json
from typing import Literal
from uuid import UUID

from klegal_gold.domain.common import content_hash
from klegal_gold.domain.identity import SourceCaseIdentifier

from .records import Records
from .session import Database


class Ledger:
    def __init__(self, db: Database, records: Records) -> None:
        self.db, self.records = db, records

    def register(
        self,
        kind: Literal["FETCH", "ASSET", "ENRICHMENT"],
        identifier: SourceCaseIdentifier,
        input_version: str,
        rules_version: str,
        target: str,
    ) -> str:
        values = [
            kind,
            identifier.source,
            identifier.source_id,
            input_version,
            rules_version,
            target,
        ]
        if not all(values):
            raise ValueError("INCOMPLETE_ITEM_IDENTITY")
        key = content_hash(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode())
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO work_items VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (key, *values),
            )
        return key

    def record_attempt(
        self,
        item_key: str,
        attempt_id: UUID,
        outcome: Literal["SUCCEEDED", "FAILED", "PARTIAL"],
        *,
        artifact_id: str | None = None,
        job_id: UUID | None = None,
        error_code: str | None = None,
    ) -> None:
        import re

        if error_code is not None and not re.fullmatch("[A-Z][A-Z0-9_]{0,63}", error_code):
            raise ValueError("INVALID_LEDGER_ERROR_CODE")
        if artifact_id is not None:
            self.records.store.verify(self.records.blob(artifact_id))
        values = (item_key, job_id, outcome, artifact_id, error_code)
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO work_item_attempts
                   (attempt_id,item_key,job_id,outcome,artifact_id,error_code)
                   VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (attempt_id, *values),
            )
            row = conn.execute(
                "SELECT item_key,job_id,outcome,artifact_id,error_code"
                " FROM work_item_attempts WHERE attempt_id=%s",
                (attempt_id,),
            ).fetchone()
            if row is None or tuple(row.values()) != values:
                raise ValueError("LEDGER_ATTEMPT_CONFLICT")
