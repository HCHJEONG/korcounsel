"""Synthetic tar fixtures; never read a Docker volume or a corpus database."""

import importlib.util
import io
import json
import tarfile
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from klegal_gold.storage.files import Blob, FileStore


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[3] / "scripts/restore_exact_docker_blobs.py"
    spec = importlib.util.spec_from_file_location("restore_exact_blobs", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def blob(raw):
    digest = sha256(raw).hexdigest()
    return Blob(digest, f"blobs/{digest[:2]}/{digest}", len(raw))


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        for name, raw, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(raw) if kind == tarfile.REGTYPE else 0
            if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                member.linkname = "/etc/passwd"
            tar.addfile(member, io.BytesIO(raw) if kind == tarfile.REGTYPE else None)
    output.seek(0)
    return output


def make_audit(tmp_path, raws=(b"a", b"bb")):
    targets = [blob(raw) for raw in raws]
    data = {
        "version": "registered-blob-host-path-audit-1",
        "host_data_dir": str(tmp_path),
        "summary": {"problem_blobs": len(targets)},
        "issues": [
            {
                "sha256": b.sha256,
                "storage_key": b.storage_key,
                "size_bytes": b.size_bytes,
                "issue": "FILE_MISSING",
            }
            for b in targets
        ],
    }
    path = tmp_path / "audit.json"
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    return path, sha256(raw).hexdigest(), targets


def test_fixed_audit_and_explicit_range_bounds(module, tmp_path):
    path, digest, expected = make_audit(tmp_path)
    _, targets = module.load_targets(path, digest)
    assert targets == sorted(expected, key=lambda b: b.sha256)
    assert module.select_targets(targets, 0, 1, 10) == targets[:1]
    with pytest.raises(ValueError, match="BOUND_EXCEEDED"):
        module.select_targets(targets, 0, 2, 1)
    with pytest.raises(ValueError, match="AUDIT_HASH_MISMATCH"):
        module.load_targets(path, "0" * 64)


@pytest.mark.parametrize("change", ["key", "duplicate", "issue", "size"])
def test_invalid_audit_targets_rejected(module, tmp_path, change):
    path, _, _ = make_audit(tmp_path)
    data = json.loads(path.read_bytes())
    if change == "key":
        data["issues"][0]["storage_key"] = "../outside"
    elif change == "duplicate":
        data["issues"][1] = data["issues"][0]
    elif change == "issue":
        data["issues"][0]["issue"] = "SIZE_MISMATCH"
    else:
        data["issues"][0]["size_bytes"] = True
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="INVALID_AUDIT_TARGET"):
        module.load_targets(path, sha256(raw).hexdigest())


def test_exact_restore_reuse_and_original_bytes(module, tmp_path):
    raw = b"historical immutable bytes\x00\xff"
    target = blob(raw)
    stream = archive([(target.storage_key, raw, tarfile.REGTYPE)])
    original_tar = stream.getvalue()
    files = FileStore(tmp_path / "host")
    events = []
    first = module.process_archive(stream, [target], files, events.append)
    assert first["counts"] == {"RESTORED_VERIFIED": 1}
    assert first["restored_bytes"] == len(raw)
    assert files.path(target.storage_key).read_bytes() == raw
    assert stream.getvalue() == original_tar
    old_stat = files.path(target.storage_key).stat()
    second = module.process_archive(archive([]), [target], files, events.append)
    assert second["counts"] == {"REUSED_VERIFIED": 1}
    assert second["restored_bytes"] == 0
    assert files.path(target.storage_key).stat().st_ino == old_stat.st_ino
    assert files.path(target.storage_key).stat().st_mtime_ns == old_stat.st_mtime_ns


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE])
def test_tar_nonregular_targets_never_installed(module, tmp_path, kind):
    target = blob(b"a")
    files = FileStore(tmp_path / "host")
    result = module.process_archive(
        archive([(target.storage_key, b"", kind)]), [target], files, lambda event: None
    )
    assert result["counts"] == {"SOURCE_NOT_REGULAR_FILE": 1}
    assert not files.path(target.storage_key).exists()


@pytest.mark.parametrize(
    "raw,status", [(b"xx", "SOURCE_SIZE_MISMATCH"), (b"b", "SOURCE_CONTENT_MISMATCH")]
)
def test_wrong_source_size_or_hash_never_installed(module, tmp_path, raw, status):
    target = blob(b"a")
    files = FileStore(tmp_path / "host")
    result = module.process_archive(
        archive([(target.storage_key, raw, tarfile.REGTYPE)]), [target], files, lambda event: None
    )
    assert result["counts"] == {status: 1}
    assert not files.path(target.storage_key).exists()


