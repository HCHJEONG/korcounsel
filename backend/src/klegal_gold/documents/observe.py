"""Diagnostic HTML observations. These hashes/locations are not evidence offsets."""

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

from klegal_gold.domain.common import content_hash


class Observer(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.text: list[str] = []
        self.hidden = 0
        self.images: list[dict[str, Any]] = []
        self.links: list[dict[str, Any]] = []
        self.tables = 0
        self.jtables = 0
        self.pdf_links = 0
        self.image_mappings: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style"}:
            self.hidden += 1
        if "contImagePath" in (values.get("class") or "").split():
            name, filename = values.get("name"), values.get("value")
            if name and filename:
                self.image_mappings.setdefault(name, []).append(filename)
        if tag == "img":
            original = values.get("src")
            resolved = urljoin(self.base, original) if original else None
            if resolved and urlsplit(resolved).scheme not in {"https", "http"}:
                resolved = None
            self.images.append(
                {
                    "order": len(self.images),
                    "original_src": original,
                    "name": values.get("name"),
                    "resolved_url": resolved,
                    "srcset_original": values.get("srcset"),
                    "alt": values.get("alt"),
                    "html_line_column": self.getpos(),
                }
            )
        if tag == "table":
            self.tables += 1
        if values.get("jtable"):
            self.jtables += 1
        if tag == "a":
            target = (values.get("href") or "") + " " + (values.get("onclick") or "")
            if any(x in target for x in ("linkContJomun", "fncLawPop", "lsLinkProc", "joNo=")):
                self.links.append(
                    {
                        "order": len(self.links),
                        "href": values.get("href"),
                        "onclick": values.get("onclick"),
                        "html_line_column": self.getpos(),
                    }
                )
            if ".pdf" in target.lower():
                self.pdf_links += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.text.append(data)


def observe_html(html: str, base: str, *, scourt_id: str | None = None) -> dict[str, Any]:
    parser = Observer(base)
    parser.feed(html)
    for ref in parser.images:
        candidates = parser.image_mappings.get(ref["name"], [])
        ref["provider_mapping_values"] = candidates
        if ref["original_src"] is None and candidates and scourt_id is not None:
            if len(set(candidates)) == 1 and scourt_id.isascii() and scourt_id.isdigit():
                ref["resolved_url"] = (
                    "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?"
                    + urlencode(
                        {
                            "pgmId": "PGP1011M04",
                            "jisCntntsSrno": scourt_id,
                            "atchImgFileNm": candidates[0],
                        }
                    )
                )
                ref["resolution_basis"] = "Observed provider contImagePath name/value mapping"
            else:
                ref["resolution_failure"] = "AMBIGUOUS_PROVIDER_MAPPING"
    text = " ".join(" ".join(parser.text).split())
    return {
        "observation_version": "html-diagnostic-1",
        "html_sha256": content_hash(html.encode()),
        "text_sha256": content_hash(text.encode()),
        "text_length": len(text),
        "images": parser.images,
        "statute_links": parser.links,
        "tables": parser.tables,
        "legacy_jtables": parser.jtables,
        "pdf_reference_count": parser.pdf_links,
        "editorial_markers": {
            k: k in text for k in ("판시사항", "판결요지", "결정요지", "이유", "이 유")
        },
        "requires_ocr": None,
        "binary_acquired": False,
        "scope": "Observed HTML only; text hash is diagnostic, not evidence or semantic equality",
    }
