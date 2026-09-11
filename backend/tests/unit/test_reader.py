from hashlib import sha256

import pytest

from klegal_gold.documents.reader import image_occurrences, render_document


def refs(html):
    return image_occurrences(html, source_id="123", base_url="https://portal.scourt.go.kr/")


def test_repeated_images_keep_unicode_tag_offsets_and_table_positions():
    html = '😀앞\n<table><tr><td colspan="2"><img name="a"></td></tr></table>중간<img name="a"/>뒤'
    images = refs(html)
    assert len(images) == 2
    assert images[0]["html_start"] == html.index("<img")
    assert images[1]["html_start"] == html.rindex("<img")
    assert images[0]["reference_id"] != images[1]["reference_id"]
    for ref in images:
        ref["blob_hash"] = "a" * 64
        assert html[ref["html_start"] : ref["html_end"]] == ref["html_tag"]
    result = render_document(html, images, "b" * 64)
    assert result.count('<img src="/api/reader/') == 2
    assert '<td colspan="2"><img' in result
    assert result.index("/images/0") < result.index("중간") < result.index("/images/1")


@pytest.mark.parametrize(
    "markup",
    [
        "<script>alert(1)</script>",
        '<iframe src="https://evil.example"></iframe>',
        "<svg><script>alert(1)</script></svg>",
        '<math><mi href="javascript:alert(1)">x</mi></math>',
        '<object data="https://evil.example"></object>',
        '<embed src="https://evil.example">',
        '<form action="https://evil.example"><input autofocus onfocus="alert(1)"></form>',
        '<a href="javascript:alert(1)">링크</a>',
        '<div style="background:url(https://evil.example)">문단</div>',
        '<img src="//evil.example" onerror="alert(1)">',
        '<img srcset="https://evil.example 2x" src="data:image/svg+xml,evil">',
        '<base href="https://evil.example"><link rel="stylesheet" href="//evil.example">',
        '<template><img src="https://evil.example"></template>',
        '<noscript><img src="//evil.example"></noscript>',
        '<p onclick="alert(1)" id="location">본문 &lt;script&gt;</p>',
    ],
)
def test_unsafe_html_is_inert(markup):
    result = render_document(markup, refs(markup), "a" * 64)
    for fragment in [
        "https://evil.example",
        'src="//',
        "javascript:",
        "onerror=",
        "onclick=",
        "<script",
        "<svg",
        "<math",
        "<iframe",
        "<object",
        "<embed",
        "<form",
        "<base",
        "<link",
    ]:
        assert fragment not in result


def test_missing_failed_and_mismatch_are_visible_at_original_position():
    html = '앞<img name="one">중간<img name="two">뒤<img name="three">'
    images = refs(html)
    images[1]["status"] = "FAILED"
    images[2]["status"] = "ID_MISMATCH"
    rendered = render_document(html, images, "a" * 64)
    assert rendered.index("앞") < rendered.index("이미지 미확보") < rendered.index("중간")
    assert "이미지 취득 실패" in rendered and "이미지 연결 미확정" in rendered
    assert "<img" not in rendered


def test_changed_parent_is_rejected():
    html = '<img name="a">'
    images = refs(html)
    assert images[0]["parent_html_sha256"] == sha256(html.encode()).hexdigest()
    with pytest.raises(ValueError, match="POSITION"):
        render_document(html + "변경", images, "a" * 64)


@pytest.mark.parametrize(
    "origin", ["http://example.com", "https://example.com/path", "https://u@example.com"]
)
def test_cookie_origin_rejects_insecure_or_non_origin_values(origin):
    from pydantic import ValidationError

    from klegal_gold.config import Settings

    with pytest.raises(ValidationError):
        Settings(web_origin=origin)


def test_cookie_origin_accepts_https_and_local_development():
    from klegal_gold.config import Settings

    assert Settings(web_origin="https://korcounsel.com").web_origin == "https://korcounsel.com"
    assert Settings(web_origin="http://127.0.0.1:5173").web_origin == "http://127.0.0.1:5173"
