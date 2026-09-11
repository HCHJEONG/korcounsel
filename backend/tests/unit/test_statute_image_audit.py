"""Static image audit guards retain img, srcset and embedded visual references."""

import importlib.util
from hashlib import sha256
from html import escape
from pathlib import Path


def audit_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "audit_legacy_statute_images.py"
    spec = importlib.util.spec_from_file_location("audit_statute_images_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_static_visual_references_and_payload_offsets():
    audit = audit_module()
    payload = (
        '<table><tr><td><IMG src="/flDownload.do?flSeq=1" '
        'srcset="one.png 1x, two.png 2x">'
        '<svg><image href="vector.png"/></svg><picture><source srcset="x.png"></picture>'
        '<span style="background:u&#114;l(bg.png)">내용</span>'
        "<style>.x{background: url(other.png)}</style></td></tr></table>"
    )
    observed = audit.payload_observation(payload, sha256(payload.encode()).hexdigest())
    assert len(observed["images"]) == 1
    assert observed["images"][0]["resolved_url"] == "https://www.law.go.kr/flDownload.do?flSeq=1"
    assert observed["images"][0]["srcset_original"] == "one.png 1x, two.png 2x"
    reasons = {reason for ref in observed["visual_references"] for reason in ref["reasons"]}
    assert reasons == {"VISUAL_ELEMENT", "SRCSET_ATTRIBUTE", "CSS_URL_ATTRIBUTE", "CSS_URL_TEXT"}
    for ref in observed["visual_references"]:
        if "html_start" in ref:
            assert payload[ref["html_start"] : ref["html_end"]] == ref["html_tag"]
    assert audit.payload_observation("일반 조문 내용", sha256(b"plain").hexdigest()) is None


def test_payload_dedup_preserves_every_parent_citation():
    audit = audit_module()
    payload = '<table><tr><td><img src="a.png"></td></tr></table>'
    anchor = '<a name="linkContJomun" jtable="' + escape(payload, quote=True) + '">제1조</a>'
    result = audit.inspect_batch(
        [
            {"__legacy_position": 7, "case_txt_scraped_with_tags": anchor + anchor},
            {"__legacy_position": 9, "case_txt_scraped_with_tags": anchor},
        ]
    )
    assert result["rows"] == 2 and result["nonempty_occurrences"] == 3
    assert len(result["payloads"]) == len(result["payload_hashes"]) == 1
    assert [(r["position"], r["statute_order"]) for r in result["locations"]] == [
        (7, 0),
        (7, 1),
        (9, 0),
    ]
