"""Complete rejected HTTP bodies survive validation without weakening fetch bounds."""

import io
from datetime import datetime

import pytest

from klegal_gold.assets.images import ImageResponseRejected, fetch_image
from klegal_gold.sources.law_api import _NoRedirect

URL = "https://www.law.go.kr/flDownload.do?flSeq=123"
BAD_HTML = b"<html>\r\n<body>provider failure &amp; detail</body>\r\n</html>"
BROKEN_GIF = b"GIF89a\x01\x00\x01\x00\x80"


def opener_for(monkeypatch, raw, content_type):
    class Response(io.BytesIO):
        headers = {"Content-Type": content_type}

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == URL
            assert timeout == 20
            return Response(raw)

    def build(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], _NoRedirect)
        return Opener()

    monkeypatch.setattr("klegal_gold.assets.images.build_opener", build)


@pytest.mark.parametrize("raw,content_type", [(BAD_HTML, "text/html"), (BROKEN_GIF, "image/gif")])
def test_fetch_rejection_retains_exact_complete_response(monkeypatch, raw, content_type):
    opener_for(monkeypatch, raw, content_type)
    with pytest.raises(ImageResponseRejected, match="IMAGE_DECODE_FAILED") as caught:
        fetch_image(URL)
    response = caught.value.response
    assert response.body == raw
    assert response.content_type == content_type
    assert response.metadata["final_url"] == URL
    assert datetime.fromisoformat(response.metadata["retrieved_at"]).tzinfo is not None
    assert raw.decode("latin1") not in str(caught.value)


def test_oversize_partial_response_is_not_a_quarantinable_decode_failure(monkeypatch):
    opener_for(monkeypatch, BAD_HTML, "text/html")
    with pytest.raises(ValueError, match="IMAGE_TOO_LARGE") as caught:
        fetch_image(URL, max_bytes=4)
    assert not isinstance(caught.value, ImageResponseRejected)
