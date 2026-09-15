"""Versioned original sixty-column contract; provenance is stored beside values."""

from typing import Any

VERSION = "case-fields-5"
NAMES = """case_txt_scraped_with_tags case_txt_in_file case_full_no case_official_name
case_unofficial_name citedPlace previous_case decision_items decision_gists main_decision
reasoning case_comment related_articles applicable_acts applicable_precedents applicable_acts_tail
applicable_precedents_tail applicable_acts_in_body applicable_precedents_in_body following_cases
original_case site hangul_keyword important supreme jeonhap party_info multipartycase uppercase
file_created_time etcdoc file_process_time folder_file_name case_no code case_sort court_name
decision_date judge repealed_cases party_info_dict closing_argument gmeta_contId gmeta_gjaeInfo
gmeta_sngoDay gmeta_bubNm gmeta_panTypeNm gmeta_saNm gmeta_saNo for_lawschool lmeta_serialno
lmeta_saNm lmeta_saNo lmeta_sngoDay lmeta_bubNm lmeta_bubCode lmeta_saType lmeta_saCode
lmeta_deType lmeta_sentence""".split()
SECTIONS = {
    "previous_case": ["원심판결", "원심결정", "원판결", "원결정", "불복대상결정"],
    "decision_items": ["판시사항", "결정사항"],
    "decision_gists": ["판결요지", "결정요지"],
    "main_decision": ["주문"],
    "reasoning": ["이유", "판결이유", "결정이유", "재정이유"],
    "applicable_acts": ["참조조문"],
    "applicable_precedents": ["참조판례"],
    "case_comment": ["평석"],
    "related_articles": ["관련문헌"],
    "applicable_acts_tail": ["참조조문"],
    "applicable_precedents_tail": ["참조판례"],
    "applicable_acts_in_body": ["본문참조조문"],
    "applicable_precedents_in_body": ["본문참조판례"],
    "following_cases": ["따름판례"],
    "original_case": ["원심판결"],
    "multipartycase": ["다수당사자판례"],
    "uppercase": ["상급심판결"],
    "etcdoc": ["기타문서"],
    "closing_argument": ["변론종결"],
}
TAIL = {
    "case_comment",
    "related_articles",
    "applicable_acts_tail",
    "applicable_precedents_tail",
    "applicable_acts_in_body",
    "applicable_precedents_in_body",
    "following_cases",
    "original_case",
    "multipartycase",
    "uppercase",
    "etcdoc",
}
GMETA = {
    "gmeta_contId": "jisCntntsSrno",
    "gmeta_gjaeInfo": "jdcpctPublcCtt",
    "gmeta_sngoDay": "prnjdgYmd",
    "gmeta_bubNm": "cortNm",
    "gmeta_panTypeNm": "adjdTypNm",
    "gmeta_saNm": "csNmLstCtt",
    "gmeta_saNo": "csNoLstCtt",
}
LMETA = {
    "lmeta_serialno": "판례일련번호",
    "lmeta_saNm": "사건명",
    "lmeta_saNo": "사건번호",
    "lmeta_sngoDay": "선고일자",
    "lmeta_bubNm": "법원명",
    "lmeta_bubCode": "법원종류코드",
    "lmeta_saType": "사건종류명",
    "lmeta_saCode": "사건종류코드",
    "lmeta_deType": "판결유형",
    "lmeta_sentence": "선고",
}
HISTORICAL = {"file_created_time", "folder_file_name", "hangul_keyword", "for_lawschool"}
STATUSES = {
    "PRESENT",
    "NOT_PROVIDED",
    "NOT_APPLICABLE",
    "NOT_PROCESSED",
    "ERROR",
    "REVIEW",
    "LEGACY_STORED",
}


def field(
    name: str,
    value: Any = None,
    *,
    status: str = "NOT_PROVIDED",
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "status": status,
        "reason": reason,
        "evidence": evidence or {},
        "rule_version": VERSION,
    }


def validate(fields: list[dict[str, Any]]) -> None:
    if [f["name"] for f in fields] != NAMES:
        raise ValueError("FIELDS_CONTRACT_MISMATCH")
    for f in fields:
        if f["status"] not in STATUSES or not f["reason"]:
            raise ValueError("FIELDS_STATUS_INVALID")
        if f["status"] == "PRESENT" and (f["value"] is None or not f["evidence"]):
            raise ValueError("FIELDS_EVIDENCE_MISSING")
