"""The current-only runner never treats a legacy link failure as permission to retry images."""

import importlib.util
import json
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def module(monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "current_image_run", scripts / "run_current_provider_images.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def make_audit(module, tmp_path, count=3):
    import audit_current_provider_images as audit

    from klegal_gold.documents.reader import image_occurrences

    html = "".join(
        f'<input class="contImagePath" name="img{i}" value="a{i}.gif"><img name="img{i}">'
        for i in range(count)
    )
    original = json.loads(
        audit.encoded(
            image_occurrences(html, source_id="123", base_url="https://portal.scourt.go.kr/")
        )
    )
    refs = [
        {
            "current_reader_id": "a" * 64,
            "order": i,
            "current_html_sha256": sha256(html.encode()).hexdigest(),
            "current_html_artifact_id": "reader-html:" + sha256(html.encode()).hexdigest(),
            "scope": audit.SCOPE,
            "notice": audit.NOTICE,
            "legacy_link_approved": False,
            "source_system": "scourt",
            "source_id": "123",
            "original_src": ref["original_src"],
            "name": ref["name"],
            "resolved_url": ref["resolved_url"],
            "provider_mapping_values": ref["provider_mapping_values"],
            "image_reference": ref,
            "legacy_bindings": [],
            "acquisition_state": "NEVER_ATTEMPTED",
            "acquisition": None,
            "attempt_records": 0,
            "provider_mapping_exact": True,
            "eligible_never_attempted": True,
        }
        for i, ref in enumerate(original)
    ]
    value = {
        "version": audit.VERSION,
        "scope": audit.SCOPE,
        "notice": audit.NOTICE,
        "legacy_link_approved": False,
        "snapshot_at": "fixture",
        "receipts": [],
        "references": refs,
        "parents": [],
        "verified_blobs": [],
        "verification": {
            "receipt_reader_and_html_hashes": True,
            "all_image_occurrences_reparsed_and_matched": True,
            "unique_parent_and_order": True,
        },
        "summary": {"eligible_never_attempted": audit.count_refs(refs)},
    }
    directory = tmp_path / "audit"
    audit.write_audit(value, directory, write_manifests=True)
    digest = sha256((directory / "summary.json").read_bytes()).hexdigest()
    return directory, digest, module.load_audit(directory, digest)


class MemoryRecords:
    def __init__(self):
        self.values, self.metadata, self.jobs = {}, {}, {}
        self.ledger, self.attempts = {}, {}
        self.draining = self.foreign = False
        self.fetched = []
        self.worker_calls = 0
        self.behavior = "success"
        self.fail_urls = set()
        self.submit_loss = False
        self.submit_count = 0
        self.db = self

    @contextmanager
    def connect(self):
        yield self

    def execute(self, query, params=None):
        rows = []
        if "FROM image_acquisitions" in query:
            rows = [{"url": url, **self.ledger[url]} for url in params[0] if url in self.ledger]
        elif "FROM image_acquisition_attempts" in query:
            rows = [
                {"url": url, "records": self.attempts[url]}
                for url in params[0]
                if url in self.attempts
            ]
        elif "SELECT job_id FROM jobs WHERE request_key" in query:
            job = self.jobs.get(params[0])
            rows = [{"job_id": job.job_id}] if job else []
        elif "SELECT status,lease_until" in query:
            job = next(j for j in self.jobs.values() if j.job_id == params[0])
            rows = [{"status": job.status, "live": job.live}]
        elif "FROM jobs WHERE status IN" in query:
            active = [j for j in self.jobs.values() if j.status in {"QUEUED", "RUNNING"}]
            if "NOT (request_key" in query:
                blocked = self.foreign or any(j.key not in params[0] for j in active)
            else:
                blocked = self.foreign or any(j.job_id != params[0] for j in active)
            rows = [{"found": 1}] if blocked else []
        elif not query.startswith("SET TRANSACTION"):
            raise AssertionError(query)
        return SimpleNamespace(fetchall=lambda: rows, fetchone=lambda: rows[0] if rows else None)

    def put_artifact(self, artifact, raw, **kwargs):
        if artifact in self.values:
            assert self.values[artifact] == raw
            assert self.metadata[artifact] == kwargs
        self.values[artifact] = raw
        self.metadata[artifact] = kwargs

    def read(self, artifact):
        return self.values[artifact]


@pytest.fixture
def harness(module, monkeypatch):
    records = MemoryRecords()

    class Queue:
        def __init__(self, db, **kwargs):
            self.db = db

        def drain_status(self):
            return {"draining": records.draining}

        def get(self, job_id):
            return next(j for j in records.jobs.values() if j.job_id == job_id)

        def submit_image_batch(self, key, artifact, **kwargs):
            assert kwargs["max_urls"] == 500
            records.submit_count += 1
            if key not in records.jobs:
                records.jobs[key] = SimpleNamespace(
                    key=key,
                    job_id=key,
                    status="QUEUED",
                    live=False,
                    checkpoint={},
                    attempts=0,
                    payload={"manifest_artifact_id": artifact},
                )
            job = records.jobs[key]
            assert job.payload["manifest_artifact_id"] == artifact
            if records.submit_loss:
                records.submit_loss = False
                raise OSError("lost response after job creation")
            return job

        def worker_heartbeat(self, *args, **kwargs):
            pass

    class Worker:
        def __init__(self, queue, saved):
            self.worker_id = "fixture"

        def run_once(self):
            records.worker_calls += 1
            job = next(j for j in records.jobs.values() if j.status in {"QUEUED", "RUNNING"})
            job.attempts += 1
            refs = json.loads(records.read(job.payload["manifest_artifact_id"]))["references"]
            acquired = 0
            for url in dict.fromkeys(r["resolved_url"] for r in refs):
                if records.ledger.get(url, {}).get("status") == "ACQUIRED":
                    continue
                records.fetched.append(url)
                state = "FAILED" if url in records.fail_urls else "ACQUIRED"
                records.ledger[url] = {
                    "status": state,
                    "blob_hash": "b" * 64 if state == "ACQUIRED" else None,
                }
                records.attempts[url] = records.attempts.get(url, 0) + 1
                acquired += int(state == "ACQUIRED")
                if records.behavior == "pause_after_one":
                    records.draining = True
                    job.status = "QUEUED"
                    job.checkpoint = {"image_acquired": acquired}
                    return True
                if records.behavior == "error_after_one":
                    job.status = "QUEUED"
                    job.checkpoint = {"image_acquired": acquired}
                    return True
            job.checkpoint = {"image_acquired": acquired}
            job.status = "FAILED" if records.behavior == "terminal_failure" else "SUCCEEDED"
            return True

    monkeypatch.setattr(module, "Queue", Queue)
    monkeypatch.setattr(module, "Worker", Worker)
    monkeypatch.setattr(module, "verify_sources", lambda *args: None)
    return records


def test_changed_summary_or_artifact_rejected_before_execution(module, tmp_path):
    directory, digest, _ = make_audit(module, tmp_path)
    with pytest.raises(ValueError, match="SUMMARY_HASH_MISMATCH"):
        module.load_audit(directory, "0" * 64)
    candidate = directory / "never-attempted-001.json"
    candidate.write_bytes(candidate.read_bytes() + b" ")
    with pytest.raises(ValueError, match="AUDIT_FILE_HASH_MISMATCH"):
        module.load_audit(directory, digest)


def test_attempted_urls_filtered_but_original_candidate_and_parent_preserved(
    module, harness, tmp_path
):
    _, _, audit = make_audit(module, tmp_path)
    refs = audit["candidates"][0]["payload"]["references"]
    harness.ledger[refs[0]["resolved_url"]] = {"status": "FAILED"}
    harness.attempts[refs[1]["resolved_url"]] = 1
    report = module.run(audit, harness, tmp_path / "run")
    assert report["status"] == "COMPLETED"
    assert harness.fetched == [refs[2]["resolved_url"]]
    item = report["results"][0]
    assert item["excluded_urls"] == 2
    original = audit["candidates"][0]
    assert harness.read(original["artifact_id"]) == original["raw"]
    execution = json.loads(harness.read(item["manifest_artifact_id"]))
    assert execution["original_manifest_sha256"] == original["sha256"]
    assert execution["references"] == [refs[2]]
    assert execution["legacy_link_approved"] is False
    assert harness.metadata[item["manifest_artifact_id"]]["parent_id"] == original["artifact_id"]


def test_normal_image_failures_recorded_without_retry_and_completed_job_reused(
    module, harness, tmp_path
):
    _, _, audit = make_audit(module, tmp_path)
    url = audit["candidates"][0]["payload"]["references"][0]["resolved_url"]
    harness.fail_urls.add(url)
    first = module.run(audit, harness, tmp_path / "run")
    assert first["status"] == "COMPLETED"
    assert first["results"][0]["current_url_states"] == {"FAILED": 1, "ACQUIRED": 2}
    second = module.run(audit, harness, tmp_path / "run")
    assert second["executed_batches"] == 0
    assert harness.fetched.count(url) == 1
    assert harness.worker_calls == 1


def test_interruption_resumes_same_job_and_does_not_refetch_acquired(module, harness, tmp_path):
    _, _, audit = make_audit(module, tmp_path)
    harness.behavior = "pause_after_one"
    first = module.run(audit, harness, tmp_path / "run")
    assert first["results"][0]["status"] == "QUEUED"
    first_url = harness.fetched[0]
    harness.behavior = "success"
    harness.draining = False
    second = module.run(audit, harness, tmp_path / "run")
    assert second["status"] == "COMPLETED"
    assert second["results"][0]["job_id"] == first["results"][0]["job_id"]
    assert harness.fetched.count(first_url) == 1
    assert len(harness.jobs) == 1


def test_partial_failed_url_prevents_automatic_second_worker_attempt(module, harness, tmp_path):
    _, _, audit = make_audit(module, tmp_path)
    url = audit["candidates"][0]["payload"]["references"][0]["resolved_url"]
    harness.fail_urls.add(url)
    harness.behavior = "error_after_one"
    first = module.run(audit, harness, tmp_path / "run")
    assert first["status"] == "PAUSED"
    assert first["stop_reason"] == "CURRENT_ONLY_PRIOR_ATTEMPT_REQUIRES_REVIEW"
    assert harness.worker_calls == 1
    second = module.run(audit, harness, tmp_path / "run")
    assert second["stop_reason"] == first["stop_reason"]
    assert harness.fetched == [url]


def test_lost_submit_response_recovers_existing_owned_job(module, harness, tmp_path):
    _, _, audit = make_audit(module, tmp_path)
    harness.submit_loss = True
    with pytest.raises(OSError):
        module.run(audit, harness, tmp_path / "run")
    assert len(harness.jobs) == 1
    second = module.run(audit, harness, tmp_path / "run")
    assert second["status"] == "COMPLETED"
    assert len(harness.jobs) == 1
    assert len(harness.fetched) == 3
    partial = [json.loads(p.read_bytes()) for p in (tmp_path / "run").glob("run-*.json")]
    assert any(r["status"] == "INTERRUPTED" for r in partial)


@pytest.mark.parametrize(
    "mode,reason", [("foreign", "ANOTHER_WORKER_JOB_ACTIVE"), ("draining", "RUNTIME_DRAINING")]
)
def test_foreign_job_or_drain_stops_before_submission(module, harness, tmp_path, mode, reason):
    _, _, audit = make_audit(module, tmp_path)
    setattr(harness, mode, True)
    report = module.run(audit, harness, tmp_path / "run")
    assert report["status"] == "PAUSED"
    assert report["stop_reason"] == reason
    assert not harness.jobs and not harness.fetched


def test_terminal_job_failure_stops_without_new_job_or_retry(module, harness, tmp_path):
    _, _, audit = make_audit(module, tmp_path)
    harness.behavior = "terminal_failure"
    first = module.run(audit, harness, tmp_path / "run")
    assert first["stop_reason"] == "CURRENT_ONLY_TERMINAL_JOB_FAILED"
    second = module.run(audit, harness, tmp_path / "run")
    assert second["stop_reason"] == first["stop_reason"]
    assert harness.worker_calls == 1 and len(harness.jobs) == 1


def test_bound_500_urls_and_resume_past_completed_batch_with_next_queued(module, harness, tmp_path):
    _, _, audit = make_audit(module, tmp_path, count=501)
    first = module.run(audit, harness, tmp_path / "run", max_batches=1)
    assert first["status"] == "BOUNDED"
    assert len(harness.fetched) == 500
    harness.behavior = "pause_after_one"
    second = module.run(audit, harness, tmp_path / "run", max_batches=1)
    assert second["results"][0]["status"] == "SUCCEEDED"
    assert second["results"][1]["status"] == "QUEUED"
    harness.behavior = "success"
    harness.draining = False
    third = module.run(audit, harness, tmp_path / "run", max_batches=1)
    assert third["status"] == "COMPLETED"
    assert len(harness.fetched) == 501
    assert len(harness.jobs) == 2


def test_all_previously_acquired_creates_no_job(module, harness, tmp_path):
    _, _, audit = make_audit(module, tmp_path)
    for ref in audit["candidates"][0]["payload"]["references"]:
        harness.ledger[ref["resolved_url"]] = {"status": "ACQUIRED"}
    result = module.run(audit, harness, tmp_path / "run")
    assert result["status"] == "COMPLETED"
    assert result["results"][0]["status"] == "SKIPPED_ALREADY_ATTEMPTED"
    assert harness.worker_calls == 0 and not harness.jobs


def test_local_resume_receipt_cannot_change_selection(module, harness, tmp_path):
    _, _, audit = make_audit(module, tmp_path)
    module.run(audit, harness, tmp_path / "run")
    path = tmp_path / "run/selection-001.json"
    state = json.loads(path.read_bytes())
    state["references"].pop()
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="SELECTION_RECEIPT_MISMATCH"):
        module.run(audit, harness, tmp_path / "run")
    assert harness.worker_calls == 1


