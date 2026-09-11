"""Synthetic image contexts around the six observed source-title display differences."""

from hashlib import sha256
from html import escape

import pytest

from klegal_gold.documents.image_links import (
    DISPLAY_LINK_VERSION,
    TITLE_VERSION,
    VERSION,
    link_legacy_images,
)
from klegal_gold.documents.reader import image_occurrences

OBSERVED_TITLES = [
    (
        "서울고등법원 2011. 2. 24. 선고 2010누8326 판결",
        "서울고법 2011. 2. 24. 선고 2010누8326 판결",
    ),
    (
        "대법원 2011. 1. 20. 선고 2009두13474 전원합의체 판결 ★",
        "대법원 2011. 1. 20. 선고 2009두13474 전원합의체 판결",
    ),
    (
        "대법원 2011. 1. 20. 선고 2008도10479 전원합의체 판결 ★",
        "대법원 2011. 1. 20. 선고 2008도10479 전원합의체 판결",
    ),
    (
        "서울행정법원 2010. 12. 24. 선고 2009구합38787 판결",
        "서울행법 2010. 12. 24. 선고 2009구합38787 판결",
    ),
    (
        "부산지방법원 2010. 12. 10. 선고 2009구합5672 판결",
        "부산지법 2010. 12. 10. 선고 2009구합5672 판결",
    ),
    (
        "대법원 2010. 11. 18. 선고 2008두167 전원합의체 판결 ★",
        "대법원 2010. 11. 18. 선고 2008두167 전원합의체 판결",
    ),
]


def pair(
    old_title=OBSERVED_TITLES[0][0],
    new_title=OBSERVED_TITLES[0][1],
    *,
    old_names=("img1",),
    new_names=("img1",),
):
    before, after = "앞 문맥" * 50, "뒤 문맥" * 50
    old = "<div><strong>" + escape(old_title) + " [사건명]〈주제〉 [공2011,1]</strong>"
    new = "<div><h2>" + escape(new_title).replace(" ", "&nbsp;") + "</h2>"
    for name in old_names:
        old += (
            before
            + f'<img name="{name}" src="https://glaw.scourt.go.kr/wsjo/cm/imgDownload.do?contId=123&amp;attachImgNm={name}.gif">'
            + after
        )
    for name in new_names:
        new += (
            f'<input class="contImagePath" name="{name}" value="{name}.gif">'
            + before
            + f'<img name="{name}">'
            + after
        )
    old += "</div>"
    new += "</div>"
    current = {
        "source_id": "123",
        "title": new_title,
        "html_sha256": sha256(new.encode()).hexdigest(),
        "images": image_occurrences(new, source_id="123", base_url="https://portal.scourt.go.kr/"),
    }
    for ref in current["images"]:
        ref.update(status="ACQUIRED", blob_hash="b" * 64)
    return old, new, current


@pytest.mark.parametrize("old_title,new_title", OBSERVED_TITLES)
def test_observed_display_difference_requires_both_source_headings(old_title, new_title):
    old, new, current = pair(old_title, new_title)
    linked = link_legacy_images(old, new, current, source_id="123", title=old_title)
    assert linked[0]["blob_hash"] == "b" * 64
    proof = linked[0]["link_evidence"]
    assert proof["version"] == DISPLAY_LINK_VERSION
    assert proof["historical_binary_identity_verified"] is False
    title_proof = proof["title_comparison"]
    assert title_proof["version"] == TITLE_VERSION
    assert title_proof["legacy_html_sha256"] == sha256(old.encode()).hexdigest()
    assert title_proof["legacy_title"] == old_title
    assert title_proof["current_title"] == new_title
    assert title_proof["legacy_header"].startswith(old_title)
    assert " ".join(title_proof["current_header"].split()) == new_title


@pytest.mark.parametrize(
    "new_title",
    [
        "부산고법 2011. 2. 24. 선고 2010누8326 판결",
        "서울지법 2011. 2. 24. 선고 2010누8326 판결",
        "서울고법(제주) 2011. 2. 24. 선고 2010누8326 판결",
        "서울고법 2011. 2. 25. 선고 2010누8326 판결",
        "서울고법 2011. 2. 24. 선고 2010누8327 판결",
        "서울고법 2011. 2. 24. 선고 2010누8326 결정",
        "서울고법 2011. 2. 24. 선고 2010누8326 중간판결",
        "서울고법 2011. 2. 24. 선고 2010누8326 전원합의체 판결",
        "서울고법 2011. 2. 24. 자 2010누8326 판결",
        "서울고법 2011. 2. 24. 선고 2010누8326,2010누8327 판결",
        "서울고법 2011. 2. 24. 선고 2010누8326(본소),2010누8327(반소) 판결",
        "서울고법 2011. 2. 24. 선고 2010누8326 판결 ★★",
        "서울고법 2011. 2. 24. 선고 2010누8326 ★ 판결",
    ],
)
def test_same_source_id_does_not_relax_court_date_docket_or_kind(new_title):
    old, new, current = pair(new_title=new_title)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=OBSERVED_TITLES[0][0])