def test_tar_path_traversal_and_unselected_files_never_extracted(module, tmp_path):
    target, other = blob(b"a"), blob(b"other")
    files = FileStore(tmp_path / "host")
    entries = [
        ("../outside", b"bad", tarfile.REGTYPE),
        ("./" + target.storage_key, b"a", tarfile.REGTYPE),
        (other.storage_key, b"other", tarfile.REGTYPE),
    ]
    result = module.process_archive(archive(entries), [target], files, lambda event: None)
    assert result["counts"] == {"SOURCE_NOT_PRESENT": 1}
    assert list(files.root.iterdir()) == []
    assert not (tmp_path / "outside").exists()


def test_existing_corrupt_host_never_overwritten(module, tmp_path):
    target = blob(b"a")
    files = FileStore(tmp_path / "host")
    destination = files.path(target.storage_key)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"x")
    result = module.process_archive(
        archive([(target.storage_key, b"a", tarfile.REGTYPE)]), [target], files, lambda event: None
    )
    assert result["counts"] == {"HOST_INTEGRITY_FAILED": 1}
    assert destination.read_bytes() == b"x"


def test_existing_host_symlink_never_followed(module, tmp_path):
    target = blob(b"a")
    files = FileStore(tmp_path / "host")
    destination = files.path(target.storage_key)
    destination.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_bytes(b"a")
    destination.symlink_to(outside)
    result = module.process_archive(
        archive([(target.storage_key, b"a", tarfile.REGTYPE)]), [target], files, lambda event: None
    )
    assert result["counts"] == {"HOST_INTEGRITY_FAILED": 1}
    assert destination.is_symlink()
    assert outside.read_bytes() == b"a"


def test_partial_put_failure_resume_verifies_completed_file(module, tmp_path, monkeypatch):
    targets = [blob(b"a"), blob(b"bb")]
    entries = [
        (b.storage_key, raw, tarfile.REGTYPE) for b, raw in zip(targets, [b"a", b"bb"], strict=True)
    ]
    files = FileStore(tmp_path / "host")
    original_put = files.put

    def interrupted_put(raw):
        if raw == b"bb":
            raise OSError("synthetic disk failure")
        return original_put(raw)

    monkeypatch.setattr(files, "put", interrupted_put)
    first = module.process_archive(archive(entries), targets, files, lambda event: None)
    assert first["counts"] == {"RESTORED_VERIFIED": 1, "RESTORE_FAILED": 1}
    monkeypatch.setattr(files, "put", original_put)
    second = module.process_archive(archive(entries), targets, files, lambda event: None)
    assert second["counts"] == {"REUSED_VERIFIED": 1, "RESTORED_VERIFIED": 1}
    for target in targets:
        files.verify(target)


def test_interrupted_stream_records_all_unprocessed_targets(module, tmp_path):
    targets = [blob(b"a"), blob(b"bb")]
    events = []
    with pytest.raises(tarfile.ReadError):
        module.process_archive(
            io.BytesIO(b"truncated"), targets, FileStore(tmp_path / "host"), events.append
        )
    assert [e["status"] for e in events] == ["NOT_PROCESSED_INTERRUPTED"] * 2 + ["INTERRUPTED"]
    assert events[-1]["summary"]["completed_stream"] is False


def test_preflight_reads_sizes_without_installing_or_claiming_hash(module):
    target = blob(b"a")
    result = module.process_archive(
        archive([(target.storage_key, b"b", tarfile.REGTYPE)]), [target], None, lambda event: None
    )
    assert result["counts"] == {"SOURCE_PRESENT_SIZE_MATCH": 1}
    assert result["restored_bytes"] == 0


def test_duplicate_tar_member_reported_without_overwrite(module, tmp_path):
    target = blob(b"a")
    files = FileStore(tmp_path / "host")
    entries = [
        (target.storage_key, b"a", tarfile.REGTYPE),
        (target.storage_key, b"b", tarfile.REGTYPE),
    ]
    result = module.process_archive(archive(entries), [target], files, lambda event: None)
    assert result["counts"] == {"RESTORED_VERIFIED": 1, "DUPLICATE_TAR_MEMBER": 1}
    assert files.path(target.storage_key).read_bytes() == b"a"


