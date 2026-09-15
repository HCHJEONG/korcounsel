import json
from datetime import UTC, datetime

import pytest

from klegal_gold.sources.law_api import Response, SourceError
from klegal_gold.sources.scourt import ScourtPortalSource, validate_window, window_params


@pytest.mark.parametrize(
    "start,end",
    [
        (None, "2024-09-30"),
        ("2024-09-30", None),
        ("2024-02-30", "2024-03-01"),
        ("2024-10-01", "2024-09-30"),
        ("2024-01-01", "2024-12-31"),
    ],
)
def test_invalid_window(start, end):
    with pytest.raises(SourceError):
        validate_window(start, end)


@pytest.mark.parametrize(
    "day,valid",
    [
        ("20240901", True),
        ("20240930", True),
        ("20241001", False),
        ("20240831", False),
        ("20240931", False),
    ],
)
def test_provider_must_honor_calendar_window(day, valid):
    captures = []

    class Transport:
        def post_window_listing(self, params, progress):
            assert params["dma_searchParam"]["prnjdgYmdFrom"] == "20240901"
            return Response(
                json.dumps(
                    {
                        "status": 200,
                        "data": {
                            "status": 200,
                            "totalCount": 1,
                            "dlt_jdcpctRslt": [{"jisCntntsSrno": 123, "prnjdgYmd": day}],
                        },
                    }
                ).encode(),
                200,
                "application/json",
                "https://portal.scourt.go.kr/",
                datetime.now(UTC),
            )

    source = ScourtPortalSource(
        preserve=captures.append,
        transport=Transport(),
        date_from="2024-09-01",
        date_to="2024-09-30",
        sleep=lambda _: None,
    )
    if valid:
        assert source.list_page(page=1).ids == ("123",)
    else:
        with pytest.raises(SourceError):
            source.list_page(page=1)
    assert len(captures) == 1


def test_window_scope_is_date_specific():
    assert window_params("", 1, 80, "2024-09-01", "2024-09-30") != window_params(
        "", 1, 80, "2024-10-01", "2024-10-31"
    )
