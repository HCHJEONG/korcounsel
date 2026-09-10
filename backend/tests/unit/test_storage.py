from concurrent.futures import ThreadPoolExecutor

import pytest

from klegal_gold.db.accounts import hash_password, verify_password
from klegal_gold.storage.files import FileStore


def test_concurrent_file_put_never_overwrites(tmp_path):
    store = FileStore(tmp_path)
    raw = "immutable 😀\n".encode()
    with ThreadPoolExecutor(4) as pool:
        blobs = list(pool.map(lambda _: store.put(raw), range(8)))
    assert len(set(blobs)) == 1
    assert store.path(blobs[0].storage_key).read_bytes() == raw
    assert not list(tmp_path.glob("blobs/*/.pending-*"))


@pytest.mark.parametrize("key", ["../secret", "/etc/passwd", "blobs/00/" + "f" * 64])
def test_path_escape_rejected(tmp_path, key):
    with pytest.raises(ValueError, match="INVALID_STORAGE_KEY"):
        FileStore(tmp_path).path(key)


def test_symlink_directory_rejected(tmp_path):
    store = FileStore(tmp_path / "store")
    (tmp_path / "other").mkdir()
    (store.root / "blobs").symlink_to(tmp_path / "other", target_is_directory=True)
    with pytest.raises(ValueError, match="STORAGE_"):
        store.put(b"data")


def test_password_hashes_use_random_salt():
    password = "synthetic-long-password"
    a, b = hash_password(password), hash_password(password)
    assert a != b and password not in a
    assert verify_password(password, a)
    assert not verify_password("wrong", a)
    assert not verify_password(password, "plain")
