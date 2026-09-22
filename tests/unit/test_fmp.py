from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from cash_research.config import Settings
from cash_research.models import Evidence, SourceResult
from cash_research.sources.fmp import FmpStableAdapter


NOW = datetime(2026, 9, 21, 5, 0, tzinfo=timezone.utc)


def _settings(tmp_path: Path, *, key: str = "synthetic-fmp-key") -> Settings:
    return Settings.model_validate(
        {
            "root": tmp_path,
            "enabled_sources": ["fmp_stable"],
            "credentials": {"FMP_API_KEY": key},
        }
    )


def _request(
    *,
    operation: str,
    parameters: dict[str, object] | None = None,
    required_fields: list[str] | None = None,
    as_of: str = "2026-09-21T05:00:00Z",
) -> dict[str, object]:
    return {
        "request_id": f"fmp-{operation}-request",
        "source": "fmp_stable",
        "operation": operation,
        "subject": {
            "market": "US",
            "exchange": "XNAS",
            "symbol": "ACME",
            "currency": "USD",
        },
        "as_of": as_of,
        "parameters": parameters or {},
        "required_fields": required_fields
        or ["company_name", "market_cap", "currency", "exchange"],
    }


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_profile_uses_current_stable_fields_and_preserves_raw_payload(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/stable/profile"
        assert request.url.params["symbol"] == "ACME"
        assert request.url.params["apikey"] == "synthetic-fmp-key"
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "ACME",
                    "companyName": "ACME Synthetic Corp",
                    "price": 125.5,
                    "marketCap": 1000000000,
                    "beta": 1.2,
                    "lastDividend": 0.75,
                    "currency": "USD",
                    "exchange": "NASDAQ",
                    "industry": "Synthetic Systems",
                    "sector": "Technology",
                    "ipoDate": "2020-01-02",
                }
            ],
        )

    adapter = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    )
    result = adapter.fetch(
        _request(operation="profile"),
        output_ref="data/records/run-fmp/profile/raw.json",
    )

    source_result = SourceResult.model_validate(result["source_result"])
    evidence = tuple(Evidence.model_validate(item) for item in result["evidence"])
    assert source_result.quality == "limited"
    assert source_result.payload_ref == "data/records/run-fmp/profile/raw.json"
    assert source_result.observed_at is None
    assert source_result.available_at is None
    assert result["raw_payload"][0]["marketCap"] == 1000000000
    profile = result["normalized"]["profile"]
    assert profile["company_name"] == "ACME Synthetic Corp"
    assert profile["market_cap"] == 1000000000
    assert profile["last_dividend"] == 0.75
    assert "dividend_yield" not in profile
    assert profile["exchange"] == "NASDAQ"
    assert result["normalized"]["requested_exchange"] == "XNAS"
    assert result["normalized"]["exchange_identity_status"] == "verified"
    assert result["normalized"]["historical_eligible"] is False
    assert evidence[0].source_ref == "data/records/run-fmp/profile/raw.json"
    assert json.dumps(result).find("synthetic-fmp-key") == -1
    assert not (tmp_path / "data").exists()


