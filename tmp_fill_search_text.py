from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.domain.legacy import LegacyCaseRecord
from klegal_gold.ingestion.legacy import legacy_content_revision
from klegal_gold.storage.files import FileStore

settings = load_settings()
db = Database.from_settings(settings)
records = Records(db, FileStore(settings.data_dir))
updated = 0
missing = 0
last = ""
while True:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT artifact_id, content_revision
            FROM legacy_records
            WHERE artifact_id > %s
            ORDER BY artifact_id
            LIMIT 500
            """,
            (last,),
        ).fetchall()
    if not rows:
        break
    for row in rows:
        last = row["artifact_id"]
        try:
            record = LegacyCaseRecord.model_validate_json(records.read(row["artifact_id"]))
        except (OSError, ValueError):
            missing += 1
            continue
        if legacy_content_revision(record) != row["content_revision"]:
            raise ValueError("LEGACY_REVISION_MISMATCH")
        with db.connect() as conn:
            records._project(conn, record, row["content_revision"])
        updated += 1
        if updated % 5000 == 0:
            print({"updated": updated, "missing": missing}, flush=True)
print({"updated": updated, "missing": missing}, flush=True)