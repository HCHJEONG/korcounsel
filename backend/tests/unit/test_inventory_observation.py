import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from klegal_gold.documents.observe import observe_html
from klegal_gold.domain.identity import SourceSystem
from klegal_gold.ingestion.inventory import collect_inventory
from klegal_gold.sources.law_api import Listing, Response
from klegal_gold.sources.scourt import ScourtPortalSource


def resp(data):
    return Response(
        json.dumps(data).encode(),
        200,
        "application/json",
        "https://portal.scourt.go.kr/",
        datetime.now(UTC),
    )


class Source:
    def __init__(self, pages):
        self.pages = iter(pages)

    def list_page(self, **kwargs):
        return next(self.pages)


def listing(ids, total, page=1):
    return Listing(
        resp({}),
        page,
        total,
        tuple({"jisCntntsSrno": i, "cortNm": "법원"} for i in ids),
        "jisCntntsSrno",
    )


def test_bounded_inventory_and_page_commit_are_same_immutable_snapshot():
    saved = []
    result = collect_inventory(
        Source([listing(["1"], 10)]),
        system=SourceSystem.SCOURT,
        scope={"query": ""},
        max_pages=1,
        display=1,
        on_page=saved.append,
    )
    assert result == saved[-1]
    assert result.snapshot.completeness == "PARTIAL"
    assert result.snapshot.source_ids == ("1",)


@pytest.mark.parametrize(
    "second,code",
    [(listing(["1"], 2, 2), "REPEATED_PAGE_IDS"), (listing(["2"], 3, 2), "TOTAL_CHANGED")],
)
def test_partial_inventory_retains_completed_pages(second, code):
    result = collect_inventory(
        Source([listing(["1"], 2), second]),
        system=SourceSystem.SCOURT,
        scope={},
        max_pages=2,
        display=1,
    )
    assert result.snapshot.failed_pages == (f"2:{code}",)
    assert result.snapshot.source_ids == ("1",)
    assert result.snapshot.completeness == "PARTIAL"


def test_all_rows_without_frozen_token_still_unknown():
    result = collect_inventory(
        Source([listing(["1"], 1)]), system=SourceSystem.SCOURT, scope={}, max_pages=2, display=1
    )
    assert result.snapshot.completeness == "UNKNOWN"


def test_scope_changes_hash_and_popularity_does_not_change_metadata():
    results = []
    for score in [1, 99]:
        page = listing(["1"], 1)
        page.rows[0]["gnrlCntntsPopltScor"] = score
        results.append(
            collect_inventory(
                Source([page]),
                system=SourceSystem.SCOURT,
                scope={"q": score},
                max_pages=1,
                display=1,
            ).snapshot
        )
    assert results[0].metadata_hash == results[1].metadata_hash
    assert results[0].scope_hash != results[1].scope_hash


@pytest.mark.parametrize(
    "html,key,expected",
    [
        ('<img src="/a.png">', "images", 1),
        ("<img src='../a.png'>", "images", 1),
        ('<img src="//example.org/a.png">', "images", 1),
        ('<img src="data:image/png;base64,AA">', "images", 1),
        ('<img name="img1">', "images", 1),
        ('<img srcset="a.png 1x, b.png 2x">', "images", 1),
        ('<img alt="표"><img alt="표">', "images", 2),
        ("<table><tr><td>금액 1,000원</td></tr></table>", "tables", 1),
        ('<a jtable="&lt;table&gt;">조문</a>', "legacy_jtables", 1),
        ('<a onclick="linkContJomun(1)">법</a>', "statute_links", 1),
        ('<a onclick="fncLawPop(1)">법</a>', "statute_links", 1),
        ('<a href="/a.pdf">첨부</a>', "pdf_reference_count", 1),
        ("<p>이유만 있는 본문</p>", "images", 0),
        ("<script>secret</script><p>판결</p>", "text_length", 2),
        ("<style>.a{}</style><p>결정</p>", "text_length", 2),
    ],
)
def test_diagnostic_fixture_categories(html, key, expected):
    result = observe_html(html, "https://portal.scourt.go.kr/page/")
    value = result[key]
    assert (len(value) if isinstance(value, list) else value) == expected
    assert result["requires_ocr"] is None
    assert not result["binary_acquired"]


