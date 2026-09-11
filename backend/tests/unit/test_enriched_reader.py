from hashlib import sha256
from html import escape

import pytest

from klegal_gold.assets.images import validate_image
from klegal_gold.documents.image_links import link_legacy_images
from klegal_gold.documents.reader import image_occurrences, render_document
from klegal_gold.enrichment.legacy_statutes import statute_occurrences


def render(html):
    return render_document(
        html,
        image_occurrences(html, source_id="123", base_url="https://glaw.scourt.go.kr/"),
        "a" * 64,
    )


def test_statute_payload_position_status_structure_and_inert_content():
    table = '<table><tr><td rowspan="2">제1조 내용 😀</td></tr></table><script>bad()</script><img src="https://evil.example/x">'  # noqa: E501
    html = (
        '😀앞<p><a name="linkContJomun" jtable="'
        + escape(table, quote=True)
        + '">법 제1조</a>뒤</p>'
    )
    old_hash = sha256(html.encode()).hexdigest()
    articles = statute_occurrences(html)
    assert articles[0]["html_start"] == html.index("<a")
    assert articles[0]["parent_html_sha256"] == old_hash
    assert articles[0]["payload"] == table
    output = render(html)
    assert 'href="#statute-0"' in output and 'href="#citation-0"' in output
    assert '<td rowspan="2">제1조 내용 😀</td>' in output
    assert "적용 버전 미확인" in output
    assert "evil.example" not in output and "bad()" not in output
    assert sha256(html.encode()).hexdigest() == old_hash
    assert output.index("법 제1조") < output.index("뒤") < output.index("제1조 내용")


def test_missing_failure_and_repeated_payloads_remain_distinct():
    html = '<a name="linkContJomun">미연결</a><a jtable="jomun not registered at 법제처">실패</a>'
    html += (
        '<a jtable="&lt;table&gt;&lt;tr&gt;'
        '&lt;td&gt;보존&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;">같음</a>' * 2
    )
    articles = statute_occurrences(html)
    assert [x["status"] for x in articles] == [
        "UNLINKED",
        "LEGACY_FAILURE",
        "PRESERVED",
        "PRESERVED",
    ]
    assert len({x["reference_id"] for x in articles}) == 4
    output = render(html)
    assert "과거 보강 실패: jomun not registered at 법제처" in output
    assert "제공 정보 부재 여부 미확인" in output
    assert output.count("<td>보존</td>") == 2


def test_hidden_and_nested_statute_payloads_do_not_execute_or_recurse():
    html = (
        '<template><a jtable="bad">숨김</a></template>'
        + '<a jtable="&lt;table&gt;&lt;a jtable=evil&gt;안쪽&lt;/a&gt;&lt;/table&gt;">바깥</a>'
    )  # noqa: E501
    assert len(statute_occurrences(html)) == 1
    assert render(html).count('class="statute-item"') == 1
    assert "evil" not in render(html)


def pair():
    before = "앞문맥" * 50
    after = "뒤문맥" * 50
    old = (
        before
        + '<img name="img1" src="https://glaw.scourt.go.kr/wsjo/cm/imgDownload.do?contId=123&amp;attachImgNm=a.gif">'  # noqa: E501
        + after
    )
    new = (
        '<input class="contImagePath" name="img1" value="a.gif">'
        + before
        + '<img name="img1">'
        + after
    )
    current = {
        "source_id": "123",
        "title": "법원 사건 판결",
        "html_sha256": sha256(new.encode()).hexdigest(),
        "images": image_occurrences(new, source_id="123", base_url="https://portal.scourt.go.kr/"),
    }
    current["images"][0].update(status="ACQUIRED", blob_hash="b" * 64)
    return old, new, current


def test_link_requires_context_and_preserves_historical_unknown():
    old, new, current = pair()
    linked = link_legacy_images(old, new, current, source_id="123", title="법원 사건 판결")
    assert linked[0]["blob_hash"] == "b" * 64
    assert linked[0]["link_evidence"]["historical_binary_identity_verified"] is False
    bad = link_legacy_images(
        old.replace("앞문맥", "다른말"), new, current, source_id="123", title="법원 사건 판결"
    )
    assert "blob_hash" not in bad[0]
    with pytest.raises(ValueError, match="IDENTITY"):
        link_legacy_images(old, new, current, source_id="456", title="법원 사건 판결")


def test_truncated_image_header_is_not_a_decoded_image():
    with pytest.raises(ValueError, match="DECODE"):
        validate_image(b"GIF89a\x01\x00\x01\x00")
