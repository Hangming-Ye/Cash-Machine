from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from cash_research.config import Settings
from cash_research.models import DataGap, PortfolioSnapshot, SourceResult
from cash_research.sources.ibkr_flex import IbkrFlexReadOnlyAdapter


NOW = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)
SEND_OK = """<?xml version="1.0"?><FlexStatementResponse><Status>Success</Status><ReferenceCode>REF-123</ReferenceCode><Url>https://untrusted.invalid/result</Url></FlexStatementResponse>"""
PENDING = """<?xml version="1.0"?><FlexStatementResponse><Status>Fail</Status><ErrorCode>1001</ErrorCode><ErrorMessage>Statement generation in progress</ErrorMessage></FlexStatementResponse>"""
MULTI = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="synthetic-readonly" type="AF"><FlexStatements count="2">
<FlexStatement accountId="SYNTH-A" fromDate="20260917" toDate="20260918" whenGenerated="20260919;020000">
<AccountInformation accountId="SYNTH-A" currency="USD"/><CashReportCurrency accountId="SYNTH-A" currency="USD" endingCash="1250.25"/><CashReportCurrency accountId="SYNTH-A" currency="EUR" endingCash="5.50"/>
<OpenPositions><OpenPosition accountId="SYNTH-A" symbol="ACME" assetCategory="STK" currency="USD" position="10" positionValue="900" costBasisMoney="800" market="US" listingExchange="XNAS"/></OpenPositions>
<Trades><Trade accountId="SYNTH-A" tradeID="TR-A" symbol="ACME" buySell="BUY" quantity="10" tradePrice="80" dateTime="20260918;140000" currency="USD"/></Trades></FlexStatement>
<FlexStatement accountId="SYNTH-B" fromDate="20260917" toDate="20260918" whenGenerated="20260919;020000">
<AccountInformation accountId="SYNTH-B" currency="EUR"/><CashReportCurrency accountId="SYNTH-B" currency="EUR" endingCash="500.50"/>
<OpenPositions><OpenPosition accountId="SYNTH-B" symbol="EUCO" assetCategory="STK" currency="EUR" position="5" positionValue="2000" costBasisMoney="1950" market="EU" listingExchange="XETR"/></OpenPositions>
</FlexStatement></FlexStatements></FlexQueryResponse>"""


def _settings(tmp_path: Path, **credentials: str) -> Settings:
    values = {
        "IBKR_FLEX_TOKEN": "synthetic-token",
        "IBKR_FLEX_QUERY_ID": "synthetic-query",
        "IBKR_FLEX_EXPECTED_ACCOUNT_REFS": "SYNTH-A,SYNTH-B",
        **credentials,
    }
    return Settings.model_validate(
        {"root": tmp_path, "credentials": values, "enabled_sources": ["ibkr_flex"]}
    )


def _request(operation: str = "positions", **parameters: object) -> dict[str, object]:
    return {
        "request_id": f"fixture-{operation}",
        "source": "ibkr_flex",
        "operation": operation,
        "subject": "authorized-portfolio",
        "as_of": "2026-09-21T03:00:00Z",
        "parameters": parameters,
        "required_fields": ["account_ref", "currency"],
    }


def _adapter(tmp_path: Path, handler, **kwargs: object) -> IbkrFlexReadOnlyAdapter:
    credential_overrides = kwargs.pop("credential_overrides", {})
    assert isinstance(credential_overrides, dict)
    return IbkrFlexReadOnlyAdapter(
        _settings(tmp_path, **credential_overrides),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
        sleeper=lambda _seconds: None,
        monotonic=lambda: 100.0,
        **kwargs,
    )


def test_send_pending_get_statement_preserves_multi_account_currency_and_t_plus_one(
    tmp_path: Path,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/SendRequest"):
            assert request.url.params["t"] == "synthetic-token"
            assert request.url.params["q"] == "synthetic-query"
            return httpx.Response(200, text=SEND_OK)
        if len(calls) == 2:
            return httpx.Response(200, text=PENDING)
        return httpx.Response(200, text=MULTI)

    result = _adapter(tmp_path, handler).fetch(
        _request(), output_ref="data/records/ibkr/raw.xml"
    )
    source = SourceResult.model_validate(result["source_result"])
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    assert source.quality == "limited"
    assert "cutoff_timezone_unknown" in source.errors
    assert source.observed_at is None and source.available_at is None
    assert result["raw_payload"] == MULTI
    assert result["normalized"]["report_to_dates"] == ["20260918"]
    assert result["normalized"]["when_generated_raw"] == ["20260919;020000"]
    assert result["normalized"]["t_plus_one"] is True
    assert len(snapshot.accounts) == 2
    assert {b.currency for a in snapshot.accounts for b in a.balances} == {"USD", "EUR"}
    assert {p.account_ref for p in snapshot.positions} == {"SYNTH-A", "SYNTH-B"}
    assert snapshot.reported_at is None
    assert all(request.method == "GET" for request in calls)
    assert [request.url.path.rsplit("/", 1)[-1] for request in calls] == [
        "SendRequest", "GetStatement", "GetStatement"
    ]


def test_explicit_empty_position_sections_are_confirmed_empty(tmp_path: Path) -> None:
    report = """<FlexQueryResponse type="AF"><FlexStatements count="2"><FlexStatement accountId="SYNTH-A" toDate="20260918"><AccountInformation accountId="SYNTH-A" currency="USD"/><CashReportCurrency accountId="SYNTH-A" currency="USD" endingCash="0"/><OpenPositions count="0"/></FlexStatement><FlexStatement accountId="SYNTH-B" toDate="20260918"><AccountInformation accountId="SYNTH-B" currency="EUR"/><CashReportCurrency accountId="SYNTH-B" currency="EUR" endingCash="0"/><OpenPositions count="0"/></FlexStatement></FlexStatements></FlexQueryResponse>"""
    responses = iter([SEND_OK, report])
    adapter = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses)))
    result = adapter.fetch(_request(), output_ref="data/records/empty/raw.xml")
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    assert snapshot.positions == ()
    assert snapshot.complete_read is True
    assert snapshot.confirmed_empty is True


def test_missing_position_section_is_not_empty_portfolio(tmp_path: Path) -> None:
    report = """<FlexQueryResponse type="AF"><FlexStatements count="1"><FlexStatement accountId="A"><AccountInformation accountId="A" currency="USD"/></FlexStatement></FlexStatements></FlexQueryResponse>"""
    responses = iter([SEND_OK, report])
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        _request(), output_ref="data/records/missing/raw.xml"
    )
    assert result["portfolio_snapshot"] is None
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"
    assert any("OpenPositions" in gap["required_content"] for gap in result["gaps"])


def test_accounts_and_executions_use_only_read_protocol(tmp_path: Path) -> None:
    for operation in ("accounts", "executions"):
        seen: list[str] = []
        responses = iter([SEND_OK, MULTI])

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, text=next(responses))

        result = _adapter(tmp_path, handler).fetch(
            _request(operation), output_ref=f"data/records/{operation}/raw.xml"
        )
        assert result["portfolio_snapshot"] is None
        assert all(path.endswith(("SendRequest", "GetStatement")) for path in seen)
        if operation == "accounts":
            assert len(result["normalized"]["accounts"]) == 2
        else:
            assert result["normalized"]["executions"][0]["tradeID"] == "TR-A"


def test_csv_existing_query_is_preserved_with_explicit_limited_coverage(tmp_path: Path) -> None:
    csv_body = "accountId,currency,endingCash\r\nA,USD,10.00\r\n"
    responses = iter([SEND_OK, csv_body])
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        _request("accounts"), output_ref="data/records/csv/raw.csv"
    )
    assert result["raw_payload"] == csv_body
    assert result["normalized"]["raw_format"] == "csv"
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"
    assert result["portfolio_snapshot"] is None


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (401, "private body", "unauthorized"),
        (429, "private body", "rate_limited"),
        (500, "private body", "external"),
        (200, "not xml or csv", "invalid_response"),
    ],
)
def test_http_and_malformed_failures_are_sanitized(
    tmp_path: Path, status: int, body: str, reason: str
) -> None:
    result = _adapter(tmp_path, lambda _: httpx.Response(status, text=body)).fetch(
        _request(), output_ref="data/records/fail/raw.xml"
    )
    source = SourceResult.model_validate(result["source_result"])
    assert source.quality == "failed" and reason in source.errors
    assert result["raw_payload"] is None and result["portfolio_snapshot"] is None
    assert body not in str(result)


def test_invalid_query_is_not_retried(tmp_path: Path) -> None:
    invalid = """<FlexStatementResponse><Status>Fail</Status><ErrorCode>1014</ErrorCode><ErrorMessage>Query is invalid</ErrorMessage></FlexStatementResponse>"""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=invalid)

    result = _adapter(tmp_path, handler).fetch(
        _request(), output_ref="data/records/invalid/raw.xml"
    )
    assert calls == 1
    assert "invalid_query" in result["source_result"]["errors"]


def test_pending_exhaustion_is_failed_and_bounded(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=SEND_OK if calls == 1 else PENDING)

    result = _adapter(tmp_path, handler, poll_attempts=2).fetch(
        _request(), output_ref="data/records/pending/raw.xml"
    )
    assert calls == 3
    assert result["source_result"]["quality"] == "failed"
    assert "pending" in result["source_result"]["errors"]


def test_token_reflection_and_xml_entities_are_dropped(tmp_path: Path) -> None:
    for body in (
        "synthetic-token,accountId,currency\r\nA,USD\r\n",
        '<!DOCTYPE x [<!ENTITY y SYSTEM "file:///x">]><x>&y;</x>',
    ):
        responses = iter([SEND_OK, body])
        result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
            _request(), output_ref="data/records/unsafe/raw.xml"
        )
        assert result["raw_payload"] is None
        assert result["source_result"]["quality"] == "failed"


def test_missing_identity_and_ambiguous_position_are_limited_without_defaults(
    tmp_path: Path,
) -> None:
    report = """<FlexQueryResponse type="AF"><FlexStatements count="1"><FlexStatement toDate="20260918"><AccountInformation/><CashReportCurrency endingCash="12.5"/><OpenPositions><OpenPosition symbol="ACME" position="1"/></OpenPositions></FlexStatement></FlexStatements></FlexQueryResponse>"""
    responses = iter([SEND_OK, report])
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        _request(), output_ref="data/records/unknown/raw.xml"
    )
    assert result["portfolio_snapshot"] is None
    assert result["normalized"]["accounts"] == []
    assert result["normalized"]["positions"] == []
    assert result["normalized"]["excluded_rows"]
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"


def test_position_with_unreported_account_is_excluded_instead_of_breaking_snapshot(
    tmp_path: Path,
) -> None:
    report = """<FlexQueryResponse type="AF"><FlexStatements count="2"><FlexStatement accountId="SYNTH-A"><AccountInformation accountId="SYNTH-A" currency="USD"/><CashReportCurrency accountId="SYNTH-A" currency="USD" endingCash="1"/><OpenPositions><OpenPosition accountId="OTHER" symbol="ACME" assetCategory="STK" currency="USD" position="1" market="US" listingExchange="XNAS"/></OpenPositions></FlexStatement><FlexStatement accountId="SYNTH-B"><AccountInformation accountId="SYNTH-B" currency="EUR"/><CashReportCurrency accountId="SYNTH-B" currency="EUR" endingCash="1"/><OpenPositions count="0"/></FlexStatement></FlexStatements></FlexQueryResponse>"""
    responses = iter([SEND_OK, report])
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        _request(), output_ref="data/records/unlinked/raw.xml"
    )
    assert result["portfolio_snapshot"] is None
    assert result["normalized"]["positions"] == []
    assert any(
        row["reason"] == "account_ref_not_present_in_account_sections"
        for row in result["normalized"]["excluded_rows"]
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"


def test_historical_cutoff_excludes_later_or_unproven_report_rows(tmp_path: Path) -> None:
    responses = iter([SEND_OK, MULTI])
    request = _request()
    request["as_of"] = "2026-09-17T23:59:59Z"
    result = _adapter(
        tmp_path,
        lambda _: httpx.Response(200, text=next(responses)),
        credential_overrides={"IBKR_FLEX_QUERY_TIMEZONE": "UTC"},
    ).fetch(
        request, output_ref="data/records/historical/raw.json"
    )
    assert result["raw_payload"] == MULTI
    assert result["normalized"]["positions"] == []
    assert result["normalized"]["historical_eligibility"] == "not_proven"
    assert result["portfolio_snapshot"] is None
    assert "after_as_of_cutoff" in result["source_result"]["errors"]


def test_older_report_with_unknown_availability_is_retained_but_not_pit_proven(
    tmp_path: Path,
) -> None:
    responses = iter([SEND_OK, MULTI])
    request = _request()
    request["as_of"] = "2026-09-20T23:59:59Z"
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        request, output_ref="data/records/unproven-history/raw.json"
    )
    assert len(result["normalized"]["positions"]) == 2
    assert result["normalized"]["historical_eligibility"] == "not_proven"
    assert result["portfolio_snapshot"] is not None
    assert "historical_availability_unproven" in result["source_result"]["errors"]
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"


def test_unknown_required_field_is_rejected_before_http(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=SEND_OK)

    request = _request()
    request["required_fields"] = ["made_up_field"]
    result = _adapter(tmp_path, handler).fetch(
        request, output_ref="data/records/unsupported/raw.json"
    )
    assert calls == 0
    assert result["source_result"]["errors"] == ["invalid"]


def test_required_position_field_checks_every_returned_row(tmp_path: Path) -> None:
    report = MULTI.replace(' positionValue="2000"', '')
    responses = iter([SEND_OK, report])
    request = _request()
    request["required_fields"] = ["market_value"]
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        request, output_ref="data/records/per-row/raw.json"
    )
    assert "required_fields_missing" in result["source_result"]["errors"]
    assert any("market_value" in gap["required_content"] for gap in result["gaps"])


def test_explicit_empty_positions_satisfy_row_fields_without_fake_rows(tmp_path: Path) -> None:
    report = """<FlexQueryResponse type="AF"><FlexStatements count="2"><FlexStatement accountId="SYNTH-A"><AccountInformation accountId="SYNTH-A" currency="USD"/><CashReportCurrency accountId="SYNTH-A" currency="USD" endingCash="0"/><OpenPositions count="0"/></FlexStatement><FlexStatement accountId="SYNTH-B"><AccountInformation accountId="SYNTH-B" currency="EUR"/><CashReportCurrency accountId="SYNTH-B" currency="EUR" endingCash="0"/><OpenPositions count="0"/></FlexStatement></FlexStatements></FlexQueryResponse>"""
    responses = iter([SEND_OK, report])
    request = _request()
    request["required_fields"] = ["symbol", "quantity"]
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        request, output_ref="data/records/empty-fields/raw.json"
    )
    assert "required_fields_missing" not in result["source_result"]["errors"]
    assert result["portfolio_snapshot"]["confirmed_empty"] is True


def test_missing_accounts_and_execution_sections_limit_the_matching_operation(
    tmp_path: Path,
) -> None:
    report = """<FlexQueryResponse type="AF"><FlexStatements count="2"><FlexStatement accountId="SYNTH-A"><AccountInformation accountId="SYNTH-A" currency="USD"/></FlexStatement><FlexStatement accountId="SYNTH-B"><AccountInformation accountId="SYNTH-B" currency="EUR"/></FlexStatement></FlexStatements></FlexQueryResponse>"""
    for operation in ("accounts", "executions"):
        responses = iter([SEND_OK, report])
        result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
            _request(operation), output_ref=f"data/records/missing-{operation}/raw.json"
        )
        assert "missing_section" in result["source_result"]["errors"]


def test_non_stock_position_is_not_labeled_as_shares(tmp_path: Path) -> None:
    report = MULTI.replace('assetCategory="STK"', 'assetCategory="OPT"', 1)
    responses = iter([SEND_OK, report])
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        _request(), output_ref="data/records/non-stock/raw.json"
    )
    assert len(result["normalized"]["positions"]) == 1
    assert any(row["reason"] == "unsupported_or_missing_asset_category" for row in result["normalized"]["excluded_rows"])
    assert result["portfolio_snapshot"]["complete_read"] is False


def test_non_activity_query_is_not_relabelled_t_plus_one(tmp_path: Path) -> None:
    report = MULTI.replace('type="AF"', 'type="TC"')
    responses = iter([SEND_OK, report])
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        _request(), output_ref="data/records/tc/raw.json"
    )
    assert result["normalized"]["query_kind"] == "unknown_or_unsupported"
    assert result["normalized"]["t_plus_one"] is None
    assert result["normalized"]["positions"] == []
    assert result["portfolio_snapshot"] is None
    assert "unsupported_query_type" in result["source_result"]["errors"]


def test_known_exchange_maps_market_but_missing_exchange_remains_optional(tmp_path: Path) -> None:
    report = MULTI.replace(' market="US"', '', 1).replace(' listingExchange="XETR"', '', 1)
    responses = iter([SEND_OK, report])
    result = _adapter(tmp_path, lambda _: httpx.Response(200, text=next(responses))).fetch(
        _request(), output_ref="data/records/identity/raw.json"
    )
    positions = result["normalized"]["positions"]
    assert positions[0]["security"]["market"] == "US"
    assert positions[1]["security"]["market"] == "EU"
    assert positions[1]["security"]["exchange"] is None


def test_verified_query_timezone_enables_generation_instant_and_reported_at_requirement(
    tmp_path: Path,
) -> None:
    responses = iter([SEND_OK, MULTI])
    settings = _settings(tmp_path, IBKR_FLEX_QUERY_TIMEZONE="UTC")
    adapter = IbkrFlexReadOnlyAdapter(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=next(responses)))),
        clock=lambda: NOW,
        sleeper=lambda _: None,
        monotonic=lambda: 100.0,
    )
    request = _request()
    request["required_fields"] = ["reported_at"]
    result = adapter.fetch(request, output_ref="data/records/tz/raw.json")
    assert result["source_result"]["available_at"] == "2026-09-19T02:00:00Z"
    assert result["portfolio_snapshot"]["reported_at"] == "2026-09-19T02:00:00Z"
    assert "required_fields_missing" not in result["source_result"]["errors"]


def test_execution_after_cutoff_is_excluded_even_if_report_date_is_not_later(
    tmp_path: Path,
) -> None:
    report = MULTI.replace('dateTime="20260918;140000"', 'dateTime="20260922;140000"')
    responses = iter([SEND_OK, report])
    request = _request("executions")
    request["required_fields"] = ["trade_id"]
    result = _adapter(
        tmp_path,
        lambda _: httpx.Response(200, text=next(responses)),
        credential_overrides={"IBKR_FLEX_QUERY_TIMEZONE": "UTC"},
    ).fetch(
        request, output_ref="data/records/future-trade/raw.json"
    )
    assert result["normalized"]["executions"] == []
    assert any(row["reason"] == "after_as_of_cutoff" for row in result["normalized"]["excluded_rows"])
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"


def test_provider_timezone_controls_date_cutoff_across_utc_midnight(tmp_path: Path) -> None:
    report = MULTI.replace('toDate="20260918"', 'toDate="20260919"')
    responses = iter([SEND_OK, report])
    request = _request()
    request["as_of"] = "2026-09-19T00:30:00Z"  # 2026-09-18 in New York
    result = _adapter(
        tmp_path,
        lambda _: httpx.Response(200, text=next(responses)),
        credential_overrides={"IBKR_FLEX_QUERY_TIMEZONE": "America/New_York"},
    ).fetch(request, output_ref="data/records/midnight/raw.json")
    assert result["normalized"]["positions"] == []
    assert result["normalized"]["cutoff_timezone"] == "America/New_York"
    assert "after_as_of_cutoff" in result["source_result"]["errors"]


def test_invalid_report_and_trade_calendar_dates_are_retained_raw_and_limited(
    tmp_path: Path,
) -> None:
    invalid_report = MULTI.replace('toDate="20260918"', 'toDate="20261340"')
    responses = iter([SEND_OK, invalid_report])
    report_result = _adapter(
        tmp_path,
        lambda _: httpx.Response(200, text=next(responses)),
        credential_overrides={"IBKR_FLEX_QUERY_TIMEZONE": "UTC"},
    ).fetch(_request(), output_ref="data/records/invalid-report-date/raw.json")
    assert report_result["raw_payload"] == invalid_report
    assert "invalid_report_date" in report_result["source_result"]["errors"]
    assert report_result["normalized"]["invalid_report_dates"] == ["20261340"]

    invalid_trade = MULTI.replace('dateTime="20260918;140000"', 'dateTime="20261340;140000"')
    responses = iter([SEND_OK, invalid_trade])
    trade_result = _adapter(
        tmp_path,
        lambda _: httpx.Response(200, text=next(responses)),
        credential_overrides={"IBKR_FLEX_QUERY_TIMEZONE": "UTC"},
    ).fetch(_request("executions"), output_ref="data/records/invalid-trade-date/raw.json")
    assert trade_result["raw_payload"] == invalid_trade
    assert trade_result["normalized"]["executions"] == []
    assert any(row["reason"] == "invalid_trade_date" for row in trade_result["normalized"]["excluded_rows"])
    assert SourceResult.model_validate(trade_result["source_result"]).quality == "limited"


def test_operation_query_reference_selects_configured_mapping(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/SendRequest"):
            seen.append(request.url.params["q"])
            return httpx.Response(200, text=SEND_OK)
        return httpx.Response(200, text=MULTI)

    settings = _settings(tmp_path, IBKR_FLEX_QUERY_ID_POSITIONS="positions-query")
    adapter = IbkrFlexReadOnlyAdapter(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
        sleeper=lambda _: None,
        monotonic=lambda: 100.0,
    )
    adapter.fetch(
        _request(query_ref="positions"), output_ref="data/records/mapped/raw.xml"
    )
    assert seen == ["positions-query"]


def test_process_local_send_pacing_covers_per_second_and_ten_per_minute(
    tmp_path: Path,
) -> None:
    sleeps: list[float] = []
    call_number = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_number
        call_number += 1
        return httpx.Response(200, text=SEND_OK if request.url.path.endswith("/SendRequest") else MULTI)

    adapter = IbkrFlexReadOnlyAdapter(
        _settings(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
        sleeper=sleeps.append,
        monotonic=lambda: 100.0,
    )
    for index in range(11):
        request = _request("accounts")
        request["request_id"] = f"pacing-{index}"
        adapter.fetch(request, output_ref=f"data/records/pacing-{index}/raw.xml")
    assert call_number == 22
    assert any(wait >= 60.0 for wait in sleeps)
    assert any(wait == 1.0 for wait in sleeps)


def test_invalid_request_output_path_and_disabled_source_make_no_http_call(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=SEND_OK)

    disabled = Settings.model_validate(
        {"root": tmp_path, "credentials": {"IBKR_FLEX_TOKEN": "x", "IBKR_FLEX_QUERY_ID": "q"}, "enabled_sources": ["tiingo"]}
    )
    adapter = IbkrFlexReadOnlyAdapter(disabled, client=httpx.Client(transport=httpx.MockTransport(handler)))
    for request, output_ref in (
        (_request("submit_order"), "data/records/x/raw.xml"),
        (_request(), "../escape.xml"),
        ({**_request(), "source": "longbridge_oauth"}, "data/records/x/raw.xml"),
    ):
        result = adapter.fetch(request, output_ref=output_ref)
        assert result["source_result"]["quality"] == "failed"
    assert calls == 0


def test_gaps_validate_and_use_request_identity(tmp_path: Path) -> None:
    result = _adapter(tmp_path, lambda _: httpx.Response(429, text="private")).fetch(
        _request(), output_ref="data/records/gap/raw.xml"
    )
    gaps = [DataGap.model_validate(item) for item in result["gaps"]]
    assert gaps and all(gap.request_id == "fixture-positions" for gap in gaps)
    assert all(gap.attempts[0]["source"] == "ibkr_flex" for gap in gaps)