@pytest.mark.parametrize(
    "old_title,new_title",
    [
        (
            "부산고등법원 2011. 2. 10. 선고 2010나897 판결",
            "부산고등법원 2011. 2. 10. 선고 2010나897(본소),2010나903(반소) 판결",
        ),
        (
            "서울고등법원 2011. 2. 10. 선고 2009나119131 판결",
            "서울고등법원 2011. 2. 10. 선고 2009나119131,2009나119148(병합) 판결",
        ),
        (
            "서울고등법원 2010. 12. 30. 선고 2010나25263 판결",
            "서울고등법원 2010. 12. 30. 선고 "
            "2010나25263(본소),2010나25270(반소),2010나25287(반소) 판결",
        ),
        (
            "수원지방법원 성남지원 2010. 12. 1. 선고 2009가합17130 판결",
            "수원지방법원 성남지원 2010. 12. 1. 선고 2009가합17130(본소),2010가합7740(반소) 판결",
        ),
        (
            "서울중앙지방법원 2010. 11. 29. 선고 2008가합124238 판결",
            "서울중앙지방법원 2010. 11. 29. 선고 2008가합124238,2010가합53780(병합) 판결",
        ),
        (
            "광주고등법원 2010. 12. 22. 선고 2010나110 판결",
            "광주고등법원(제주) 2010. 12. 22. 선고 2010나110(본소),2010나127(반소) 판결",
        ),
    ],
)
def test_extra_merged_or_counterclaim_dockets_and_jeju_are_still_rejected(old_title, new_title):
    old, new, current = pair(old_title, new_title)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=old_title)


@pytest.mark.parametrize(
    "failure",
    [
        "old_header",
        "current_header",
        "current_hash",
        "old_missing",
        "current_missing",
        "old_hidden",
        "current_hidden",
        "duplicate_h2",
        "preceding_text",
        "source_id",
    ],
)
def test_display_normalization_requires_unambiguous_source_header_evidence(failure):
    old, new, current = pair()
    if failure == "old_header":
        old = old.replace("2010누8326", "2010누9999")
    elif failure == "current_header":
        new = new.replace("2010누8326", "2010누9999")
    elif failure == "current_hash":
        current["html_sha256"] = "0" * 64
    elif failure == "old_missing":
        old = old.replace("strong", "p")
    elif failure == "current_missing":
        new = new.replace("h2", "p")
    elif failure == "old_hidden":
        old = old.replace("<div>", "<div hidden>", 1)
    elif failure == "current_hidden":
        new = new.replace("<div>", "<div style='display: none'>", 1)
    elif failure == "duplicate_h2":
        new = new.replace("</h2>", "</h2><h2>다른 사건</h2>", 1)
    elif failure == "preceding_text":
        old = "<p>먼저 본문이 있는 경우</p>" + old
    elif failure == "source_id":
        current["source_id"] = "124"
    if failure != "current_hash":
        current["html_sha256"] = sha256(new.encode()).hexdigest()
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=OBSERVED_TITLES[0][0])


@pytest.mark.parametrize("failure", ["context", "filename", "name", "image_contid"])
def test_display_normalization_preserves_image_occurrence_constraints(failure):
    old, new, current = pair()
    if failure == "context":
        old = old.replace("앞 문맥", "다른 내용")
    elif failure == "filename":
        old = old.replace("img1.gif", "other.gif")
    elif failure == "name":
        old = old.replace('name="img1"', 'name="other"')
    elif failure == "image_contid":
        old = old.replace("contId=123", "contId=124")
    linked = link_legacy_images(old, new, current, source_id="123", title=OBSERVED_TITLES[0][0])
    assert linked[0]["status"] == "ID_MISMATCH"
    assert "link_evidence" not in linked[0] and "blob_hash" not in linked[0]


def test_duplicate_current_occurrences_are_not_selected_arbitrarily():
    old, new, current = pair(new_names=("img1", "img1"))
    linked = link_legacy_images(old, new, current, source_id="123", title=OBSERVED_TITLES[0][0])
    assert "link_evidence" not in linked[0]


def test_one_current_occurrence_cannot_be_reused_for_repeated_legacy_positions():
    old, new, current = pair(old_names=("img1", "img1"))
    linked = link_legacy_images(old, new, current, source_id="123", title=OBSERVED_TITLES[0][0])
    assert sum("link_evidence" in ref for ref in linked) == 1


def test_reversed_unique_provider_occurrence_order_is_rejected():
    old, new, current = pair(old_names=("img1", "img2"), new_names=("img2", "img1"))
    with pytest.raises(ValueError, match="IMAGE_OCCURRENCE_ORDER_CONFLICT"):
        link_legacy_images(old, new, current, source_id="123", title=OBSERVED_TITLES[0][0])


def test_exact_title_links_keep_the_existing_rule_and_evidence_shape():
    title = OBSERVED_TITLES[0][0]
    old, new, current = pair(title, title)
    linked = link_legacy_images(old, new, current, source_id="123", title=title)
    assert linked[0]["link_evidence"]["version"] == VERSION
    assert "title_comparison" not in linked[0]["link_evidence"]