def test_three_annual_statements_preserve_raw_metadata_without_claiming_pit(
    tmp_path: Path,
) -> None:
    statement_rows = {
        "/stable/income-statement": {"revenue": 1000, "netIncome": 100},
        "/stable/balance-sheet-statement": {"totalAssets": 5000, "totalDebt": 500},
        "/stable/cash-flow-statement": {"operatingCashFlow": 200, "capitalExpenditure": -50},
    }
    called: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request.url.path)
        assert request.url.params["symbol"] == "ACME"
        assert request.url.params["period"] == "annual"
        assert request.url.params["limit"] == "2"
        row = {
            "date": "2025-09-30",
            "symbol": "ACME",
            "reportedCurrency": "USD",
            "cik": "0000000001",
            "filingDate": "2025-11-01",
            "acceptedDate": "2025-11-01 06:01:36",
            "fiscalYear": "2025",
            "period": "FY",
            "link": "https://example.test/filing",
            **statement_rows[request.url.path],
        }
        return httpx.Response(200, json=[row])

    adapter = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    )
    result = adapter.fetch(
        _request(
            operation="statements",
            parameters={
                "period": "annual",
                "limit": 2,
                "statement_types": ["income", "balance", "cash"],
            },
            required_fields=[
                "reported_currency",
                "filing_date",
                "accepted_date",
                "link",
            ],
        ),
        output_ref="data/records/run-fmp/statements/raw.json",
    )

    source_result = SourceResult.model_validate(result["source_result"])
    evidence = tuple(Evidence.model_validate(item) for item in result["evidence"])
    assert source_result.quality == "complete"
    assert set(called) == set(statement_rows)
    assert set(result["raw_payload"]) == {"income", "balance", "cash"}
    assert result["raw_payload"]["income"][0]["acceptedDate"] == "2025-11-01 06:01:36"
    assert result["raw_payload"]["income"][0]["fiscalYear"] == "2025"
    assert result["raw_payload"]["income"][0]["link"] == "https://example.test/filing"
    assert result["normalized"]["point_in_time_status"] == "not_proven_no_archival_versions"
    assert result["normalized"]["statements"]["income"][0]["accepted_date_raw"] == "2025-11-01 06:01:36"
    assert result["normalized"]["statements"]["income"][0]["reported_currency"] == "USD"
    assert source_result.available_at is None
    assert all(item.available_at is None for item in evidence)


def test_statement_partial_preserves_success_and_failure_by_table(
    tmp_path: Path,
) -> None:
    times = iter(
        [
            datetime(2026, 9, 21, 5, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 21, 5, 2, tzinfo=timezone.utc),
            datetime(2026, 9, 21, 5, 3, tzinfo=timezone.utc),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stable/balance-sheet-statement":
            return httpx.Response(429, json={"Error Message": "Limit Reach"})
        value_key = (
            "revenue"
            if request.url.path == "/stable/income-statement"
            else "operatingCashFlow"
        )
        return httpx.Response(
            200,
            json=[
                {
                    "date": "2025-09-30",
                    "symbol": "ACME",
                    "reportedCurrency": "USD",
                    "filingDate": "2025-11-01",
                    "acceptedDate": "2025-11-01 06:01:36",
                    "fiscalYear": "2025",
                    "period": "FY",
                    value_key: 100,
                }
            ],
        )

    adapter = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: next(times)
    )
    result = adapter.fetch(
        _request(
            operation="statements",
            parameters={"period": "annual", "limit": 1, "statement_types": ["income", "balance", "cash"]},
            required_fields=["reported_currency"],
        ),
        output_ref="data/records/run-fmp/partial/raw.json",
    )

    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.quality == "limited"
    assert source_result.retrieved_at.isoformat() == "2026-09-21T05:03:00+00:00"
    assert result["raw_payload"]["income"]
    assert result["raw_payload"]["balance"] is None
    assert result["raw_payload"]["cash"]
    assert result["normalized"]["successful_statements"] == ["income", "cash"]
    assert result["normalized"]["failed_statements"] == {"balance": "rate_limited"}
    assert "balance:rate_limited" in source_result.errors
    gap = next(item for item in result["gaps"] if "balance" in item["required_content"])
    assert gap["attempts"][0]["at"] == "2026-09-21T05:02:00+00:00"


def test_statement_cutoff_retains_future_raw_but_excludes_it_from_normalized_history(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "date": "2025-06-30",
                    "symbol": "ACME",
                    "reportedCurrency": None,
                    "filingDate": "2025-08-01",
                    "acceptedDate": "2025-08-01 08:00:00",
                    "fiscalYear": "2025",
                    "period": "FY",
                    "revenue": 900,
                    "audited": True,
                    "badNumber": "NaN",
                },
                {
                    "date": "2025-09-30",
                    "symbol": "ACME",
                    "reportedCurrency": "USD",
                    "filingDate": "2025-11-01",
                    "acceptedDate": "2025-11-01 06:01:36",
                    "fiscalYear": "2025",
                    "period": "FY",
                    "revenue": 1000,
                },
            ],
        )

    adapter = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    )
    result = adapter.fetch(
        _request(
            operation="statements",
            parameters={"period": "annual", "limit": 2, "statement_types": ["income"]},
            required_fields=["reported_currency", "revenue"],
            as_of="2025-10-15T12:00:00Z",
        ),
        output_ref="data/records/run-fmp/cutoff/raw.json",
    )

    source_result = SourceResult.model_validate(result["source_result"])
    rows = result["normalized"]["statements"]["income"]
    excluded = result["normalized"]["excluded_rows"]["income"]
    assert len(result["raw_payload"]["income"]) == 2
    assert len(rows) == 1
    assert rows[0]["date_raw"] == "2025-06-30"
    assert rows[0]["reported_currency"] is None
    assert rows[0]["unknown_reasons"]["reported_currency"]
    assert "audited" not in rows[0]["values"]
    assert "badNumber" not in rows[0]["values"]
    assert excluded == [
        {
            "index": 1,
            "reason": "after_as_of_cutoff",
            "date_raw": "2025-09-30",
            "filing_date_raw": "2025-11-01",
            "accepted_date_raw": "2025-11-01 06:01:36",
        }
    ]
    assert source_result.quality == "limited"
    assert source_result.available_at is None


