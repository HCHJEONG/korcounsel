"""Synthetic image contexts around observed source-title display differences."""

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


# Two additional wave-1 source observations; image contexts remain synthetic fixtures.
OBSERVED_TITLES.extend(
    [
        (
            "서울중앙지방법원 2010. 8. 11. 선고 2010가합2843 판결",
            "서울중앙지법 2010. 8. 11. 선고 2010가합2843 판결",
        ),
        (
            "서울중앙지방법원 2010. 2. 3. 선고 2007가합16309 판결",
            "서울중앙지법 2010. 2. 3. 선고 2007가합16309 판결",
        ),
    ]
)


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


@pytest.mark.parametrize(
    "old_title,new_title",
    [
        (
            "서울중앙지방법원 2010. 2. 3. 선고 2007가합16309 판결",
            "서울중앙지법 2010. 2. 3. 선고 2007가합16309,2007가합16310(병합) 판결",
        ),
        (
            "대전고등법원 2010. 9. 16. 선고 2009나1338 판결",
            "대전고등법원(청주) 2010. 9. 16. 선고 2009나1338 판결",
        ),
        (
            "창원지방법원 2010. 9. 15. 선고 2009가합2682 판결",
            "창원지법 2010. 9. 15. 선고 2009가합2682,3043 판결",
        ),
    ],
)
def test_new_display_alias_still_rejects_joined_dockets_and_cheongju_branch(old_title, new_title):
    old, new, current = pair(old_title, new_title)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=old_title)


# Actual observed title strings through wave 7; surrounding image HTML is synthetic.
OBSERVED_V3_TITLES = [
    (
        4351,
        "서울남부지방법원 2009. 8. 14. 선고 2008가합20578 판결 ",
        "서울남부지법 2009. 8. 14. 선고 2008가합20578 판결",
    ),
    (
        5039,
        "대법원 2009. 5. 28. 선고 2007후3301 판결 * ",
        "대법원 2009. 5. 28. 선고 2007후3301 판결",
    ),
    (
        8924,
        " 대법원 2007. 12. 13. 선고 2005후728 판결 * ",
        "대법원 2007. 12. 13. 선고 2005후728 판결",
    ),
    (
        9710,
        "청주지방법원 2007. 8. 30. 선고 2006고정1457 판결 ",
        "청주지법 2007. 8. 30. 선고 2006고정1457 판결",
    ),
    (
        9820,
        "청주지방법원 2007. 8. 23. 선고 2007고정272 판결 ",
        "청주지법 2007. 8. 23. 선고 2007고정272 판결",
    ),
    (
        10851,
        "대구지방법원 2020. 7. 10. 선고 2018가합209786 판결 ",
        "대구지법 2020. 7. 10. 선고 2018가합209786 판결",
    ),
    (
        12622,
        "울산지방법원 2020. 6. 11. 선고 2018고정60 판결 ",
        "울산지법 2020. 6. 11. 선고 2018고정60 판결",
    ),
    (14206, "대법원 2005. 11. 16.자 2005스26 결정 * ", "대법원 2005. 11. 16.자 2005스26 결정"),
    (
        17193,
        "대법원 2004. 5. 14. 선고 2002다13782 판결 * ",
        "대법원 2004. 5. 14. 선고 2002다13782 판결",
    ),
    (
        17822,
        " 대법원 2003. 12. 26. 선고 2002후2020 판결 * ",
        "대법원 2003. 12. 26. 선고 2002후2020 판결",
    ),
    (
        18658,
        "특허법원 2003. 6. 20. 선고 2003허366 판결 ",
        "특허법원 2003. 6. 20. 선고 2003허366 판결：상고",
    ),
    (
        18704,
        "특허법원 2003. 6. 5. 선고 2002허8349 판결 ",
        "특허법원 2003. 6. 5. 선고 2002허8349 판결：확정",
    ),
    (
        18810,
        "특허법원 2003. 5. 1. 선고 2002허6671 판결 ",
        "특허법원 2003. 5. 1. 선고 2002허6671 판결：상고기각·확정",
    ),
    (
        18837,
        "대법원 2003. 4. 25. 선고 2001후2740 판결 * ",
        "대법원 2003. 4. 25. 선고 2001후2740 판결",
    ),
    (
        18862,
        "특허법원 2003. 4. 25. 선고 2002허8035 판결 ",
        "특허법원 2003. 4. 25. 선고 2002허8035 판결：확정",
    ),
    (
        18932,
        "특허법원 2003. 4. 10. 선고 2002허8172 판결 ",
        "특허법원 2003. 4. 10. 선고 2002허8172 판결：확정",
    ),
    (
        18940,
        "특허법원 2003. 4. 4. 선고 2002허7667 판결 ",
        "특허법원 2003. 4. 4. 선고 2002허7667 판결：확정",
    ),
    (
        19159,
        "특허법원 2003. 1. 24. 선고 2002허6169 판결 ",
        "특허법원 2003. 1. 24. 선고 2002허6169 판결：확정",
    ),
    (
        19187,
        "특허법원 2003. 1. 10. 선고 2002허5708 판결 ",
        "특허법원 2003. 1. 10. 선고 2002허5708 판결：상고기각·확정",
    ),
    (
        19188,
        "특허법원 2003. 1. 9. 선고 2002허4804 판결 ",
        "특허법원 2003. 1. 9. 선고 2002허4804 판결：확정",
    ),
    (
        19402,
        "대법원 2002. 11. 13. 선고 2000후3807 판결 * ",
        "대법원 2002. 11. 13. 선고 2000후3807 판결",
    ),
    (
        19598,
        "특허법원 2002. 10. 11. 선고 2002허2471 판결 ",
        "특허법원 2002. 10. 11. 선고 2002허2471 판결：확정",
    ),
    (
        19935,
        "특허법원 2002. 7. 19. 선고 2001허4777 판결 ",
        "특허법원 2002. 7. 19. 선고 2001허4777 판결：상고",
    ),
    (
        20183,
        "대구지방법원 2019. 11. 8. 선고 2018가단139279 판결 ",
        "대구지법 2019. 11. 8. 선고 2018가단139279 판결",
    ),
    (21153, "대법원 2001. 8. 21. 선고 98후522 판결 * ", "대법원 2001. 8. 21. 선고 98후522 판결"),
    (
        21237,
        "특허법원 2001. 7. 20. 선고 2000허7038 판결 ",
        "특허법원 2001. 7. 20. 선고 2000허7038 판결 : 확정",
    ),
    (
        21249,
        "특허법원 2001. 7. 13. 선고 2000허5551 판결 ",
        "특허법원 2001. 7. 13. 선고 2000허5551 판결 : 상고",
    ),
    (
        21474,
        "특허법원 2001. 5. 24. 선고 2000허6691 판결 ",
        "특허법원 2001. 5. 24. 선고 2000허6691 판결 : 상고기각",
    ),
    (
        22035,
        "부산고등법원 2000. 12. 15. 선고 98나4361 판결 ",
        "부산고법 2000. 12. 15. 선고 98나4361 판결 : 상고기각",
    ),
    (
        23539,
        "대구지방법원 2019. 8. 29. 선고 2018구합25044 판결 ",
        "대구지법 2019. 8. 29. 선고 2018구합25044 판결",
    ),
    (
        25632,
        "수원지방법원안양지원 2019. 7. 4. 선고 2017가단117587 판결 ",
        "수원지법 안양지원 2019. 7. 4. 선고 2017가단117587 판결",
    ),
]


