ALTER TABLE jobs ADD COLUMN handler_version text NOT NULL DEFAULT 'persistence-1';
CREATE TABLE projection_rebuild_inputs (
    job_id uuid NOT NULL REFERENCES jobs(job_id),
    artifact_id text NOT NULL REFERENCES artifacts(artifact_id),
    content_revision text NOT NULL CHECK(content_revision ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY(job_id,artifact_id)
);
CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON projection_rebuild_inputs
    FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
