"""Conservative occurrence links between legacy HTML and a preserved provider response."""

from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit

from klegal_gold.documents.reader import HIDDEN, image_occurrences

VERSION = "image-context-link-1"


def image_contexts(html: str) -> list[tuple[str, str]]:
    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.text = ""
            self.positions: list[int] = []
            self.hidden: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "img":
                self.positions.append(len(self.text))
            if tag in HIDDEN and tag != "embed":
                self.hidden.append(tag)

        def handle_endtag(self, tag: str) -> None:
            if self.hidden and tag == self.hidden[-1]:
                self.hidden.pop()

        def handle_data(self, data: str) -> None:
            if not self.hidden:
                self.text += "".join(data.split())

    parser = Parser()
    parser.feed(html)
    return [(parser.text[max(0, p - 120) : p], parser.text[p : p + 120]) for p in parser.positions]


def link_legacy_images(
    html: str, current_html: str, current: dict[str, Any], *, source_id: str, title: str
) -> list[dict[str, Any]]:
    if (
        source_id != current["source_id"]
        or not source_id.isascii()
        or not source_id.isdigit()
        or "".join(title.split()) != "".join(current["title"].split())
    ):
        raise ValueError("IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED")
    refs = image_occurrences(html, source_id=source_id, base_url="https://glaw.scourt.go.kr/")
    old_context = image_contexts(html)
    new_context = image_contexts(current_html)
    candidates = current["images"]
    used: set[int] = set()
    for ref, context in zip(refs, old_context, strict=True):
        ref["status"] = "ID_MISMATCH"
        ref["link_reason"] = "No unique provider occurrence matching source, filename and context"
        original = urlsplit(ref.get("original_src") or "")
        query = parse_qs(original.query)
        filename = query.get("attachImgNm", [])
        matches = []
        if query.get("contId") == [source_id] and len(filename) == 1:
            for candidate, new in zip(candidates, new_context, strict=True):
                mapping = candidate.get("provider_mapping_values", [])
                if (
                    set(mapping) == set(filename)
                    and ref.get("name") == candidate.get("name")
                    and context == new
                    and min(map(len, context)) >= 30
                ):
                    matches.append(candidate)
        if len(matches) == 1 and matches[0]["order"] not in used:
            chosen = matches[0]
            used.add(chosen["order"])
            ref["status"] = chosen.get("status", "PENDING")
            for key in ("blob_hash", "media_type", "acquisition"):
                if key in chosen:
                    ref[key] = chosen[key]
            ref["link_reason"] = (
                "Exact source/title, filename/name and before/after text (120 characters)"
            )
            ref["link_evidence"] = {
                "version": VERSION,
                "current_html_sha256": current["html_sha256"],
                "current_reference_id": chosen["reference_id"],
                "current_order": chosen["order"],
                "provider_mapping_values": chosen["provider_mapping_values"],
                "resolved_url": chosen["resolved_url"],
                "before_text": context[0],
                "after_text": context[1],
                "historical_binary_identity_verified": False,
            }
        elif not ref.get("original_src"):
            ref["status"] = "PENDING"
            ref["link_reason"] = "Original source has no image URL; provider mapping unconfirmed"
        elif "alert_img_01.png" in original.path:
            ref["status"] = "PENDING"
            ref["link_reason"] = "Legacy provider UI notice image; no preserved bytes"
    linked_orders = [x["link_evidence"]["current_order"] for x in refs if "link_evidence" in x]
    if linked_orders != sorted(linked_orders):
        raise ValueError("IMAGE_OCCURRENCE_ORDER_CONFLICT")
    return refs
