from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from klegal_gold.search.index import LegacySearchIndex, snapshot_key
from klegal_gold.search.parquet import search_legacy_parquet

pytestmark = pytest.mark.integration


def fixture(path: Path):
    rows = [
        {
            "case_txt_scraped_with_tags": "Straße 소송 2024도8174 100% a_b a\\b",
            "other": "경계",
            "__legacy_position": 5,
        },
        {"case_txt_scraped_with_tags": "STRASSE 소송", "other": "다른", "__legacy_position": 1},
        {"case_txt_scraped_with_tags": "소송 끝", "other": "경계", "__legacy_position": 8},
    ]
    pq.write_table(pa.Table.from_pylist(rows), path, row_group_size=1)


def test_index_matches_original_scan_and_rejects_changed_snapshot(db, tmp_path):
    path = tmp_path / "source.parquet"
    fixture(path)
    index = LegacySearchIndex(db)
    assert index.search(path, "소송") is None
    index.build(path, snapshot_key(path), lambda _: None)
    for q in ["STRASSE", "2024도8174", "소송", "%", "_", "\\", "없는말", "끝\n경계", "   "]:
        for limit in [1, 30]:
            assert index.search(path, q, limit) == search_legacy_parquet(path, q, limit=limit)
    replacement = tmp_path / "new.parquet"
    pq.write_table(pa.Table.from_pylist([{"other": "새 내용"}]), replacement)
    replacement.replace(path)
    assert index.search(path, "소송") is None


def test_incomplete_index_is_invisible_and_resumes_committed_groups(db, tmp_path):
    path = tmp_path / "source.parquet"
    fixture(path)
    index = LegacySearchIndex(db)
    key = snapshot_key(path)

    def interrupt(state):
        if state.get("next_group") == 1:
            raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        index.build(path, key, interrupt)
    assert index.search(path, "소송") is None
    index.build(path, key, lambda _: None)
    index.build(path, key, lambda _: None)
    assert index.search(path, "소송") == search_legacy_parquet(path, "소송")
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM legacy_search_rows").fetchone()["n"] == 3


def test_prefix_search_keeps_order_and_finds_matches_after_prefix(db, tmp_path):
    path = tmp_path / "many.parquet"
    rows = [
        {
            "case_txt_scraped_with_tags": "소유권" if i < 280 else "뒤쪽 고유문구",
            "__legacy_position": i,
        }
        for i in range(300)
    ]
    pq.write_table(pa.Table.from_pylist(rows), path, row_group_size=64)
    index = LegacySearchIndex(db)
    index.build(path, snapshot_key(path), lambda _: None)
    for query in ["소유권", "고유문구", "없음"]:
        assert index.search(path, query) == search_legacy_parquet(path, query)