@pytest.mark.parametrize("change", ["scope", "failed_reference", "legacy_row"])
def test_rehashed_but_invalid_candidate_contract_rejected(module, tmp_path, change):
    directory, _, _ = make_audit(module, tmp_path)
    summary = json.loads((directory / "summary.json").read_bytes())
    path = directory / "never-attempted-001.json"
    value = json.loads(path.read_bytes())
    if change == "scope":
        value["scope"] = "LEGACY_CORPUS"
    elif change == "failed_reference":
        value["references"][0]["acquisition_state"] = "FAILED"
    else:
        value["references"][0]["row_position"] = 42
    raw = module.encoded(value)
    path.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    summary["artifacts"][path.name] = {"sha256": digest, "size_bytes": len(raw)}
    summary["candidate_manifests"][0]["artifact_id_candidate"] = (
        "image-manifest:current-source-only-" + digest
    )
    encoded = module.encoded(summary)
    (directory / "summary.json").write_bytes(encoded)
    with pytest.raises(ValueError, match="CANDIDATE_(CONTRACT|REFERENCE)_MISMATCH"):
        module.load_audit(directory, sha256(encoded).hexdigest())


def test_actual_execution_fields_must_match_current_parent(module, tmp_path, monkeypatch):
    _, _, audit = make_audit(module, tmp_path)
    refs = audit["candidates"][0]["payload"]["references"]
    current = json.loads(json.dumps(refs))
    parent = {
        "html_sha256": refs[0]["current_html_sha256"],
        "html_artifact_id": refs[0]["current_html_artifact_id"],
    }
    monkeypatch.setattr(module, "inspect_reader", lambda *args: (parent, current))
    refs[0]["name"] = "changed"
    with pytest.raises(ValueError, match="CURRENT_PARENT_MISMATCH"):
        module.verify_sources(None, audit)


def test_atomic_state_install_does_not_overwrite_other_content(module, tmp_path):
    path = tmp_path / "state.json"
    module.atomic_local(path, b"original")
    module.atomic_local(path, b"original")
    with pytest.raises(ValueError, match="LOCAL_RUN_STATE_CONFLICT"):
        module.atomic_local(path, b"changed")
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob("*.pending-*"))
