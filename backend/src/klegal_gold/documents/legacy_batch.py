"""Bounded, hash-pinned legacy reader publication through the persistent worker.

Downloads remain separate jobs. Ledger completion concerns reader preservation,
never successful acquisition of every image or verification of a law version.
"""

import json
import re
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq
from psycopg.types.json import Jsonb

from klegal_gold.assets.images import valid_lawgo_image_url, validate_image
from klegal_gold.db.records import Records
from klegal_gold.documents.image_links import link_legacy_images
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.search.parquet import _original_index, _text, legacy_snapshot

if TYPE_CHECKING:
    from klegal_gold.jobs.queue import Job

VERSION = "legacy-reader-batch-1"
COLUMNS = (
    "__legacy_position",
    "__legacy_index",
    "case_txt_scraped_with_tags",
    "case_full_no",
    "gmeta_contId",
    "lmeta_serialno",
)
Progress = Callable[[dict[str, Any]], None]


def validate_input(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("INVALID_LEGACY_READER_BATCH_INPUT")
    positions = payload.get("positions")
    current = payload.get("current_readers", {})
    if (
        payload.get("version") != VERSION
        or (
            "acquisition_revision" in payload
            and (
                not isinstance(payload["acquisition_revision"], str)
                or not re.fullmatch("[0-9a-f]{64}", payload["acquisition_revision"])
            )
        )
        or (
            "retry_generation" in payload
            and (type(payload["retry_generation"]) is not int or payload["retry_generation"] < 0)
        )
        or (
            "include_statute_images" in payload
            and type(payload["include_statute_images"]) is not bool
        )
        or not isinstance(positions, list)
        or not 1 <= len(positions) <= 100
        or any(type(p) is not int or p < 0 for p in positions)
        or len(set(positions)) != len(positions)
        or not isinstance(current, dict)
        or any(
            str(p) not in {str(x) for x in positions}
            or not isinstance(reader, str)
            or not re.fullmatch("[0-9a-f]{64}", reader)
            for p, reader in current.items()
        )
        or any(
            not isinstance(payload.get(field), str)
            or not re.fullmatch("[0-9a-f]{64}", payload[field])
            for field in ("parquet_sha256", "snapshot_sha256")
        )
    ):
        raise ValueError("INVALID_LEGACY_READER_BATCH_INPUT")


def _fingerprint(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class LegacyReaderBatch:
    def __init__(self, records: Records) -> None:
        self.records = records
        self.reader = ReaderStore(records)
        # A process must hash all bytes before using this cache. Any observable file
        # replacement/change invalidates it; it never trusts a supplied checksum alone.
        self._verified: tuple[Path, tuple[int, int, int, int, int], str] | None = None
        self._group: tuple[int, dict[int, dict[str, Any]]] | None = None

    def verify_input(self, path: Path, payload: dict[str, Any], progress: Progress) -> None:
        validate_input(payload)
        signature = _fingerprint(path)
        key = (path.resolve(), signature, payload["parquet_sha256"])
        if self._verified != key:
            digest = sha256()
            checked = 0
            with path.open("rb") as stream:
                while chunk := stream.read(8 * 1024 * 1024):
                    digest.update(chunk)
                    checked += len(chunk)
                    progress({"phase": "VERIFY_PARQUET", "bytes_checked": checked})
            if digest.hexdigest() != payload["parquet_sha256"] or _fingerprint(path) != signature:
                raise ValueError("LEGACY_PARQUET_HASH_MISMATCH")
            self._verified = key
            self._group = None
        if legacy_snapshot(path) != payload["snapshot_sha256"]:
            raise ValueError("LEGACY_SNAPSHOT_MISMATCH")

    def _select(self, path: Path, positions: list[int]) -> dict[int, dict[str, Any]]:
        selected: dict[int, dict[str, Any]] = {}
        parquet = pq.ParquetFile(path)
        locator = parquet.schema.names.index("__legacy_position")
        for group in range(parquet.num_row_groups):
            stats = parquet.metadata.row_group(group).column(locator).statistics
            if (
                stats
                and stats.has_min_max
                and not any(stats.min <= p <= stats.max for p in positions)
            ):
                continue
            if self._group is None or self._group[0] != group:
                rows = parquet.read_row_group(group, columns=list(COLUMNS)).to_pylist()
                self._group = (group, {r["__legacy_position"]: r for r in rows})
                if len(self._group[1]) != len(rows):
                    raise ValueError("DUPLICATE_LEGACY_POSITION")
            for position in positions:
                if position in self._group[1]:
                    if position in selected:
                        raise ValueError("DUPLICATE_LEGACY_POSITION")
                    selected[position] = self._group[1][position]
        if self._verified is not None and _fingerprint(path) != self._verified[1]:
            self._verified = None
            raise ValueError("LEGACY_PARQUET_CHANGED")
        return selected

    def _links(
        self, html: str, title: str, source: str, current_id: str, prior: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        current = self.reader.read(current_id)
        if current["origin"] != "CURRENT_SOURCE":
            raise ValueError("EXPECTED_CURRENT_SOURCE_READER")
        current_html = self.records.read(current["html_artifact_id"]).decode()
        if sha256(current_html.encode()).hexdigest() != current["html_sha256"]:
            raise ValueError("CURRENT_BODY_HASH_MISMATCH")
        linked = link_legacy_images(html, current_html, current, source_id=source, title=title)
        previous = {r["reference_id"]: r for r in prior["images"]} if prior else {}
        pending = []
        urls = [r["link_evidence"]["resolved_url"] for r in linked if r.get("link_evidence")]
        with self.records.db.connect() as conn:
            acquired = (
                {
                    row["url"]: row
                    for row in conn.execute(
                        "SELECT * FROM image_acquisitions WHERE url=ANY(%s)", (urls,)
                    ).fetchall()
                }
                if urls
                else {}
            )
            attempts = (
                {
                    row["url"]: row
                    for row in conn.execute(
                        "SELECT DISTINCT ON(url) url,attempt_id,recorded_at,job_id "
                        "FROM image_acquisition_attempts WHERE url=ANY(%s) "
                        "ORDER BY url,recorded_at DESC,attempt_id DESC",
                        (urls,),
                    ).fetchall()
                }
                if urls
                else {}
            )
        for index, ref in enumerate(linked):
            evidence = ref.get("link_evidence")
            if evidence:
                url = evidence["resolved_url"]
                saved = acquired.get(url)
                attempt_row = attempts.get(url)
                attempt = (
                    {key: value for key, value in attempt_row.items() if key != "url"}
                    if attempt_row
                    else None
                )
                if saved and saved["status"] == "ACQUIRED":
                    digest = saved["blob_hash"]
                    raw = self.records.store.path(f"blobs/{digest[:2]}/{digest}").read_bytes()
                    if sha256(raw).hexdigest() != digest:
                        raise ValueError("IMAGE_HASH_MISMATCH")
                    metadata = validate_image(raw)
                    self.records.put_artifact(
                        "reader-image:" + digest,
                        raw,
                        origin="DERIVED",
                        metadata={"kind": "PRESERVED_IMAGE_BYTES"},
                    )
                    ref.update(
                        blob_hash=digest,
                        status="ACQUIRED",
                        decode=metadata,
                        acquisition={"url": url, "attempt": attempt},
                    )
                elif saved and not ref.get("blob_hash"):
                    ref.update(
                        status=saved["status"],
                        acquisition={
                            "url": url,
                            "attempt": attempt,
                            "error": saved["last_error_code"],
                        },
                    )
            # A new mapping or absent acquisition may not erase an already proven
            # occurrence. The older link evidence remains explicit in this revision.
            old = previous.get(ref["reference_id"])
            if old and old.get("blob_hash") and not ref.get("blob_hash"):
                linked[index] = ref = dict(old)
                evidence = ref.get("link_evidence")
            if ref.get("blob_hash"):
                ref["decode"] = validate_image(
                    self.records.read("reader-image:" + ref["blob_hash"])
                )
            elif evidence:
                pending.append(
                    {
                        **{key: value for key, value in ref.items() if key != "reference_id"},
                        "legacy_reader_reference_id": ref["reference_id"],
                        "occurrence_order": ref["order"],
                        "source_id": source,
                        "source_system": "scourt",
                        "resolved_url": evidence["resolved_url"],
                        "reference_status": "RESOLVED",
                        "reason": ref["link_reason"],
                        "current_reader_id": current_id,
                    }
                )
        return json.loads(json.dumps(linked, default=str)), pending

    def _statute_links(
        self, html: str, lawgo_id: str, prior: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Use only image URLs actually retained inside a legacy lawgo payload."""
        from klegal_gold.documents.reader import statute_image_occurrences

        refs = statute_image_occurrences(html)
        previous = {
            (r["article_reference_id"], r["reference_id"]): r
            for r in (prior or {}).get("statute_images", [])
        }
        urls = sorted(
            {
                r["resolved_url"]
                for r in refs
                if r.get("resolved_url") and valid_lawgo_image_url(r["resolved_url"])
            }
        )
        with self.records.db.connect() as conn:
            acquired = (
                {
                    row["url"]: row
                    for row in conn.execute(
                        "SELECT * FROM image_acquisitions WHERE url=ANY(%s)", (urls,)
                    ).fetchall()
                }
                if urls
                else {}
            )
            attempts = (
                {
                    row["url"]: row
                    for row in conn.execute(
                        "SELECT DISTINCT ON(url) url,attempt_id,recorded_at,job_id "
                        "FROM image_acquisition_attempts WHERE url=ANY(%s) "
                        "ORDER BY url,recorded_at DESC,attempt_id DESC",
                        (urls,),
                    ).fetchall()
                }
                if urls
                else {}
            )
        pending = []
        for index, ref in enumerate(refs):
            url = ref.get("resolved_url")
            safe = bool(url and valid_lawgo_image_url(url))
            ref.update(
                source_system="law_go_kr",
                source_id=lawgo_id,
                status="PENDING",
                reference_status="RESOLVED" if safe else "UNRESOLVED",
                reason=(
                    "Image URL preserved inside the case's legacy lawgo statute payload"
                    if safe
                    else "Preserved statute image URL is outside the official HTTPS endpoint"
                ),
                acquisition={"url": url, "status": "PENDING"},
            )
            saved = acquired.get(url) if safe else None
            attempt = attempts.get(url)
            if attempt:
                attempt = {key: value for key, value in attempt.items() if key != "url"}
            if saved and saved["status"] == "ACQUIRED":
                digest = saved["blob_hash"]
                raw = self.records.store.path(f"blobs/{digest[:2]}/{digest}").read_bytes()
                if sha256(raw).hexdigest() != digest:
                    raise ValueError("IMAGE_HASH_MISMATCH")
                metadata = validate_image(raw)
                self.records.put_artifact(
                    "reader-image:" + digest,
                    raw,
                    origin="DERIVED",
                    metadata={"kind": "PRESERVED_IMAGE_BYTES"},
                )
                ref.update(
                    blob_hash=digest,
                    status="ACQUIRED",
                    decode=metadata,
                    acquisition={
                        "url": url,
                        "status": "ACQUIRED",
                        "sha256": digest,
                        "attempt": attempt,
                    },
                )
            elif saved:
                ref.update(
                    status=saved["status"],
                    acquisition={
                        "url": url,
                        "status": saved["status"],
                        "attempt": attempt,
                        "error": saved["last_error_code"],
                    },
                )
            old = previous.get((ref["article_reference_id"], ref["reference_id"]))
            if old and old.get("blob_hash") and not ref.get("blob_hash"):
                refs[index] = ref = dict(old)
            if ref.get("blob_hash"):
                ref["decode"] = validate_image(
                    self.records.read("reader-image:" + ref["blob_hash"])
                )
            else:
                # The worker preserves unresolved refs as well; only safe RESOLVED URLs fetch.
                pending.append(
                    {
                        **{key: value for key, value in ref.items() if key != "reference_id"},
                        "legacy_reader_reference_id": ref["reference_id"],
                        "occurrence_order": ref["order"],
                    }
                )
        return json.loads(json.dumps(refs, default=str)), pending

    def verify_reader(self, document_id: str) -> dict[str, Any]:
        manifest = self.reader.read(document_id)
        raw = self.records.read(manifest["html_artifact_id"])
        if sha256(raw).hexdigest() != manifest["html_sha256"]:
            raise ValueError("READER_PARENT_MISMATCH")
        checked = set()
        for ref in manifest["images"]:
            digest = ref.get("blob_hash")
            if digest and digest not in checked:
                validate_image(self.records.read("reader-image:" + digest))
                checked.add(digest)
        statute_refs = self.reader._manifest_statute_images(manifest)
        if statute_refs is not None:
            from klegal_gold.documents.reader import validate_statute_image_links

            validate_statute_image_links(raw.decode(), statute_refs)
            checked_acquisitions: set[str] = set()
            for ref in statute_refs:
                acquired = ref.get("acquisition", {})
                if not isinstance(acquired, dict):
                    raise ValueError("INVALID_STATUTE_IMAGE_ACQUISITION")
                if ref.get("blob_hash"):
                    proof = json.dumps(
                        [ref["blob_hash"], ref.get("status"), ref.get("resolved_url"), acquired],
                        sort_keys=True,
                    )
                    if proof not in checked_acquisitions:
                        self.reader._statute_blob(ref)
                        checked_acquisitions.add(proof)
                elif ref.get("status") == "ACQUIRED" or (
                    isinstance(acquired, dict) and acquired.get("status") == "ACQUIRED"
                ):
                    raise ValueError("STATUTE_IMAGE_BLOB_MISSING")
        for article in manifest["statutes"]:
            artifact = article.get("payload_artifact_id")
            if artifact and artifact not in checked:
                if sha256(self.records.read(artifact)).hexdigest() != article["payload_sha256"]:
                    raise ValueError("READER_STATUTE_HASH_MISMATCH")
                checked.add(artifact)
        return manifest

    def stage_row(
        self,
        row: dict[str, Any],
        snapshot: str,
        current_id: str | None,
        *,
        include_statute_images: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        position = row["__legacy_position"]
        html = _text(row["case_txt_scraped_with_tags"])
        title = _text(row["case_full_no"]).strip()
        source = _text(row["gmeta_contId"])
        if not html.strip():
            raise ValueError("LEGACY_BODY_EMPTY")
        body_hash = sha256(html.encode()).hexdigest()
        previous_id = self.reader.find_legacy(body_hash, position, snapshot)
        pending: list[dict[str, Any]] = []
        if previous_id is not None and current_id is None and not include_statute_images:
            document_id = previous_id
            manifest = self.verify_reader(document_id)
            # Verify the archived HTML remains readable even when publication is reused.
            if self.records.read(manifest["html_artifact_id"]).decode() != html:
                raise ValueError("READER_PARENT_MISMATCH")
        else:
            prior = self.reader.read(previous_id) if previous_id else None
            provenance: dict[str, Any] = (
                dict(prior["provenance"])
                if prior
                else {
                    "snapshot_sha256": snapshot,
                    "row_position": position,
                    "original_index": _original_index(row["__legacy_index"]),
                    "field": "case_txt_scraped_with_tags",
                    "lawgo_serialno": _text(row["lmeta_serialno"]),
                    "historical_binary_identity_verified": False,
                }
            )
            linked = prior["images"] if prior else None
            statute_images = prior.get("statute_images") if prior else None
            if include_statute_images:
                statute_images, statute_pending = self._statute_links(
                    html, _text(row["lmeta_serialno"]), prior
                )
                pending.extend(statute_pending)
            if current_id is not None:
                linked, body_pending = self._links(html, title, source, current_id, prior)
                pending.extend(body_pending)
                provenance["current_reader_id"] = current_id
            document_id = self.reader.preserve(
                html,
                title=title,
                source_id=source,
                origin="LEGACY_CORPUS",
                provenance=provenance,
                acquisitions={},
                linked_images=linked,
                statute_images=statute_images,
            )
            manifest = self.reader.read(document_id)
        for ref in pending:
            ref["row_position"] = position
        result = {
            "position": position,
            "title": title,
            "body_hash": body_hash,
            "document_id": document_id,
            "images": len(manifest["images"]),
            "linked": sum(bool(x.get("blob_hash")) for x in manifest["images"]),
            "statutes": len(manifest["statutes"]),
            "preserved_statutes": sum(x["status"] == "PRESERVED" for x in manifest["statutes"]),
        }
        if "statute_images" in manifest:
            result["statute_images"] = len(manifest["statute_images"])
            result["statute_images_linked"] = sum(
                bool(ref.get("blob_hash")) for ref in manifest["statute_images"]
            )
        return result, pending

    def _download_manifest(self, pending: list[dict[str, Any]]) -> str:
        raw = json.dumps(
            {"references": pending}, ensure_ascii=False, sort_keys=True, default=str
        ).encode()
        artifact_id = "image-manifest:legacy-reader-" + sha256(raw).hexdigest()
        self.records.put_artifact(
            artifact_id, raw, origin="MANIFEST", metadata={"kind": "IMAGE_REFERENCE_MANIFEST"}
        )
        return artifact_id

    def run(self, job: "Job", path: Path, progress: Progress) -> str:
        payload = json.loads(self.records.read(job.payload["manifest_artifact_id"]))
        self.verify_input(path, payload, progress)
        positions = payload["positions"]
        selected = self._select(path, positions)
        for position in positions:
            progress({"phase": "STAGE_ROWS", "row_position": position})
            with self.records.db.connect() as conn:
                prior = conn.execute(
                    "SELECT * FROM legacy_reader_batch_rows WHERE job_id=%s AND row_position=%s",
                    (job.job_id, position),
                ).fetchone()
            if prior:
                if prior["reader_artifact"]:
                    self.verify_reader(prior["reader_artifact"].removeprefix("reader:"))
                continue
            status, artifact_id, error = "STAGED", None, None
            try:
                if position not in selected:
                    raise ValueError("LEGACY_ROW_MISSING")
                result, pending = self.stage_row(
                    selected[position],
                    payload["snapshot_sha256"],
                    payload.get("current_readers", {}).get(str(position)),
                    include_statute_images=payload.get("include_statute_images", False),
                )
                artifact_id = "reader:" + result["document_id"]
                result["pending"] = json.loads(json.dumps(pending, default=str))
            except (OSError, ValueError) as exc:
                status = "FAILED"
                # Whitelisted codes only: no paths, source HTML or exception messages.
                allowed = {
                    "LEGACY_ROW_MISSING",
                    "LEGACY_BODY_EMPTY",
                    "IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED",
                    "IMAGE_OCCURRENCE_ORDER_CONFLICT",
                    "EXPECTED_CURRENT_SOURCE_READER",
                    "CURRENT_BODY_HASH_MISMATCH",
                    "IMAGE_HASH_MISMATCH",
                    "IMAGE_DECODE_FAILED",
                    "READER_PARENT_MISMATCH",
                    "READER_STATUTE_HASH_MISMATCH",
                    "INVALID_STATUTE_IMAGE_MANIFEST",
                    "INVALID_STATUTE_IMAGE_ACQUISITION",
                    "STATUTE_IMAGE_COUNT_MISMATCH",
                    "STATUTE_IMAGE_POSITION_MISMATCH",
                    "STATUTE_IMAGE_BLOB_MISSING",
                    "STATUTE_IMAGE_HASH_MISMATCH",
                    "READER_IMAGE_HASH_MISMATCH",
                    "BLOB_INTEGRITY_FAILED",
                    "ARTIFACT_NOT_FOUND",
                    "READER_HASH_MISMATCH",
                }
                error = str(exc) if str(exc) in allowed else "LEGACY_READER_ROW_FAILED"
                result = {"position": position, "pending": []}
            with self.records.db.connect() as conn:
                owner = conn.execute(
                    "SELECT 1 FROM jobs WHERE job_id=%s AND lease_token=%s "
                    "AND status='RUNNING' AND lease_until>clock_timestamp() FOR UPDATE",
                    (job.job_id, job.lease_token),
                ).fetchone()
                if owner is None:
                    raise ValueError("LEGACY_READER_LEASE_LOST")
                conn.execute(
                    "INSERT INTO legacy_reader_batch_rows"
                    "(job_id,row_position,reader_artifact,status,result,error_code) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (job.job_id, position, artifact_id, status, Jsonb(result), error),
                )
        progress({"phase": "RECONCILE_ROWS", "rows": len(positions)})
        with self.records.db.connect() as conn:
            rows = conn.execute(
                "SELECT row_position,status,result,error_code FROM legacy_reader_batch_rows "
                "WHERE job_id=%s ORDER BY row_position",
                (job.job_id,),
            ).fetchall()
        if sorted(positions) != [r["row_position"] for r in rows]:
            raise ValueError("LEGACY_READER_RECONCILIATION_FAILED")
        pending = [ref for row in rows for ref in row["result"].get("pending", [])]
        download_id = self._download_manifest(pending)
        output = {
            "version": VERSION,
            "input_manifest": job.payload["manifest_artifact_id"],
            "parquet_sha256": payload["parquet_sha256"],
            "snapshot_sha256": payload["snapshot_sha256"],
            "staged": sum(r["status"] == "STAGED" for r in rows),
            "failed": sum(r["status"] == "FAILED" for r in rows),
            "rows": [
                {
                    **{k: v for k, v in r["result"].items() if k != "pending"},
                    "status": r["status"],
                    "error_code": r["error_code"],
                }
                for r in rows
            ],
            "download_manifest": download_id,
            "download_references": len(pending),
            "all_images_acquired": False,
            "law_versions_verified": False,
        }
        return self.records.save_manifest(
            "legacy-reader-result:" + str(job.job_id), "LEGACY_READER_BATCH", output
        )


def stage(
    path: Path,
    positions: list[int],
    current_ids: dict[int, str],
    records: Records,
    *,
    include_statute_images: bool = False,
) -> dict[str, Any]:
    """Compatibility helper for small, explicitly invoked offline/publication tests."""
    if not 1 <= len(positions) <= 50 or len(set(positions)) != len(positions):
        raise ValueError("INVALID_LEGACY_READER_SAMPLE")
    batch = LegacyReaderBatch(records)
    rows = batch._select(path, positions)
    if set(rows) != set(positions):
        raise ValueError("MISSING_LEGACY_ROWS")
    result, pending = [], []
    snapshot = legacy_snapshot(path)
    for position in positions:
        entry, references = batch.stage_row(
            rows[position],
            snapshot,
            current_ids.get(position),
            include_statute_images=include_statute_images,
        )
        result.append(entry)
        pending.extend(references)
    return {
        "rows": result,
        "download_manifest": batch._download_manifest(pending),
        "download_references": len(pending),
    }
