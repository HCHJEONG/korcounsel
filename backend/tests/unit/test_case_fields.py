from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from klegal_gold.fields.contract import NAMES
from klegal_gold.fields.extract import extract
from klegal_gold.fields.store import encoded, legacy_fields, parquet_bytes

HTML = (
    "<h2>대법원 2026. 6. 25. 선고 2026두30340 판결</h2><p>【판시사항】</p>"
    "<p>[1] 쟁점</p>"
    "<p>【판결요지】답변</p>"
    "<p>【전 문】</p>"
    "<p>【원고】갑</p>"
    "<p>【원심판결】서울고법</p>"
    "<p>【주 문】기각한다.</p>"
    "<p>【이 유】</p>"
    "<p>첫 문단</p>"
    "<table><tr><td>A</td><td>B</td></tr></table><script>bad()</script>"
)


def run(html=HTML, **kw):
    metadata = {
        "jisCntntsSrno": "123",
        "prnjdgYmd": "20260625",
        "csNoLstCtt": "2026두30340",
        "cortNm": "대법원",
    }
    metadata.update(kw)
    return extract(
        html,
        metadata,
        title="제목",
        source_id="123",
        html_artifact_id="html:1",
        metadata_artifact_id="http:1",
        processed_at="2026-09-15T00:00:00Z",
        lawgo_status="UNMATCHED",
    )


def test_sections_are_bounded_and_source_unchanged():
    fields = run()
    f = {x["name"]: x for x in fields}
    assert len(fields) == 60 and list(f) == NAMES
    assert f["case_txt_scraped_with_tags"]["value"] == HTML
    assert "bad()" not in f["case_txt_in_file"]["value"]
    assert "[1] 쟁점" in f["decision_items"]["value"]
    assert "답변" not in f["decision_items"]["value"]
    assert "갑" not in f["main_decision"]["value"]
    assert "A\tB" in f["reasoning"]["value"]
    assert f["decision_date"]["value"] == "2026-06-25"
    assert f["file_created_time"]["status"] == "NOT_APPLICABLE"
    assert f["repealed_cases"]["status"] == "REVIEW"
    assert f["lmeta_serialno"]["status"] == "NOT_PROVIDED"
    text = f["case_txt_in_file"]["value"]
    start, end = f["decision_items"]["evidence"]["ranges"][0]
    assert text[start:end].strip() == f["decision_items"]["value"]


def test_bad_date_and_repeated_heading_are_not_success():
    f = {x["name"]: x for x in run(HTML + "<p>【주문】다른 주문</p>", prnjdgYmd="20260230")}
    assert f["decision_date"]["status"] == "ERROR"
    assert f["main_decision"]["status"] == "REVIEW"


def test_sixty_column_parquet_roundtrip():
    fields = run()
    raw = parquet_bytes(fields, {"reader_document_id": "a" * 64})
    table = pq.read_table(pa.BufferReader(raw))
    assert table.column_names == NAMES and table.num_rows == 1
    assert table.to_pylist()[0] == {f["name"]: encoded(f["value"], f["name"]) for f in fields}


def test_legacy_values_are_not_reinterpreted(tmp_path):
    row = {n: "no_info" for n in NAMES}
    row["case_txt_scraped_with_tags"] = HTML
    row["__legacy_position"] = 3
    path = tmp_path / "legacy.parquet"
    pq.write_table(pa.Table.from_pylist([row]), path)
    result = legacy_fields(path, 3, sha256(HTML.encode()).hexdigest())
    assert all(f["status"] == "LEGACY_STORED" for f in result["fields"])
    assert result["fields"][1]["value"] == "no_info"
    with pytest.raises(ValueError, match="BODY_VERSION_CHANGED"):
        legacy_fields(path, 3, "0" * 64)


def test_numbered_paragraphs_are_not_section_boundaries():
    html = (
        "<p>【판시사항】</p>"
        "<p>[1] 첫 쟁점</p>"
        "<p>[2] 둘째 쟁점</p>"
        "<p>【이유】</p>"
        "<p>[1] 이유 문단</p>"
        "<p>[관련문헌]후주</p>"
    )
    fields = {f["name"]: f for f in run(html)}
    assert "[2] 둘째 쟁점" in fields["decision_items"]["value"]
    assert "[1] 이유 문단" in fields["reasoning"]["value"]
    assert "후주" not in fields["reasoning"]["value"]
    assert "후주" in fields["related_articles"]["value"]


def test_patent_claims_and_prayer_remain_inside_parent_sections():
    html = (
        "<p>【주문】기각</p>"
        "<p>【청구취지 및 항소취지】청구 내용</p>"
        "<p>【이유】발명</p>"
        "<table><tr><td>【청구항 1】조성물</td></tr></table><p>마지막 판단</p>"
    )
    f = {x["name"]: x for x in run(html)}
    assert "청구 내용" in f["main_decision"]["value"]
    assert "조성물" in f["reasoning"]["value"]
    assert "마지막 판단" in f["reasoning"]["value"]
