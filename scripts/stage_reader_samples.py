"""Publish bounded, already acquired current-source samples as immutable reader artifacts."""

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.storage.files import FileStore


def title_of(html: str) -> str:
    class Title(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_title = False
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag == "h2" and not self.parts:
                self.in_title = True

        def handle_endtag(self, tag):
            if tag == "h2":
                self.in_title = False

        def handle_data(self, data):
            if self.in_title:
                self.parts.append(data)

    parser = Title()
    parser.feed(html)
    return " ".join("".join(parser.parts).split())


def stage(directory: Path, records: Records) -> dict:
    mapping_raw = (directory / "mapping.json").read_bytes()
    mapping = json.loads(mapping_raw)
    sample_store = FileStore(directory.resolve())
    html_raw = sample_store.path(mapping["html_storage_key"]).read_bytes()
    if hashlib.sha256(html_raw).hexdigest() != mapping["html_sha256"]:
        raise ValueError("PARENT_HASH_MISMATCH")
    acquisitions = {}
    ledger_raw = (directory / "ledger.jsonl").read_bytes()
    for line in ledger_raw.decode().splitlines():
        item = json.loads(line)
        acquisitions[item["url"]] = item
    for item in acquisitions.values():
        if item["status"] == "ACQUIRED":
            raw = sample_store.path(item["storage_key"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("IMAGE_HASH_MISMATCH")
            records.put_artifact(
                "reader-image:" + item["sha256"],
                raw,
                origin="DERIVED",
                metadata={"kind": "PRESERVED_IMAGE_BYTES"},
            )
    provenance = {}
    for name, raw in [("mapping", mapping_raw), ("acquisition_ledger", ledger_raw)]:
        digest = hashlib.sha256(raw).hexdigest()
        artifact = "reader-evidence:" + digest
        records.put_artifact(artifact, raw, origin="MANIFEST", metadata={"kind": name})
        provenance[name + "_artifact_id"] = artifact
    for response in mapping["source_responses"]:
        digest = response["sha256"]
        raw = sample_store.path(f"blobs/{digest[:2]}/{digest}").read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("SOURCE_RESPONSE_HASH_MISMATCH")
        records.put_artifact(
            "reader-source:" + digest,
            raw,
            origin="HTTP_RESPONSE",
            metadata={"kind": "SOURCE_RESPONSE", **response},
        )
    provenance["source_responses"] = mapping["source_responses"]
    html = html_raw.decode()
    document_id = ReaderStore(records).preserve(
        html,
        title=title_of(html) or "법원 보존 본문 " + mapping["source_id"],
        source_id=mapping["source_id"],
        origin="CURRENT_SOURCE",
        provenance=provenance,
        acquisitions=acquisitions,
    )
    manifest = ReaderStore(records).read(document_id)
    return {
        "document_id": document_id,
        "title": manifest["title"],
        "occurrences": len(manifest["images"]),
        "acquired": sum(bool(r.get("blob_hash")) for r in manifest["images"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if len(args.directories) > 10:
        parser.error("At most 10 source samples per run")
    settings = load_settings()
    records = Records(Database.from_settings(settings), FileStore(settings.data_dir))
    result = [stage(path, records) for path in args.directories]
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
