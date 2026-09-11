"""Display-title v3 creates immutable reader revisions without changing identity checks."""

from hashlib import sha256
from html import escape

import pytest

from klegal_gold.db.records import Records
from klegal_gold.documents.legacy_batch import LegacyReaderBatch
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)
URL = (
    "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on"
    "?pgmId=PGP1011M04&jisCntntsSrno=123&atchImgFileNm=a.gif"
)


@pytest.mark.parametrize(
    "old_title,new_title",
    [
        (
            "부산고등법원 2000. 12. 15. 선고 98나4361 판결",
            "부산고법 2000. 12. 15. 선고 98나4361 판결 : 상고기각",
        ),
        (
            "수원지방법원안양지원 2019. 7. 4. 선고 2017가단117587 판결",
            "수원지법 안양지원 2019. 7. 4. 선고 2017가단117587 판결",
        ),
        ("대법원 2005. 11. 16.자 2005스26 결정 *", "대법원 2005. 11. 16.자 2005스26 결정"),
        (
            "특허법원 2003. 5. 1. 선고 2002허6671 판결",
            "특허법원 2003. 5. 1. 선고 2002허6671 판결：상고기각·확정",
        ),
        (
            "의정부지방법원 2016. 9. 8. 선고 2016노1619 판결 ",
            "의정부지법 2016. 9. 8. 선고 2016노1619 판결",
        ),
        (
            "광주고등법원 2016. 4. 8. 선고 2015나13309 판결 ",
            "광주고법 2016. 4. 8. 선고 2015나13309 판결",
        ),
        (
            "대구고등법원 2015. 11. 26. 선고 2015나20484 판결 ",
            "대구고법 2015. 11. 26. 선고 2015나20484 판결",
        ),
        (
            "대전지방법원 2015. 4. 9. 선고 2013노3258 판결 ",
            "대전지법 2015. 4. 9. 선고 2013노3258 판결",
        ),
        (
            "인천지방법원 2014. 2. 6. 선고 2013구합10155 판결 ",
            "인천지법 2014. 2. 6. 선고 2013구합10155 판결",
        ),
        (
            "서울동부지방법원 2013. 12. 10. 선고 2012가합8909 판결 ",
            "서울동부지법 2013. 12. 10. 선고 2012가합8909 판결",
        ),
        (
            "서울서부지방법원 2012. 8. 23. 선고 2012노260 판결 ",
            "서울서부지법 2012. 8. 23. 선고 2012노260 판결",
        ),
        (
            "제주지방법원 2011. 5. 12. 선고 2009가합3339 판결 ",
            "제주지법 2011. 5. 12. 선고 2009가합3339 판결",
        ),
        (
            "서울지방법원 1996. 9. 12. 선고 92가합19434 판결 ",
            "서울지법 1996. 9. 12. 선고 92가합19434 판결 : 항소",
        ),
    ],
)
def test_v3_stage_preserves_raw_titles_body_and_display_annotation(
    db, tmp_path, old_title, new_title
):
    records = Records(db, FileStore(tmp_path))
    reader = ReaderStore(records)
    digest = sha256(GIF).hexdigest()
    records.put_artifact(
        "reader-image:" + digest,
        GIF,
        origin="DERIVED",
        metadata={"kind": "PRESERVED_IMAGE_BYTES"},
    )
    before, after = "앞문맥" * 60, "뒤문맥" * 60
    old = (
        "<strong>"
        + escape(old_title)
        + " [사건명]</strong>"
        + before
        + '<img name="img1" src="https://glaw.scourt.go.kr/img?contId=123&amp;attachImgNm=a.gif">'
        + after
    )
    current_html = (
        "<h2>"
        + escape(new_title)
        + "</h2>"
        + '<input class="contImagePath" name="img1" value="a.gif">'
        + before
        + '<img name="img1">'
        + after
    )
    current = reader.preserve(
        current_html,
        title=new_title,
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={URL: {"status": "ACQUIRED", "sha256": digest}},
    )
    row = {
        "__legacy_position": 1,
        "__legacy_index": "1",
        "case_txt_scraped_with_tags": old,
        "case_full_no": old_title,
        "gmeta_contId": "123",
        "lmeta_serialno": "456",
    }
    batch = LegacyReaderBatch(records)
    base, _ = batch.stage_row(row, "a" * 64, None)
    staged, pending = batch.stage_row(row, "a" * 64, current)
    assert pending == [] and staged["linked"] == 1
    assert staged["document_id"] != base["document_id"]
    manifest = batch.verify_reader(staged["document_id"])
    evidence = manifest["images"][0]["link_evidence"]["title_comparison"]
    assert evidence["version"] == "image-title-display-3"
    assert evidence["legacy_title"] == old_title.strip() and evidence["current_title"] == new_title
    assert evidence["legacy_header"] == old_title + " [사건명]"
    assert records.read(manifest["html_artifact_id"]).decode() == old
    assert reader.read(base["document_id"])["images"][0].get("blob_hash") is None
    assert reader.image(staged["document_id"], 0)[0] == GIF
    if any(mark in new_title for mark in ("상고", "항소")):
        span = evidence["current_provider_display_suffix_span"]
        assert new_title[span["start"] : span["end"]] == evidence["current_provider_display_suffix"]
        assert evidence["same_disposition_text"] == "판결"
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM source_versions").fetchone()["n"] == 0
