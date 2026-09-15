from klegal_gold.quality.checks import anomalies, inspect, transient


def test_transient_allowlist_does_not_retry_unknown_or_permanent():
    for code in ("IMAGE_NETWORK_ERROR", "LAWGO_TRANSPORT_ERROR", "HTTP_429", "HTTP_503"):
        assert transient(code)
    for code in (
        "LAWGO_HTTP_ERROR",
        "HTTP_404",
        "HTTP_401",
        "LAWGO_ARTICLE_STRUCTURE_CHANGED",
        "IMAGE_DECODE_FAILED",
    ):
        assert not transient(code)


def test_quality_detects_old_silent_omissions_without_modifying_fields():
    fields = [
        {"name": "party_info", "value": "", "status": "NOT_PROVIDED"},
        {"name": "reasoning", "value": "", "status": "NOT_PROVIDED"},
        {
            "name": "main_decision",
            "value": "【주문】기각\n【이    유주1)】이유",
            "status": "PRESENT",
        },
    ]
    result = anomalies(
        "<p>【피 고 인】갑</p><p>【주문】기각</p><p>【이    유주1)】이유</p>", fields
    )
    assert {r["code"] for r in result} == {"HEADING_WITHOUT_FIELD", "REASONING_IN_ORDER"}
    assert {r["location"] for r in result} == {"party_info", "reasoning", "main_decision"}
    assert fields[0]["status"] == "NOT_PROVIDED"
    assert anomalies("<p>판시사항 없이 이유만 제공됨</p>", []) == []
    assert anomalies("<p>본문에서 인용한 【이유】는 표제가 아니다</p>", []) == []


def test_quality_distinguishes_absence_review_and_partial_failure():
    reader = {
        "source_id": "1",
        "title": "표본",
        "images": [],
        "statutes": [
            {
                "reference_id": "one",
                "provider_status": "FAILED",
                "provider_error": "LAWGO_ARTICLE_STRUCTURE_CHANGED",
            },
            {
                "reference_id": "two",
                "provider_status": "FAILED",
                "provider_error": "LAWGO_TRANSPORT_ERROR",
            },
            {
                "reference_id": "three",
                "provider_status": "PRESERVED",
                "provider_error": "LAWGO_TRANSPORT_ERROR",
            },
        ],
        "provenance": {"lawgo_status": "CONFLICT"},
    }
    fields = {
        "state": "REVIEW",
        "fields": [
            {"name": "decision_gists", "status": "NOT_PROVIDED", "reason": "미제공", "value": None}
        ],
    }
    result = inspect(reader, fields, "")
    assert result["counts"] == {"LOGIC_REQUIRED": 1, "RETRYABLE": 1, "REVIEW": 2, "NOT_PROVIDED": 1}
    assert result["statutes_preserved"] == 1
