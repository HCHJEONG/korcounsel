"""Wave orchestration preserves bounded groups, partial work and immutable resume proof."""

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
        "image_waves", scripts / "run_legacy_image_waves.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def row(position, source="123", usable=True):
    return {
        "position": position,
        "source_id": source,
        "source_id_usable": usable,
        "body_hash": "b" * 64,
        "snapshot_sha256": "a" * 64,
    }


class FakeRecords:
    def __init__(self):
        self.values = {}
        self.jobs = {}
        self.draining = False
        self.foreign = False
        self.downloaded = False
        self.download_status = "SUCCEEDED"
        self.stage_status = "SUCCEEDED"
        self.source_statuses = {}
        self.failed_rows = set()
        self.calls = []
        self.db = self

    @contextmanager
    def connect(self):
        yield self

    def execute(self, query, params):
        owned = params[0]
        active = self.foreign or any(
            job.status in {"QUEUED", "RUNNING"} and key not in owned
            for key, job in self.jobs.items()
        )
        return SimpleNamespace(fetchone=lambda: {"found": 1} if active else None)

    def put_artifact(self, artifact, raw, **kwargs):
        if artifact in self.values:
            assert self.values[artifact] == raw
        self.values[artifact] = raw

    def read(self, artifact):
        return self.values[artifact]


@pytest.fixture
def harness(module, monkeypatch):
    records = FakeRecords()

    class Queue:
        def __init__(self, db, **kwargs):
            pass

        def drain_status(self):
            return {"draining": records.draining}

        def get(self, job_id):
            return next(job for job in records.jobs.values() if job.job_id == job_id)

        def submit_image_batch(self, key, artifact, **kwargs):
            if key not in records.jobs:
                records.jobs[key] = SimpleNamespace(
                    job_id=key,
                    status="QUEUED",
                    payload={"manifest_artifact_id": artifact},
                    checkpoint={},
                    attempts=0,
                )
            return records.jobs[key]

        def worker_heartbeat(self, *args, **kwargs):
            pass

    class Reader:
        def __init__(self, saved):
            pass

        def read(self, document_id):
            return json.loads(records.read("reader:" + document_id))

    def prepare(saved, targets, **kwargs):
        records.calls.append(
            ("prepare", [r["position"] for r in targets], kwargs["inventory_hash"])
        )
        source = targets[0]["source_id"]
        status = records.source_statuses.get(source, "CURRENT_EVIDENCE_PRESERVED")
        document = (
            sha256(source.encode()).hexdigest() if status == "CURRENT_EVIDENCE_PRESERVED" else None
        )
        if document:
            records.put_artifact("reader:" + document, b"{}")
        return {
            "results": [
                {
                    "source_id": source,
                    "positions": [r["position"] for r in targets],
                    "status": status,
                    "current_reader": document,
                    "job_id": None,
                }
            ],
            "current_readers": {str(r["position"]): document for r in targets} if document else {},
        }

    def make_plan(path, saved, **kwargs):
        records.calls.append(("plan", kwargs))
        digest = sha256(module.encoded([kwargs, records.downloaded])).hexdigest()
        manifest = "legacy-reader-batch:" + digest
        plan = {
            "parquet_sha256": "p" * 64,
            "snapshot_sha256": "a" * 64,
            "batches": [{"positions": kwargs["positions"], "manifest_artifact_id": manifest}],
        }
        artifact = "legacy-reader-plan:" + digest
        records.put_artifact(artifact, module.encoded(plan))
        records.put_artifact(manifest, module.encoded(kwargs))
        return {"plan_artifact_id": artifact, "batches": 1, "rows": len(kwargs["positions"])}

    def run_plan(saved, pointer, **kwargs):
        records.calls.append(("stage", records.downloaded))
        plan = json.loads(records.read(pointer["plan_artifact_id"]))
        batch = plan["batches"][0]
        manifest = batch["manifest_artifact_id"]
        key = "reader-stage:" + manifest.split(":", 1)[1]
        refs = (
            []
            if records.downloaded
            else [
                {
                    "resolved_url": "https://portal.scourt.go.kr/image",
                    "row_position": p,
                    "occurrence_order": i,
                    "reference_status": "RESOLVED",
                }
                for p in batch["positions"]
                if p not in records.failed_rows
                for i in range(2)
            ]
        )
        download = "pending:" + key
        records.put_artifact(download, module.encoded({"references": refs}))
        result = {
            "input_manifest": manifest,
            "parquet_sha256": plan["parquet_sha256"],
            "snapshot_sha256": plan["snapshot_sha256"],
            "download_manifest": download,
            "rows": [
                {
                    "position": p,
                    "status": "FAILED" if p in records.failed_rows else "STAGED",
                    "error_code": "TITLE_MISMATCH" if p in records.failed_rows else None,
                }
                for p in batch["positions"]
            ],
        }
        artifact = "stage-result:" + key
        records.put_artifact(artifact, module.encoded(result))
        job = SimpleNamespace(
            job_id=key,
            status=records.stage_status,
            payload={"manifest_artifact_id": manifest},
            checkpoint={"result_manifest": artifact},
        )
        records.jobs[key] = job
        return {
            "plan_artifact_id": pointer["plan_artifact_id"],
            "results": [{"job_id": key, "status": job.status, "positions": batch["positions"]}],
        }

    def run_owned_job(saved, queue, worker, job):
        records.calls.append(("download", job.job_id))
        job.status = records.download_status
        job.checkpoint = {"image_failed": 1, "image_acquired": 0}
        if job.status == "SUCCEEDED":
            records.downloaded = True
        return job

    monkeypatch.setattr(module, "Queue", Queue)
    monkeypatch.setattr(module, "Worker", lambda *args: SimpleNamespace(worker_id="fixture"))
    monkeypatch.setattr(module, "ReaderStore", Reader)
    monkeypatch.setattr(module, "prepare", prepare)
    monkeypatch.setattr(module, "make_plan", make_plan)
    monkeypatch.setattr(module, "run_plan", run_plan)
    monkeypatch.setattr(module, "run_owned_job", run_owned_job)
    return records


