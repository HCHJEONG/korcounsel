"""Immutable reader manifests stored through the existing artifact repository."""

import json
import re
from hashlib import sha256
from typing import Any

from klegal_gold.assets.images import image_metadata, validate_image
from klegal_gold.db.records import Records
from klegal_gold.documents.reader import (
    STATUTE_IMAGE_VERSION,
    VERSION,
    image_occurrences,
    render_document,
    validate_statute_image_links,
)
from klegal_gold.enrichment.legacy_statutes import statute_occurrences

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
        linked_images: list[dict[str, Any]] | None = None,
        statute_images: list[dict[str, Any]] | None = None,
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
                ref["media_type"] = MEDIA[validate_image(raw)["format"]]
            ref["acquisition"] = acquired
        if linked_images is not None:
            if origin != "LEGACY_CORPUS" or len(linked_images) != len(refs):
                raise ValueError("INVALID_LEGACY_IMAGE_LINKS")
            for original, linked in zip(refs, linked_images, strict=True):
                if any(original[k] != linked[k] for k in ("reference_id", "html_tag", "order")):
                    raise ValueError("LEGACY_IMAGE_POSITION_MISMATCH")
                if linked.get("blob_hash"):
                    if not linked.get("link_evidence"):
                        raise ValueError("MISSING_IMAGE_LINK_EVIDENCE")
                    validate_image(self.records.read("reader-image:" + linked["blob_hash"]))
            refs = linked_images
        raw = html.encode()
        html_hash = sha256(raw).hexdigest()
        parent_id = "reader-html:" + html_hash
        entries: dict[str, dict[str, Any]] = {
            parent_id: {
                "artifact_id": parent_id,
                "raw": raw,
                "origin": "DERIVED",
                "metadata": {"kind": "READER_SOURCE_HTML"},
            }
        }
        statutes = statute_occurrences(html)
        for article in statutes:
            if article["payload"]:
                artifact = "legacy-statute:" + article["payload_sha256"]
                entries[artifact] = {
                    "artifact_id": artifact,
                    "raw": article["payload"].encode(),
                    "origin": "DERIVED",
                    "metadata": {"kind": "LEGACY_LAWGO_PAYLOAD", "version_status": "UNVERIFIED"},
                }
                article["payload_artifact_id"] = artifact
        statute_refs = None
        if statute_images is not None:
            validate_statute_image_links(html, statute_images, parsed_statutes=statutes)
            statute_refs = [dict(ref) for ref in statute_images]
            for ref in statute_refs:
                acquired = ref.get("acquisition", {})
                if not isinstance(acquired, dict):
                    raise ValueError("INVALID_STATUTE_IMAGE_ACQUISITION")
                if ref.get("blob_hash"):
                    _, media = self._statute_blob(ref)
                    ref["media_type"] = media
                elif ref.get("status") == "ACQUIRED" or acquired.get("status") == "ACQUIRED":
                    raise ValueError("STATUTE_IMAGE_BLOB_MISSING")
        payload = {
            "version": STATUTE_IMAGE_VERSION if statute_refs is not None else VERSION,
            "title": title,
            "source_id": source_id,
            "origin": origin,
            "provenance": provenance,
            "html_artifact_id": parent_id,
            "html_sha256": html_hash,
            "images": refs,
            "statutes": statutes,
        }
        if statute_refs is not None:
            payload["statute_images"] = statute_refs
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        document_id = sha256(encoded).hexdigest()
        # Validate renderability before publishing the immutable manifest.
        render_document(
            html, refs, document_id, parsed_statutes=statutes, statute_images=statute_refs
        )
        entries["reader:" + document_id] = {
            "artifact_id": "reader:" + document_id,
            "raw": encoded,
            "origin": "MANIFEST",
            "parent_id": parent_id,
            "metadata": {
                "kind": "READER_DOCUMENT",
                "title": title,
                "source_id": source_id,
                "origin": origin,
                "image_count": len(refs),
                "acquired_count": sum(bool(r.get("blob_hash")) for r in refs),
                **(
                    {
                        "statute_image_count": len(statute_refs),
                        "statute_image_acquired_count": sum(
                            bool(r.get("blob_hash")) for r in statute_refs
                        ),
                    }
                    if statute_refs is not None
                    else {}
                ),
                **(
                    {
                        "legacy_body_hash": html_hash,
                        "legacy_position": provenance["row_position"],
                        "legacy_snapshot": provenance["snapshot_sha256"],
                    }
                    if origin == "LEGACY_CORPUS"
                    else {}
                ),
            },
        }
        self.records.put_artifacts(list(entries.values()))
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
        return render_document(
            html,
            manifest["images"],
            document_id,
            statute_images=self._manifest_statute_images(manifest),
        )

    @staticmethod
    def _manifest_statute_images(manifest: dict[str, Any]) -> list[dict[str, Any]] | None:
        refs = manifest.get("statute_images")
        if "statute_images" not in manifest and manifest.get("version") != STATUTE_IMAGE_VERSION:
            return None
        if (
            manifest.get("version") != STATUTE_IMAGE_VERSION
            or not isinstance(refs, list)
            or any(not isinstance(ref, dict) for ref in refs)
        ):
            raise ValueError("INVALID_STATUTE_IMAGE_MANIFEST")
        return refs

    def _statute_blob(self, ref: dict[str, Any]) -> tuple[bytes, str]:
        digest = ref.get("blob_hash")
        acquired = ref.get("acquisition")
        if (
            not isinstance(digest, str)
            or re.fullmatch("[0-9a-f]{64}", digest) is None
            or ref.get("status") != "ACQUIRED"
            or not isinstance(acquired, dict)
            or acquired.get("status") != "ACQUIRED"
            or acquired.get("sha256") != digest
            or acquired.get("url") != ref.get("resolved_url")
        ):
            raise ValueError("INVALID_STATUTE_IMAGE_ACQUISITION")
        raw = self.records.read("reader-image:" + digest)
        if sha256(raw).hexdigest() != digest:
            raise ValueError("STATUTE_IMAGE_HASH_MISMATCH")
        return raw, MEDIA[validate_image(raw)["format"]]

    def statute_image(
        self, document_id: str, article_order: int, image_order: int
    ) -> tuple[bytes, str]:
        manifest = self.read(document_id)
        refs = self._manifest_statute_images(manifest)
        if refs is None or article_order < 0 or image_order < 0:
            raise ValueError("STATUTE_IMAGE_UNAVAILABLE")
        html = self.records.read(manifest["html_artifact_id"]).decode()
        if sha256(html.encode()).hexdigest() != manifest["html_sha256"]:
            raise ValueError("READER_PARENT_MISMATCH")
        validate_statute_image_links(html, refs)
        for ref in refs:
            if ref["article_order"] == article_order and ref["order"] == image_order:
                return self._statute_blob(ref)
        raise ValueError("STATUTE_IMAGE_UNAVAILABLE")

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
                   AND metadata->>'origin'='CURRENT_SOURCE'
                   AND strpos(lower(metadata->>'title'), lower(%s))>0
                   ORDER BY created_at DESC,artifact_id LIMIT 30""",
                (query,),
            ).fetchall()
        return [
            {"document_id": r["artifact_id"].removeprefix("reader:"), **r["metadata"]} for r in rows
        ]

    def find_legacy(self, body_hash: str, position: int, snapshot: str) -> str | None:
        with self.records.db.connect() as conn:
            row = conn.execute(
                """SELECT artifact_id FROM artifacts
                   WHERE metadata->>'kind'='READER_DOCUMENT'
                   AND metadata->>'legacy_body_hash'=%s
                   AND metadata->>'legacy_position'=%s
                   AND metadata->>'legacy_snapshot'=%s
                   ORDER BY created_at DESC,artifact_id DESC LIMIT 1""",
                (body_hash, str(position), snapshot),
            ).fetchone()
        return row["artifact_id"].removeprefix("reader:") if row else None
