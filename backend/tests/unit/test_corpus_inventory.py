import json
from hashlib import sha256
from html import escape

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from klegal_gold.enrichment.corpus_inventory import inspect_row, run_inventory


def row(html, position=7):
    return {
        "__legacy_position": position,
        "__legacy_index": '{"value": "legacy-index"}',
        "case_txt_scraped_with_tags": html,
        "case_full_no": "법원 사건 판결",
        "gmeta_contId": "123",
        "lmeta_serialno": "456",
    }


def test_inventory_distinguishes_image_occurrences_ui_hidden_and_table():
    image = '<img name="img1" src="/img?contId=123&amp;attachImgNm=a.gif">'
    html = (
        "😀" + image + "<table><tr><td>" + image + "</td></tr></table>"
        '<img src="/images/alert_img_01.png"><img name="img2">'
        '<template><img src="/hidden.gif"></template>'
    )
    result = inspect_row(row(html), "a" * 64, 0)
    assert not result.errors
    assert result.row["original_index"] == "legacy-index"
    assert result.row["image_occurrences"] == 5
    assert result.row["body_images"] == 3
    assert result.row["provider_ui_images"] == 1
    assert result.row["hidden_images"] == 1
    assert result.row["table_body_images"] == 1
    assert result.row["missing_src_body_images"] == 1
    assert result.images[0]["html_start"] == 1
    assert result.images[0]["legacy_filenames"] == ["a.gif"]
    assert result.images[0]["reference_id"] != result.images[1]["reference_id"]
    assert result.images[3]["reference_status"] == "MISSING_SRC"
    assert all("html_tag" not in image for image in result.images)
    assert result.row["body_hash"] == sha256(html.encode()).hexdigest()


def test_inventory_preserves_all_statute_states_without_payload_duplication():
    payload = "<table><tr><td>법률 본문</td></tr></table>"
    html = (
        '<a name="linkContJomun">미연결</a>'
        '<a jtable="jomun not registered at 법제처">실패</a>'
        + '<a jtable="'
        + escape(payload, quote=True)
        + '">저장</a>' * 1
    )
    result = inspect_row(row(html), "a" * 64, 0)
    assert not result.errors
    assert result.row["statute_occurrences"] == 3
    assert result.row["preserved_statutes"] == 1
    assert result.row["failed_statutes"] == 1
    assert result.row["unlinked_statutes"] == 1
    assert result.statutes[2]["payload_sha256"] == sha256(payload.encode()).hexdigest()
    assert "payload" not in result.statutes[2]
    assert "source_attributes" not in result.statutes[2]
    assert result.statutes[2]["version_status"] == "UNVERIFIED"


def test_inventory_parse_error_is_unknown_not_zero(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("synthetic parser failure")

    monkeypatch.setattr("klegal_gold.enrichment.corpus_inventory.image_occurrences", fail)
    result = inspect_row(row("<p>본문</p>"), "a" * 64, 0)
    assert result.row["status"] == "ERROR"
    assert result.row["image_occurrences"] is None
    assert result.row["body_images"] is None
    assert result.row["statute_occurrences"] == 0
    assert result.errors[0]["code"] == "IMAGE_OBSERVATION_FAILED"


def test_inventory_atomic_files_hashes_counts_and_source_unchanged(tmp_path):
    rows = [row("<p>본문</p>", 0), row('<img src="/one.gif">', 1), row(None, 2)]
    table = pa.Table.from_pylist(rows).replace_schema_metadata(
        {
            b"legacy": json.dumps({"snapshot_sha256": "a" * 64}).encode(),
        }
    )
    source = tmp_path / "legacy.parquet"
    pq.write_table(table, source)
    before = source.read_bytes()
    output = tmp_path / "inventory"
    result = run_inventory(source, output)
    assert result["totals"]["rows"] == 3
    assert result["totals"]["rows_error"] == 1
    assert result["totals"]["image_target_rows"] == 2
    assert result["distinct_positions"] == 3
    assert result["error_codes"] == {"BODY_NOT_STRING": 1}
    assert len((output / "rows.jsonl").read_text().splitlines()) == 3
    for name, artifact in result["artifacts"].items():
        data = (output / name).read_bytes()
        assert sha256(data).hexdigest() == artifact["sha256"]
        assert len(data) == artifact["bytes"]
    assert source.read_bytes() == before
    assert result["input"]["parquet_sha256"] == sha256(before).hexdigest()
    with pytest.raises(FileExistsError):
        run_inventory(source, output)
    parallel = run_inventory(source, tmp_path / "parallel", processes=2)
    assert parallel["artifacts"] == result["artifacts"]
    assert parallel["totals"] == result["totals"]


def test_invalid_locator_and_missing_body_remain_auditable():
    result = inspect_row(row(123, None), "a" * 64, 45)
    assert result.row["row_ordinal"] == 45
    assert result.row["status"] == "ERROR"
    assert result.row["body_hash"] is None
    assert [error["code"] for error in result.errors] == ["INVALID_ROW_POSITION", "BODY_NOT_STRING"]
