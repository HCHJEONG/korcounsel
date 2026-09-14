"""Image positions in provider-linked current statute payloads."""

import json
from hashlib import sha256
from typing import Any

from klegal_gold.assets.images import valid_lawgo_image_url, validate_image
from klegal_gold.db.records import Records
from klegal_gold.documents.reader import statute_image_occurrences


def current_statute_images(
    records: Records,
    html: str,
    statutes: list[dict[str, Any]],
    prior: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    refs = statute_image_occurrences(html, parsed_statutes=statutes)
    previous = {
        (r["article_reference_id"], r["reference_id"], r["payload_sha256"]): r for r in prior or []
    }
    for index, ref in enumerate(refs):
        url = ref["resolved_url"]
        safe = valid_lawgo_image_url(url)
        article = statutes[ref["article_order"]]
        ref.update(
            source_system="law_go_kr",
            source_id=article.get("lawgo_source_id", ""),
            reference_status="RESOLVED" if safe else "UNRESOLVED",
            reason="Image in preserved provider statute payload",
            payload_artifact_id=article.get("payload_artifact_id"),
            status="PENDING",
            acquisition={"url": url, "status": "PENDING"},
        )
        with records.db.connect() as conn:
            saved = (
                conn.execute("SELECT * FROM image_acquisitions WHERE url=%s", (url,)).fetchone()
                if safe
                else None
            )
            attempt = (
                conn.execute(
                    "SELECT attempt_id,recorded_at,job_id FROM image_acquisition_attempts "
                    "WHERE url=%s ORDER BY recorded_at DESC,attempt_id DESC LIMIT 1",
                    (url,),
                ).fetchone()
                if safe
                else None
            )
        if saved:
            state = saved["status"]
            ref.update(
                status=state,
                acquisition={
                    "url": url,
                    "status": state,
                    "error": saved["last_error_code"],
                    "attempt": attempt,
                },
            )
            if state == "ACQUIRED":
                digest = saved["blob_hash"]
                raw = records.store.path(f"blobs/{digest[:2]}/{digest}").read_bytes()
                if sha256(raw).hexdigest() != digest:
                    raise ValueError("STATUTE_IMAGE_HASH_MISMATCH")
                ref["decode"] = validate_image(raw)
                records.put_artifact(
                    "reader-image:" + digest,
                    raw,
                    origin="DERIVED",
                    metadata={"kind": "PRESERVED_IMAGE_BYTES"},
                )
                ref["blob_hash"] = digest
                ref["acquisition"]["sha256"] = digest
        old = previous.get(
            (ref["article_reference_id"], ref["reference_id"], ref["payload_sha256"])
        )
        if old and old.get("blob_hash") and not ref.get("blob_hash"):
            refs[index] = {**ref, **old}
    result: list[dict[str, Any]] = json.loads(json.dumps(refs, default=str))
    return result
