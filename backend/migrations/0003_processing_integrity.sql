ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check
    CHECK(kind IN ('VERIFY_ARTIFACT','REBUILD_PROJECTION'));
ALTER TABLE artifacts ADD CONSTRAINT artifact_blob_identity UNIQUE(artifact_id,blob_hash);
ALTER TABLE source_versions ADD CONSTRAINT source_version_blob_matches
    FOREIGN KEY(artifact_id,raw_content_hash) REFERENCES artifacts(artifact_id,blob_hash);
CREATE FUNCTION check_source_response() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS(SELECT 1 FROM artifacts
                  WHERE artifact_id=NEW.artifact_id AND origin='HTTP_RESPONSE') THEN
        RAISE EXCEPTION 'SOURCE_VERSION_REQUIRES_HTTP_RESPONSE';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER source_response BEFORE INSERT ON source_versions
    FOR EACH ROW EXECUTE FUNCTION check_source_response();
