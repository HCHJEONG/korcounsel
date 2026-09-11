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
TITLE_VERSION = "image-title-display-3"
# Only display pairs observed in preserved source responses; not registry aliases.
# Evidence from completed waves: docs/legacy-title-display-v3.md.
COURT_DISPLAY_ALIASES = {
    "서울고법": "서울고등법원",
    "서울행법": "서울행정법원",
    "부산지법": "부산지방법원",
    "서울중앙지법": "서울중앙지방법원",
    "서울남부지법": "서울남부지방법원",
    "청주지법": "청주지방법원",
    "대구지법": "대구지방법원",
    "울산지법": "울산지방법원",
    "부산고법": "부산고등법원",
    "수원지법안양지원": "수원지방법원안양지원",
    "수원지법": "수원지방법원",
    "광주지법": "광주지방법원",
    "의정부지법": "의정부지방법원",
    "광주고법": "광주고등법원",
    "대구고법": "대구고등법원",
    "대전지법": "대전지방법원",
    "인천지법": "인천지방법원",
    "서울동부지법": "서울동부지방법원",
    "서울서부지법": "서울서부지방법원",
    "제주지법": "제주지방법원",
    "서울지법": "서울지방법원",
}
TITLE = re.compile(
    r"(?P<court>[^0-9]+)(?P<date>[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}\.)"
    r"(?P<pronouncement>선고|자)(?P<docket>[0-9]{2,4}[가-힣]+[0-9]+)"
    r"(?P<kind>전원합의체판결|전원합의체결정|중간판결|판결|결정|명령|재결)"
    r"(?:(?P<star>[★*])|(?P<provider_suffix>[:：](?:상고기각·확정|상고기각|확정|상고|항소)))?"
)
# Raw spellings observed after 판결; no expansion to arbitrary finality labels.
PROVIDER_DISPLAY_SUFFIXES = frozenset(
    {"：상고", "：확정", "：상고기각·확정", ": 확정", ": 상고", ": 상고기각", ": 항소"}
)
VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)


def _compact(value: str) -> str:
    return "".join(value.split())


def _parse_display_title(value: str) -> dict[str, Any] | None:
    indices = [index for index, character in enumerate(value) if not character.isspace()]
    match = TITLE.fullmatch("".join(value[index] for index in indices))
    if match is None:
        return None
    fields: dict[str, Any] = {key: item or "" for key, item in match.groupdict().items()}
    spans: dict[str, dict[str, Any] | None] = {}
    for key in fields:
        start, end = match.span(key)
        if start < 0 or start == end:
            spans[key] = None
            continue
        raw_start, raw_end = indices[start], indices[end - 1] + 1
        spans[key] = {
            "text": value[raw_start:raw_end],
            "start": raw_start,
            "end": raw_end,
            "index_contract": "Python Unicode codepoint [start,end)",
        }
    suffix = spans["provider_suffix"]
    if suffix is not None:
        suffix["colon_codepoint"] = ord(suffix["text"][0])
    if suffix is not None and (
        fields["kind"] != "판결" or suffix["text"] not in PROVIDER_DISPLAY_SUFFIXES
    ):
        return None
    if fields["star"] == "*" and fields["kind"] not in {"판결", "결정"}:
        return None
    fields["raw_spans"] = spans
    return fields


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
    old = _parse_display_title(title)
    new = _parse_display_title(current["title"])
    if old is None or new is None:
        return None
    old_fields, new_fields = old, new
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
        "legacy_title_sha256": sha256(title.encode()).hexdigest(),
        "current_title_sha256": sha256(current["title"].encode()).hexdigest(),
        "current_html_sha256": current["html_sha256"],
        "legacy_title_field_spans": old_fields["raw_spans"],
        "current_title_field_spans": new_fields["raw_spans"],
        "legacy_court_raw": old_fields["court"],
        "current_court_raw": new_fields["court"],
        "court_display_normalized": old_court,
        "same_date_text": old_fields["date"],
        "same_docket_text": old_fields["docket"],
        "same_disposition_text": old_fields["kind"],
        "legacy_terminal_star": old_fields["star"],
        "current_terminal_star": new_fields["star"],
        "legacy_terminal_star_span": old_fields["raw_spans"]["star"],
        "current_terminal_star_span": new_fields["raw_spans"]["star"],
        "legacy_provider_display_suffix": (
            old_fields["raw_spans"]["provider_suffix"]["text"]
            if old_fields["raw_spans"]["provider_suffix"]
            else ""
        ),
        "current_provider_display_suffix": (
            new_fields["raw_spans"]["provider_suffix"]["text"]
            if new_fields["raw_spans"]["provider_suffix"]
            else ""
        ),
        "legacy_provider_display_suffix_span": old_fields["raw_spans"]["provider_suffix"],
        "current_provider_display_suffix_span": new_fields["raw_spans"]["provider_suffix"],
        "provider_display_suffix_scope": (
            "Provider title annotation only; not a decision key or verified current legal status"
        ),
        "scope": "Display comparison only; no canonical registration or decision-key change",
    }


