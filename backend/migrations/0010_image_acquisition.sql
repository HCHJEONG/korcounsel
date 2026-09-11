ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN (
 'VERIFY_ARTIFACT','REBUILD_PROJECTION','FETCH_LAW_DETAIL','FETCH_SCOURT_DETAIL',
 'FETCH_SCOURT_INVENTORY','IMPORT_LEGACY_BUNDLE','ACQUIRE_IMAGE_BATCH'
));

CREATE TABLE image_references (
 reference_id text PRIMARY KEY CHECK (btrim(reference_id) <> ''),
 manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
 source_system text NOT NULL CHECK (source_system IN ('scourt','law_go_kr','lawnb','legacy_import')),
 source_id text NOT NULL CHECK (btrim(source_id) <> ''),
 row_position bigint CHECK (row_position IS NULL OR row_position >= 0),
 occurrence_order integer NOT NULL CHECK (occurrence_order >= 0),
 original_src text,
 image_name text,
 resolved_url text,
 reference_status text NOT NULL CHECK(reference_status IN ('RESOLVED','NAME_ONLY','ID_MISMATCH','UNRESOLVED')),
 reason text NOT NULL CHECK (btrim(reason) <> ''),
 context jsonb NOT NULL CHECK(jsonb_typeof(context)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK (reference_status <> 'RESOLVED' OR resolved_url IS NOT NULL)
);

CREATE TABLE image_acquisitions (
 url text PRIMARY KEY CHECK (btrim(url) <> ''),
 status text NOT NULL CHECK(status IN ('PENDING','ACQUIRED','FAILED','SKIPPED')),
 blob_hash text REFERENCES blobs(sha256),
 size_bytes bigint CHECK(size_bytes IS NULL OR size_bytes >= 0),
 content_type text,
 image_metadata jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(image_metadata)='object'),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0),
 last_error_code text,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK ((status='ACQUIRED')=(blob_hash IS NOT NULL))
);

CREATE TABLE image_acquisition_attempts (
 attempt_id uuid PRIMARY KEY,
 job_id uuid NOT NULL REFERENCES jobs(job_id),
 url text NOT NULL REFERENCES image_acquisitions(url),
 outcome text NOT NULL CHECK(outcome IN ('ACQUIRED','FAILED','SKIPPED')),
 blob_hash text REFERENCES blobs(sha256),
 size_bytes bigint CHECK(size_bytes IS NULL OR size_bytes >= 0),
 error_code text,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK ((outcome='ACQUIRED')=(blob_hash IS NOT NULL))
);

CREATE INDEX image_references_manifest ON image_references(manifest_hash, occurrence_order);
CREATE INDEX image_references_url ON image_references(resolved_url) WHERE resolved_url IS NOT NULL;
CREATE INDEX image_acquisitions_status ON image_acquisitions(status, updated_at);
CREATE TRIGGER immutable_image_references BEFORE UPDATE OR DELETE ON image_references
 FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
CREATE TRIGGER immutable_image_attempts BEFORE UPDATE OR DELETE ON image_acquisition_attempts
 FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();