# Wave 8: exact observed unbranched Suwon and Gwangju display pairs.
OBSERVED_V3_TITLES.extend(
    [
        (
            27373,
            "수원지방법원 2018. 6. 14. 선고 2018고합24 판결 ",
            "수원지법 2018. 6. 14. 선고 2018고합24 판결",
        ),
        (
            28915,
            "광주지방법원 2017. 8. 18. 선고 2017고합146 판결 ",
            "광주지법 2017. 8. 18. 선고 2017고합146 판결",
        ),
    ]
)


# Waves 9–13: independently checked CAS headings; image contexts here are synthetic.
OBSERVED_V3_TITLES.extend(
    [
        (
            30903,
            "의정부지방법원 2016. 9. 8. 선고 2016노1619 판결 ",
            "의정부지법 2016. 9. 8. 선고 2016노1619 판결",
        ),
        (
            31744,
            "광주고등법원 2016. 4. 8. 선고 2015나13309 판결 ",
            "광주고법 2016. 4. 8. 선고 2015나13309 판결",
        ),
        (
            32413,
            "대구고등법원 2015. 11. 26. 선고 2015나20484 판결 ",
            "대구고법 2015. 11. 26. 선고 2015나20484 판결",
        ),
        (
            33622,
            "대전지방법원 2015. 4. 9. 선고 2013노3258 판결 ",
            "대전지법 2015. 4. 9. 선고 2013노3258 판결",
        ),
        (
            36088,
            "인천지방법원 2014. 2. 6. 선고 2013구합10155 판결 ",
            "인천지법 2014. 2. 6. 선고 2013구합10155 판결",
        ),
        (
            36484,
            "서울동부지방법원 2013. 12. 10. 선고 2012가합8909 판결 ",
            "서울동부지법 2013. 12. 10. 선고 2012가합8909 판결",
        ),
        (
            39519,
            "서울서부지방법원 2012. 8. 23. 선고 2012노260 판결 ",
            "서울서부지법 2012. 8. 23. 선고 2012노260 판결",
        ),
        (
            42679,
            "제주지방법원 2011. 5. 12. 선고 2009가합3339 판결 ",
            "제주지법 2011. 5. 12. 선고 2009가합3339 판결",
        ),
    ]
)