def test_current_profile_is_not_used_as_a_historical_snapshot(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "ACME",
                    "companyName": "Current ACME",
                    "marketCap": 10,
                    "currency": "USD",
                    "exchange": "NASDAQ",
                }
            ],
        )

    adapter = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    )
    result = adapter.fetch(
        _request(operation="profile", as_of="2025-01-01T00:00:00Z"),
        output_ref="data/records/run-fmp/historical-profile/raw.json",
    )

    assert SourceResult.model_validate(result["source_result"]).quality == "limited"
    assert result["raw_payload"][0]["companyName"] == "Current ACME"
    assert result["normalized"]["profile"] is None
    assert result["normalized"]["excluded_current_profile"]["company_name"] == "Current ACME"
    assert result["normalized"]["historical_eligible"] is False


def test_invalid_or_disabled_requests_make_no_http_call(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid request reached HTTP")

    disabled = Settings.model_validate(
        {"root": tmp_path, "enabled_sources": ["tiingo"], "credentials": {"FMP_API_KEY": "x"}}
    )
    cases = [
        (disabled, _request(operation="profile"), "data/records/disabled/raw.json"),
        (
            _settings(tmp_path),
            {**_request(operation="profile"), "source": "other"},
            "data/records/source/raw.json",
        ),
        (
            _settings(tmp_path),
            {
                **_request(operation="profile"),
                "subject": {"market": "US", "exchange": "NASDAQ", "symbol": "BAD/../", "currency": "USD"},
            },
            "data/records/symbol/raw.json",
        ),
        (
            _settings(tmp_path),
            _request(operation="submit_order"),
            "data/records/order/raw.json",
        ),
        (
            _settings(tmp_path),
            _request(operation="statements", parameters={"period": "quarter", "limit": 1, "statement_types": ["income"]}),
            "data/records/date/raw.json",
        ),
        (
            _settings(tmp_path),
            _request(operation="profile"),
            "../escape.json",
        ),
        (
            _settings(tmp_path),
            _request(operation="profile", required_fields=["dividend_yield"]),
            "data/records/required/raw.json",
        ),
    ]

    for settings, request, output_ref in cases:
        result = FmpStableAdapter(settings, client=_client(handler), clock=lambda: NOW).fetch(
            request, output_ref=output_ref
        )
        assert SourceResult.model_validate(result["source_result"]).quality == "failed"
    assert calls == 0


def test_http_and_payload_failures_are_sanitized_and_never_echo_credentials(
    tmp_path: Path,
) -> None:
    scenarios: list[tuple[str, Callable[[httpx.Request], httpx.Response], str]] = [
        ("401", lambda _: httpx.Response(401, text="synthetic-fmp-key"), "unauthorized"),
        ("403", lambda _: httpx.Response(403, json={"error": "bad key synthetic-fmp-key"}), "unauthorized"),
        ("429", lambda _: httpx.Response(429, text="limit synthetic-fmp-key"), "rate_limited"),
        ("500", lambda _: httpx.Response(500, text="server synthetic-fmp-key"), "external"),
        ("non-json", lambda _: httpx.Response(200, text="not json synthetic-fmp-key"), "external"),
        ("error-object", lambda _: httpx.Response(200, json={"Error Message": "Invalid API KEY synthetic-fmp-key"}), "unauthorized"),
        ("reflected", lambda _: httpx.Response(200, json=[{"symbol": "ACME", "exchange": "NASDAQ", "note": "synthetic-fmp-key"}]), "external"),
    ]

    for _, handler, reason in scenarios:
        adapter = FmpStableAdapter(
            _settings(tmp_path), client=_client(handler), clock=lambda: NOW
        )
        result = adapter.fetch(
            _request(operation="profile"),
            output_ref="data/records/run-fmp/error/raw.json",
        )
        source_result = SourceResult.model_validate(result["source_result"])
        assert source_result.quality == "failed"
        assert source_result.errors == (reason,)
        assert result["raw_payload"] is None
        assert "synthetic-fmp-key" not in json.dumps(result)


def test_profile_identity_mismatch_preserves_raw_but_never_normalizes_it(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "OTHER",
                    "companyName": "Wrong Company",
                    "marketCap": 1,
                    "currency": "USD",
                    "exchange": "NYSE",
                }
            ],
        )

    adapter = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    )
    output_ref = "data/records/run-fmp/mismatch/raw.json"
    result = adapter.fetch(_request(operation="profile"), output_ref=output_ref)

    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.quality == "failed"
    assert source_result.payload_ref == output_ref
    assert source_result.errors == ("wrong_security",)
    assert result["raw_payload"][0]["symbol"] == "OTHER"
    assert result["normalized"]["profile"] is None
    assert result["normalized"]["returned_identity"] == {
        "symbol": "OTHER",
        "exchange": "NYSE",
        "currency": "USD",
    }


