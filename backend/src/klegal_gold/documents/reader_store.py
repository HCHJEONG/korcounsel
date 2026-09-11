"""Immutable reader manifests stored through the existing artifact repository."""

import json
import re
from hashlib import sha256
from typing import Any

from klegal_gold.assets.images import image_metadata
from klegal_gold.db.records import Records
from klegal_gold.documents.reader import VERSION, image_occurrences, render_document

MEDIA = {
    "GIF": "image/gif",
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
}


class ReaderStore:
    def __init__(self, records: Records) -> None:
        self.records = records

    def preserve(
        self,
        html: str,
        *,
        title: str,
        source_id: str,
        origin: str,
        provenance: dict[str, Any],
        acquisitions: dict[str, dict[str, Any]],
    ) -> str:
        base = (
            "https://portal.scourt.go.kr/"
            if origin == "CURRENT_SOURCE"
            else "https://glaw.scourt.go.kr/"
        )
        refs = image_occurrences(html, source_id=source_id, base_url=base)
        for ref in refs:
            acquired = acquisitions.get(ref["resolved_url"], {})
            ref["status"] = acquired.get("status", "PENDING")
            if acquired.get("status") == "ACQUIRED":
                digest = acquired["sha256"]
                raw = self.records.read("reader-image:" + digest)
                if sha256(raw).hexdigest() != digest:
                    raise ValueError("READER_IMAGE_HASH_MISMATCH")
                ref["blob_hash"] = digest
                ref["media_type"] = MEDIA[image_metadata(raw)["format"]]
            ref["acquisition"] = acquired
        raw = html.encode()
        html_hash = sha256(raw).hexdigest()
        parent_id = "reader-html:" + html_hash
        self.records.put_artifact(
            parent_id, raw, origin="DERIVED", metadata={"kind": "READER_SOURCE_HTML"}
        )
        payload = {
            "version": VERSION,
            "title": title,
            "source_id": source_id,
            "origin": origin,
            "provenance": provenance,
            "html_artifact_id": parent_id,
            "html_sha256": html_hash,
            "images": refs,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        document_id = sha256(encoded).hexdigest()
        # Validate renderability before publishing the immutable manifest.
        render_document(html, refs, document_id)
        self.records.put_artifact(
            "reader:" + document_id,
            encoded,
            origin="MANIFEST",
            parent_id=parent_id,
            metadata={
                "kind": "READER_DOCUMENT",
                "title": title,
                "source_id": source_id,
                "origin": origin,
                "image_count": len(refs),
                "acquired_count": sum(bool(r.get("blob_hash")) for r in refs),
            },
        )
        return document_id

    def read(self, document_id: str) -> dict[str, Any]:
        if not re.fullmatch("[0-9a-f]{64}", document_id):
            raise ValueError("READER_NOT_FOUND")
        raw = self.records.read("reader:" + document_id)
        if sha256(raw).hexdigest() != document_id:
            raise ValueError("READER_HASH_MISMATCH")
        result: dict[str, Any] = json.loads(raw)
        return result

    def html(self, document_id: str) -> str:
        manifest = self.read(document_id)
        html = self.records.read(manifest["html_artifact_id"]).decode()
        if sha256(html.encode()).hexdigest() != manifest["html_sha256"]:
            raise ValueError("READER_PARENT_MISMATCH")
        return render_document(html, manifest["images"], document_id)

    def image(self, document_id: str, order: int) -> tuple[bytes, str]:
        manifest = self.read(document_id)
        refs = manifest["images"]
        if not 0 <= order < len(refs) or not refs[order].get("blob_hash"):
            raise ValueError("READER_IMAGE_UNAVAILABLE")
        ref = refs[order]
        raw = self.records.read("reader-image:" + ref["blob_hash"])
        return raw, MEDIA[image_metadata(raw)["format"]]

    def search(self, query: str = "") -> list[dict[str, Any]]:
        with self.records.db.connect() as conn:
            rows = conn.execute(
                """SELECT artifact_id,metadata FROM artifacts
                   WHERE metadata->>'kind'='READER_DOCUMENT'
                   AND strpos(lower(metadata->>'title'), lower(%s))>0
                   ORDER BY created_at DESC,artifact_id LIMIT 30""",
                (query,),
            ).fetchall()
        return [
            {"document_id": r["artifact_id"].removeprefix("reader:"), **r["metadata"]} for r in rows
        ]
