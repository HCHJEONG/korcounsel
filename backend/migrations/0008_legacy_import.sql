ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN (
 'VERIFY_ARTIFACT','REBUILD_PROJECTION','FETCH_LAW_DETAIL','FETCH_SCOURT_DETAIL',
 'FETCH_SCOURT_INVENTORY','IMPORT_LEGACY_BUNDLE'
));
CREATE TABLE legacy_bundle_rows (
 job_id uuid NOT NULL REFERENCES jobs(job_id),
 row_position bigint NOT NULL CHECK(row_position >= 0),
 input_artifact text NOT NULL REFERENCES artifacts(artifact_id),
 record_artifact text REFERENCES artifacts(artifact_id),
 status text NOT NULL CHECK(status IN ('PRESERVED','QUARANTINED')),
 reasons jsonb NOT NULL CHECK(jsonb_typeof(reasons)='array'),
 PRIMARY KEY(job_id,row_position),
 CHECK ((status='PRESERVED')=(record_artifact IS NOT NULL))
);
CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON legacy_bundle_rows
 FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
