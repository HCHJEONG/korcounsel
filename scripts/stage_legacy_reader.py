"""Publish a bounded legacy reader revision; queue downloads separately from publication.

The current reader is evidence, never a replacement for the legacy body. Re-running
with the same evidence reuses artifacts. New acquisitions create new reader revisions.
"""

import argparse
import json
from pathlib import Path

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.legacy_batch import stage
from klegal_gold.storage.files import FileStore

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", required=True)
    parser.add_argument("--current", action="append", default=[], help="POSITION:CURRENT_READER_ID")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    positions = [int(x) for x in args.positions.split(",")]
    if not 1 <= len(positions) <= 50 or len(set(positions)) != len(positions):
        parser.error("Choose 1..50 distinct positions per batch")
    current_ids = {int(x.split(":", 1)[0]): x.split(":", 1)[1] for x in args.current}
    settings = load_settings()
    if settings.legacy_parquet_path is None:
        parser.error("LEGACY_PARQUET_PATH is required")
    records = Records(Database.from_settings(settings), FileStore(settings.data_dir))
    result = stage(settings.legacy_parquet_path, positions, current_ids, records)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
