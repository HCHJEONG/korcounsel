"""Deterministic extraction from preserved scourt data. Never modifies source HTML."""

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from klegal_gold.fields.contract import (
    GMETA,
    HISTORICAL,
    LMETA,
    NAMES,
    SECTIONS,
    TAIL,
    field,
    validate,
)


class Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if not self.hidden and tag in {"br", "p", "div", "tr", "h2"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "tr", "h2"}:
            self.parts.append("\n")
        if not self.hidden and tag in {"td", "th"}:
            self.parts.append("\t")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def visible(html: str) -> str:
    parser = Text()
    parser.feed(html)
    parser.close()
    return re.sub(r"\n[ \t\r]*\n+", "\n", "".join(parser.parts)).strip()


def extract(
    html: str,
    metadata: dict[str, Any],
    *,
    title: str,
    source_id: str,
    html_artifact_id: str,
    metadata_artifact_id: str,
    processed_at: str,
    lawgo: dict[str, Any] | None = None,
    lawgo_artifact_id: str | None = None,
    lawgo_status: str = "NOT_PROCESSED",
) -> list[dict[str, Any]]:
    text = visible(html)
    evidence = {"artifact_id": html_artifact_id, "representation": "visible-text-v1"}
    result = {
        n: field(n, reason="원문에 해당 구획 또는 정보가 제공되지 않음", evidence=evidence)
        for n in NAMES
    }

    def put(name: str, value: Any, ev: dict[str, Any], reason: str) -> None:
        if value is not None and value != "":
            result[name] = field(name, value, status="PRESENT", reason=reason, evidence=ev)

    put("case_txt_scraped_with_tags", html, {"artifact_id": html_artifact_id}, "보존 HTML 그대로")
    put("case_txt_in_file", text, evidence, "태그 제거·줄바꿈 표현, 원문 HTML 불변")
    h2 = re.search(r"<h2\b[^>]*>(.*?)</h2>", html, re.S | re.I)
    full = visible(h2[1]) if h2 else title
    put("case_full_no", full, evidence, "제공 제목")
    for name, key in {
        **GMETA,
        "case_official_name": "csNmLstCtt",
        "case_unofficial_name": "jdcpctCsAlsNm",
        "citedPlace": "jdcpctPublcCtt",
        "court_name": "cortNm",
    }.items():
        put(
            name,
            metadata.get(key),
            {"artifact_id": metadata_artifact_id, "key": key},
            "scourt 공식 metadata",
        )
    put(
        "gmeta_contId",
        str(source_id),
        {"artifact_id": metadata_artifact_id, "key": "jisCntntsSrno"},
        "출처 관찰 ID",
    )
    docket = re.search(r"[0-9]{2,4}[가-힣]+[0-9]+", str(metadata.get("csNoLstCtt", "")))
    if docket:
        put(
            "case_no",
            docket[0],
            evidence,
            "legacy 계약의 대표 사건번호; 병합 번호는 gmeta_saNo에 보존",
        )
        code = re.sub(r"[0-9]", "", docket[0])
        put("code", code, evidence, "대표 사건번호 기호")
        sorts = {"다": "민사", "도": "형사", "두": "행정", "스": "가사", "모": "형사"}
        if code in sorts:
            put("case_sort", sorts[code], evidence, "legacy 사건기호 분류표")
        else:
            result["case_sort"] = field(
                "case_sort", status="REVIEW", reason="사건기호 분류표 대조 필요", evidence=evidence
            )
    for name, key in {"decision_date": "prnjdgYmd", "gmeta_sngoDay": "prnjdgYmd"}.items():
        raw = metadata.get(key)
        if raw:
            try:
                day = datetime.strptime(str(raw).replace("-", ""), "%Y%m%d").date().isoformat()
                put(
                    name,
                    day,
                    {"artifact_id": metadata_artifact_id, "key": key},
                    "달력 유효성 검증·ISO 날짜",
                )
            except ValueError:
                result[name] = field(
                    name, raw, status="ERROR", reason="유효하지 않은 제공 날짜", evidence=evidence
                )
    headings = list(re.finditer(r"【([^】]{1,50})】|(?m:^)[ \t]*\[([^]\n]{1,30})\]", text))
    tail_labels = {label for name in TAIL for label in SECTIONS[name]}
    body_labels = {label for name in SECTIONS if name not in TAIL for label in SECTIONS[name]} | {
        "전문"
    }
    party_label = r"원고|피고|청구인|신청인|항고인|피신청인|상고인|사건본인|참가인|검사"
    headings = [
        match
        for match in headings
        if (
            (
                match[1]
                and (re.sub(r"\s", "", match[1]) in body_labels or re.search(party_label, match[1]))
            )
            or (match[2] and re.sub(r"\s", "", match[2]) in tail_labels)
        )
    ]
    sections = []
    for i, match in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections.append(
            (
                re.sub(r"\s", "", match[1] or match[2]),
                bool(match[2]),
                match.start(),
                end,
                match.end(),
            )
        )
    for name, labels in SECTIONS.items():
        matches = [s for s in sections if s[0] in labels and s[1] == (name in TAIL)]
        if matches:
            value = "\n".join(text[s[2] : s[3]].strip() for s in matches)
            ev = {**evidence, "ranges": [[s[2], s[3]] for s in matches]}
            put(name, value, ev, "제공된 명시적 구획")
            if len(matches) > 1:
                result[name].update(status="REVIEW", reason="동일 구획 반복: 자동 병합 검토 필요")
    parties = [
        s
        for s in sections
        if not s[1]
        and re.search(r"원고|피고|청구인|신청인|항고인|피신청인|상고인|사건본인|참가인|검사", s[0])
    ]
    if parties:
        put(
            "party_info",
            "\n".join(text[s[2] : s[3]].strip() for s in parties),
            evidence,
            "당사자 구획",
        )
        put(
            "party_info_dict",
            {s[0]: text[s[4] : s[3]].strip() for s in parties},
            evidence,
            "당사자 역할별 원표기; 대리인 문구 보존",
        )
    judges = re.search(r"(?m)^\s*(대법관|대법원장|판사|재판관|군판사)\s+([^\n]+)", text)
    if judges:
        put(
            "judge",
            {judges[1]: judges[2].strip()},
            {**evidence, "ranges": [list(judges.span())]},
            "판사 서명 구획; 이름·역할 원표기 보존",
        )
    for name, flag in {
        "supreme": metadata.get("cortNm") == "대법원",
        "jeonhap": "전원합의체" in full,
    }.items():
        put(name, flag, evidence, "제공 법원·제목 표식")
    if "★" in full or "*" in full:
        put("important", True, evidence, "제공 제목 별표")
    put("site", "scourt", {"artifact_id": metadata_artifact_id}, "출처")
    put(
        "file_process_time",
        processed_at,
        {"operation": "BUILD_CASE_FIELDS"},
        "이번 파생 생성 작업 시작 시각; 과거 파일 시각 아님",
    )
    for name in HISTORICAL:
        result[name] = field(
            name,
            status="NOT_APPLICABLE",
            reason="legacy 파일·외부 편집 workflow 전용; 현재 수집 원천에는 없음",
        )
    result["repealed_cases"] = field(
        "repealed_cases",
        status="REVIEW",
        reason="전체 corpus의 판례 폐기 역참조 감사 필요; 본문 부재로 미폐기 단정 금지",
    )
    for name, key in LMETA.items():
        if lawgo_status == "EXACT" and lawgo is not None:
            put(
                name,
                lawgo.get(key),
                {"artifact_id": lawgo_artifact_id, "key": key},
                "동일성 확인된 lawgo 제공 metadata",
            )
        elif lawgo_status in {"CONFLICT", "AMBIGUOUS", "METADATA_INCOMPLETE"}:
            result[name] = field(
                name,
                status="REVIEW",
                reason="lawgo 동일성 미확정: " + lawgo_status,
                evidence={"artifact_id": lawgo_artifact_id},
            )
        else:
            result[name] = field(
                name,
                status="NOT_PROCESSED"
                if lawgo_status in {"NOT_PROCESSED", "PENDING"}
                else "NOT_PROVIDED",
                reason="lawgo 연결 결과: " + lawgo_status,
                evidence={"artifact_id": lawgo_artifact_id},
            )
    fields = [result[n] for n in NAMES]
    validate(fields)
    return fields
