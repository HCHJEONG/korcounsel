import pytest

from klegal_gold.enrichment.current_lawgo import article_table, exact_metadata, provider_links


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
