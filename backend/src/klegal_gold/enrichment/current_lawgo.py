"""Provider-linked lawgo enrichment; never derive statute requests from citations."""

import json
import re
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
from typing import Any

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.enrichment.legacy_statutes import statute_occurrences
from klegal_gold.enrichment.statute_images import current_statute_images
from klegal_gold.normalize.decision import court_comparison_key, decision_kind, docket_aliases
from klegal_gold.sources.law_api import LawOpenApiCaseSource
from klegal_gold.sources.lawgo_html import fetch_provider_html

VERSION = "current-lawgo-3"
CALL = re.compile(
    r"(?:javascript:)?fncLawPop\('([^'<>]+)','JO','([0-9]{6})','(prec(?:[0-9]{8})?)'\);?"
)


def exact_metadata(provenance: dict[str, Any], candidate: dict[str, Any]) -> bool:
    aliases = docket_aliases(str(provenance.get("case_number") or ""))
    kind = decision_kind(provenance.get("decision_type"))
    day = str(provenance.get("decision_date") or "")
    return bool(
        aliases
        and kind
        and re.fullmatch(r"[0-9]{8}", day)
        and court_comparison_key(provenance.get("court"))
        and court_comparison_key(provenance.get("court"))
        == court_comparison_key(candidate.get("법원명"))
        and set(aliases) == set(docket_aliases(str(candidate.get("사건번호") or "")))
        and kind == decision_kind(candidate.get("판결유형"))
        and day == str(candidate.get("선고일자") or "").replace("-", "").replace(".", "")
    )


def provider_links(html: str, *, source_id: str | None = None) -> tuple[str, list[dict[str, str]]]:
    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.day = ""
            self.source_id = ""
            self.links: list[dict[str, str]] = []
            self.active: dict[str, str] | None = None

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = dict(attrs)
            if tag == "input" and values.get("id") == "precSeq":
                self.source_id = values.get("value") or ""
            if tag == "input" and values.get("id") == "precYd":
                self.day = values.get("value") or ""
            if tag == "a":
                match = CALL.fullmatch(values.get("onclick") or "")
                self.active = None
                if match:
                    self.active = {
                        "law_name": match[1],
                        "article": match[2],
                        "provider_context": match[3],
                        "text": "",
                        "provider_tag": self.get_starttag_text() or "",
                    }
                    self.links.append(self.active)

        def handle_data(self, text: str) -> None:
            if self.active is not None:
                self.active["text"] += text

        def handle_endtag(self, tag: str) -> None:
            if tag == "a":
                self.active = None

    parser = Parser()
    parser.feed(html)
    if not re.fullmatch(r"[0-9]{8}", parser.day):
        raise ValueError("LAWGO_FRAME_STRUCTURE_CHANGED")
    if source_id is not None and parser.source_id != source_id:
        raise ValueError("LAWGO_FRAME_ID_MISMATCH")
    valid_links = []
    for link in parser.links:
        try:
            provider_article_params(link, parser.day)
        except ValueError:
            continue
        valid_links.append(link)
        link["text"] = " ".join(link["text"].split())
    return parser.day, valid_links


def provider_article_params(link: dict[str, str], frame_day: str) -> dict[str, str]:
    """Mirror the observed JO/prec branch; retain provider-selected historical date."""
    context = link.get("provider_context", "prec")
    if re.fullmatch(r"prec(?:[0-9]{8})?", context) is None:
        raise ValueError("UNSUPPORTED_LAWGO_CONTEXT")
    day = frame_day if context == "prec" else context[4:]
    if re.fullmatch(r"[0-9]{8}", day) is None:
        raise ValueError("INVALID_LAWGO_DATE")
    datetime.strptime(day, "%Y%m%d")
    return {
        "joNo": link["article"],
        "joEfYd": "",
        "mode": "11",
        "lsNm": link["law_name"],
        "ancYd": "",
        "lsId": "prec" + day,
        "efYd": day,
        "lsClsCd": "L",
    }


