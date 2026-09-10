CREATE TABLE app_users (
    user_id uuid PRIMARY KEY,
    username text NOT NULL UNIQUE CHECK (btrim(username) <> ''),
    password_hash text NOT NULL CHECK (password_hash LIKE 'scrypt$%'),
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE app_sessions (
    token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    user_id uuid NOT NULL REFERENCES app_users(user_id),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE blobs (
    sha256 text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    storage_key text NOT NULL UNIQUE,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE artifacts (
    artifact_id text PRIMARY KEY CHECK (btrim(artifact_id) <> ''),
    blob_hash text NOT NULL REFERENCES blobs(sha256),
    origin text NOT NULL CHECK (origin IN ('HTTP_RESPONSE','LEGACY_ARCHIVE','DERIVED','MANIFEST')),
    parent_id text REFERENCES artifacts(artifact_id),
    metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE identity_events (
    sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    event_id uuid PRIMARY KEY,
    payload jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE documents (
    canonical_id text PRIMARY KEY,
    current_revision integer NOT NULL CHECK (current_revision > 0),
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE document_revisions (
    canonical_id text NOT NULL REFERENCES documents(canonical_id),
    revision integer NOT NULL CHECK (revision > 0),
    event_id uuid NOT NULL REFERENCES identity_events(event_id),
    payload jsonb NOT NULL,
    PRIMARY KEY (canonical_id, revision)
);
ALTER TABLE documents ADD CONSTRAINT current_document_revision
    FOREIGN KEY (canonical_id,current_revision)
    REFERENCES document_revisions(canonical_id,revision) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE case_keys (
    key_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    court text NOT NULL CHECK (btrim(court) <> ''),
    case_number text NOT NULL CHECK (btrim(case_number) <> ''),
    UNIQUE (court,case_number)
);
CREATE TABLE document_case_keys (
    canonical_id text NOT NULL,
    revision integer NOT NULL,
    key_id bigint NOT NULL REFERENCES case_keys(key_id),
    PRIMARY KEY (canonical_id,revision,key_id),
    FOREIGN KEY (canonical_id,revision) REFERENCES document_revisions(canonical_id,revision)
);
CREATE TABLE active_source_links (
    source text NOT NULL CHECK (source IN ('scourt','law_go_kr','lawnb','legacy_import')),
    source_id text NOT NULL CHECK (btrim(source_id) <> ''),
    canonical_id text NOT NULL,
    revision integer NOT NULL,
    PRIMARY KEY (source,source_id),
    FOREIGN KEY (canonical_id,revision) REFERENCES document_revisions(canonical_id,revision)
);
CREATE TABLE legacy_records (
    preservation_id text NOT NULL,
    content_revision text NOT NULL CHECK (content_revision ~ '^[0-9a-f]{64}$'),
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    row_position bigint NOT NULL CHECK (row_position >= 0),
    original_index text NOT NULL,
    coverage text NOT NULL CHECK (coverage IN ('FULL_ROW','METADATA_PROJECTION')),
    artifact_id text NOT NULL REFERENCES artifacts(artifact_id),
    PRIMARY KEY (preservation_id,content_revision),
    UNIQUE(snapshot_hash,row_position,content_revision)
);
CREATE TABLE legacy_import_attempts (
    attempt_id uuid PRIMARY KEY,
    run_id text NOT NULL,
    preservation_id text NOT NULL,
    content_revision text NOT NULL,
    status text NOT NULL CHECK (status IN ('PRESERVED','QUARANTINED')),
    reasons jsonb NOT NULL CHECK (jsonb_typeof(reasons) = 'array'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY(preservation_id,content_revision)
        REFERENCES legacy_records(preservation_id,content_revision)
);
CREATE TABLE case_projection (
    preservation_id text NOT NULL,
    content_revision text NOT NULL,
    court text,
    case_numbers jsonb NOT NULL,
    decision_date date,
    body_state text NOT NULL,
    PRIMARY KEY (preservation_id,content_revision),
    FOREIGN KEY(preservation_id,content_revision)
        REFERENCES legacy_records(preservation_id,content_revision)
);
CREATE INDEX case_projection_court ON case_projection(court);
CREATE TABLE inventories (
    snapshot_id text PRIMARY KEY,
    source text NOT NULL,
    scope_hash text NOT NULL,
    completeness text NOT NULL CHECK (completeness IN ('COMPLETE','PARTIAL','UNKNOWN')),
    artifact_id text NOT NULL REFERENCES artifacts(artifact_id)
);
CREATE TABLE manifests (
    manifest_id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('REGISTRY','DATASET','ASSET','IMPORT')),
    artifact_id text NOT NULL REFERENCES artifacts(artifact_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- Append-only evidence/history is enforced even against accidental repository UPDATEs.
CREATE FUNCTION reject_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'IMMUTABLE_HISTORY';
END;
$$;
DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'blobs','artifacts','identity_events','document_revisions','document_case_keys',
        'legacy_records','legacy_import_attempts','inventories','manifests'
    ] LOOP
        EXECUTE format('CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION reject_history_mutation()', table_name);
    END LOOP;
END;
$$;

CREATE TABLE source_versions (
    source text NOT NULL CHECK(source IN ('scourt','law_go_kr','lawnb')),
    source_id text NOT NULL,
    raw_content_hash text NOT NULL REFERENCES blobs(sha256),
    artifact_id text NOT NULL REFERENCES artifacts(artifact_id),
    PRIMARY KEY(source,source_id,raw_content_hash)
);
CREATE TABLE source_receipts (
    receipt_id uuid PRIMARY KEY,
    artifact_id text NOT NULL REFERENCES artifacts(artifact_id),
    receipt_artifact_id text NOT NULL REFERENCES artifacts(artifact_id)
);
CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON source_versions
    FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON source_receipts
    FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
