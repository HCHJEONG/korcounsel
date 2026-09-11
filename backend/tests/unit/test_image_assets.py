import json
from hashlib import sha256

import pytest

from klegal_gold.assets.images import (
    image_metadata,
    references_from_manifest,
    valid_scourt_image_url,
)


def test_manifest_preserves_resolved_name_only_and_id_mismatch():
    payload = {
        "image_references": [
            {
                "source_id": "100",
                "row_position": 7,
                "src": "/old.gif",
                "name": "A.gif",
                "resolved_url": "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?name=A.gif",
            },
            {"source_id": "100", "name": "B.gif"},
            {
                "source_id": "old-cont-id",
                "name": "C.gif",
                "resolved_url": "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?name=C.gif",
                "id_mismatch_reason": "provider mapped through a different contId",
            },
        ]
    }
    raw = json.dumps(payload).encode()
    refs = references_from_manifest(raw)
    assert [ref.reference_status for ref in refs] == ["RESOLVED", "NAME_ONLY", "ID_MISMATCH"]
    assert refs[0].manifest_hash == sha256(raw).hexdigest()
    assert refs[1].resolved_url is None
    assert (
        refs[2].reason
        == "provider image identifier does not match the expected document identifier"
    )


def test_scourt_image_url_allowlist():
    assert valid_scourt_image_url(
        "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?name=x.gif"
    )
    assert not valid_scourt_image_url(
        "https://glaw.scourt.go.kr/wsjo/cm/imgDownload.do?contId=1955787&attachImgNm=x.gif"
    )
    assert not valid_scourt_image_url(
        "http://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?name=x"
    )
    assert not valid_scourt_image_url("https://example.com/pgp/pgp003/downloadImgFile.on?name=x")
    assert not valid_scourt_image_url("https://portal.scourt.go.kr/other?name=x")


def test_image_metadata_accepts_known_headers_and_rejects_html():
    assert image_metadata(b"GIF89a\x01\x00\x02\x00rest") == {
        "format": "GIF",
        "width": 1,
        "height": 2,
    }
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + b"\0\0\0\03\0\0\0\04"
    assert image_metadata(png) == {"format": "PNG", "width": 3, "height": 4}
    with pytest.raises(ValueError, match="UNSUPPORTED_IMAGE_BYTES"):
        image_metadata(b"<html>not an image</html>")
