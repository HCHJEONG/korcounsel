"""Version-bound image occurrences and an inert HTML reading representation."""

from __future__ import annotations

from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from typing import Any

from klegal_gold.documents.observe import observe_html

VERSION = "image-reader-1"
TAGS = frozenset(
    "p div span br hr table thead tbody tfoot tr td th caption colgroup col "
    "b strong i em u s sub sup h1 h2 h3 h4 h5 h6 ul ol li dl dt dd blockquote pre".split()
)
VOID = {"br", "hr", "col"}
HIDDEN = {"script", "style", "iframe", "object", "embed", "svg", "math", "template", "noscript"}


def image_occurrences(html: str, *, source_id: str, base_url: str) -> list[dict[str, Any]]:
    """Offsets identify source HTML tags, never normalized text evidence."""
    observation = observe_html(html, base_url, scourt_id=source_id)
    lines = [0]
    for index, char in enumerate(html):
        if char == "\n":
            lines.append(index + 1)
    tags: list[str] = []

    class Tags(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "img":
                tag_text = self.get_starttag_text()
                if tag_text is None:
                    raise ValueError("MISSING_IMAGE_TAG")
                tags.append(tag_text)

    parser = Tags()
    parser.feed(html)
    result = []
    for ref, tag in zip(observation["images"], tags, strict=True):
        line, column = ref["html_line_column"]
        start = lines[line - 1] + column
        end = start + len(tag)
        if html[start:end] != tag:
            raise ValueError("IMAGE_TAG_POSITION_MISMATCH")
        result.append(
            {
                **ref,
                "occurrence_order": ref["order"],
                "html_start": start,
                "html_end": end,
                "html_tag": tag,
                "before": html[max(0, start - 100) : start],
                "after": html[end : end + 100],
                "parent_html_sha256": observation["html_sha256"],
                "reference_id": sha256(
                    f"{observation['html_sha256']}:{start}:{end}".encode()
                ).hexdigest(),
            }
        )
    return result


def render_document(html: str, refs: list[dict[str, Any]], document_id: str) -> str:
    """Render only escaped text, structural allowlist tags and internal image URLs."""
    parent_hash = sha256(html.encode()).hexdigest()
    for ref in refs:
        if (
            ref["parent_html_sha256"] != parent_hash
            or html[ref["html_start"] : ref["html_end"]] != ref["html_tag"]
        ):
            raise ValueError("READER_POSITION_MISMATCH")

    class Renderer(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.output: list[str] = []
            self.order = 0
            self.hidden: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "img":
                ref = refs[self.order]
                self.order += 1
                if self.hidden:
                    return
                name = escape(
                    ref.get("alt") or ref.get("name") or f"본문 이미지 {self.order}", quote=True
                )
                if ref.get("blob_hash"):
                    src = f"/api/reader/{document_id}/images/{ref['order']}"
                    self.output.append(
                        f'<img src="{src}" alt="{name}" data-occurrence="{ref["order"]}">'
                    )
                else:
                    status = {
                        "FAILED": "이미지 취득 실패",
                        "ID_MISMATCH": "이미지 연결 미확정",
                    }.get(str(ref.get("status")), "이미지 미확보")
                    self.output.append(
                        f'<span class="missing-image" role="note">[{status}: {name}]</span>'
                    )
                return
            if tag in HIDDEN:
                if tag != "embed":
                    self.hidden.append(tag)
                return
            if self.hidden or tag not in TAGS:
                return
            safe_attrs = ""
            for key, value in attrs:
                if (
                    key in {"colspan", "rowspan"}
                    and tag in {"td", "th"}
                    and value
                    and value.isdecimal()
                    and 1 <= int(value) <= 100
                ):
                    safe_attrs += f' {key}="{int(value)}"'
            self.output.append(f"<{tag}{safe_attrs}>")

        def handle_endtag(self, tag: str) -> None:
            if self.hidden:
                if tag == self.hidden[-1]:
                    self.hidden.pop()
                return
            if tag in TAGS and tag not in VOID:
                self.output.append(f"</{tag}>")

        def handle_data(self, data: str) -> None:
            if not self.hidden:
                self.output.append(escape(data))

    parser = Renderer()
    parser.feed(html)
    if parser.order != len(refs):
        raise ValueError("READER_IMAGE_COUNT_MISMATCH")
    style = (
        "body{font:17px/1.85 sans-serif;color:#1f2933;margin:24px;overflow-wrap:anywhere}"
        "img{max-width:100%;height:auto}"
        "table{border-collapse:collapse;max-width:100%}"
        "td,th{border:1px solid #ddd;padding:6px}"
        "pre{white-space:pre-wrap}"
        ".missing-image{display:inline-block;border:1px dashed #a77;padding:6px;color:#854}"
    )
    return (
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src &apos;none&apos;; img-src &apos;self&apos;; '
        "style-src &apos;unsafe-inline&apos;; base-uri &apos;none&apos;; "
        'form-action &apos;none&apos;"><title>판례 본문</title><style>'
        + style
        + "</style><body>"
        + "".join(parser.output)
        + "</body></html>"
    )
