"""Synthetic contexts test the observed ImageIdN -> imgN provider display migration."""

from copy import deepcopy
from hashlib import sha256
from html import escape

import pytest

from klegal_gold.documents.image_links import NAME_LINK_VERSION, VERSION, link_legacy_images
from klegal_gold.documents.reader import image_occurrences

TITLE = "대법원 1996. 10. 11. 선고 95후1944 판결"


def pair(old_names=("ImageId0",), new_names=("img0",), *, current_order=None, new_title=TITLE):
    original = "<strong>" + TITLE + " [사건명]</strong>"
    chunks = []
    for index, (old_name, new_name) in enumerate(zip(old_names, new_names, strict=True)):
        before, after = f"앞문맥{index}" * 60, f"뒷문맥{index}" * 60
        # Repeated name/filename occurrences remain distinct by their surrounding text.
        filename = "a" + (old_name or "missing") + ".gif"
        original += (
            before
            + '<img name="'
            + escape(old_name or "", quote=True)
            + '" src="https://glaw.scourt.go.kr/img?contId=123&amp;attachImgNm='
            + filename
            + '">'
            + after
        )
        chunks.append(
            '<input class="contImagePath" name="'
            + escape(new_name or "", quote=True)
            + '" value="'
            + filename
            + '">'
            + before
            + '<img name="'
            + escape(new_name or "", quote=True)
            + '">'
            + after
        )
    current_html = (
        "<h2>"
        + escape(new_title)
        + "</h2>"
        + "".join(
            chunks[index]
            for index in (current_order if current_order is not None else range(len(chunks)))
        )
    )
    current = {
        "source_id": "123",
        "title": new_title,
        "html_sha256": sha256(current_html.encode()).hexdigest(),
        "images": image_occurrences(
            current_html, source_id="123", base_url="https://portal.scourt.go.kr/"
        ),
    }
    return original, current_html, current


@pytest.mark.parametrize("digits", ["0", "1", "12", "01", "06"])
def test_same_numeric_name_preserves_raw_reference_and_absolute_name_spans(digits):
    old, new, current = pair(("ImageId" + digits,), ("img" + digits,))
    original = image_occurrences(old, source_id="123", base_url="https://glaw.scourt.go.kr/")[0]
    result = link_legacy_images(old, new, current, source_id="123", title=TITLE)[0]
    assert result["name"] == original["name"]
    assert result["original_src"] == original["original_src"]
    assert result["html_tag"] == original["html_tag"]
    assert result["reference_id"] == original["reference_id"]
    proof = result["link_evidence"]
    assert proof["version"] == NAME_LINK_VERSION
    names = proof["name_comparison"]
    assert names["version"] == "image-name-display-1"
    assert names["legacy_name"] == "ImageId" + digits
    assert names["current_name"] == "img" + digits
    assert names["same_decimal_digits"] == digits
    for prefix, html in (("legacy", old), ("current", new)):
        span = names[prefix + "_name_span"]
        assert html[span["start"] : span["end"]] == names[prefix + "_name"] == span["text"]
        assert names[prefix + "_html_sha256"] == sha256(html.encode()).hexdigest()
        assert (
            html[names[prefix + "_tag_start"] : names[prefix + "_tag_end"]]
            == names[prefix + "_html_tag"]
        )
    assert names["legacy_order"] == names["current_order"] == 0
    assert proof["historical_binary_identity_verified"] is False


@pytest.mark.parametrize(
    "old_name,new_name",
    [
        ("ImageId1", "img2"),
        ("imageid1", "img1"),
        ("ImageID1", "img1"),
        ("ImageId1", "IMG1"),
        ("ImageId01", "img1"),
        ("ImageId1", "img01"),
        ("img1", "ImageId1"),
        ("unrelated1", "img1"),
        ("ImageId１", "img1"),
        ("ImageId-1", "img-1"),
        (None, "img0"),
    ],
)
def test_unobserved_prefix_case_digit_or_reverse_mappings_stay_unlinked(old_name, new_name):
    old, new, current = pair((old_name,), (new_name,))
    linked = link_legacy_images(old, new, current, source_id="123", title=TITLE)
    assert "link_evidence" not in linked[0]


