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
        linked_statutes: list[dict[str, Any]] | None = None,
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
        self.validate_name_links(html, refs, title=title, source_id=source_id)
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
        if linked_statutes is not None:
            if origin != "CURRENT_SOURCE" or len(statutes) != len(linked_statutes):
                raise ValueError("INVALID_CURRENT_STATUTE_LINKS")
            for observed, linked in zip(statutes, linked_statutes, strict=True):
                for key in (
                    "order",
                    "reference_id",
                    "html_tag",
                    "html_start",
                    "html_end",
                    "parent_html_sha256",
                    "text",
                    "source_attributes",
                ):
                    if observed[key] != linked.get(key):
                        raise ValueError("CURRENT_STATUTE_POSITION_MISMATCH")
                if linked["payload"] != observed["payload"]:
                    from klegal_gold.enrichment.current_lawgo import article_table

                    raw = self.records.read(linked["payload_artifact_id"])
                    frame = self.records.read(linked["frame_artifact_id"]).decode()
                    if (
                        article_table(raw.decode()) != linked["payload"]
                        or linked["provider_link"]["provider_tag"] not in frame
                    ):
                        raise ValueError("CURRENT_STATUTE_EVIDENCE_MISMATCH")
            statutes = linked_statutes
        for article in statutes:
            if article["payload"] and not article.get("provider_link"):
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
                **(
                    {"current_root_document_id": provenance["current_root_document_id"]}
                    if origin == "CURRENT_SOURCE" and "current_root_document_id" in provenance
                    else {}
                ),
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
        if origin == "CURRENT_SOURCE":
            self.index_current(document_id, title, html)
        return document_id

    def refresh_current_images(self, document_id: str) -> str:
        from klegal_gold.enrichment.statute_images import current_statute_images

        manifest = self.read(document_id)
        if manifest.get("origin") != "CURRENT_SOURCE":
            raise ValueError("NOT_CURRENT_READER")
        urls = sorted(
            {str(ref["resolved_url"]) for ref in manifest["images"] if ref.get("resolved_url")}
        )
        acquisitions: dict[str, dict[str, Any]] = {}
        if urls:
            with self.records.db.connect() as conn:
                rows = conn.execute(
                    "SELECT url,status,blob_hash,last_error_code FROM image_acquisitions "
                    "WHERE url=ANY(%s)",
                    (urls,),
                ).fetchall()
            for row in rows:
                entry: dict[str, Any] = {"url": row["url"], "status": row["status"]}
                if row["status"] == "ACQUIRED":
                    digest = row["blob_hash"]
                    raw = self.records.store.path(f"blobs/{digest[:2]}/{digest}").read_bytes()
                    if sha256(raw).hexdigest() != digest:
                        raise ValueError("READER_IMAGE_HASH_MISMATCH")
                    self.records.put_artifact(
                        "reader-image:" + digest,
                        raw,
                        origin="DERIVED",
                        metadata={"kind": "PRESERVED_IMAGE_BYTES"},
                    )
                    entry["sha256"] = digest
                elif row["last_error_code"]:
                    entry["error"] = row["last_error_code"]
                acquisitions[row["url"]] = entry
        provenance = dict(manifest["provenance"])
        provenance["current_root_document_id"] = provenance.get(
            "current_root_document_id", document_id
        )
        provenance["previous_reader_document_id"] = document_id
        provenance["image_refresh"] = "image-acquisition-ledger-1"
        return self.preserve(
            self.records.read(manifest["html_artifact_id"]).decode(),
            title=manifest["title"],
            source_id=manifest["source_id"],
            origin="CURRENT_SOURCE",
            provenance=provenance,
            acquisitions=acquisitions,
            statute_images=current_statute_images(
                self.records,
                self.records.read(manifest["html_artifact_id"]).decode(),
                manifest["statutes"],
                manifest.get("statute_images"),
            ),
            linked_statutes=[
                next(
                    (
                        old
                        for old in manifest["statutes"]
                        if old["reference_id"] == ref["reference_id"]
                    ),
                    ref,
                )
                for ref in statute_occurrences(
                    self.records.read(manifest["html_artifact_id"]).decode()
                )
            ],
        )

    def validate_name_links(
        self, html: str, refs: list[dict[str, Any]], *, title: str, source_id: str
    ) -> None:
        """Recompute only the new name-display proofs; prior exact link versions stay intact."""
        from klegal_gold.documents.image_links import NAME_LINK_VERSION, link_legacy_images

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        metadata_bound: set[tuple[str, str]] = set()
        for ref in refs:
            proof = ref.get("link_evidence", {})
            if "name_comparison" not in proof and proof.get("version") != NAME_LINK_VERSION:
                continue
            if proof.get("version") != NAME_LINK_VERSION or not isinstance(
                proof.get("name_comparison"), dict
            ):
                raise ValueError("INVALID_IMAGE_NAME_LINK")
            current_hash = proof.get("current_html_sha256", "")
            if not isinstance(current_hash, str) or not re.fullmatch("[0-9a-f]{64}", current_hash):
                raise ValueError("INVALID_IMAGE_NAME_LINK")
            comparison = proof.get("title_comparison")
            if comparison is None:
                binding = proof["name_comparison"].get("source_title_binding")
                if not isinstance(binding, dict):
                    raise ValueError("INVALID_IMAGE_NAME_LINK")
                current_title = binding.get("current_title")
                if isinstance(current_title, str) and (
                    current_title != title or binding.get("current_header") != current_title
                ):
                    metadata_bound.add((current_hash, current_title))
            else:
                current_title = (
                    comparison.get("current_title") if isinstance(comparison, dict) else None
                )
            if not isinstance(current_title, str):
                raise ValueError("INVALID_IMAGE_NAME_LINK")
            grouped.setdefault((current_hash, current_title), []).append(ref)
        for (current_hash, current_title), selected in grouped.items():
            if (current_hash, current_title) in metadata_bound:
                self._validate_current_name_title(current_hash, current_title, source_id)
            raw = self.records.read("reader-html:" + current_hash)
            if sha256(raw).hexdigest() != current_hash:
                raise ValueError("CURRENT_BODY_HASH_MISMATCH")
            current_html = raw.decode()
            current = {
                "source_id": source_id,
                "title": current_title,
                "html_sha256": current_hash,
                "images": image_occurrences(
                    current_html, source_id=source_id, base_url="https://portal.scourt.go.kr/"
                ),
            }
            expected = link_legacy_images(
                html, current_html, current, source_id=source_id, title=title
            )
            for ref in selected:
                order = ref.get("order")
                if (
                    type(order) is not int
                    or not 0 <= order < len(expected)
                    or ref.get("reference_id") != expected[order]["reference_id"]
                    or ref.get("name") != expected[order]["name"]
                    or ref.get("original_src") != expected[order]["original_src"]
                    or ref["link_evidence"] != expected[order].get("link_evidence")
                ):
                    raise ValueError("INVALID_IMAGE_NAME_LINK")

    def _validate_current_name_title(self, html_hash: str, title: str, source_id: str) -> None:
        """Bind newly accepted spacing differences to stored current-reader metadata."""
        parent_id = "reader-html:" + html_hash
        with self.records.db.connect() as conn:
            row = conn.execute(
                "SELECT artifact_id FROM artifacts WHERE parent_id=%s "
                "AND metadata->>'kind'='READER_DOCUMENT' "
                "AND metadata->>'origin'='CURRENT_SOURCE' "
                "AND metadata->>'source_id'=%s AND metadata->>'title'=%s "
                "AND artifact_id LIKE 'reader:%%' ORDER BY artifact_id LIMIT 1",
                (parent_id, source_id, title),
            ).fetchone()
        if row is None:
            raise ValueError("INVALID_IMAGE_NAME_LINK")
        current = self.read(row["artifact_id"].removeprefix("reader:"))
        if (
            current.get("origin") != "CURRENT_SOURCE"
            or current.get("source_id") != source_id
            or current.get("title") != title
            or current.get("html_sha256") != html_hash
            or current.get("html_artifact_id") != parent_id
        ):
            raise ValueError("INVALID_IMAGE_NAME_LINK")

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
        rendered = render_document(
            html,
            manifest["images"],
            document_id,
            statute_images=self._manifest_statute_images(manifest),
            parsed_statutes=manifest["statutes"],
        )
        if manifest["origin"] == "CURRENT_SOURCE":
            state = manifest["provenance"].get("lawgo_status", "PENDING")
            label = {
                "EXACT": "lawgo 판례 연결 확인 · 조문별 보강 상태와 적용 버전은 각 위치에서 확인",
                "UNMATCHED": "lawgo 대응 판례 미연결",
                "AMBIGUOUS": "lawgo 연결 후보 모호 · 검토 필요",
                "CONFLICT": "lawgo 연결 정보 충돌 · 검토 필요",
                "CREDENTIAL_UNAVAILABLE": "lawgo 취득 설정 미완료 · 보강 대기",
                "METADATA_INCOMPLETE": "lawgo 연결 대조 정보 부족 · 보강 대기",
            }.get(state, "lawgo 연결·보강 대기")
            rendered = rendered.replace(
                "<body>", '<body><p class="statute-status">' + label + "</p>", 1
            )
        return rendered

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
        validate_statute_image_links(html, refs, parsed_statutes=manifest["statutes"])
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

    def search(self, query: str = "", *, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("INVALID_READER_SEARCH_LIMIT")
        with self.records.db.connect() as conn:
            rows = conn.execute(
                """SELECT artifact_id,metadata FROM (
                     SELECT DISTINCT ON(a.metadata->>'source_id')
                       a.artifact_id,a.metadata,a.created_at
                     FROM artifacts a LEFT JOIN artifacts root ON root.artifact_id=
                       'reader:' || (a.metadata->>'current_root_document_id')
                     WHERE a.metadata->>'kind'='READER_DOCUMENT'
                     AND a.metadata->>'origin'='CURRENT_SOURCE'
                     ORDER BY a.metadata->>'source_id',
                       COALESCE(root.created_at,a.created_at) DESC,
                       a.created_at DESC,a.artifact_id DESC
                   ) latest WHERE strpos(lower(metadata->>'title'),lower(%s))>0
                   ORDER BY created_at DESC,artifact_id DESC LIMIT %s OFFSET %s""",
                (query, limit, offset),
            ).fetchall()
        return [
            {"document_id": r["artifact_id"].removeprefix("reader:"), **r["metadata"]} for r in rows
        ]

    def index_current(self, document_id: str, title: str, html: str) -> None:
        with self.records.db.connect() as conn:
            conn.execute(
                "INSERT INTO current_reader_search VALUES(%s,%s,%s) "
                "ON CONFLICT(artifact_id) DO NOTHING",
                ("reader:" + document_id, title.casefold(), html.casefold()),
            )

    def rebuild_current_search(self, progress: Any) -> None:
        # Missing rows are the durable checkpoint. A published immutable reader
        # remains usable if indexing was interrupted after artifact registration.
        while True:
            with self.records.db.connect() as conn:
                rows = conn.execute(
                    "SELECT a.artifact_id FROM artifacts a LEFT JOIN current_reader_search s "
                    "USING(artifact_id) WHERE a.metadata->>'kind'='READER_DOCUMENT' "
                    "AND a.metadata->>'origin'='CURRENT_SOURCE' AND s.artifact_id IS NULL "
                    "ORDER BY a.artifact_id LIMIT 100"
                ).fetchall()
            if not rows:
                return
            for row in rows:
                document_id = row["artifact_id"].removeprefix("reader:")
                manifest = self.read(document_id)
                html = self.records.read(manifest["html_artifact_id"]).decode()
                if sha256(html.encode()).hexdigest() != manifest["html_sha256"]:
                    raise ValueError("READER_PARENT_MISMATCH")
                self.index_current(document_id, manifest["title"], html)
                progress({"phase": "CURRENT_READER_INDEX"})

    def search_indexed(self, query: str, *, limit: int) -> list[dict[str, Any]] | None:
        if "\x00" in query:
            return None
        latest = """WITH latest AS (
            SELECT DISTINCT ON(a.metadata->>'source_id')
                a.artifact_id,a.metadata,a.created_at
            FROM artifacts a LEFT JOIN artifacts root ON root.artifact_id=
                'reader:' || (a.metadata->>'current_root_document_id')
            WHERE a.metadata->>'kind'='READER_DOCUMENT'
                AND a.metadata->>'origin'='CURRENT_SOURCE'
            ORDER BY a.metadata->>'source_id', COALESCE(root.created_at,a.created_at) DESC,
                a.created_at DESC,a.artifact_id DESC
        ) """
        needle = query.casefold()
        pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self.records.db.connect() as conn:
            missing = conn.execute(
                latest + "SELECT 1 FROM latest LEFT JOIN current_reader_search USING(artifact_id) "
                "WHERE title_text IS NULL LIMIT 1"
            ).fetchone()
            if missing:
                return None
            # Keep the existing title-first policy; only use body matches when
            # there are no title hits. Filter after choosing the latest revision.
            for column in ("title_text", "html_text"):
                rows = conn.execute(
                    latest
                    + "SELECT latest.* FROM latest JOIN current_reader_search USING(artifact_id) "
                    f"WHERE {column} LIKE %s ORDER BY created_at DESC,artifact_id DESC LIMIT %s",
                    (pattern, limit),
                ).fetchall()
                if rows:
                    return [
                        {
                            "document_id": row["artifact_id"].removeprefix("reader:"),
                            **row["metadata"],
                            "indexed_column": column,
                        }
                        for row in rows
                    ]
        return []

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