def article_table(html: str) -> str:
    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.depth = 0
            self.parts: list[str] = []
            self.found = 0
            self.service_error = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = dict(attrs)
            if tag == "div" and values.get("id") == "error500":
                self.service_error = True
            if tag == "table" and not self.depth and values.get("summary") == "조문정보":
                self.found += 1
                self.depth = 1
            elif tag == "table" and self.depth:
                self.depth += 1
            if self.depth:
                self.parts.append(self.get_starttag_text() or "")

        def handle_endtag(self, tag: str) -> None:
            if self.depth:
                self.parts.append(f"</{tag}>")
                if tag == "table":
                    self.depth -= 1

        def handle_data(self, data: str) -> None:
            if self.depth:
                self.parts.append(data)

        def handle_entityref(self, name: str) -> None:
            self.handle_data(f"&{name};")

        def handle_charref(self, name: str) -> None:
            self.handle_data(f"&#{name};")

    parser = Parser()
    parser.feed(html)
    if parser.service_error and "요청하신 페이지를 정상적으로 제공할 수 없습니다" in html:
        raise ValueError("LAWGO_SERVICE_UNAVAILABLE")
    table = "".join(parser.parts)
    if parser.found != 1 or parser.depth or 'id="lsLinkTable"' not in table:
        raise ValueError("LAWGO_ARTICLE_STRUCTURE_CHANGED")
    if not re.search(r"제[0-9]+조", table):
        raise ValueError("LAWGO_ARTICLE_EMPTY")
    return table


