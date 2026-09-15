import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from klegal_gold.enrichment.current_lawgo import (
    article_table,
    exact_metadata,
    provider_links,
    source_identity,
)

OBSERVED = json.loads(
    (Path(__file__).parents[1] / "fixtures/lawgo_full_docket_35.json").read_text()
)


@pytest.mark.parametrize("case", OBSERVED, ids=lambda c: c["source_id"])
def test_preserved_full_metadata_resolves_observed_conflicts(case):
    records = Mock()
    records.read.return_value = json.dumps(
        {"data": {"dma_jdcpctDtl": case["source_metadata"]}}
    ).encode()
    original = {"source_id": case["source_id"], "provenance": case["provenance"]}
    p = source_identity(records, original)
    records.read.assert_called_once_with("http:" + case["metadata_hash"])
    assert "full_case_number" not in original["provenance"]
    assert not exact_metadata(case["provenance"], case["candidate"])
    assert exact_metadata(p, case["candidate"], detail=True)
    for key, value in (
        ("법원명", "다른법원"),
        ("사건번호", p["case_number"]),
        ("판결유형", "명령"),
        ("선고일자", "19990101"),
    ):
        assert not exact_metadata(p, {**case["candidate"], key: value}, detail=True)
    records.read.return_value = json.dumps(
        {"data": {"dma_jdcpctDtl": {**case["source_metadata"], "jisCntntsSrno": "wrong"}}}
    ).encode()
    with pytest.raises(ValueError, match="SCOURT_IDENTITY_EVIDENCE_MISMATCH"):
        source_identity(records, original)


def test_role_and_region_are_not_erased():
    p = {
        "court": "부산고등법원",
        "case_number": "2023나11053",
        "full_case_number": "(울산)2023나11053",
        "decision_type": "판결",
        "decision_date": "20240101",
    }
    row = {
        "법원명": p["court"],
        "사건번호": "(부산)2023나11053",
        "판결유형": "판결",
        "선고일자": "20240101",
    }
    assert not exact_metadata(p, row, detail=True)
    p["full_case_number"] = "2023나11053(본소), 2023나11054(반소)"
    row["사건번호"] = "2023나11053(반소), 2023나11054(본소)"
    assert not exact_metadata(p, row, detail=True)


def test_only_explicit_provider_calls_are_selected():
    html = """<input id="precYd" value="20170413">
    <a onclick="javascript:fncLawPop('형법','JO','024600','prec');">형법 제246조</a>
    <a>형법 제355조</a><a onclick="evil()">형법 제356조</a>"""
    day, links = provider_links(html)
    assert day == "20170413"
    assert len(links) == 1
    assert links[0]["article"] == "024600"
    assert links[0]["text"] == "형법 제246조"
    with pytest.raises(ValueError, match="STRUCTURE_CHANGED"):
        provider_links("<html>error</html>")


def test_metadata_requires_all_dockets_branch_kind_and_date():
    provenance = {
        "court": "서울지방법원 동부지원",
        "case_number": "2000가합1, 2",
        "decision_type": "판결",
        "decision_date": "20000101",
    }
    row = {
        "법원명": "서울지방법원 동부지원",
        "사건번호": "2000가합1, 2000가합2",
        "판결유형": "판결",
        "선고일자": "2000-01-01",
    }
    assert exact_metadata(provenance, row)
    for key, wrong in (
        ("법원명", "서울지방법원"),
        ("사건번호", "2000가합1"),
        ("판결유형", "결정"),
        ("선고일자", "2000-02-01"),
    ):
        assert not exact_metadata(provenance, {**row, key: wrong})


def test_article_structure_cannot_be_http_success_only():
    for html in (
        "<html>error</html>",
        '<table summary="조문정보"><tbody id="lsLinkTable"></tbody></table>',
    ):
        with pytest.raises(ValueError):
            article_table(html)
    html = (
        '<table summary="조문정보"><tbody id="lsLinkTable">'
        "<tr><td>제246조 내용</td></tr></tbody></table>"
    )
    assert article_table(html) == html


@pytest.mark.parametrize(
    "court,branch,docket,day",
    [
        ("춘천지방법원", "강릉지원", "2023나31881", "20240903"),
        ("수원지방법원", "여주지원", "2024고단43", "20240910"),
        ("인천지방법원", "부천지원", "2023가단109994", "20240911"),
        ("춘천지방법원", "강릉지원", "2024노158", "20241212"),
    ],
)
def test_branch_display_whitespace_does_not_create_conflict(court, branch, docket, day):
    # Real observed name pairs; date is synthetic where not material to this regression.
    provenance = {
        "court": court + branch,
        "case_number": docket,
        "decision_type": "판결",
        "decision_date": day,
    }
    candidate = {
        "법원명": court + " " + branch,
        "사건번호": docket,
        "판결유형": "판결",
        "선고일자": day,
    }
    assert exact_metadata(provenance, candidate)
    assert provenance["court"] == court + branch
    assert candidate["법원명"] == court + " " + branch
    for changed in (
        {"법원명": court},
        {"법원명": court + " 다른지원"},
        {"사건번호": docket + ", 999999"},
        {"판결유형": "결정"},
        {"선고일자": "19990101"},
    ):
        assert not exact_metadata(provenance, {**candidate, **changed})


def test_whitespace_only_court_is_not_exact():
    assert not exact_metadata(
        {
            "court": " \t",
            "case_number": "2024다1",
            "decision_type": "판결",
            "decision_date": "20240101",
        },
        {"법원명": " ", "사건번호": "2024다1", "판결유형": "판결", "선고일자": "20240101"},
    )


def test_http_200_provider_error_page_is_not_an_article_structure_change():
    from klegal_gold.quality.checks import transient

    # Minimal fixture of the saved 1953 Pharmaceutical Affairs Act response.
    html = (
        '<html><title>국가법령정보센터 | 오류페이지</title><div id="error500">'
        "현재 사용자가 많아 요청하신 페이지를 정상적으로 제공할 수 없습니다."
        "</div></html>"
    )
    with pytest.raises(ValueError, match="^LAWGO_SERVICE_UNAVAILABLE$"):
        article_table(html)
    assert transient("LAWGO_SERVICE_UNAVAILABLE")
    # A script-only law popup and arbitrary markup are still non-transient.
    for other in (
        '<input id="lnkLsId" value="001783"><script>openPop(url)</script>',
        '<div id="error500">unrecognized response</div>',
    ):
        with pytest.raises(ValueError, match="^LAWGO_ARTICLE_STRUCTURE_CHANGED$"):
            article_table(other)


@pytest.mark.parametrize("context,expected", [("prec", "20110310"), ("prec20100514", "20100514")])
def test_provider_selected_date_is_not_replaced(context, expected):
    from klegal_gold.enrichment.current_lawgo import provider_article_params

    html = f"""<input id="precYd" value="20110310">
    <a onclick="javascript:fncLawPop('법','JO','003600','{context}');">법 제36조</a>"""
    day, links = provider_links(html)
    assert links[0]["provider_context"] == context
    params = provider_article_params(links[0], day)
    assert params["lsId"] == "prec" + expected and params["efYd"] == expected
    assert provider_article_params({"law_name": "법", "article": "003600"}, day)["efYd"] == day


@pytest.mark.parametrize(
    "context", ["prec20101301", "prec20100230", "prec2010", "detc20100514", "prec20100514');evil('"]
)
def test_invalid_or_unobserved_context_is_not_requested(context):
    html = f"""<input id="precYd" value="20110310">
    <a onclick="javascript:fncLawPop('법','JO','003600','{context}');">법 제36조</a>"""
    assert provider_links(html)[1] == []
