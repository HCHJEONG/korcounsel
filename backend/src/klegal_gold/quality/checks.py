"""Read-only deterministic checks, independent of the field extraction implementation."""

import re
from collections import Counter
from typing import Any

from klegal_gold.fields.extract import visible

VERSION = "quality-1"
CATEGORIES = ("RETRYABLE", "LOGIC_REQUIRED", "REVIEW", "NOT_PROVIDED", "PENDING")


def transient(code: str) -> bool:
    # Unknown HTTP status, 404, authentication, decode and structure failures are NOT transient.
    return code in {
        "LAWGO_TRANSPORT_ERROR",
        "LAWGO_TRANSPORT_FAILED",
        "LAWGO_SERVICE_UNAVAILABLE",
        "IMAGE_TRANSPORT_ERROR",
        "SOURCE_TRANSPORT_ERROR",
        "IMAGE_NETWORK_ERROR",
    } or bool(re.fullmatch(r"(?:(?:IMAGE|LAWGO|SOURCE)_)?HTTP_(?:408|429|500|502|503|504)", code))


def anomalies(html: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = visible(html)
    values = {f["name"]: f for f in fields}
    findings = []
    # Only explicit bracketed headings at a line boundary; quoted prose is not a heading.
    labels = {
        "주문": "main_decision",
        "이유": "reasoning",
        "판결이유": "reasoning",
        "결정이유": "reasoning",
        "원고": "party_info",
        "피고": "party_info",
        "피고인": "party_info",
        "상고인": "party_info",
        "항소인": "party_info",
    }
    for match in re.finditer(r"(?m)^[ \t]*【([^】\n]{1,50})】", text):
        label = re.sub(r"\s|주\d+\)", "", match[1])
        name = labels.get(label)
        if name and not values.get(name, {}).get("value"):
            findings.append(
                {
                    "category": "LOGIC_REQUIRED",
                    "code": "HEADING_WITHOUT_FIELD",
                    "location": name,
                    "range": list(match.span()),
                    "detail": match[0].strip(),
                }
            )
    order = values.get("main_decision", {}).get("value")
    if isinstance(order, str) and re.search(
        r"【\s*(?:판\s*결\s*)?이\s*유(?:\s*주\d+\))?\s*】", order
    ):
        findings.append(
            {
                "category": "LOGIC_REQUIRED",
                "code": "REASONING_IN_ORDER",
                "location": "main_decision",
                "detail": "주문에 이유 표제 포함",
            }
        )
    return findings


def inspect(reader: dict[str, Any], fields: dict[str, Any], html: str) -> dict[str, Any]:
    issues = anomalies(html, fields["fields"]) if fields["state"] != "NOT_PROCESSED" else []
    for f in fields["fields"]:
        category = {
            "ERROR": "LOGIC_REQUIRED",
            "REVIEW": "REVIEW",
            "NOT_PROCESSED": "PENDING",
            "NOT_PROVIDED": "NOT_PROVIDED",
        }.get(f["status"])
        if category:
            issues.append(
                {
                    "category": category,
                    "code": "FIELD_" + f["status"],
                    "location": f["name"],
                    "detail": f["reason"],
                }
            )
    for kind, refs in (
        ("image", reader["images"]),
        ("statute_image", reader.get("statute_images", [])),
    ):
        for ref in refs:
            if ref["status"] == "ACQUIRED":
                continue
            code = str(
                ref.get("acquisition", {}).get("last_error_code")
                or ref.get("acquisition", {}).get("error")
                or ref.get("reason")
                or ref["status"]
            )
            issues.append(
                {
                    "category": "RETRYABLE"
                    if transient(code)
                    else "PENDING"
                    if ref["status"] == "PENDING"
                    else "LOGIC_REQUIRED",
                    "code": code,
                    "location": kind + ":" + ref["reference_id"],
                    "detail": ref["status"],
                }
            )
    for ref in reader["statutes"]:
        status = ref.get("provider_status", ref.get("status", "UNLINKED"))
        if status == "PRESERVED" and ref.get("version_status") != "VERIFIED":
            issues.append(
                {
                    "category": "REVIEW",
                    "code": "STATUTE_VERSION_UNVERIFIED",
                    "location": "statute:" + ref["reference_id"],
                    "detail": "적용 법령 버전 미확인",
                }
            )
        if status != "PRESERVED":
            code = str(ref.get("provider_error") or status)
            category = (
                "RETRYABLE"
                if status == "FAILED" and transient(code)
                else "LOGIC_REQUIRED"
                if status == "FAILED"
                else "REVIEW"
                if status == "AMBIGUOUS"
                else "PENDING"
            )
            issues.append(
                {
                    "category": category,
                    "code": code,
                    "location": "statute:" + ref["reference_id"],
                    "detail": status,
                }
            )
    link = reader["provenance"].get("lawgo_status", "NOT_PROCESSED")
    if link != "EXACT":
        issues.append(
            {
                "category": "REVIEW" if link in {"CONFLICT", "AMBIGUOUS"} else "PENDING",
                "code": "LAWGO_" + link,
                "location": "lawgo",
                "detail": link,
            }
        )
    counts = dict(Counter(i["category"] for i in issues))
    return {
        "source_id": reader["source_id"],
        "title": reader["title"],
        "fields_revision": fields.get("revision"),
        "field_state": fields["state"],
        "counts": counts,
        "issues": issues,
        "images_acquired": sum(
            r["status"] == "ACQUIRED" for r in reader["images"] + reader.get("statute_images", [])
        ),
        "statutes_preserved": sum(
            r.get("provider_status", r.get("status")) == "PRESERVED" for r in reader["statutes"]
        ),
    }