def run(module, records, tmp_path, rows, **kwargs):
    return module.run_waves(
        records,
        tmp_path / "corpus.parquet",
        rows,
        {"inventory_sha256": "i" * 64, "targets_sha256": "t" * 64},
        tmp_path / "receipts",
        **kwargs,
    )


def test_source_groups_never_split_or_repeat(module):
    rows = [row(i, str(i)) for i in range(201)] + [row(300, "0"), row(301, "bad", False)]
    waves = module.source_waves(rows)
    assert [len(w) for w in waves] == [100, 100, 1]
    assert [r["position"] for r in waves[0][0]] == [0, 300]
    sources = [group[0]["source_id"] for wave in waves for group in wave]
    assert len(sources) == len(set(sources)) == 201


def test_501_urls_preserve_all_repeated_positions(module):
    refs = [{"resolved_url": f"https://provider/{i}", "row_position": i} for i in range(501)]
    refs += [
        {"resolved_url": "https://provider/0", "row_position": 800},
        {"resolved_url": "https://provider/500", "row_position": 801},
        {"resolved_url": None, "row_position": 802},
    ]
    chunks = module.split_download_references(refs)
    assert len(chunks) == 2
    assert [len({r["resolved_url"] for r in c if r["resolved_url"]}) for c in chunks] == [500, 1]
    assert sorted(r["row_position"] for c in chunks for r in c) == sorted(
        r["row_position"] for r in refs
    )
    assert {r["row_position"] for r in chunks[0] if r["resolved_url"] == "https://provider/0"} == {
        0,
        800,
    }


def test_inventory_hash_and_row_identity_checked(module, tmp_path):
    inventory, targets = tmp_path / "all.jsonl", tmp_path / "targets.json"
    raw = module.encoded(row(0)) + b"\n"
    inventory.write_bytes(raw)
    targets.write_text(json.dumps({"rows": [row(0)]}))
    digest = sha256(raw).hexdigest()
    selected, _ = module.load_targets(targets, inventory, expected_hash=digest)
    assert selected == [row(0)]
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        module.load_targets(targets, inventory)
    targets.write_text(json.dumps({"rows": [row(0, "changed")]}))
    with pytest.raises(ValueError, match="TARGET_INVENTORY_MISMATCH"):
        module.load_targets(targets, inventory, expected_hash=digest)


def test_not_found_and_row_failures_do_not_stop_other_rows(module, harness, tmp_path):
    harness.source_statuses["missing"] = "SOURCE_NOT_FOUND"
    harness.failed_rows.add(2)
    result = run(
        module, harness, tmp_path, [row(0), row(1, "missing"), row(2), row(3, "bad", False)]
    )
    assert result["status"] == "COMPLETED"
    wave = result["waves"][0]
    assert [r["status"] for r in wave["row_results"]] == ["STAGED", "FAILED", "SOURCE_NOT_FOUND"]
    assert wave["downloads"][0]["checkpoint"]["image_failed"] == 1
    assert wave["restage"]["rows"][1]["status"] == "FAILED"
    assert result["unusable_rows"][0]["position"] == 3
    assert harness.calls[0][1] == [0, 2]
    assert len([c for c in harness.calls if c[0] == "stage"]) == 2