class CurrentLawgo:
    def __init__(self, records: Records) -> None:
        self.records = records

    def _request(self, endpoint: str, params: dict[str, str], key: str) -> bytes:
        # Checkpoint is an immutable per-job response artifact. Reuse on restart.
        try:
            raw = self.records.read(key)
        except ValueError as exc:
            if str(exc) != "ARTIFACT_NOT_FOUND":
                raise
        else:
            with self.records.db.connect() as conn:
                row = conn.execute(
                    "SELECT metadata FROM artifacts WHERE artifact_id=%s", (key,)
                ).fetchone()
            if row is None or row["metadata"].get("status") != 200:
                raise ValueError("LAWGO_HTTP_ERROR")
            return raw
        response = fetch_provider_html(endpoint, params)
        raw = response.body
        self.records.put_artifact(
            key,
            raw,
            origin="HTTP_RESPONSE",
            metadata={
                "kind": "LAWGO_PROVIDER_RESPONSE",
                "endpoint": endpoint,
                "parameters": params,
                "rule_version": VERSION,
                "retrieved_at": response.retrieved_at.isoformat(),
                "status": response.status,
                "mime_type": response.mime_type,
            },
        )
        if response.status != 200:
            raise ValueError("LAWGO_HTTP_ERROR")
        return raw

    def run(
        self,
        document_id: str,
        job_id: str,
        progress: Callable[[], None],
        *,
        transient_only: bool = False,
    ) -> str:
        store = ReaderStore(self.records)
        original = store.read(document_id)
        if original["origin"] != "CURRENT_SOURCE":
            raise ValueError("NOT_CURRENT_READER")
        provenance = dict(original["provenance"])
        prefix = "current-lawgo:" + job_id
        plan_id = prefix + ":plan"
        if transient_only:
            previous = provenance.get("lawgo_plan_artifact_id")
            if not previous:
                raise ValueError("LAWGO_RETRY_PLAN_REQUIRED")
            plan_id = previous
        try:
            plan = json.loads(self.records.read(plan_id))
        except ValueError as exc:
            if transient_only or str(exc) != "ARTIFACT_NOT_FOUND":
                raise
            settings = load_settings()
            plan = {"status": "UNMATCHED", "candidates": [], "links": []}
            if settings.law_api_credential is None:
                plan["status"] = "CREDENTIAL_UNAVAILABLE"
            elif not provenance.get("case_number"):
                plan["status"] = "METADATA_INCOMPLETE"
            else:

                def preserve(response: Any) -> None:
                    from klegal_gold.sources.persistence import preserve_response

                    preserve_response(self.records, response, job_id)

                client = LawOpenApiCaseSource(
                    settings.law_api_credential,
                    preserve=preserve,
                    progress=progress,
                    max_attempts=1,
                )
                listing = client.list_page(page=1, display=20, docket=provenance["case_number"])
                plan["candidates"] = list(listing.rows)
                matching = [row for row in listing.rows if exact_metadata(provenance, row)]
                if listing.total > 20 or len(matching) > 1:
                    plan["status"] = "AMBIGUOUS"
                elif len(matching) == 1:
                    sid = str(matching[0]["판례일련번호"])
                    detail = client.fetch_detail(sid)
                    if not exact_metadata(provenance, detail.fields):
                        plan["status"] = "CONFLICT"
                    else:
                        raw = self._request(
                            "precInfoP.do", {"precSeq": sid, "mode": "0"}, prefix + ":frame"
                        )
                        day, links = provider_links(raw.decode("utf-8"), source_id=sid)
                        if day != provenance["decision_date"]:
                            raise ValueError("LAWGO_FRAME_DATE_MISMATCH") from None
                        plan.update(
                            status="EXACT",
                            source_id=sid,
                            day=day,
                            links=links,
                            frame_artifact_id=prefix + ":frame",
                        )
            self.records.put_artifact(
                plan_id,
                json.dumps(plan, ensure_ascii=False, sort_keys=True).encode(),
                origin="DERIVED",
                metadata={"kind": "LAWGO_LINK_PLAN"},
            )
        progress()
        html = self.records.read(original["html_artifact_id"]).decode()
        existing = {item["reference_id"]: item for item in original["statutes"]}
        statutes = [
            deepcopy(existing.get(item["reference_id"], item)) for item in statute_occurrences(html)
        ]
        for article in statutes:
            if transient_only:
                from klegal_gold.quality.checks import transient

                if article.get("provider_status") != "FAILED" or not transient(
                    str(article.get("provider_error", ""))
                ):
                    continue
            if article["payload"]:
                continue
            links = [link for link in plan["links"] if link["text"] == article["text"]]
            targets = {
                (
                    link["law_name"],
                    link["article"],
                    provider_article_params(link, plan["day"])["efYd"],
                )
                for link in links
            }
            article["provider_status"] = "UNLINKED"
            if len(targets) != 1:
                if targets:
                    article["provider_status"] = "AMBIGUOUS"
                continue
            link = links[0]
            key = (
                prefix + ":article:" + sha256(json.dumps(link, sort_keys=True).encode()).hexdigest()
            )
            progress()
            try:
                params = provider_article_params(link, plan["day"])
                raw = self._request("lsLinkProc.do", params, key)
                table = article_table(raw.decode("utf-8"))
                article.update(
                    payload=table,
                    payload_sha256=sha256(table.encode()).hexdigest(),
                    payload_artifact_id=key,
                    status="PRESERVED",
                    provider_status="PRESERVED",
                    version_status="UNVERIFIED",
                    provider_link=link,
                    provider_request=params,
                    lawgo_source_id=plan["source_id"],
                    frame_artifact_id=plan["frame_artifact_id"],
                )
            except ValueError as exc:
                article.update(provider_status="FAILED", provider_error=str(exc))
        provenance.update(
            current_root_document_id=provenance.get("current_root_document_id", document_id),
            previous_reader_document_id=document_id,
            lawgo_plan_artifact_id=plan_id,
            lawgo_status=plan["status"],
            lawgo_rule_version=VERSION,
        )
        return store.preserve(
            html,
            title=original["title"],
            source_id=original["source_id"],
            origin="CURRENT_SOURCE",
            provenance=provenance,
            acquisitions={
                ref["resolved_url"]: ref.get("acquisition", {})
                for ref in original["images"]
                if ref.get("resolved_url")
            },
            linked_statutes=statutes,
            statute_images=current_statute_images(
                self.records, html, statutes, original.get("statute_images")
            ),
        )