@pytest.mark.parametrize(
    "change",
    ["filename", "context", "current_span", "current_hash", "duplicate_name", "encoded_name"],
)
def test_name_migration_does_not_bypass_filename_context_or_raw_span_evidence(change):
    old, new, current = pair()
    if change == "filename":
        current["images"][0]["provider_mapping_values"] = ["different.gif"]
    elif change == "context":
        new = new.replace("앞문맥0", "다른문맥0")
    elif change == "current_span":
        current["images"][0]["html_start"] += 1
    elif change == "current_hash":
        current["html_sha256"] = "a" * 64
    elif change == "duplicate_name":
        old = old.replace('name="ImageId0"', 'name="ImageId0" name="ImageId0"')
    else:
        old = old.replace('name="ImageId0"', 'name="ImageId&#48;"')
    linked = link_legacy_images(old, new, current, source_id="123", title=TITLE)
    assert "link_evidence" not in linked[0]


def test_exact_historical_name_path_keeps_its_previous_link_version():
    old, new, current = pair(("img0",), ("img0",))
    linked = link_legacy_images(old, new, current, source_id="123", title=TITLE)
    assert linked[0]["link_evidence"]["version"] == VERSION
    assert "name_comparison" not in linked[0]["link_evidence"]


def test_repeated_same_numeric_name_requires_distinct_context_and_preserves_order():
    old, new, current = pair(("ImageId0", "ImageId0"), ("img0", "img0"))
    linked = link_legacy_images(old, new, current, source_id="123", title=TITLE)
    assert [ref["link_evidence"]["current_order"] for ref in linked] == [0, 1]
    assert linked[0]["reference_id"] != linked[1]["reference_id"]


def test_duplicate_matching_candidates_are_not_chosen():
    old, new, current = pair()
    current["images"].append(deepcopy(current["images"][0]))
    # The second occurrence has the same candidate context and cannot be arbitrarily selected.
    image = current["images"][0]
    start, end = image["html_start"], image["html_end"]
    before, after = "앞문맥0" * 60, "뒷문맥0" * 60
    new += before + new[start:end] + after
    current["html_sha256"] = sha256(new.encode()).hexdigest()
    current["images"] = image_occurrences(
        new, source_id="123", base_url="https://portal.scourt.go.kr/"
    )
    linked = link_legacy_images(old, new, current, source_id="123", title=TITLE)
    assert "link_evidence" not in linked[0]


def test_name_migration_does_not_allow_reversed_provider_occurrence_order():
    old, new, current = pair(("ImageId0", "ImageId1"), ("img0", "img1"), current_order=[1, 0])
    with pytest.raises(ValueError, match="IMAGE_OCCURRENCE_ORDER_CONFLICT"):
        link_legacy_images(old, new, current, source_id="123", title=TITLE)


def test_name_migration_does_not_bypass_source_or_title_identity():
    old, new, current = pair()
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="124", title=TITLE)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(
            old, new, current, source_id="123", title=TITLE.replace("95후1944", "95후1945")
        )


@pytest.mark.parametrize(
    "heading_change", ["different_h2", "missing_h2", "multiple_h2", "different_strong", "hidden_h2"]
)
def test_new_name_links_require_actual_visible_headings_even_when_declared_titles_match(
    heading_change,
):
    old, new, current = pair()
    if heading_change == "different_h2":
        new = new.replace(TITLE, TITLE.replace("95후1944", "95후1945"))
    elif heading_change == "missing_h2":
        new = new.replace("<h2>", "<p>").replace("</h2>", "</p>")
    elif heading_change == "multiple_h2":
        new += "<h2>" + TITLE + "</h2>"
    elif heading_change == "different_strong":
        old = old.replace(TITLE, TITLE.replace("95후1944", "95후1945"))
    else:
        new = new.replace("<h2>", "<h2 hidden>")
    current["html_sha256"] = sha256(new.encode()).hexdigest()
    current["images"] = image_occurrences(
        new, source_id="123", base_url="https://portal.scourt.go.kr/"
    )
    assert current["title"] == TITLE
    linked = link_legacy_images(old, new, current, source_id="123", title=TITLE)
    assert "link_evidence" not in linked[0]


def test_exact_multi_docket_heading_does_not_require_single_docket_display_parser():
    title = "대법원 1996. 10. 11. 선고 95후1944,95후1945 판결"
    old, new, current = pair()
    old, new = old.replace(TITLE, title), new.replace(TITLE, title)
    current.update(
        title=title,
        html_sha256=sha256(new.encode()).hexdigest(),
        images=image_occurrences(new, source_id="123", base_url="https://portal.scourt.go.kr/"),
    )
    linked = link_legacy_images(old, new, current, source_id="123", title=title)
    assert linked[0]["link_evidence"]["version"] == NAME_LINK_VERSION
    assert "title_comparison" not in linked[0]["link_evidence"]
    binding = linked[0]["link_evidence"]["name_comparison"]["source_title_binding"]
    assert binding["legacy_title"] == binding["current_title"] == title
