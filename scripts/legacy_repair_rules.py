"""Analysis-only date repair proposals; never mutate archived rows."""

import re
from datetime import date
from typing import Any

from klegal_gold.ingestion.legacy import _date as parse_legacy_date

VERSION = "legacy-date-repair-3"
DATE = re.compile(r"(?<![0-9])([0-9]{4})\.\s*([0-9]{1,2})\.\s*([0-9]{1,2})\.(?![0-9])")
CLOSING_DATE = re.compile(r"(?<![0-9])([0-9]{4})\.\s*([0-9]{1,2})\.\s*([0-9]{1,2})(?![0-9])\.?")
CLOSING = re.compile(r"【\s*변론\s*종(?:결|료)(?:일)?\s*】([^【]*)")


def candidates(
    text: str, *, offset: int = 0, pattern: re.Pattern[str] = DATE
) -> list[dict[str, Any]]:
    result = []
    for match in pattern.finditer(text):
        try:
            value = date(*(int(part) for part in match.groups())).isoformat()
        except ValueError:
            value = None
        result.append(
            {
                "text": match[0],
                "start": offset + match.start(),
                "end": offset + match.end(),
                "date": value,
            }
        )
    return result


def metadata_date(value: Any) -> dict[str, Any]:
    if value is None or type(value) is int and value == 0 or value in ("", "empty", "no_info"):
        return {"status": "MISSING", "value": None}
    if not isinstance(value, str):
        return {"status": "INVALID", "value": None}
    try:
        parsed = parse_legacy_date(value.strip())
    except ValueError:
        match = DATE.fullmatch(value.strip())
        if not match:
            return {"status": "INVALID", "value": None}
        try:
            parsed = date(*(int(part) for part in match.groups()))
        except ValueError:
            return {"status": "INVALID", "value": None}
    return {"status": "VALID", "value": parsed.isoformat()}


def propose_decision(title: str, visible_html: str, metadata: dict[str, Any]) -> dict[str, Any]:
    found = candidates(title)
    values = {item["date"] for item in found if item["date"]}
    observed = {name: metadata_date(value) for name, value in metadata.items()}

    def compact(value: str) -> str:
        return "".join(value.split())

    source_title_present = bool(title.strip()) and compact(title).rstrip("★☆*") in compact(
        visible_html
    )
    status = "READY"
    selected = next(iter(values)) if len(found) == 1 and len(values) == 1 else None
    if any(item["date"] is None for item in found):
        status = "INVALID_TITLE_DATE"
    elif selected is None:
        status = "AMBIGUOUS_TITLE" if found else "MISSING_TITLE_DATE"
    elif selected == "2072-01-01":
        status = "SENTINEL_DATE"
    elif not source_title_present:
        status = "TITLE_NOT_CONFIRMED_IN_HTML"
    elif any(item["status"] == "INVALID" for item in observed.values()):
        status = "INVALID_METADATA"
    elif any(item["value"] != selected for item in observed.values() if item["status"] == "VALID"):
        status = "METADATA_CONFLICT"
    return {
        "status": status,
        "candidate": selected,
        "evidence_field": "case_full_no",
        "evidence": found,
        "title_confirmed_in_html": source_title_present,
        "metadata": observed,
    }


def propose_closing(text: str, visible_html: str, previous: Any) -> dict[str, Any]:
    sections = list(CLOSING.finditer(text))
    found = [
        item
        for section in sections
        for item in candidates(section[1], offset=section.start(1), pattern=CLOSING_DATE)
    ]
    values = {item["date"] for item in found if item["date"]}
    selected = max(values) if values else None
    source_dates = {
        item["date"]
        for section in CLOSING.finditer(visible_html)
        for item in candidates(section[1], pattern=CLOSING_DATE)
    }
    old = previous.isoformat() if isinstance(previous, date) else previous
    status = "READY"
    if any(item["date"] is None for item in found):
        status = "INVALID_DATE"
    elif not found:
        status = "NOT_FOUND" if not isinstance(previous, date) else "EXISTING_DATE_NOT_REPRODUCED"
    elif len(found) > 1:
        status = "REVIEW_MULTIPLE"
    elif selected not in source_dates:
        status = "NOT_CONFIRMED_IN_HTML"
    elif isinstance(previous, date) and old != selected:
        status = "EXISTING_DATE_CONFLICT"
    return {
        "status": status,
        "candidate": selected,
        "previous_scalar": old,
        "sections": [
            {"text": section[0], "start": section.start(), "end": section.end()}
            for section in sections
        ],
        "evidence_field": "case_txt_in_file",
        "evidence": found,
        "policy": "legacy maximum retained as candidate; multiple occurrences require review",
    }
