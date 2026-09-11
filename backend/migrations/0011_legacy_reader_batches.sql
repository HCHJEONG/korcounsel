ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN (
 'VERIFY_ARTIFACT','REBUILD_PROJECTION','FETCH_LAW_DETAIL','FETCH_SCOURT_DETAIL',
 'FETCH_SCOURT_INVENTORY','IMPORT_LEGACY_BUNDLE','ACQUIRE_IMAGE_BATCH','STAGE_LEGACY_READER_BATCH'
));

CREATE TABLE legacy_reader_batch_rows (
 job_id uuid NOT NULL REFERENCES jobs(job_id),
 row_position bigint NOT NULL CHECK(row_position >= 0),
 reader_artifact text REFERENCES artifacts(artifact_id),
 status text NOT NULL CHECK(status IN ('STAGED','FAILED')),
 result jsonb NOT NULL CHECK(jsonb_typeof(result)='object'),
 error_code text,
 PRIMARY KEY(job_id,row_position),
 CHECK ((status='STAGED')=(reader_artifact IS NOT NULL)),
 CHECK ((status='FAILED')=(error_code IS NOT NULL))
);
CREATE TRIGGER immutable_legacy_reader_batch_rows
 BEFORE UPDATE OR DELETE ON legacy_reader_batch_rows
 FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();

CREATE INDEX legacy_reader_document_lookup ON artifacts (
 (metadata->>'legacy_snapshot'), (metadata->>'legacy_position'),
 (metadata->>'legacy_body_hash'), created_at DESC, artifact_id DESC
) WHERE metadata->>'kind'='READER_DOCUMENT';

CREATE INDEX current_reader_document_lookup ON artifacts (
 (metadata->>'source_id'), created_at DESC, artifact_id DESC
) WHERE metadata->>'kind'='READER_DOCUMENT' AND metadata->>'origin'='CURRENT_SOURCE';

ALTER TABLE manifests DROP CONSTRAINT manifests_kind_check;
ALTER TABLE manifests ADD CONSTRAINT manifests_kind_check CHECK(kind IN (
 'REGISTRY','DATASET','ASSET','IMPORT','DOCUMENT_OBSERVATION','INVENTORY_PAGES','LEGACY_READER_BATCH'
));