# Wave 14: historical Seoul District Court, with the exact provider annotation.
OBSERVED_V3_TITLES.append(
    (
        45992,
        "서울지방법원 1996. 9. 12. 선고 92가합19434 판결 ",
        "서울지법 1996. 9. 12. 선고 92가합19434 판결 : 항소",
    )
)


@pytest.mark.parametrize("position,old_title,new_title", OBSERVED_V3_TITLES)
def test_v3_observed_display_pairs_preserve_raw_spans(position, old_title, new_title):
    old, new, current = pair(old_title, new_title)
    linked = link_legacy_images(old, new, current, source_id="123", title=old_title)
    proof = linked[0]["link_evidence"]["title_comparison"]
    assert proof["version"] == "image-title-display-3"
    assert proof["same_docket_text"] and proof["same_disposition_text"]
    for prefix, raw in (("legacy", old_title), ("current", new_title)):
        assert proof[prefix + "_title_sha256"] == sha256(raw.encode()).hexdigest()
        for span in proof[prefix + "_title_field_spans"].values():
            if span:
                assert raw[span["start"] : span["end"]] == span["text"]
                assert span["index_contract"] == "Python Unicode codepoint [start,end)"
        suffix = proof[prefix + "_provider_display_suffix_span"]
        assert proof[prefix + "_provider_display_suffix"] == (suffix["text"] if suffix else "")
        star = proof[prefix + "_terminal_star_span"]
        assert proof[prefix + "_terminal_star"] == (star["text"] if star else "")
    assert "not a decision key" in proof["provider_display_suffix_scope"]
    assert linked[0]["link_evidence"]["historical_binary_identity_verified"] is False
    assert linked[0]["blob_hash"] == "b" * 64


@pytest.mark.parametrize(
    "old_title,new_title",
    [
        (
            "수원지방법원안양지원 2019. 7. 4. 선고 2017가단117587 판결",
            "수원지법 2019. 7. 4. 선고 2017가단117587 판결",
        ),
        (
            "수원지방법원안양지원 2019. 7. 4. 선고 2017가단117587 판결",
            "수원지법 성남지원 2019. 7. 4. 선고 2017가단117587 판결",
        ),
        (
            "수원지방법원성남지원 2019. 7. 4. 선고 2017가단117587 판결",
            "수원지법 성남지원 2019. 7. 4. 선고 2017가단117587 판결",
        ),
        ("대법원 2001. 1. 5.자 98후287 결정", "대법원 2001. 1. 5.자 98후287 심결"),
        (
            "대구지방법원 2007. 6. 28. 선고 2004가합16918 판결",
            "대구지법 2007. 6. 28. 선고 2004가합16918,2007가합6082 판결",
        ),
        (
            "광주고등법원 2009. 10. 28. 선고 2008나7795 판결",
            "광주고등법원 2009. 10. 28. 선고 2008나7795(반소) 판결",
        ),
        (
            "특허법원 2003. 6. 20. 선고 2003허366 판결",
            "특허법원 2003. 6. 20. 선고 2003허366 판결 : 확정됨",
        ),
        (
            "특허법원 2003. 6. 20. 선고 2003허366 판결",
            "특허법원 2003. 6. 20. 선고 2003허366 판결 : 상고기각·확정",
        ),
        (
            "특허법원 2003. 6. 20. 선고 2003허366 판결",
            "특허법원 2003. 6. 20. 선고 2003허366 판결：상고기각",
        ),
        (
            "특허법원 2003. 6. 20. 선고 2003허366 판결",
            "특허법원 2003. 6. 20. 선고 2003허366 판결 : 상 고",
        ),
        (
            "특허법원 2003. 6. 20. 선고 2003허366 판결",
            "특허법원 2003. 6. 20. 선고 2003허366 판결 * : 확정",
        ),
        ("대법원 2005. 11. 16.자 2005스26 결정", "대법원 2005. 11. 16.자 2005스26 결정 : 확정"),
        ("대법원 2005. 11. 16.자 2005스26 결정", "대법원 2005. 11. 16.자 2005스26 결정 **"),
        ("대법원 2005. 11. 16.자 2005스26 결정", "대법원 2005. 11. 16.자 2005스26 * 결정"),
        ("대법원 2005. 11. 16.자 2005스26 명령", "대법원 2005. 11. 16.자 2005스26 명령 *"),
    ],
)
def test_v3_does_not_generalize_unobserved_suffixes_branches_or_decision_kinds(
    old_title, new_title
):
    old, new, current = pair(old_title, new_title)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=old_title)


