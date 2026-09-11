import secrets
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from klegal_gold.db.accounts import Accounts
from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.storage.files import FileStore
from klegal_gold.web.app import create_app
from klegal_gold.web.auth import accounts
from klegal_gold.web.reader import reader_store

GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)
ORIGIN = {"origin": "http://127.0.0.1:5173"}


@pytest.fixture
def reader_client(db, tmp_path):
    account_service = Accounts(db)
    password = secrets.token_urlsafe(24)
    account_service.create("reader-test", password)
    records = Records(db, FileStore(tmp_path))
    digest = sha256(GIF).hexdigest()
    records.put_artifact("reader-image:" + digest, GIF, origin="DERIVED", metadata={})
    store = ReaderStore(records)
    url = "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?pgmId=PGP1011M04&jisCntntsSrno=123&atchImgFileNm=a.gif"  # noqa: E501
    html = (
        '<input class="contImagePath" name="a" value="a.gif">'
        + '<p>앞<img name="a">중간<img name="a">뒤<img name="missing"></p>'
    )
    document_id = store.preserve(
        html,
        title="반복 이미지 실제 DB fixture",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={url: {"status": "ACQUIRED", "sha256": digest}},
    )
    app = create_app()
    app.dependency_overrides[accounts] = lambda: account_service
    app.dependency_overrides[reader_store] = lambda: store
    with TestClient(app) as client:
        yield client, password, document_id, store, db


def test_auth_image_bytes_repeat_logout_and_origin(reader_client):
    client, password, document_id, store, db = reader_client
    prefix = "/api/reader/" + document_id
    for path in ["/api/cases/search?q=x", "/api/reader", prefix + "/html", prefix + "/images/0"]:
        assert client.get(path).status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "reader-test", "password": password}
        ).status_code
        == 403
    )
    login = client.post(
        "/api/auth/login", headers=ORIGIN, json={"username": "reader-test", "password": password}
    )
    assert login.status_code == 200
    assert (
        "HttpOnly" in login.headers["set-cookie"]
        and "SameSite=strict" in login.headers["set-cookie"]
    )
    assert client.get("/api/reader").json()[0]["acquired_count"] == 2
    html = client.get(prefix + "/html")
    assert html.status_code == 200 and html.headers["cache-control"] == "no-store"
    assert "sandbox" in html.headers["content-security-policy"]
    assert "이미지 미확보" in html.text
    first = client.get(prefix + "/images/0")
    assert first.content == GIF and first.headers["content-type"] == "image/gif"
    assert client.get(prefix + "/images/1").content == GIF
    assert client.get(prefix + "/images/2").status_code == 404
    manifest = store.read(document_id)
    assert len(manifest["images"]) == 3
    assert (
        client.post(
            "/api/auth/logout", headers={"origin": "https://evil.example"}, json={}
        ).status_code
        == 403
    )
    assert client.get("/api/auth/session").status_code == 200
    assert client.post("/api/auth/logout", headers=ORIGIN, json={}).status_code == 200
    assert client.get(prefix + "/images/0").status_code == 401


def test_expired_and_disabled_sessions(reader_client):
    client, password, document_id, store, db = reader_client
    client.post(
        "/api/auth/login", headers=ORIGIN, json={"username": "reader-test", "password": password}
    )
    with db.connect() as conn:
        conn.execute("UPDATE app_sessions SET expires_at=clock_timestamp()-interval '1 second'")
    assert client.get("/api/reader/" + document_id + "/html").status_code == 401
    client.post(
        "/api/auth/login", headers=ORIGIN, json={"username": "reader-test", "password": password}
    )
    with db.connect() as conn:
        conn.execute("UPDATE app_users SET enabled=false")
    assert client.get("/api/reader").status_code == 401


def test_legacy_route_uses_revision_and_rejects_wrong_row(reader_client, tmp_path, monkeypatch):
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    from klegal_gold.documents.reader import image_occurrences

    client, password, current_id, store, db = reader_client
    body = '<p>앞<img name="a">뒤<a name="linkContJomun" jtable="&lt;table&gt;&lt;tr&gt;&lt;td&gt;조문내용&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;">법1조</a></p>'  # noqa: E501
    digest = sha256(body.encode()).hexdigest()
    table = pa.table(
        {
            "__legacy_position": [7, 8],
            "case_txt_scraped_with_tags": [body, body],
            "gmeta_contId": ["123", "123"],
        }
    )
    table = table.replace_schema_metadata(
        {b"legacy": json.dumps({"snapshot_sha256": "s"}).encode()}
    )
    path = tmp_path / "legacy.parquet"
    pq.write_table(table, path)
    monkeypatch.setenv("LEGACY_PARQUET_PATH", str(path))
    refs = image_occurrences(body, source_id="123", base_url="https://glaw.scourt.go.kr/")
    refs[0].update(
        blob_hash=sha256(GIF).hexdigest(), status="ACQUIRED", link_evidence={"test": True}
    )
    revision = store.preserve(
        body,
        title="기존표본",
        source_id="123",
        origin="LEGACY_CORPUS",
        provenance={"row_position": 7, "snapshot_sha256": "s"},
        acquisitions={},
        linked_images=refs,
    )
    url = f"/api/cases/7/body?body_hash={digest}"
    assert client.get(url).status_code == 401
    client.post(
        "/api/auth/login", headers=ORIGIN, json={"username": "reader-test", "password": password}
    )
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["X-Reader-Revision"] == revision
    assert f"/api/reader/{revision}/images/0" in response.text
    assert "<td>조문내용</td>" in response.text
    assert client.get(url + "&reader_revision=" + revision).text == response.text
    assert (
        client.get(f"/api/cases/8/body?body_hash={digest}&reader_revision={revision}").status_code
        == 409
    )
    assert client.get(url + "&reader_revision=" + current_id).status_code == 409
    assert client.get(url.replace(digest, "0" * 64)).status_code == 409
    assert client.get(f"/api/cases/8/body?body_hash={digest}").status_code == 200
    assert len(store.read(revision)["statutes"]) == 1