def test_profile_currency_mismatch_is_rejected_as_identity_conflict(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "ACME",
                    "companyName": "Wrong Currency ACME",
                    "marketCap": 1,
                    "currency": "EUR",
                    "exchange": "NASDAQ",
                }
            ],
        )

    output_ref = "data/records/run-fmp/currency-mismatch/raw.json"
    result = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    ).fetch(_request(operation="profile"), output_ref=output_ref)

    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.quality == "failed"
    assert source_result.errors == ("wrong_security",)
    assert source_result.payload_ref == output_ref
    assert result["raw_payload"][0]["currency"] == "EUR"
    assert result["normalized"]["profile"] is None


def test_profile_missing_currency_and_nonfinite_or_boolean_numbers_remain_null(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "ACME",
                    "companyName": "Sparse ACME",
                    "price": True,
                    "marketCap": "Infinity",
                    "lastDividend": None,
                    "currency": None,
                    "exchange": "NASDAQ",
                }
            ],
        )

    result = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    ).fetch(
        _request(
            operation="profile",
            required_fields=["price", "market_cap", "currency", "exchange"],
        ),
        output_ref="data/records/run-fmp/sparse/raw.json",
    )

    source_result = SourceResult.model_validate(result["source_result"])
    profile = result["normalized"]["profile"]
    assert source_result.quality == "limited"
    assert profile["price"] is None
    assert profile["market_cap"] is None
    assert profile["currency"] is None
    assert profile["last_dividend"] is None
    assert set(result["normalized"]["unknown_reasons"]) >= {
        "price",
        "market_cap",
        "currency",
    }
    assert any("price" in gap["required_content"] for gap in result["gaps"])
    assert "USD" not in json.dumps(profile)


def test_process_environment_credential_is_used_only_when_settings_has_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FMP_API_KEY", "process-fmp-key")
    settings = Settings.model_validate(
        {"root": tmp_path, "enabled_sources": ["fmp_stable"]}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apikey"] == "process-fmp-key"
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "ACME",
                    "companyName": "ACME",
                    "marketCap": 1,
                    "currency": "USD",
                    "exchange": "NASDAQ",
                }
            ],
        )

    result = FmpStableAdapter(
        settings, client=_client(handler), clock=lambda: NOW
    ).fetch(
        _request(operation="profile"),
        output_ref="data/records/run-fmp/process-env/raw.json",
    )

    assert SourceResult.model_validate(result["source_result"]).quality == "limited"
    assert "process-fmp-key" not in json.dumps(result)


