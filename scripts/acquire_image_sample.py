"""Bounded analysis asset acquisition, with durable per-URL resume ledger."""

import argparse
import hashlib
import io
import json
import signal
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from PIL import Image

from klegal_gold.documents.observe import observe_html
from klegal_gold.sources.law_api import _NoRedirect
from klegal_gold.sources.scourt import ScourtPortalSource
from klegal_gold.storage.files import FileStore

MAX_BYTES = 16 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 25_000_000
STOP = False


def stop(signum: int, frame: Any) -> None:
    global STOP
    STOP = True


def validate_image(body: bytes) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(body)) as picture:
            result = {
                "format": picture.format,
                "size": list(picture.size),
                "frames": getattr(picture, "n_frames", 1),
            }
            picture.verify()
        with Image.open(io.BytesIO(body)) as picture:
            picture.load()
    return result


def valid_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "portal.scourt.go.kr"
        and (parsed.path == "/pgp/pgp003/downloadImgFile.on")
    )


def run(source_id: str, output: Path, report: Path, max_files: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    store = FileStore(output.resolve())
    source_records = []

    def preserve(response: Any) -> None:
        blob = store.put(response.body)
        source_records.append(
            {
                "sha256": blob.sha256,
                "url": response.safe_url,
                "retrieved_at": response.retrieved_at.isoformat(),
            }
        )

    # Reuse hash-fixed mapping on resume; a refresh must use a new output directory.
    mapping_path = output / "mapping.json"
    if mapping_path.exists():
        mapping = json.loads(mapping_path.read_text())
        if mapping["source_id"] != source_id:
            raise ValueError("SOURCE_ID_MISMATCH")
        if (
            hashlib.sha256(store.path(mapping["html_storage_key"]).read_bytes()).hexdigest()
            != mapping["html_sha256"]
        ):
            raise ValueError("PARENT_HTML_HASH_MISMATCH")
    else:
        detail = ScourtPortalSource(preserve=preserve).fetch_detail(source_id)
        html = detail.fields["body"]["orgdocXmlCtt"]
        parent = store.put(html.encode())
        mapping = {
            "source_id": source_id,
            "scope": "CURRENT_SOURCE_NOT_HISTORICAL_IDENTITY_CONFIRMATION",
            "html_sha256": parent.sha256,
            "html_storage_key": parent.storage_key,
            "source_responses": source_records,
            "observation": observe_html(html, "https://portal.scourt.go.kr/", scourt_id=source_id),
        }
        temp = output / "mapping.pending"
        temp.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")
        temp.replace(mapping_path)
    refs = mapping["observation"]["images"]
    urls = list(dict.fromkeys(ref["resolved_url"] for ref in refs if ref["resolved_url"]))
    previous = {}
    ledger_path = output / "ledger.jsonl"
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            record = json.loads(line)
            previous[record["url"]] = record
    fetched = reused = 0
    with ledger_path.open("a") as ledger:
        for url in urls[:max_files]:
            if STOP or (output / "STOP").exists():
                break
            old = previous.get(url)
            if old and old["status"] == "ACQUIRED":
                path = store.path(old["storage_key"])
                if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == old["sha256"]:
                    validate_image(path.read_bytes())
                    reused += 1
                    continue
            result = {"url": url, "at": datetime.now(UTC).isoformat(), "status": "FAILED"}
            try:
                if not valid_url(url):
                    raise ValueError("UNSUPPORTED_SOURCE_URL")
                request = Request(
                    url, headers={"User-Agent": "KorCounsel/0.1", "Accept-Encoding": "identity"}
                )
                started = time.monotonic()
                try:
                    reply = build_opener(_NoRedirect()).open(request, timeout=15)
                except HTTPError as error:
                    reply = error
                with reply:
                    body = bytearray()
                    while True:
                        if time.monotonic() - started > 30:
                            raise ValueError("RESPONSE_DEADLINE")
                        chunk = reply.read1(65536)
                        if not chunk:
                            break
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ValueError("BODY_LIMIT")
                    result.update(
                        http_status=reply.code, content_type=reply.headers.get("Content-Type")
                    )
                blob = store.put(bytes(body))
                result.update(
                    sha256=blob.sha256, storage_key=blob.storage_key, bytes=blob.size_bytes
                )
                if reply.code != 200:
                    raise ValueError("HTTP_REJECTED")
                if not body:
                    raise ValueError("EMPTY_IMAGE_BODY")
                result["image"] = validate_image(bytes(body))
                result["status"] = "ACQUIRED"
                fetched += 1
            except Exception as error:
                result["error"] = type(error).__name__ + ": " + str(error)[:200]
            ledger.write(json.dumps(result, ensure_ascii=False) + "\n")
            ledger.flush()
            import os

            os.fsync(ledger.fileno())
            previous[url] = result
            print(
                json.dumps({"status": result["status"], "completed": fetched + reused}), flush=True
            )
            if result.get("http_status") in (429, 503):
                break
            time.sleep(0.5)
    successful = {
        url: previous[url]
        for url in urls
        if url in previous and previous[url]["status"] == "ACQUIRED"
    }
    linked = [
        {**ref, "acquisition": previous.get(ref["resolved_url"], {"status": "PENDING"})}
        for ref in refs
    ]
    result = {
        "source_id": source_id,
        "parent_html_sha256": mapping["html_sha256"],
        "occurrences": len(refs),
        "unique_urls": len(urls),
        "acquired_urls": len(successful),
        "new_downloads": fetched,
        "verified_reused": reused,
        "unique_binary_hashes": len({item["sha256"] for item in successful.values()}),
        "total_unique_bytes": sum(
            {item["sha256"]: item["bytes"] for item in successful.values()}.values()
        ),
        "failed_urls": sum(previous.get(url, {}).get("status") == "FAILED" for url in urls),
        "pending_urls": sum(url not in previous for url in urls),
        "unresolved_occurrences": sum(not ref["resolved_url"] for ref in refs),
        "all_occurrences_linked": bool(linked)
        and all(ref["acquisition"]["status"] == "ACQUIRED" for ref in linked),
        "images": linked,
        "validation": "Pillow verify plus first-frame decode; no OCR",
        "historical_binary_identity_verified": False,
    }
    manifest = store.put(json.dumps(result, ensure_ascii=False).encode())
    result["manifest_sha256"] = manifest.sha256
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=40)
    args = parser.parse_args()
    if not 1 <= args.max_files <= 100:
        parser.error("--max-files must be 1..100")
    run(args.source_id, args.output, args.report, args.max_files)