def test_provider_image_mapping_preserves_repeated_positions_and_raw_src_absence():
    html = (
        '<img name="img1"><img name="img1"><input class="contImagePath" name="img1" value="a.gif">'
    )
    images = observe_html(html, "https://portal.scourt.go.kr/", scourt_id="123")["images"]
    assert len(images) == 2
    assert images[0]["original_src"] is None
    assert "atchImgFileNm=a.gif" in images[0]["resolved_url"]
    assert images[0]["resolved_url"] == images[1]["resolved_url"]


def test_conflicting_provider_mapping_is_not_guessed():
    html = (
        '<img name="img1"><input class="contImagePath" name="img1" value="a.gif">'
        '<input class="contImagePath" name="img1" value="b.gif">'
    )
    image = observe_html(html, "https://portal.scourt.go.kr/", scourt_id="123")["images"][0]
    assert image["resolved_url"] is None
    assert image["resolution_failure"] == "AMBIGUOUS_PROVIDER_MAPPING"


@pytest.mark.parametrize(
    "rows,total,code",
    [
        ([], 1, "PARTIAL_PAGE"),
        ([{"jisCntntsSrno": "1"}, {"jisCntntsSrno": "1"}], 2, "DUPLICATE_SOURCE_ID"),
        ([{"jisCntntsSrno": "x"}], 1, "INVALID_SOURCE_ID"),
    ],
)
def test_portal_listing_validation(rows, total, code):
    class Transport:
        def post_listing(self, *args):
            return resp(
                {
                    "status": 200,
                    "data": {"status": "200", "totalCount": str(total), "dlt_jdcpctRslt": rows},
                }
            )

    from klegal_gold.sources.law_api import SourceError

    source = ScourtPortalSource(
        transport=Transport(), preserve=lambda r: None, sleep=lambda _: None
    )
    with pytest.raises(SourceError, match=code):
        source.list_page(page=1, display=2)


def test_observed_source_fixtures_and_image_mapping():
    import hashlib

    from klegal_gold.sources.law_api import SourceError, decode
    from klegal_gold.sources.scourt import portal_data

    fixture = Path(__file__).parents[1] / "fixtures/sources"
    for row in json.loads((fixture / "step3a-manifest.json").read_text()):
        if row.get("sha256"):
            assert hashlib.sha256((fixture / row["file"]).read_bytes()).hexdigest() == row["sha256"]

    def raw(name):
        return Response(
            (fixture / name).read_bytes(),
            200,
            "application/json",
            "https://www.law.go.kr/",
            datetime.now(UTC),
        )

    assert decode(raw("law-list-oc.json"), "PrecSearch", "JSON")["totalCnt"] == "1"
    with pytest.raises(SourceError, match="SOURCE_NOT_FOUND"):
        decode(raw("law-not-found.json"), "PrecService", "JSON")
    with pytest.raises(SourceError, match="SOURCE_NOT_FOUND"):
        portal_data(raw("portal-not-found.json"), "dma_jdcpctDtl", "2061329")
    images = observe_html(
        (fixture / "portal-images-fragment.html").read_text(),
        "https://portal.scourt.go.kr/",
        scourt_id="2029039",
    )["images"]
    assert len(images) == 34
    assert len({img["resolved_url"] for img in images}) == 33
    assert all(img.get("resolution_basis") for img in images)
    assert images[26]["resolved_url"] == images[30]["resolved_url"]


def test_observed_portal_page():
    fixture = Path(__file__).parents[1] / "fixtures/sources"

    class Transport:
        def post_listing(self, *args):
            return Response(
                (fixture / "portal-list-1.json").read_bytes(),
                200,
                "application/json",
                "https://portal.scourt.go.kr/",
                datetime.now(UTC),
            )

    source = ScourtPortalSource(
        transport=Transport(), preserve=lambda _: None, sleep=lambda _: None
    )
    page = source.list_page(page=1, display=1, docket="2017도953")
    assert page.total == 2
    assert page.ids == ("2252318",)
