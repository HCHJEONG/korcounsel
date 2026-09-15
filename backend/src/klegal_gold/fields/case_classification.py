"""Date-aware, evidence-bearing descriptions of Korean court case symbols."""

from __future__ import annotations

from datetime import date
from typing import Any, TypedDict


class CaseSymbol(TypedDict):
    official_code: str
    category: str
    description: str
    stage: str | None
    panel: str | None
    procedure: str


SCOURT_GUIDE = "https://www.scourt.go.kr/portal/information/event/guide/index14.html"
RULE = "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2200000102523&chrClsCd=010201"
RULE_EFFECTIVE_FROM = date(2022, 7, 29)


SYMBOLS: dict[str, CaseSymbol] = {
    "가단": {
        "official_code": "001",
        "category": "민사",
        "description": "민사1심단독사건",
        "stage": "제1심",
        "panel": "단독",
        "procedure": "본안",
    },
    "가합": {
        "official_code": "002",
        "category": "민사",
        "description": "민사1심합의사건",
        "stage": "제1심",
        "panel": "합의",
        "procedure": "본안",
    },
    "가소": {
        "official_code": "003",
        "category": "민사",
        "description": "민사소액사건",
        "stage": None,
        "panel": None,
        "procedure": "소액",
    },
    "나": {
        "official_code": "004",
        "category": "민사",
        "description": "민사항소사건",
        "stage": "항소",
        "panel": None,
        "procedure": "본안",
    },
    "다": {
        "official_code": "005",
        "category": "민사",
        "description": "민사상고사건",
        "stage": "상고",
        "panel": None,
        "procedure": "본안",
    },
    "라": {
        "official_code": "007",
        "category": "민사",
        "description": "민사항고사건",
        "stage": "항고",
        "panel": None,
        "procedure": "항고",
    },
    "마": {
        "official_code": "009",
        "category": "민사",
        "description": "민사재항고사건",
        "stage": "재항고",
        "panel": None,
        "procedure": "재항고",
    },
    "드단": {
        "official_code": "150",
        "category": "가사",
        "description": "가사1심단독사건",
        "stage": "제1심",
        "panel": "단독",
        "procedure": "본안",
    },
    "르": {
        "official_code": "024",
        "category": "가사",
        "description": "가사항소사건",
        "stage": "항소",
        "panel": None,
        "procedure": "본안",
    },
    "므": {
        "official_code": "025",
        "category": "가사",
        "description": "가사상고사건",
        "stage": "상고",
        "panel": None,
        "procedure": "본안",
    },
    "브": {
        "official_code": "026",
        "category": "가사",
        "description": "가사항고사건",
        "stage": "항고",
        "panel": None,
        "procedure": "항고",
    },
    "스": {
        "official_code": "027",
        "category": "가사",
        "description": "가사재항고사건",
        "stage": "재항고",
        "panel": None,
        "procedure": "재항고",
    },
    "즈기": {
        "official_code": "211",
        "category": "가사",
        "description": "기타가사신청사건",
        "stage": None,
        "panel": None,
        "procedure": "신청",
    },
    "고합": {
        "official_code": "075",
        "category": "형사",
        "description": "형사1심합의사건",
        "stage": "제1심",
        "panel": "합의",
        "procedure": "본안",
    },
    "고단": {
        "official_code": "077",
        "category": "형사",
        "description": "형사1심단독사건",
        "stage": "제1심",
        "panel": "단독",
        "procedure": "본안",
    },
    "노": {
        "official_code": "079",
        "category": "형사",
        "description": "형사항소사건",
        "stage": "항소",
        "panel": None,
        "procedure": "본안",
    },
    "도": {
        "official_code": "081",
        "category": "형사",
        "description": "형사상고사건",
        "stage": "상고",
        "panel": None,
        "procedure": "본안",
    },
    "모": {
        "official_code": "085",
        "category": "형사",
        "description": "형사재항고사건",
        "stage": "재항고",
        "panel": None,
        "procedure": "재항고",
    },
    "보": {
        "official_code": "087",
        "category": "형사",
        "description": "형사준항고사건",
        "stage": "준항고",
        "panel": None,
        "procedure": "준항고",
    },
    "구합": {
        "official_code": "195",
        "category": "행정",
        "description": "행정1심사건",
        "stage": "제1심",
        "panel": None,
        "procedure": "본안",
    },
    "구단": {
        "official_code": "194",
        "category": "행정",
        "description": "행정1심재정단독사건",
        "stage": "제1심",
        "panel": "재정단독",
        "procedure": "본안",
    },
    "누": {
        "official_code": "034",
        "category": "행정",
        "description": "행정항소사건",
        "stage": "항소",
        "panel": None,
        "procedure": "본안",
    },
    "두": {
        "official_code": "035",
        "category": "행정",
        "description": "행정상고사건",
        "stage": "상고",
        "panel": None,
        "procedure": "본안",
    },
    "허": {
        "official_code": "129",
        "category": "특허",
        "description": "특허1심사건",
        "stage": "제1심",
        "panel": None,
        "procedure": "본안",
    },
    "후": {
        "official_code": "046",
        "category": "특허",
        "description": "특허상고사건",
        "stage": "상고",
        "panel": None,
        "procedure": "본안",
    },
    "추": {
        "official_code": "043",
        "category": "선거특별",
        "description": "특수소송사건",
        "stage": None,
        "panel": None,
        "procedure": "특수소송",
    },
    "카기": {
        "official_code": "074",
        "category": "신청",
        "description": "기타민사신청사건",
        "stage": None,
        "panel": None,
        "procedure": "신청",
    },
}


def classify(code: str, decision_date: date | None) -> tuple[dict[str, Any] | None, str, str]:
    symbol = SYMBOLS.get(code)
    if symbol is None:
        return None, "REVIEW", "공식 사건구분표에서 아직 구조화하지 않은 사건기호"
    parts = [symbol["category"], symbol["stage"], symbol["panel"], symbol["procedure"]]
    label_parts: list[str] = []
    for part in parts:
        if part and part != "본안" and part not in label_parts:
            label_parts.append(part)
    label = " · ".join(label_parts)
    value: dict[str, Any] = {
        "code": code,
        **symbol,
        "label": label,
        "basis": {
            "authority": "대법원 사건구분안내 및 사건별 부호문자의 부여에 관한 예규",
            "guide_url": SCOURT_GUIDE,
            "rule_url": RULE,
            "rule_effective_from": RULE_EFFECTIVE_FROM.isoformat(),
        },
        "temporal_status": "VERIFIED_EFFECTIVE_RANGE"
        if decision_date and decision_date >= RULE_EFFECTIVE_FROM
        else "HISTORICAL_VERSION_NOT_VERIFIED",
    }
    if decision_date and decision_date >= RULE_EFFECTIVE_FROM:
        return value, "PRESENT", "선고일에 적용되는 공식 사건부호 자료로 구조화"
    return value, "REVIEW", "현행 공식 설명과 corpus 저장값은 일치하나 사건 당시 예규 연혁 미확인"
