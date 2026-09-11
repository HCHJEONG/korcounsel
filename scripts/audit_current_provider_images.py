"""Audit completed current-source image receipts without writes to DB or network access."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from klegal_gold.assets.images import valid_image_url, validate_image  # noqa: E402
from klegal_gold.config import load_settings  # noqa: E402
from klegal_gold.db.records import Records  # noqa: E402
from klegal_gold.db.session import Database  # noqa: E402
from klegal_gold.documents.reader import (  # noqa: E402
    STATUTE_IMAGE_VERSION,
    image_occurrences,
)
from klegal_gold.documents.reader import (
    VERSION as READER_VERSION,
)
from klegal_gold.documents.reader_store import ReaderStore  # noqa: E402
from klegal_gold.storage.files import Blob, FileStore  # noqa: E402

VERSION = "current-provider-image-audit-1"
SCOPE = "CURRENT_SOURCE_ONLY"
NOTICE = "CURRENT_SOURCE_ONLY, legacy link not approved"
STATES = ("NEVER_ATTEMPTED", "ACQUIRED", "FAILED", "OTHER")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class SnapshotDatabase(Database):
    """Borrow the already read-only transaction; Records must not open another snapshot."""

    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


def select_receipts(conn, records, directory, start_wave, end_wave):
    if not 1 <= start_wave <= end_wave <= 19:
        raise ValueError("INVALID_WAVE_RANGE")
    receipts = []
    contract = None
    seen_positions = set()
    for number in range(start_wave, end_wave + 1):
        paths = {}
        for path in (directory / f"wave-{number:03d}").glob("wave-*.json"):
            match = re.fullmatch(r"wave-([0-9a-f]{64})\.json", path.name)
            if match is None:
                raise ValueError("INVALID_RECEIPT_FILENAME")
            paths["legacy-image-wave:" + match[1]] = path
        if not paths:
            raise ValueError("WAVE_RECEIPT_MISSING")
        registered = conn.execute(
            "SELECT artifact_id,blob_hash,metadata,created_at FROM artifacts "
            "WHERE artifact_id=ANY(%s) ORDER BY created_at DESC,artifact_id DESC",
            (list(paths),),
        ).fetchall()
        if len(registered) != len(paths):
            raise ValueError("WAVE_RECEIPT_NOT_REGISTERED")
        latest = registered[0]
        artifact = latest["artifact_id"]
        raw = records.read(artifact)
        digest = sha256(raw).hexdigest()
        if (
            artifact != "legacy-image-wave:" + digest
            or latest["blob_hash"] != digest
            or latest["metadata"].get("kind") != "LEGACY_IMAGE_WAVE_RECEIPT"
        ):
            raise ValueError("WAVE_RECEIPT_HASH_MISMATCH")
        receipt = json.loads(raw)
        local = json.loads(paths[artifact].read_bytes())
        if local != {"artifact_id": artifact, **receipt}:
            raise ValueError("LOCAL_WAVE_RECEIPT_MISMATCH")
        if receipt.get("version") != "legacy-image-waves-1" or receipt.get("wave") != number:
            raise ValueError("WAVE_RECEIPT_SCOPE_MISMATCH")
        if receipt.get("status") != "COMPLETED":
            raise ValueError("WAVE_NOT_COMPLETED")
        selected_contract = {k: receipt[k] for k in ("inventory_sha256", "targets_sha256")}
        if any(not re.fullmatch("[0-9a-f]{64}", v) for v in selected_contract.values()):
            raise ValueError("INVALID_WAVE_INPUT_HASH")
        if contract is not None and contract != selected_contract:
            raise ValueError("WAVE_INPUT_CONTRACT_MISMATCH")
        contract = selected_contract
        positions = receipt["positions"]
        if (
            any(type(p) is not int or p < 0 for p in positions)
            or len(set(positions)) != len(positions)
            or seen_positions.intersection(positions)
        ):
            raise ValueError("DUPLICATE_OR_INVALID_WAVE_POSITION")
        seen_positions.update(positions)
        receipt = {**receipt, "artifact_id": artifact, "created_at": str(latest["created_at"])}
        receipts.append(receipt)
    return receipts


def reader_bindings(receipts):
    bindings = defaultdict(list)
    for wave in receipts:
        rows = {row["position"]: row for row in wave["row_results"]}
        if len(rows) != len(wave["row_results"]) or set(rows) != set(wave["positions"]):
            raise ValueError("WAVE_ROW_RESULTS_MISMATCH")
        sources = {}
        source_ids = set()
        expected_mapping = {}
        for source in wave["source_results"]:
            if source["source_id"] in source_ids:
                raise ValueError("DUPLICATE_WAVE_SOURCE")
            source_ids.add(source["source_id"])
            for position in source["positions"]:
                if position in sources or position not in rows:
                    raise ValueError("WAVE_SOURCE_POSITION_MISMATCH")
                sources[position] = source["source_id"]
                if source.get("current_reader"):
                    expected_mapping[str(position)] = source["current_reader"]
        if (
            set(sources) != set(rows)
            or source_ids != set(wave["sources"])
            or len(source_ids) != len(wave["sources"])
            or expected_mapping != wave["current_readers"]
        ):
            raise ValueError("WAVE_CURRENT_READER_MAPPING_MISMATCH")
        for position, reader_id in wave["current_readers"].items():
            if not re.fullmatch("[0-9a-f]{64}", reader_id):
                raise ValueError("INVALID_CURRENT_READER_ID")
            bindings[reader_id].append(
                {
                    "wave": wave["wave"],
                    "receipt_artifact_id": wave["artifact_id"],
                    "legacy_row_position": int(position),
                    "source_id": sources[int(position)],
                    "legacy_stage_result": rows[int(position)],
                    "legacy_link_approved_by_audit": False,
                }
            )
    return bindings


def mapping_validation(ref, source_id):
    url = ref.get("resolved_url")
    if not url:
        return False, "NO_RESOLVED_URL"
    if not valid_image_url(url):
        return False, "URL_NOT_ALLOWED"
    values = ref.get("provider_mapping_values", [])
    if not values:
        return False, "NO_PROVIDER_MAPPING"
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.netloc != "portal.scourt.go.kr"
        or parsed.params
        or parsed.fragment
        or set(query) != {"pgmId", "jisCntntsSrno", "atchImgFileNm"}
        or query.get("pgmId") != ["PGP1011M04"]
        or query.get("jisCntntsSrno") != [source_id]
        or len(set(values)) != 1
        or query.get("atchImgFileNm") != [values[0]]
    ):
        return False, "PROVIDER_URL_SOURCE_FILENAME_MISMATCH"
    return True, None


def inspect_reader(records, reader_id, bindings):
    manifest = ReaderStore(records).read(reader_id)
    if (
        manifest.get("version") not in {"image-reader-1", READER_VERSION, STATUTE_IMAGE_VERSION}
        or manifest.get("origin") != "CURRENT_SOURCE"
        or not manifest.get("source_id")
        or any(b["source_id"] != manifest["source_id"] for b in bindings)
    ):
        raise ValueError("CURRENT_READER_SOURCE_MISMATCH")
    body_hash = manifest["html_sha256"]
    if manifest["html_artifact_id"] != "reader-html:" + body_hash:
        raise ValueError("CURRENT_HTML_ARTIFACT_MISMATCH")
    raw = records.read(manifest["html_artifact_id"])
    if sha256(raw).hexdigest() != body_hash:
        raise ValueError("CURRENT_HTML_HASH_MISMATCH")
    observed = image_occurrences(
        raw.decode("utf-8"),
        source_id=manifest["source_id"],
        base_url="https://portal.scourt.go.kr/",
    )
    # JSON normalizes the existing parser's line/column tuple to the stored array contract.
    observed = json.loads(encoded(observed))
    refs = manifest["images"]
    if len(refs) != len(observed):
        raise ValueError("CURRENT_IMAGE_COUNT_MISMATCH")
    result = []
    for order, (ref, original) in enumerate(zip(refs, observed, strict=True)):
        if (
            type(ref.get("order")) is not int
            or ref["order"] != order
            or any(key not in ref or ref[key] != value for key, value in original.items())
        ):
            raise ValueError("CURRENT_IMAGE_POSITION_OR_MAPPING_MISMATCH")
        eligible, reason = mapping_validation(ref, manifest["source_id"])
        result.append(
            {
                "scope": SCOPE,
                "notice": NOTICE,
                "legacy_link_approved": False,
                "current_reader_id": reader_id,
                "current_html_artifact_id": manifest["html_artifact_id"],
                "current_html_sha256": body_hash,
                "source_system": "scourt",
                "source_id": manifest["source_id"],
                "order": order,
                "original_src": ref["original_src"],
                "name": ref["name"],
                "resolved_url": ref["resolved_url"],
                "provider_mapping_values": ref["provider_mapping_values"],
                "valid_image_url": bool(
                    ref["resolved_url"] and valid_image_url(ref["resolved_url"])
                ),
                "provider_mapping_exact": eligible,
                "eligibility_reason": reason,
                "image_reference": ref,
                "legacy_bindings": bindings,
            }
        )
    parent = {
        "current_reader_id": reader_id,
        "reader_version": manifest["version"],
        "title": manifest["title"],
        "source_id": manifest["source_id"],
        "html_artifact_id": manifest["html_artifact_id"],
        "html_sha256": body_hash,
        "origin": manifest["origin"],
        "provenance": manifest["provenance"],
        "image_occurrences": len(refs),
        "legacy_bindings": bindings,
    }
    return parent, result


def classify(ref, acquisition, attempt_records):
    if acquisition is None and attempt_records == 0 and ref["resolved_url"]:
        state = "NEVER_ATTEMPTED"
    elif acquisition and acquisition["status"] in {"ACQUIRED", "FAILED"}:
        state = acquisition["status"]
    else:
        state = "OTHER"
    return {
        **ref,
        "acquisition_state": state,
        "acquisition": acquisition,
        "attempt_records": attempt_records,
        "eligible_never_attempted": state == "NEVER_ATTEMPTED" and ref["provider_mapping_exact"],
    }


def verify_acquired_blobs(conn, store, acquisitions):
    by_hash = {}
    for row in acquisitions.values():
        if row["status"] != "ACQUIRED":
            continue
        digest = row.get("blob_hash")
        size = row.get("size_bytes")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("ACQUIRED_BLOB_HASH_MISSING")
        if type(size) is not int or size <= 0:
            raise ValueError("ACQUIRED_BLOB_SIZE_INVALID")
        if digest in by_hash and by_hash[digest] != size:
            raise ValueError("ACQUIRED_BLOB_SIZE_CONFLICT")
        by_hash[digest] = size
    rows = conn.execute(
        "SELECT sha256,storage_key,size_bytes FROM blobs WHERE sha256=ANY(%s)",
        (list(by_hash),),
    ).fetchall()
    if {r["sha256"] for r in rows} != set(by_hash):
        raise ValueError("ACQUIRED_BLOB_NOT_REGISTERED")
    verified = []
    for row in rows:
        if row["size_bytes"] != by_hash[row["sha256"]]:
            raise ValueError("ACQUIRED_BLOB_SIZE_MISMATCH")
        blob = Blob(row["sha256"], row["storage_key"], row["size_bytes"])
        store.verify(blob)
        raw = store.path(blob.storage_key).read_bytes()
        if len(raw) != blob.size_bytes or sha256(raw).hexdigest() != blob.sha256:
            raise ValueError("BLOB_INTEGRITY_FAILED")
        verified.append(
            {"sha256": blob.sha256, "size_bytes": blob.size_bytes, **validate_image(raw)}
        )
    return sorted(verified, key=lambda r: r["sha256"])


def count_refs(refs):
    return {
        "occurrences": len(refs),
        "unique_urls": len({r["resolved_url"] for r in refs if r["resolved_url"]}),
        "current_readers": len({r["current_reader_id"] for r in refs}),
    }


def collect_audit(db, data_dir, waves_dir, start_wave, end_wave, *, verify_blobs=False):
    store = FileStore(data_dir.resolve(strict=True))
    with db.connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        snapshot = conn.execute("SELECT transaction_timestamp() AS observed_at").fetchone()
        records = Records(SnapshotDatabase(conn), store)
        receipts = select_receipts(conn, records, waves_dir, start_wave, end_wave)
        bindings = reader_bindings(receipts)
        parents, references = [], []
        for reader_id in sorted(bindings):
            parent, refs = inspect_reader(records, reader_id, bindings[reader_id])
            parents.append(parent)
            references.extend(refs)
        if len({(r["current_reader_id"], r["order"]) for r in references}) != len(references):
            raise ValueError("DUPLICATE_CURRENT_IMAGE_POSITION")
        urls = sorted({r["resolved_url"] for r in references if r["resolved_url"]})
        acquisitions = {
            r["url"]: {**r, "updated_at": str(r["updated_at"])}
            for r in conn.execute(
                "SELECT url,status,blob_hash,size_bytes,content_type,last_error_code,attempts,"
                "updated_at FROM image_acquisitions WHERE url=ANY(%s)",
                (urls,),
            ).fetchall()
        }
        attempts = {
            r["url"]: r["records"]
            for r in conn.execute(
                "SELECT url,count(*) AS records FROM image_acquisition_attempts "
                "WHERE url=ANY(%s) GROUP BY url",
                (urls,),
            ).fetchall()
        }
        references = [
            classify(r, acquisitions.get(r["resolved_url"]), attempts.get(r["resolved_url"], 0))
            for r in references
        ]
        blobs = verify_acquired_blobs(conn, store, acquisitions) if verify_blobs else []
        return {
            "version": VERSION,
            "scope": SCOPE,
            "notice": NOTICE,
            "legacy_link_approved": False,
            "snapshot_at": snapshot["observed_at"].isoformat(),
            "database_transaction": "REPEATABLE READ, READ ONLY",
            "waves": list(range(start_wave, end_wave + 1)),
            "receipts": [
                {
                    k: r[k]
                    for k in (
                        "wave",
                        "artifact_id",
                        "created_at",
                        "status",
                        "inventory_sha256",
                        "targets_sha256",
                    )
                }
                for r in receipts
            ],
            "summary": {
                "current_readers": len(parents),
                "wave_position_bindings": sum(len(b) for b in bindings.values()),
                "all_references": count_refs(references),
                "by_acquisition_state": {
                    state: count_refs([r for r in references if r["acquisition_state"] == state])
                    for state in STATES
                },
                "eligible_never_attempted": count_refs(
                    [r for r in references if r["eligible_never_attempted"]]
                ),
                "unresolved_or_invalid_mapping": dict(
                    Counter(r["eligibility_reason"] for r in references if r["eligibility_reason"])
                ),
                "unique_acquired_blobs": len(
                    {r["blob_hash"] for r in acquisitions.values() if r["status"] == "ACQUIRED"}
                ),
                "verified_blobs": len(blobs),
            },
            "verification": {
                "receipt_reader_and_html_hashes": True,
                "all_image_occurrences_reparsed_and_matched": True,
                "unique_parent_and_order": True,
                "acquired_blob_hash_size_decode": verify_blobs,
            },
            "limits": [
                "Statuses belong to the recorded database snapshot and can change afterwards.",
                "Current source preservation does not approve any legacy image attachment "
                "or title/context identity.",
                "Never-attempted requires no acquisition row and no acquisition-attempt row "
                "at this snapshot.",
                "A valid mapped URL does not guarantee a successful future image response.",
                "No source requests, downloads, DB mutations, job submissions "
                "or reader revisions are performed.",
            ],
            "parents": parents,
            "references": references,
            "verified_blobs": blobs,
        }


def manifest_reference(ref):
    original = ref["image_reference"]
    return {
        **ref,
        "original_reference_id": original["reference_id"],
        "row_position": None,
        "occurrence_order": ref["order"],
        "image_name": ref["name"],
        "parent_html_sha256": ref["current_html_sha256"],
        "reference_status": "RESOLVED",
        "reason": NOTICE,
    }


def write_audit(audit, output_dir, *, write_manifests=False):
    from run_legacy_image_waves import split_download_references

    if output_dir.exists():
        raise FileExistsError("AUDIT_OUTPUT_EXISTS")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_dir.with_name(output_dir.name + ".partial-" + uuid.uuid4().hex)
    temporary.mkdir()
    artifacts = {}

    def write(name, raw):
        with (temporary / name).open("xb") as stream:
            stream.write(raw)
        artifacts[name] = {"sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}

    for key in ("references", "parents", "verified_blobs"):
        write(key.replace("_", "-") + ".jsonl", b"".join(encoded(r) + b"\n" for r in audit[key]))
    manifests = []
    if write_manifests:
        refs = [manifest_reference(r) for r in audit["references"] if r["eligible_never_attempted"]]
        for index, chunk in enumerate(split_download_references(refs), start=1):
            value = {
                "kind": "IMAGE_REFERENCE_MANIFEST",
                "version": VERSION,
                "scope": SCOPE,
                "notice": NOTICE,
                "legacy_link_approved": False,
                "snapshot_at": audit["snapshot_at"],
                "receipts": audit["receipts"],
                "selection": "ELIGIBLE_NEVER_ATTEMPTED_ONLY",
                "references": chunk,
            }
            raw = encoded(value)
            name = f"never-attempted-{index:03d}.json"
            write(name, raw)
            manifests.append(
                {
                    "file": name,
                    "artifact_id_candidate": "image-manifest:current-source-only-"
                    + sha256(raw).hexdigest(),
                    **count_refs(chunk),
                }
            )
    summary = {
        k: v for k, v in audit.items() if k not in {"parents", "references", "verified_blobs"}
    }
    summary.update(artifacts=artifacts, candidate_manifests=manifests)
    with (temporary / "summary.json").open("xb") as stream:
        stream.write(encoded(summary) + b"\n")
    # An incomplete run stays explicitly .partial; the completed destination is never overwritten.
    os.rename(temporary, output_dir)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waves-dir", type=Path, required=True)
    parser.add_argument("--start-wave", type=int, default=1)
    parser.add_argument("--end-wave", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--data-dir", type=Path, help="Explicit existing blob store; defaults to settings"
    )
    parser.add_argument("--verify-blobs", action="store_true")
    parser.add_argument("--write-manifests", action="store_true")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("AUDIT_OUTPUT_EXISTS")
    settings = load_settings()
    audit = collect_audit(
        Database.from_settings(settings),
        args.data_dir or settings.data_dir,
        args.waves_dir,
        args.start_wave,
        args.end_wave,
        verify_blobs=args.verify_blobs,
    )
    summary = write_audit(audit, args.output_dir, write_manifests=args.write_manifests)
    print(
        json.dumps({"output_dir": str(args.output_dir), **summary["summary"]}, ensure_ascii=False)
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Avoid driver/configuration diagnostics that could include connection information.
        code = str(exc) if isinstance(exc, (ValueError, FileExistsError)) else "AUDIT_FAILED"
        if re.fullmatch("[A-Z_]+", code) is None:
            code = "AUDIT_FAILED"
        print(json.dumps({"error": code, "exception_type": type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