@pytest.mark.parametrize("status", ["FAILED", "QUEUED", "RUNNING"])
def test_unfinished_stage_job_stops_wave_with_rows_preserved(module, harness, tmp_path, status):
    harness.stage_status = status
    result = run(module, harness, tmp_path, [row(0)])
    assert result["status"] == "PAUSED"
    assert result["stop_reason"] == "STAGE_JOB_" + status
    assert result["waves"][0]["row_results"][0]["position"] == 0
    assert not any(call[0] == "download" for call in harness.calls)


def test_interrupted_download_resumes_from_verified_phase_artifact(module, harness, tmp_path):
    harness.download_status = "QUEUED"
    first = run(module, harness, tmp_path, [row(0)])
    assert first["stop_reason"] == "DOWNLOAD_JOB_QUEUED"
    checkpoint = first["waves"][0]["receipt_artifact"]
    before = len([c for c in harness.calls if c[0] == "prepare"])
    harness.download_status = "SUCCEEDED"
    second = run(module, harness, tmp_path, [row(0)], resume_wave=checkpoint)
    assert second["status"] == "COMPLETED"
    assert len([c for c in harness.calls if c[0] == "prepare"]) == before
    assert len([c for c in harness.calls if c[0] == "plan"]) == 2
    assert second["waves"][0]["stage"]["plan"] == first["waves"][0]["stage"]["plan"]


@pytest.mark.parametrize(
    "mode,code", [("draining", "RUNTIME_DRAINING"), ("foreign", "ANOTHER_WORKER_JOB_ACTIVE")]
)
def test_drain_or_foreign_job_stops_before_preparation(module, harness, tmp_path, mode, code):
    setattr(harness, mode, True)
    result = run(module, harness, tmp_path, [row(0), row(1, "other")])
    assert result["stop_reason"] == code
    assert harness.calls == []
    assert all(r["status"] == "NOT_PROCESSED" for r in result["waves"][0]["row_results"])


def test_three_consecutive_source_structure_failures_stop_next_wave(module, harness, tmp_path):
    harness.source_statuses = {str(i): "CURRENT_STRUCTURE_UNCONFIRMED" for i in range(5)}
    result = run(
        module,
        harness,
        tmp_path,
        [row(i, str(i)) for i in range(5)],
        sources_per_wave=2,
        max_waves=3,
    )
    assert result["stop_reason"] == "CONSECUTIVE_SOURCE_STRUCTURE_FAILURES"
    assert len(result["waves"]) == 2
    assert len([call for call in harness.calls if call[0] == "prepare"]) == 3
    assert result["waves"][1]["row_results"][1]["status"] == "NOT_PROCESSED"


def test_local_receipts_are_not_trusted_for_skipping(module, harness, tmp_path):
    first = run(module, harness, tmp_path, [row(0)])
    first_count = len([call for call in harness.calls if call[0] == "prepare"])
    run(module, harness, tmp_path, [row(0)])
    assert len([call for call in harness.calls if call[0] == "prepare"]) == first_count + 1
    corrupted = json.loads(harness.read(first["waves"][0]["receipt_artifact"]))
    corrupted["inventory_sha256"] = "changed"
    harness.values["corrupt"] = module.encoded(corrupted)
    with pytest.raises(ValueError, match="RESUME_INPUT_MISMATCH"):
        run(module, harness, tmp_path, [row(0)], resume_wave="corrupt")


def test_default_limit_stops_after_one_wave(module, harness, tmp_path):
    result = run(module, harness, tmp_path, [row(0), row(1, "other")], sources_per_wave=1)
    assert result["status"] == "BOUNDED"
    assert len(result["waves"]) == 1
    assert [call[1] for call in harness.calls if call[0] == "prepare"] == [[0]]


def test_terminal_download_failure_preserves_job_without_restaging(module, harness, tmp_path):
    harness.download_status = "FAILED"
    result = run(module, harness, tmp_path, [row(0)])
    assert result["stop_reason"] == "DOWNLOAD_JOB_FAILED"
    assert result["waves"][0]["downloads"][0]["status"] == "FAILED"
    assert "restage" not in result["waves"][0]


def test_source_not_found_resets_consecutive_structure_count(module, harness, tmp_path):
    harness.source_statuses = {
        "0": "SOURCE_FETCH_FAILED",
        "1": "SOURCE_FETCH_FAILED",
        "2": "SOURCE_NOT_FOUND",
        "3": "SOURCE_FETCH_FAILED",
    }
    result = run(module, harness, tmp_path, [row(i, str(i)) for i in range(4)])
    assert result["status"] == "COMPLETED"
    assert len(result["waves"][0]["source_results"]) == 4
