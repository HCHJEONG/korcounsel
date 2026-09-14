"""Replay verified source responses from one preserved acquisition, without HTTP."""

import json
from datetime import datetime

from klegal_gold.db.records import Records
from klegal_gold.jobs.queue import Job
from klegal_gold.sources.law_api import Progress, Response


class PreservedScourtTransport:
    def __init__(self, records: Records, original: Job) -> None:
        self.records, self.original = records, original

    def post(self, endpoint: str, source_id: str, progress: Progress) -> Response:
        if source_id != self.original.payload["source_id"]:
            raise ValueError("SCOURT_REPLAY_SOURCE_MISMATCH")
        with self.records.db.connect() as conn:
            rows = conn.execute(
                "SELECT artifact_id,parent_id FROM artifacts "
                "WHERE metadata->>'kind'='HTTP_ATTEMPT' "
                "AND metadata->>'run_id'=%s ORDER BY created_at DESC,artifact_id DESC",
                (str(self.original.job_id),),
            ).fetchall()
        for row in rows:
            progress()
            receipt = json.loads(self.records.read(row["artifact_id"]))
            if receipt["url"] != "https://portal.scourt.go.kr/pgp/pgp1011/" + endpoint:
                continue
            if receipt["status"] != 200:
                continue
            raw = self.records.read(row["parent_id"])
            if endpoint == "selectJdcpctCtxt.on" and raw != self.records.read(
                self.original.checkpoint["artifact_id"]
            ):
                continue
            return Response(
                raw,
                200,
                receipt["mime_type"],
                receipt["url"],
                datetime.fromisoformat(receipt["retrieved_at"]),
            )
        raise ValueError("SCOURT_REPLAY_RESPONSE_MISSING")

    def post_listing(self, query: str, page: int, display: int, progress: Progress) -> Response:
        raise ValueError("SCOURT_REPLAY_LISTING_UNSUPPORTED")
