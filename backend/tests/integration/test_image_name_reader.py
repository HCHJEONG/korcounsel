"""PostgreSQL reader preservation/reverification for observed image-name display proofs."""

import json
from copy import deepcopy
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
TITLE = "대법원 1996. 10. 11. 선고 95후1944 판결"
URL = "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?pgmId=PGP1011M04&jisCntntsSrno=123&atchImgFileNm=a.gif"


def stage(records, *, old_title=TITLE, current_title=TITLE):
    reader = ReaderStore(records)
    digest = sha256(GIF).hexdigest()
    records.put_artifact(
        "reader-image:" + digest, GIF, origin="DERIVED", metadata={"kind": "PRESERVED_IMAGE_BYTES"}
    )
    before, after = "앞문맥" * 60, "뒤문맥" * 60
    old = (
        "<strong>"
        + escape(old_title)
        + " [사건명]</strong>"
        + before
        + '<img name="ImageId0" src="https://glaw.scourt.go.kr/img?contId=123&amp;attachImgNm=a.gif">'
        + after
    )
    current_html = (
        "<h2>"
        + escape(current_title)
        + "</h2>"
        + '<input class="contImagePath" name="img0" value="a.gif">'
        + before
        + '<img name="img0">'
        + after
    )
    current = reader.preserve(
        current_html,
        title=current_title,
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
    prior, _ = batch.stage_row(row, "a" * 64, None)
    result, pending = batch.stage_row(row, "a" * 64, current)
    return reader, batch, prior, result, pending, old, current_html


@pytest.mark.parametrize(
    "old_title,current_title",
    [
        (TITLE, TITLE),
        (
            "서울지방법원 1996. 9. 12. 선고 92가합19434 판결",
            "서울지법 1996. 9. 12. 선고 92가합19434 판결 : 항소",
        ),
    ],
)
def test_name_display_reader_revision_keeps_original_name_source_and_prior_revision(
    db, tmp_path, old_title, current_title
):
    records = Records(db, FileStore(tmp_path))
    reader, batch, prior, result, pending, old, current_html = stage(
        records, old_title=old_title, current_title=current_title
    )
    assert pending == [] and result["linked"] == 1
    manifest = batch.verify_reader(result["document_id"])
    assert records.read(manifest["html_artifact_id"]).decode() == old
    ref = manifest["images"][0]
    assert ref["name"] == "ImageId0" and "contId=123" in ref["original_src"]
    assert ref["link_evidence"]["version"] == "image-context-link-3"
    proof = ref["link_evidence"]["name_comparison"]
    for prefix, html in (("legacy", old), ("current", current_html)):
        span = proof[prefix + "_name_span"]
        assert html[span["start"] : span["end"]] == proof[prefix + "_name"]
    if old_title != current_title:
        assert (
            ref["link_evidence"]["title_comparison"]["current_provider_display_suffix"] == ": 항소"
        )
    assert reader.read(prior["document_id"])["images"][0].get("blob_hash") is None
    assert reader.image(result["document_id"], 0)[0] == GIF
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM source_versions").fetchone()["n"] == 0


@pytest.mark.parametrize("mutation", ["digits", "current_span", "legacy_reference"])
def test_name_display_proof_is_recomputed_during_preserve_and_batch_resume(db, tmp_path, mutation):
    records = Records(db, FileStore(tmp_path))
    reader, batch, _, result, _, old, _ = stage(records)
    manifest = deepcopy(reader.read(result["document_id"]))
    proof = manifest["images"][0]["link_evidence"]["name_comparison"]
    if mutation == "digits":
        proof["current_name"] = "img1"
    elif mutation == "current_span":
        proof["current_name_span"]["start"] += 1
    else:
        proof["legacy_reference_id"] = "a" * 64
    with pytest.raises(ValueError, match="INVALID_IMAGE_NAME_LINK"):
        reader.preserve(
            old,
            title=TITLE,
            source_id="123",
            origin="LEGACY_CORPUS",
            provenance=manifest["provenance"],
            acquisitions={},
            linked_images=manifest["images"],
        )
    # Preserve an inconsistent fixture manifest to exercise resume verification.
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
    document_id = sha256(raw).hexdigest()
    records.put_artifact(
        "reader:" + document_id,
        raw,
        origin="DERIVED",
        parent_id=manifest["html_artifact_id"],
        metadata={"kind": "READER_DOCUMENT"},
    )
    with pytest.raises(ValueError, match="INVALID_IMAGE_NAME_LINK"):
        batch.verify_reader(document_id)


def test_name_display_link_is_served_from_general_legacy_body_api(db, tmp_path, monkeypatch):
    import secrets

    import pyarrow as pa
    import pyarrow.parquet as pq
    from fastapi.testclient import TestClient

    from klegal_gold.db.accounts import Accounts
    from klegal_gold.web.app import create_app
    from klegal_gold.web.auth import accounts
    from klegal_gold.web.reader import reader_store

    records = Records(db, FileStore(tmp_path / "artifacts"))
    reader, _, _, result, _, old, _ = stage(records)
    table = pa.table(
        {"__legacy_position": [1], "case_txt_scraped_with_tags": [old], "gmeta_contId": ["123"]}
    ).replace_schema_metadata({b"legacy": json.dumps({"snapshot_sha256": "a" * 64}).encode()})
    parquet_path = tmp_path / "legacy.parquet"
    pq.write_table(table, parquet_path)
    monkeypatch.setenv("LEGACY_PARQUET_PATH", str(parquet_path))
    account_service = Accounts(db)
    password = secrets.token_urlsafe(24)
    account_service.create("image-name-test", password)
    app = create_app()
    app.dependency_overrides[accounts] = lambda: account_service
    app.dependency_overrides[reader_store] = lambda: reader
    with TestClient(app) as client:
        body_url = "/api/cases/1/body?body_hash=" + sha256(old.encode()).hexdigest()
        assert client.get(body_url).status_code == 401
        assert (
            client.post(
                "/api/auth/login",
                headers={"origin": "http://127.0.0.1:5173"},
                json={"username": "image-name-test", "password": password},
            ).status_code
            == 200
        )
        response = client.get(body_url)
        assert response.status_code == 200
        assert response.headers["X-Reader-Revision"] == result["document_id"]
        internal_image = f"/api/reader/{result['document_id']}/images/0"
        assert internal_image in response.text
        assert 'alt="ImageId0"' in response.text
        assert "이미지 연결 미확정" not in response.text and "이미지 미확보" not in response.text
        assert (
            "glaw.scourt.go.kr" not in response.text and "portal.scourt.go.kr" not in response.text
        )
        image = client.get(internal_image)
        assert image.status_code == 200 and image.content == GIF
        assert image.headers["content-type"] == "image/gif"


@pytest.mark.parametrize(
    "old_title,current_title",
    [
        (TITLE, TITLE.replace("1996. 10.", "1996.  10.")),
        (TITLE.replace("1996. 10.", "1996.  10."), TITLE),
    ],
)
def test_compact_equal_name_titles_keep_raw_spacing_on_preserve_and_resume(
    db, tmp_path, old_title, current_title
):
    records = Records(db, FileStore(tmp_path))
    reader, batch, _, result, _, old, _ = stage(
        records, old_title=old_title, current_title=current_title
    )
    manifest = batch.verify_reader(result["document_id"])
    proof = manifest["images"][0]["link_evidence"]
    assert "title_comparison" not in proof
    binding = proof["name_comparison"]["source_title_binding"]
    assert binding["legacy_title"] == old_title
    assert binding["current_title"] == current_title
    assert binding["current_title_sha256"] == sha256(current_title.encode()).hexdigest()
    assert records.read(manifest["html_artifact_id"]).decode() == old
    reader.validate_name_links(old, manifest["images"], title=old_title, source_id="123")


@pytest.mark.parametrize("mutation", ["binding_only", "recomputed_but_unstored_metadata"])
def test_name_title_spacing_proof_rejects_tampered_or_unstored_current_title(
    db, tmp_path, mutation
):
    from klegal_gold.documents.image_links import link_legacy_images

    records = Records(db, FileStore(tmp_path))
    reader, batch, _, result, _, old, current_html = stage(records)
    manifest = reader.read(result["document_id"])
    forged_title = TITLE.replace("1996. 10.", "1996.  10.")
    if mutation == "binding_only":
        links = deepcopy(manifest["images"])
        binding = links[0]["link_evidence"]["name_comparison"]["source_title_binding"]
        binding["current_title"] = forged_title
        binding["current_title_sha256"] = sha256(forged_title.encode()).hexdigest()
    else:
        current = deepcopy(reader.read(manifest["provenance"]["current_reader_id"]))
        current["title"] = forged_title
        # The source h2 is compact-equal; every generated proof field is consistent,
        # but this raw title was never the stored current reader's metadata.
        links = link_legacy_images(old, current_html, current, source_id="123", title=TITLE)
    with pytest.raises(ValueError, match="INVALID_IMAGE_NAME_LINK"):
        reader.validate_name_links(old, links, title=TITLE, source_id="123")
    assert batch.verify_reader(result["document_id"]) == manifest