def test_missing_provider_exchange_is_unverified_not_invented_or_rejected(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "ACME",
                    "companyName": "ACME",
                    "marketCap": 1,
                    "currency": "USD",
                }
            ],
        )

    result = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    ).fetch(
        _request(operation="profile"),
        output_ref="data/records/run-fmp/missing-exchange/raw.json",
    )

    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.quality == "limited"
    assert result["raw_payload"][0].get("exchange") is None
    assert result["normalized"]["profile"]["exchange"] is None
    assert result["normalized"]["exchange_identity_status"] == "unverified"
    assert any("exchange identity" in gap["required_content"] for gap in result["gaps"])


def test_valid_empty_profile_is_distinct_from_malformed_profile_shape(
    tmp_path: Path,
) -> None:
    responses: list[object] = [[], {"unexpected": "object"}]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    adapter = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    )
    empty = adapter.fetch(
        _request(operation="profile"),
        output_ref="data/records/run-fmp/empty/raw.json",
    )
    malformed = adapter.fetch(
        _request(operation="profile"),
        output_ref="data/records/run-fmp/malformed/raw.json",
    )

    empty_result = SourceResult.model_validate(empty["source_result"])
    malformed_result = SourceResult.model_validate(malformed["source_result"])
    assert empty_result.quality == "limited"
    assert empty_result.errors == ()
    assert empty["raw_payload"] == []
    assert empty["normalized"]["empty"] is True
    assert malformed_result.quality == "failed"
    assert malformed_result.errors == ("invalid_response",)
    assert malformed["raw_payload"] == {"unexpected": "object"}
    assert malformed["normalized"]["profile"] is None


def test_valid_empty_statement_table_is_distinct_from_malformed_table_shape(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stable/income-statement":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"unexpected": request.url.path})

    result = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    ).fetch(
        _request(
            operation="statements",
            parameters={"period": "annual", "limit": 1, "statement_types": ["income", "balance"]},
            required_fields=["reported_currency"],
        ),
        output_ref="data/records/run-fmp/statement-shapes/raw.json",
    )

    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.quality == "limited"
    assert result["raw_payload"]["income"] == []
    assert result["raw_payload"]["balance"] == {
        "unexpected": "/stable/balance-sheet-statement"
    }
    assert result["normalized"]["failed_statements"] == {
        "income": "empty",
        "balance": "invalid_response",
    }


def test_mixed_valid_and_excluded_statement_rows_are_explicitly_limited(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"date": "2025-09-30", "symbol": "ACME", "reportedCurrency": "USD", "revenue": 100},
                {"date": "2025-09-30", "symbol": "OTHER", "reportedCurrency": "USD", "revenue": 200},
            ],
        )

    result = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    ).fetch(
        _request(
            operation="statements",
            parameters={"period": "annual", "limit": 2, "statement_types": ["income"]},
            required_fields=["reported_currency", "revenue"],
        ),
        output_ref="data/records/run-fmp/mixed-rows/raw.json",
    )

    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.quality == "limited"
    assert source_result.errors == ("income:excluded_rows",)
    assert result["normalized"]["successful_statements"] == ["income"]
    assert result["normalized"]["row_exclusions"] == {"income": {"wrong_security": 1}}
    assert any("excluded rows" in gap["attempts"][0]["result"] for gap in result["gaps"])


def test_all_invalid_statement_rows_fail_without_discarding_raw_payload(
    tmp_path: Path,
) -> None:
    raw_rows: list[object] = [
        {"date": "2025-09-30", "symbol": "OTHER", "reportedCurrency": "USD", "revenue": 200},
        "not-an-object",
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=raw_rows)

    output_ref = "data/records/run-fmp/all-invalid/raw.json"
    result = FmpStableAdapter(
        _settings(tmp_path), client=_client(handler), clock=lambda: NOW
    ).fetch(
        _request(
            operation="statements",
            parameters={"period": "annual", "limit": 2, "statement_types": ["income"]},
            required_fields=["reported_currency"],
        ),
        output_ref=output_ref,
    )

    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.quality == "failed"
    assert source_result.payload_ref == output_ref
    assert source_result.errors == ("income:invalid_rows",)
    assert result["raw_payload"]["income"] == raw_rows
    assert result["normalized"]["statements"]["income"] == []
    assert result["normalized"]["row_exclusions"] == {
        "income": {"wrong_security": 1, "row_not_object": 1}
    }