@pytest.mark.parametrize(
    "running,volume,active",
    [(True, "expected", b""), (False, "other", b""), (False, "expected", b"active-container")],
)
def test_source_requires_stopped_exclusive_expected_volume(
    module, monkeypatch, running, volume, active
):
    def run(command, **kwargs):
        data = [
            {
                "Id": "id",
                "State": {"Status": "running" if running else "exited", "Running": running},
                "Mounts": [{"Destination": "/data", "Type": "volume", "Name": volume}],
            }
        ]
        return SimpleNamespace(
            stdout=json.dumps(data).encode() if command[1] == "inspect" else active
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(ValueError):
        module.inspect_source("stopped-container", "expected")


def source_manifest(tmp_path, targets, audit_hash):
    result = {
        "version": "source-present-blob-targets-1",
        "audit_sha256": audit_hash,
        "target_count": len(targets),
        "target_bytes": sum(b.size_bytes for b in targets),
        "blobs": [
            {"sha256": b.sha256, "storage_key": b.storage_key, "size_bytes": b.size_bytes}
            for b in targets
        ],
    }
    path = tmp_path / "source-targets.json"
    raw = json.dumps(result).encode()
    path.write_bytes(raw)
    return path, sha256(raw).hexdigest()


def test_known_present_subset_is_bound_to_audit(module, tmp_path):
    path, digest, targets = make_audit(tmp_path)
    source, source_hash = source_manifest(tmp_path, targets[:1], digest)
    _, chosen = module.limit_source_targets(targets, source, source_hash, digest)
    assert chosen == targets[:1]
    with pytest.raises(ValueError, match="SOURCE_TARGET_AUDIT_MISMATCH"):
        module.limit_source_targets(targets, source, source_hash, "0" * 64)
    with pytest.raises(ValueError, match="SOURCE_TARGET_HASH_MISMATCH"):
        module.limit_source_targets(targets, source, "0" * 64, digest)


@pytest.mark.parametrize("change", ["unknown", "size", "duplicate"])
def test_source_subset_cannot_introduce_or_change_targets(module, tmp_path, change):
    _, digest, targets = make_audit(tmp_path)
    chosen = [blob(b"unknown")] if change == "unknown" else targets[:1]
    if change == "size":
        original = chosen[0]
        chosen = [Blob(original.sha256, original.storage_key, original.size_bytes + 1)]
    if change == "duplicate":
        chosen *= 2
    source, source_hash = source_manifest(tmp_path, chosen, digest)
    with pytest.raises(ValueError, match="SOURCE_TARGET_NOT_IN_AUDIT"):
        module.limit_source_targets(targets, source, source_hash, digest)


def create_source(root, target, raw):
    path = root / target.storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def test_bundle_exact_copy_is_independent_and_resumes(module, tmp_path):
    root = tmp_path / "bundle"
    target = blob(b"original bundle bytes")
    source = create_source(root, target, b"original bundle bytes")
    before = source.stat()
    files = FileStore(tmp_path / "host")
    first = module.process_directory(root, [target], files, lambda event: None)
    assert first["counts"] == {"RESTORED_VERIFIED": 1}
    destination = files.path(target.storage_key)
    assert destination.stat().st_ino != before.st_ino
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert source.stat().st_ino == before.st_ino
    assert source.read_bytes() == destination.read_bytes() == b"original bundle bytes"
    second = module.process_directory(root, [target], files, lambda event: None)
    assert second["counts"] == {"REUSED_VERIFIED": 1}
    assert second["restored_bytes"] == 0


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("missing", "SOURCE_NOT_PRESENT"),
        ("size", "SOURCE_SIZE_MISMATCH"),
        ("hash", "SOURCE_CONTENT_MISMATCH"),
        ("symlink", "RESTORE_FAILED"),
        ("parent-symlink", "RESTORE_FAILED"),
        ("directory", "SOURCE_NOT_REGULAR_FILE"),
    ],
)
def test_bundle_source_defects_preserved_without_installation(module, tmp_path, kind, expected):
    root = tmp_path / "bundle"
    target = blob(b"a")
    source = root / target.storage_key
    source.parent.mkdir(parents=True)
    if kind in {"size", "hash"}:
        source.write_bytes(b"wrong-size" if kind == "size" else b"b")
    if kind == "directory":
        source.mkdir()
    if kind == "symlink":
        other = tmp_path / "other"
        other.write_bytes(b"a")
        source.symlink_to(other)
    if kind == "parent-symlink":
        source.parent.rmdir()
        other = tmp_path / "other-shard"
        other.mkdir()
        (other / target.sha256).write_bytes(b"a")
        source.parent.symlink_to(other, target_is_directory=True)
    files = FileStore(tmp_path / "host")
    result = module.process_directory(root, [target], files, lambda event: None)
    assert result["counts"] == {expected: 1}
    assert not files.path(target.storage_key).exists()


