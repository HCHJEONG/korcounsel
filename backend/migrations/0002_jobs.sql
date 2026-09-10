CREATE TABLE runtime_control (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    draining boolean NOT NULL DEFAULT false,
    drain_started_at timestamptz,
    CHECK (draining = (drain_started_at IS NOT NULL))
);
INSERT INTO runtime_control(singleton) VALUES(true);
CREATE TABLE jobs (
    job_id uuid PRIMARY KEY,
    request_key text NOT NULL UNIQUE CHECK (btrim(request_key) <> ''),
    kind text NOT NULL CHECK (kind IN ('VERIFY_ARTIFACT')),
    payload jsonb NOT NULL CHECK(jsonb_typeof(payload) = 'object'),
    status text NOT NULL DEFAULT 'QUEUED'
        CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    failures integer NOT NULL DEFAULT 0 CHECK(failures >= 0),
    max_attempts integer NOT NULL CHECK(max_attempts BETWEEN 1 AND 10),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_until timestamptz,
    lease_token uuid,
    worker_id text,
    checkpoint jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(checkpoint) = 'object'),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((status = 'RUNNING') =
        (lease_until IS NOT NULL AND lease_token IS NOT NULL AND worker_id IS NOT NULL))
);
CREATE UNIQUE INDEX single_running_job ON jobs((true)) WHERE status='RUNNING';
CREATE INDEX jobs_claim ON jobs(available_at,created_at) WHERE status='QUEUED';
CREATE TABLE job_attempts (
    job_id uuid NOT NULL REFERENCES jobs(job_id),
    attempt integer NOT NULL,
    lease_token uuid NOT NULL UNIQUE,
    worker_id text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    outcome text CHECK(outcome IN ('SUCCEEDED','FAILED','LEASE_EXPIRED','CHECKPOINTED')),
    error_code text,
    PRIMARY KEY(job_id,attempt),
    CHECK ((finished_at IS NULL) = (outcome IS NULL))
);
CREATE TABLE job_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES jobs(job_id),
    event text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}',
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON job_events
    FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
-- Item ledger is distinct from a job: repeated job runs refer to the same versioned item.
CREATE TABLE work_items (
    item_key text PRIMARY KEY,
    kind text NOT NULL CHECK(kind IN ('FETCH','ASSET','ENRICHMENT')),
    source text NOT NULL,
    source_id text NOT NULL,
    input_version text NOT NULL,
    rules_version text NOT NULL,
    target text NOT NULL,
    UNIQUE(kind,source,source_id,input_version,rules_version,target)
);
CREATE TABLE work_item_attempts (
    attempt_id uuid PRIMARY KEY,
    item_key text NOT NULL REFERENCES work_items(item_key),
    job_id uuid REFERENCES jobs(job_id),
    outcome text NOT NULL CHECK(outcome IN ('SUCCEEDED','FAILED','PARTIAL')),
    artifact_id text REFERENCES artifacts(artifact_id),
    error_code text,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK(outcome <> 'SUCCEEDED' OR artifact_id IS NOT NULL)
);
CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON work_item_attempts
    FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();

CREATE TABLE worker_instances (
    worker_id text PRIMARY KEY,
    heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    stopped_at timestamptz
);
CREATE FUNCTION guard_job_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (OLD.status IN ('SUCCEEDED','FAILED') AND NEW.status <> OLD.status)
       OR (OLD.status='QUEUED' AND NEW.status NOT IN ('QUEUED','RUNNING')) THEN
        RAISE EXCEPTION 'INVALID_JOB_TRANSITION';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER job_transition BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION guard_job_transition();
CREATE FUNCTION guard_finished_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.finished_at IS NOT NULL OR TG_OP='DELETE' THEN
        RAISE EXCEPTION 'IMMUTABLE_FINISHED_ATTEMPT';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER finished_attempt BEFORE UPDATE OR DELETE ON job_attempts
    FOR EACH ROW EXECUTE FUNCTION guard_finished_attempt();