def test_v3_suffix_still_requires_current_heading_and_hash_agreement():
    old_title = "특허법원 2003. 6. 20. 선고 2003허366 판결"
    new_title = old_title + "：상고"
    old, new, current = pair(old_title, new_title)
    changed = new.replace("：상고", "：확정")
    current["html_sha256"] = sha256(changed.encode()).hexdigest()
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, changed, current, source_id="123", title=old_title)


@pytest.mark.parametrize(
    "old_title,new_title",
    [
        (
            "서울고등법원 2018. 8. 24. 선고 2018노723 판결 ",
            "서울고등법원 2018. 8. 24. 선고 2018노723-1(분리) 판결(주1)",
        ),
        (
            "서울중앙지방법원 2018. 2. 13. 선고 2016고합1202 판결 ",
            "서울중앙지방법원 2018. 2. 13. 선고 2016고합1202-1(분리), 1288-1(병합, 분리), 2017고합"
            "184(병합), 185(병합), 364(병합, 분리), 418-1(병합, 분리) 판결",
        ),
    ],
)
def test_wave8_split_dockets_and_footnotes_are_not_display_suffixes(old_title, new_title):
    old, new, current = pair(old_title, new_title)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=old_title)


@pytest.mark.parametrize(
    "position,old_title,new_title",
    [
        (
            31199,
            "광주고등법원 전주재판부 2016. 7. 21. 선고 2015나100421 판결 ",
            "광주고등법원(전주) 2016. 7. 21. 선고 2015나100421 판결",
        ),
        (
            31285,
            "광주고등법원 2016. 7. 6. 선고 2014나1166 판결 ",
            "광주고법(제주) 2016. 7. 6. 선고 2014나1166 판결",
        ),
        (
            37988,
            "광주고등법원 2013. 4. 25. 선고 2012나2991 판결 ",
            "광주고등법원(전주) 2013. 4. 25. 선고 2012나2991 판결",
        ),
        (
            38854,
            "수원지방법원 2012. 12. 5. 선고 2012고합971 판결 ",
            "수원지방법원 2012. 12. 5. 선고 2012고합971-1(분리) 판결",
        ),
        (
            42193,
            "부산고등법원 2011. 7. 13. 선고 2010나3387 판결 ",
            "부산고법(창원) 2011. 7. 13. 선고 2010나3387, 3394 판결",
        ),
    ],
)
def test_later_wave_branch_and_docket_differences_remain_unconfirmed(
    position, old_title, new_title
):
    old, new, current = pair(old_title, new_title)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=old_title)


@pytest.mark.parametrize(
    "new_title",
    [
        "서울지법 1996. 9. 12. 선고 92가합19434 판결 ：항소",
        "서울지법 1996. 9. 12. 선고 92가합19434 판결 :항소",
        "서울지법 1996. 9. 12. 선고 92가합19434 판결 : 항 소",
        "서울지법 1996. 9. 12. 선고 92가합19434 판결 : 항소기각",
        "서울지법 1996. 9. 12. 선고 92가합19434 판결 : 항소확정",
    ],
)
def test_observed_appeal_annotation_does_not_allow_unobserved_raw_spellings(new_title):
    old_title = "서울지방법원 1996. 9. 12. 선고 92가합19434 판결"
    old, new, current = pair(old_title, new_title)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=old_title)


@pytest.mark.parametrize(
    "old_title,new_title",
    [
        ("대법원 1994. 6. 24. 선고 93후1698 판결 ", "대법원 1994. 6. 24. 선고 93후1698 제3부판결"),
        (
            "서울중앙지방법원 1996. 9. 12. 선고 92가합19434 판결",
            "서울지법 1996. 9. 12. 선고 92가합19434 판결 : 항소",
        ),
        (
            "서울지방법원 1996. 9. 12. 선고 92가합19434 결정",
            "서울지법 1996. 9. 12. 선고 92가합19434 결정 : 항소",
        ),
    ],
)
def test_historical_seoul_alias_and_appeal_annotation_preserve_court_and_kind(old_title, new_title):
    old, new, current = pair(old_title, new_title)
    with pytest.raises(ValueError, match="IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED"):
        link_legacy_images(old, new, current, source_id="123", title=old_title)
