"""Small live validation. Requires an explicitly chosen KLEGAL_ENV_FILE; no DB writes."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

from klegal_gold.config import load_settings
from klegal_gold.sources.law_api import LawOpenApiCaseSource, SourceError
from klegal_gold.storage.files import FileStore


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = load_settings()
    if settings.law_api_credential is None:
        raise SystemExit("Source credential unavailable")
    store = FileStore(root / "data" / "source-smoke")
    observations = []
    receipts = []

    def preserve(response):
        blob = store.put(response.body)
        receipts.append(
            {
                "hash": blob.sha256,
                "size": blob.size_bytes,
                "path": blob.storage_key,
                "url": response.safe_url,
                "status": response.status,
                "retrieved_at": response.retrieved_at.isoformat(),
            }
        )

    for format in ("JSON", "XML"):
        client = LawOpenApiCaseSource(
            settings.law_api_credential, preserve=preserve, format=format, max_attempts=1
        )
        for source_id in ("195490", "240889"):
            item = {"source": "law_go_kr", "id": source_id, "format": format}
            try:
                detail = client.fetch_detail(source_id)
                item.update(
                    status="SUCCESS",
                    hash=detail.response.sha256,
                    fields=sorted(detail.fields),
                    field_lengths={
                        k: len(v) for k, v in detail.fields.items() if isinstance(v, str)
                    },
                )
            except SourceError as exc:
                item.update(status="FAILED", reason=str(exc))
            observations.append(item)
        if format == "JSON":
            try:
                page = client.list_page(page=1, display=1, docket="2017도953")
                observations.append(
                    {
                        "kind": "LIST",
                        "status": "SUCCESS",
                        "total": page.total,
                        "ids": page.ids,
                        "hash": page.response.sha256,
                    }
                )
            except SourceError as exc:
                observations.append({"kind": "LIST", "status": "FAILED", "reason": str(exc)})
    try:
        socket.getaddrinfo("glaw.scourt.go.kr", 443)
        dns = "RESOLVED"
    except OSError:
        dns = "RESOLUTION_FAILED"
    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "observations": observations,
        "receipts": receipts,
        "legacy_host_dns": dns,
        "scope": "Two detail IDs JSON/XML and one bounded list request; no corpus import",
    }
    out = root / "docs" / "step3-live-api.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(out), "results": observations}, ensure_ascii=False))


if __name__ == "__main__":
    main()
