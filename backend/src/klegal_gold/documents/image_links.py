"""Conservative occurrence links between legacy HTML and a preserved provider response."""

import re
from hashlib import sha256
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit

from klegal_gold.documents.reader import HIDDEN, image_occurrences
from klegal_gold.normalize.decision import decision_kind, docket_aliases

VERSION = "image-context-link-1"
DISPLAY_LINK_VERSION = "image-context-link-2"
TITLE_VERSION = "image-title-display-1"
# Only the three display pairs observed in preserved source responses; not registry aliases.
# Evidence and the six unchanged-docket rows: docs/legacy-reader-title-review.md.
COURT_DISPLAY_ALIASES = {
    "서울고법": "서울고등법원",
    "서울행법": "서울행정법원",
    "부산지법": "부산지방법원",
}
TITLE = re.compile(
    r"(?P<court>[^0-9]+)(?P<date>[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}\.)"
    r"(?P<pronouncement>선고|자)(?P<docket>[0-9]{2,4}[가-힣]+[0-9]+)"
    r"(?P<kind>전원합의체판결|전원합의체결정|중간판결|판결|결정|명령|재결)(?P<star>★?)"
)
VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)


def _compact(value: str) -> str:
    return "".join(value.split())


def _source_title(html: str, tag: str, *, leading: bool = False) -> str | None:
    """Read one plain visible source heading; the legacy strong must precede body text."""

    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.stack: list[tuple[str, bool]] = []
            self.seen_text = False
            self.titles: list[str] = []
            self.parts: list[str] | None = None
            self.depth = 0
            self.invalid = False

        def handle_starttag(self, name: str, attrs: list[tuple[str, str | None]]) -> None:
            hidden = any(item[1] for item in self.stack) or name in HIDDEN
            hidden = hidden or any(
                key == "hidden"
                or (key == "aria-hidden" and value == "true")
                or (
                    key == "style"
                    and value is not None
                    and "display:none" in _compact(value).lower()
                )
                for key, value in attrs
            )
            if self.parts is not None:
                self.invalid = True  # The observed source headings contain text only.
            if name == tag and not hidden and not (leading and self.seen_text):
                if attrs or self.parts is not None:
                    self.invalid = True
                self.parts = []
                self.depth = len(self.stack)
            if name not in VOID_TAGS:
                self.stack.append((name, hidden))

        def handle_endtag(self, name: str) -> None:
            if name == tag and self.parts is not None and len(self.stack) == self.depth + 1:
                self.titles.append("".join(self.parts))
                self.parts = None
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == name:
                    del self.stack[index:]
                    break

        def handle_data(self, data: str) -> None:
            if not any(item[1] for item in self.stack):
                if self.parts is not None:
                    self.parts.append(data)
                if data.strip():
                    self.seen_text = True

    parser = Parser()
    parser.feed(html)
    parser.close()
    if parser.invalid or parser.parts is not None or len(parser.titles) != 1:
        return None
    return parser.titles[0]


def _display_title_evidence(
    html: str, current_html: str, current: dict[str, Any], title: str
) -> dict[str, Any] | None:
    """Corroborate only display differences, without creating or changing decision keys."""
    old = TITLE.fullmatch(_compact(title))
    new = TITLE.fullmatch(_compact(current["title"]))
    if old is None or new is None:
        return None
    old_fields, new_fields = old.groupdict(), new.groupdict()
    old_court = COURT_DISPLAY_ALIASES.get(old_fields["court"], old_fields["court"])
    new_court = COURT_DISPLAY_ALIASES.get(new_fields["court"], new_fields["court"])
    if (
        old_court != new_court
        or any(
            old_fields[key] != new_fields[key]
            for key in ("date", "pronouncement", "docket", "kind")
        )
        or decision_kind(old_fields["kind"]) is None
        or docket_aliases(old_fields["docket"]) != (old_fields["docket"],)
    ):
        return None
    legacy_header = _source_title(html, "strong", leading=True)
    current_header = _source_title(current_html, "h2")
    if (
        legacy_header is None
        or current_header is None
        or _compact(legacy_header.split("[", 1)[0]) != _compact(title)
        or _compact(current_header) != _compact(current["title"])
        or sha256(current_html.encode()).hexdigest() != current["html_sha256"]
    ):
        return None
    return {
        "version": TITLE_VERSION,
        "legacy_html_sha256": sha256(html.encode()).hexdigest(),
        "legacy_header": legacy_header,
        "current_header": current_header,
        "legacy_title": title,
        "current_title": current["title"],
        "legacy_court_raw": old_fields["court"],
        "current_court_raw": new_fields["court"],
        "court_display_normalized": old_court,
        "same_date_text": old_fields["date"],
        "same_docket_text": old_fields["docket"],
        "same_disposition_text": old_fields["kind"],
        "legacy_terminal_star": old_fields["star"],
        "current_terminal_star": new_fields["star"],
        "scope": "Display comparison only; no canonical registration or decision-key change",
    }


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
    if source_id != current["source_id"] or not source_id.isascii() or not source_id.isdigit():
        raise ValueError("IMAGE_DOCUMENT_IDENTITY_UNCONFIRMED")
    title_evidence = None
    if _compact(title) != _compact(current["title"]):
        title_evidence = _display_title_evidence(html, current_html, current, title)
        if title_evidence is None:
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
                "Exact source, source-heading-verified display title, filename/name "
                "and before/after text (120 characters)"
                if title_evidence
                else "Exact source/title, filename/name and before/after text (120 characters)"
            )
            ref["link_evidence"] = {
                "version": DISPLAY_LINK_VERSION if title_evidence else VERSION,
                "current_html_sha256": current["html_sha256"],
                "current_reference_id": chosen["reference_id"],
                "current_order": chosen["order"],
                "provider_mapping_values": chosen["provider_mapping_values"],
                "resolved_url": chosen["resolved_url"],
                "before_text": context[0],
                "after_text": context[1],
                "historical_binary_identity_verified": False,
            }
            if title_evidence:
                ref["link_evidence"]["title_comparison"] = title_evidence
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
