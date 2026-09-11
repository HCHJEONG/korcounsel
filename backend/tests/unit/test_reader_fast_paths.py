from copy import deepcopy
from html import escape

import pytest

from klegal_gold.documents.observe import observe_html
from klegal_gold.documents.reader import image_occurrences, render_document
from klegal_gold.enrichment.legacy_statutes import statute_occurrences


def test_image_guard_preserves_parser_tag_recognition_and_utf8_contract():
    bodies = [
        "<p>본문😀</p>",
        "<IMG SRC='a.gif'>",
        "<iMg\nname='x'/>",
        "< img src='ignored.gif'>",
        "&lt;img src='escaped.gif'&gt;",
        "<!-- <img src='comment.gif'> -->",
        "<script><img src='script.gif'></script>",
        "<template><img src='template.gif'></template>",
        "<div title='<IMG'>본문</div>",
        "<img",
    ]
    for body in bodies:
        expected = observe_html(body, "https://glaw.scourt.go.kr/", scourt_id="123")["images"]
        refs = image_occurrences(body, source_id="123", base_url="https://glaw.scourt.go.kr/")
        assert len(refs) == len(expected)
        assert all(
            {key: ref[key] for key in item} == item
            for ref, item in zip(refs, expected, strict=True)
        )
    with pytest.raises(UnicodeEncodeError):
        image_occurrences("<p>\ud800</p>", source_id="", base_url="")


def test_preparsed_statutes_keep_exact_output_and_payload_metadata():
    payload = "<table><tr><td>법령</td><td><IMG src='a.gif'></td></tr></table>"
    link = '<a name="linkContJomun" jtable="' + escape(payload, quote=True) + '">제1조</a>'
    body = link * 2 + '<a jtable="not registered">실패</a><a name="linkContJomun">미연결</a>'
    refs = image_occurrences(body, source_id="123", base_url="https://glaw.scourt.go.kr/")
    parsed = statute_occurrences(body)
    for item in parsed:
        if item["payload"]:
            item["payload_artifact_id"] = "legacy-statute:" + item["payload_sha256"]
    before = deepcopy(parsed)
    usual = render_document(body, refs, "a" * 64)
    reused = render_document(body, refs, "a" * 64, parsed_statutes=parsed)
    assert usual == reused
    assert reused.count("<td>법령</td>") == 2
    assert reused.count("이미지 미확보") == 2
    assert 'id="statute-0"' in reused and 'id="statute-1"' in reused
    assert parsed == before