def test_bundle_existing_corrupt_host_preserved(module, tmp_path):
    root = tmp_path / "bundle"
    target = blob(b"a")
    create_source(root, target, b"a")
    files = FileStore(tmp_path / "host")
    destination = files.path(target.storage_key)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"b")
    result = module.process_directory(root, [target], files, lambda event: None)
    assert result["counts"] == {"HOST_INTEGRITY_FAILED": 1}
    assert destination.read_bytes() == b"b"


def test_bundle_interruption_leaves_complete_per_target_ledger(module, tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    targets = [blob(b"a"), blob(b"bb")]
    for target, raw in zip(targets, [b"a", b"bb"], strict=True):
        create_source(root, target, raw)
    files = FileStore(tmp_path / "host")
    original_put = files.put

    def interrupted(raw):
        if raw == b"bb":
            raise KeyboardInterrupt
        return original_put(raw)

    monkeypatch.setattr(files, "put", interrupted)
    events = []
    with pytest.raises(KeyboardInterrupt):
        module.process_directory(root, targets, files, events.append)
    assert [e["status"] for e in events] == ["RESTORED_VERIFIED", "NOT_PROCESSED_INTERRUPTED"]
    monkeypatch.setattr(files, "put", original_put)
    result = module.process_directory(root, targets, files, lambda event: None)
    assert result["counts"] == {"REUSED_VERIFIED": 1, "RESTORED_VERIFIED": 1}


def test_bundle_cli_preflight_and_restore_append_distinct_run_evidence(
    module, tmp_path, monkeypatch
):
    path, digest, targets = make_audit(tmp_path, raws=(b"a",))
    source, _ = source_manifest(tmp_path, targets, digest)
    root = tmp_path / "bundle"
    create_source(root, targets[0], b"a")
    manifest = json.loads(source.read_bytes())
    manifest["source_directory"] = str(root)
    raw = json.dumps(manifest).encode()
    source.write_bytes(raw)
    outputs = tmp_path / "runs"
    args = [
        "restore",
        "--audit",
        str(path),
        "--audit-sha256",
        digest,
        "--source-targets",
        str(source),
        "--source-targets-sha256",
        sha256(raw).hexdigest(),
        "--source-directory",
        str(root),
        "--data-dir",
        str(tmp_path),
        "--output-dir",
        str(outputs),
    ]
    monkeypatch.setattr(module.sys if hasattr(module, "sys") else __import__("sys"), "argv", args)
    assert module.main() == 0
    assert not (tmp_path / targets[0].storage_key).exists()
    args.extend(["--mode", "restore"])
    assert module.main() == 0
    assert module.main() == 0
    summaries = [json.loads(p.read_bytes()) for p in outputs.glob("*.json")]
    assert len(summaries) == 3
    assert {next(iter(s["counts"])) for s in summaries} == {
        "SOURCE_PRESENT_SIZE_MATCH",
        "RESTORED_VERIFIED",
        "REUSED_VERIFIED",
    }
    assert len(list(outputs.glob("*.jsonl"))) == 3
    assert all(s["db_access"] is False for s in summaries)


def test_cli_stop_boundary_leaves_later_bundle_targets_unprocessed(module, tmp_path):
    root = tmp_path / "bundle"
    targets = [blob(b"a"), blob(b"bb")]
    create_source(root, targets[0], b"x")
    create_source(root, targets[1], b"bb")
    files = FileStore(tmp_path / "host")
    events = []
    with pytest.raises(module.RestorationStopped, match="SOURCE_CONTENT_MISMATCH"):
        module.process_directory(root, targets, files, events.append, stop_on_error=True)
    assert [e["status"] for e in events] == ["SOURCE_CONTENT_MISMATCH", "NOT_PROCESSED_INTERRUPTED"]
    assert not files.path(targets[1].storage_key).exists()


def test_cli_stop_boundary_leaves_later_tar_targets_unprocessed(module, tmp_path):
    targets = [blob(b"a"), blob(b"bb")]
    entries = [
        (targets[0].storage_key, b"x", tarfile.REGTYPE),
        (targets[1].storage_key, b"bb", tarfile.REGTYPE),
    ]
    files = FileStore(tmp_path / "host")
    events = []
    with pytest.raises(module.RestorationStopped, match="SOURCE_CONTENT_MISMATCH"):
        module.process_archive(archive(entries), targets, files, events.append, stop_on_error=True)
    assert [e["status"] for e in events] == [
        "SOURCE_CONTENT_MISMATCH",
        "NOT_PROCESSED_INTERRUPTED",
        "INTERRUPTED",
    ]
    assert not files.path(targets[1].storage_key).exists()
