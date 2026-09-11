import io
from urllib.error import HTTPError

import pytest

from klegal_gold.assets.images import fetch_image, valid_lawgo_image_url
from klegal_gold.sources.law_api import _NoRedirect

GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


@pytest.mark.parametrize("host", ["law.go.kr", "www.law.go.kr"])
def test_lawgo_image_endpoint_allows_only_observed_https_file_key(host):
    assert valid_lawgo_image_url(f"https://{host}/flDownload.do?flSeq=6238586")


@pytest.mark.parametrize(
    "url",
    [
        "http://www.law.go.kr/flDownload.do?flSeq=6238586",
        "https://www.law.go.kr.evil.example/flDownload.do?flSeq=6238586",
        "https://user@www.law.go.kr/flDownload.do?flSeq=6238586",
        "https://www.law.go.kr:444/flDownload.do?flSeq=6238586",
        "https://www.law.go.kr/other?flSeq=6238586",
        "https://www.law.go.kr/flDownload.do?flSeq=6238586&other=1",
        "https://www.law.go.kr/flDownload.do?flSeq=1&flSeq=2",
        "https://www.law.go.kr/flDownload.do?flSeq=",
        "https://www.law.go.kr/flDownload.do?flSeq=-1",
        "https://www.law.go.kr/flDownload.do?flSeq=１２",
        "https://www.law.go.kr/flDownload.do?flSeq=abc",
        "https://www.law.go.kr/flDownload.do?flSeq=1#fragment",
        "https://www.law.go.kr/flDownload.do;extra?flSeq=1",
    ],
)
def test_lawgo_image_rejects_arbitrary_urls_before_open(monkeypatch, url):
    assert not valid_lawgo_image_url(url)
    monkeypatch.setattr(
        "klegal_gold.assets.images.build_opener", lambda *args: pytest.fail("opened")
    )
    with pytest.raises(ValueError, match="UNSAFE_IMAGE_URL"):
        fetch_image(url)


def test_lawgo_fetch_decodes_without_enabling_redirects(monkeypatch):
    url = "https://www.law.go.kr/flDownload.do?flSeq=6238586"
    calls = []

    class Response(io.BytesIO):
        headers = {"Content-Type": "image/gif"}

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            assert timeout == 20
            return Response(GIF)

    def build(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], _NoRedirect)
        return Opener()

    monkeypatch.setattr("klegal_gold.assets.images.build_opener", build)
    result = fetch_image(url)
    assert result.body == GIF and result.metadata["decode_verified"]
    assert result.metadata["final_url"] == url
    assert calls == [url]

    class Redirect:
        def open(self, request, timeout):
            raise HTTPError(url, 302, "redirect", {}, None)

    monkeypatch.setattr("klegal_gold.assets.images.build_opener", lambda *args: Redirect())
    with pytest.raises(ValueError, match="HTTP_302"):
        fetch_image(url)
