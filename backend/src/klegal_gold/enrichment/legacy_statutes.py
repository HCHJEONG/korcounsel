"""Observe legacy lawgo payloads without altering the parent HTML."""

from hashlib import sha256
from html.parser import HTMLParser
from typing import Any

VERSION = "legacy-statute-occurrence-1"


def statute_occurrences(html: str) -> list[dict[str, Any]]:
    lines = [0] + [i + 1 for i, char in enumerate(html) if char == "\n"]
    parent = sha256(html.encode()).hexdigest()

    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.items: list[dict[str, Any]] = []
            self.active: dict[str, Any] | None = None
            self.hidden: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            from klegal_gold.documents.reader import HIDDEN

            if tag in HIDDEN:
                if tag != "embed":
                    self.hidden.append(tag)
                return
            if self.hidden:
                return
            values = dict(attrs)
            if tag != "a" or not (values.get("name") == "linkContJomun" or "jtable" in values):
                return
            raw = self.get_starttag_text() or ""
            line, column = self.getpos()
            start = lines[line - 1] + column
            payload = values.get("jtable") or ""
            status = (
                "PRESERVED"
                if "<table" in payload.lower()
                else ("LEGACY_FAILURE" if payload.strip() else "UNLINKED")
            )
            item = {
                "order": len(self.items),
                "html_start": start,
                "html_end": start + len(raw),
                "html_tag": raw,
                "parent_html_sha256": parent,
                "reference_id": sha256(f"{parent}:statute:{start}".encode()).hexdigest(),
                "payload": payload,
                "payload_sha256": sha256(payload.encode()).hexdigest(),
                "status": status,
                "version_status": "UNVERIFIED",
                "text": "",
                "source_attributes": values,
                "rule_version": VERSION,
            }
            self.items.append(item)
            self.active = item

        def handle_endtag(self, tag: str) -> None:
            if self.hidden:
                if tag == self.hidden[-1]:
                    self.hidden.pop()
                return
            if tag == "a":
                self.active = None

        def handle_data(self, data: str) -> None:
            if self.active is not None and not self.hidden:
                self.active["text"] += data

    parser = Parser()
    parser.feed(html)
    for item in parser.items:
        item["text"] = " ".join(item["text"].split())
    return parser.items