# This observes one provider display migration; it is not a general image-name normalizer.
NAME_LINK_VERSION = "image-context-link-3"
NAME_VERSION = "image-name-display-1"
NAME_ATTRIBUTE = re.compile(
    r"""\s+([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?"""
)


def _image_name_span(html: str, ref: dict[str, Any]) -> dict[str, Any] | None:
    """Bind a single literal name value to the preserved img tag and document span."""
    start, end = ref.get("html_start"), ref.get("html_end")
    tag = ref.get("html_tag")
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(html)
        or html[start:end] != tag
    ):
        return None
    head = re.match(r"<img\b", tag, re.IGNORECASE)
    if head is None:
        return None
    cursor = head.end()
    names = []
    while match := NAME_ATTRIBUTE.match(tag, cursor):
        cursor = match.end()
        if match[1].lower() != "name":
            continue
        groups = [index for index in (2, 3, 4) if match[index] is not None]
        if len(groups) != 1 or match[groups[0]] != ref.get("name"):
            return None
        name_start, name_end = match.span(groups[0])
        names.append(
            {
                "text": html[start + name_start : start + name_end],
                "start": start + name_start,
                "end": start + name_end,
                "index_contract": "Python Unicode codepoint [start,end)",
            }
        )
    if re.fullmatch(r"\s*/?>", tag[cursor:]) is None or len(names) != 1:
        return None
    return names[0]


def _image_name_evidence(
    html: str,
    current_html: str,
    original: dict[str, Any],
    candidate: dict[str, Any],
    current_hash: str,
) -> dict[str, Any] | None:
    old_name, new_name = original.get("name"), candidate.get("name")
    if not isinstance(old_name, str) or not isinstance(new_name, str):
        return None
    matched = re.fullmatch(r"ImageId([0-9]+)", old_name)
    if matched is None or new_name != "img" + matched[1]:
        return None
    legacy_hash = sha256(html.encode()).hexdigest()
    if (
        sha256(current_html.encode()).hexdigest() != current_hash
        or original.get("parent_html_sha256") != legacy_hash
        or candidate.get("parent_html_sha256") != current_hash
    ):
        return None
    old_span = _image_name_span(html, original)
    new_span = _image_name_span(current_html, candidate)
    if old_span is None or new_span is None:
        return None
    return {
        "version": NAME_VERSION,
        "legacy_name": old_name,
        "current_name": new_name,
        "same_decimal_digits": matched[1],
        "legacy_name_span": old_span,
        "current_name_span": new_span,
        "legacy_html_sha256": legacy_hash,
        "current_html_sha256": current_hash,
        "legacy_reference_id": original["reference_id"],
        "current_reference_id": candidate["reference_id"],
        "legacy_order": original["order"],
        "current_order": candidate["order"],
        "legacy_html_tag": original["html_tag"],
        "current_html_tag": candidate["html_tag"],
        "legacy_tag_start": original["html_start"],
        "legacy_tag_end": original["html_end"],
        "current_tag_start": candidate["html_start"],
        "current_tag_end": candidate["html_end"],
        "scope": "Observed ImageIdN to imgN display only; historical binary identity unverified",
    }


def _name_source_titles(
    html: str, current_html: str, title: str, current_title: str
) -> dict[str, Any] | None:
    """Bind new name links to actual headings even when the declared titles are exact."""
    old_header = _source_title(html, "strong", leading=True)
    new_header = _source_title(current_html, "h2")
    if (
        old_header is None
        or new_header is None
        or _compact(old_header.split("[", 1)[0]) != _compact(title)
        or _compact(new_header) != _compact(current_title)
    ):
        return None
    return {
        "legacy_title": title,
        "current_title": current_title,
        "legacy_title_sha256": sha256(title.encode()).hexdigest(),
        "current_title_sha256": sha256(current_title.encode()).hexdigest(),
        "legacy_header": old_header,
        "current_header": new_header,
        "scope": "Exact source-heading binding; no additional title parsing or decision-key change",
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
    name_titles: dict[str, Any] | None = None
    name_titles_checked = False
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
                    and context == new
                    and min(map(len, context)) >= 30
                ):
                    name_evidence = None
                    if ref.get("name") != candidate.get("name"):
                        if not name_titles_checked:
                            name_titles = _name_source_titles(
                                html, current_html, title, current["title"]
                            )
                            name_titles_checked = True
                        if name_titles is None:
                            continue
                        name_evidence = _image_name_evidence(
                            html, current_html, ref, candidate, current["html_sha256"]
                        )
                        if name_evidence is None:
                            continue
                        name_evidence["source_title_binding"] = name_titles
                    matches.append((candidate, name_evidence))
        if len(matches) == 1 and matches[0][0]["order"] not in used:
            chosen, name_evidence = matches[0]
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
            if name_evidence:
                ref["link_reason"] += (
                    "; observed ImageIdN to imgN with exact numeric token and raw spans"
                )
            ref["link_evidence"] = {
                "version": (
                    NAME_LINK_VERSION
                    if name_evidence
                    else DISPLAY_LINK_VERSION
                    if title_evidence
                    else VERSION
                ),
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
            if name_evidence:
                ref["link_evidence"]["name_comparison"] = name_evidence
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
