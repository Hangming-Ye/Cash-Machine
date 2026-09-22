from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from cash_research.config import Settings
from cash_research.models import DataGap, SourceResult
from cash_research.sources.tiingo import TiingoAdapter


OUTPUT_REF = "data/records/rec_00000000000000000000000000000000/sources/tiingo.json"


def _settings(tmp_path: Path, *, key: str = "synthetic-key", enabled: bool = True) -> Settings:
    return Settings(
        root=tmp_path,
        enabled_sources=("tiingo",) if enabled else ("finnhub",),
        credentials={"TIINGO_API_KEY": SecretStr(key)} if key else {},
    )


def _request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "request_id": "request-tiingo-bars",
        "source": "tiingo",
        "operation": "bars",
        "subject": {"market": "US", "exchange": "XNAS", "symbol": "SYNB", "currency": "USD"},
        "as_of": "2026-01-15T23:00:00Z",
        "parameters": {
            "start_date": "2026-01-13",
            "end_date": "2026-01-14",
            "bar_interval": "1d",
            "price_basis": "raw",
        },
        "required_fields": [
            "raw_ohlcv",
            "adjusted_ohlcv",
            "div_cash",
            "split_factor",
            "market_date",
        ],
    }
    value.update(overrides)
    return value


def _rows() -> list[dict[str, object]]:
    return [
        {
            "date": "2026-01-13T00:00:00.000Z",
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 1000,
            "adjOpen": 5.0,
            "adjHigh": 5.5,
            "adjLow": 4.75,
            "adjClose": 5.25,
            "adjVolume": 2000,
            "divCash": 0.0,
            "splitFactor": 2.0,
        },
        {
            "date": "2026-01-14T00:00:00.000Z",
            "open": 5.3,
            "high": 5.6,
            "low": 5.1,
            "close": 5.5,
            "volume": None,
            "adjOpen": 5.3,
            "adjHigh": 5.6,
            "adjLow": 5.1,
            "adjClose": 5.5,
            "adjVolume": 2100,
            "divCash": 0.1,
            "splitFactor": 1.0,
        },
    ]


def _adapter(
    tmp_path: Path,
    handler: object,
    *,
    key: str = "synthetic-key",
    enabled: bool = True,
) -> tuple[TiingoAdapter, httpx.Client]:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return TiingoAdapter(_settings(tmp_path, key=key, enabled=enabled), client=client), client


def _validate(result: dict[str, object]) -> SourceResult:
    assert {"source_result", "raw_payload", "normalized", "evidence", "gaps"} <= set(result)
    source = SourceResult.model_validate(result["source_result"])
    assert result["evidence"] == []
    for item in result["gaps"]:  # type: ignore[union-attr]
        gap = DataGap.model_validate(item)
        assert gap.request_id == "request-tiingo-bars"
        assert all("at" in attempt for attempt in gap.attempts)
    return source


def test_daily_raw_basis_preserves_both_bases_actions_and_missing_raw_volume(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tiingo/daily/SYNB/prices"
        assert request.url.params["startDate"] == "2026-01-13"
        assert request.url.params["endDate"] == "2026-01-14"
        assert request.url.params["resampleFreq"] == "daily"
        assert "token" not in request.url.params
        assert request.headers["authorization"] == "Token synthetic-key"
        return httpx.Response(200, json=_rows())

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.quality == "limited"
    assert source.observed_at is None and source.available_at is None
    assert source.payload_ref == OUTPUT_REF
    assert result["raw_payload"] == _rows()
    normalized = result["normalized"]
    assert normalized["actual_source"] == "tiingo:/tiingo/daily/{ticker}/prices"  # type: ignore[index]
    assert normalized["price_basis"] == normalized["volume_basis"] == "raw"  # type: ignore[index]
    assert normalized["rows"][0]["selected"]["close"] == 10.5  # type: ignore[index]
    assert normalized["rows"][0]["selected"]["volume"] == 1000  # type: ignore[index]
    assert normalized["rows"][1]["selected"]["volume"] is None  # type: ignore[index]
    assert normalized["rows"][1]["adjusted"]["volume"] == 2100  # type: ignore[index]
    assert normalized["rows"][0]["div_cash"] == 0.0  # type: ignore[index]
    assert normalized["rows"][0]["split_factor"] == 2.0  # type: ignore[index]
    assert normalized["units"] == {"price": "USD/share", "volume": "shares", "div_cash": "USD/share", "split_factor": "ratio"}  # type: ignore[index]
    assert normalized["adjustment_status"]["history"] == "provider_history_may_revise_after_corporate_actions"  # type: ignore[index]
    assert normalized["point_in_time_status"] == "not_proven"  # type: ignore[index]
    assert any(gap["gap_id"].startswith("G-02-") for gap in result["gaps"])  # type: ignore[index]


def test_adjusted_basis_uses_adjusted_prices_and_matching_adjusted_volume(
    tmp_path: Path,
) -> None:
    adapter, client = _adapter(tmp_path, lambda request: httpx.Response(200, json=_rows()))
    request = _request(
        parameters={
            "start_date": "2026-01-13",
            "end_date": "2026-01-14",
            "bar_interval": "1d",
            "price_basis": "adjusted",
        }
    )
    try:
        result = adapter.fetch(request, output_ref=OUTPUT_REF)
    finally:
        client.close()
    normalized = result["normalized"]
    assert normalized["price_basis"] == normalized["volume_basis"] == "adjusted"  # type: ignore[index]
    assert normalized["rows"][0]["selected"] == {"open": 5.0, "high": 5.5, "low": 4.75, "close": 5.25, "volume": 2000}  # type: ignore[index]


def test_rows_after_as_of_or_outside_requested_dates_are_excluded_not_deleted(
    tmp_path: Path,
) -> None:
    rows = _rows() + [
        {**_rows()[0], "date": "2026-01-15T00:00:00.000Z"},
        {**_rows()[0], "date": "2026-01-12T00:00:00.000Z"},
    ]
    adapter, client = _adapter(tmp_path, lambda request: httpx.Response(200, json=rows))
    try:
        result = adapter.fetch(
            _request(as_of="2026-01-14T23:00:00Z"), output_ref=OUTPUT_REF
        )
    finally:
        client.close()
    assert len(result["raw_payload"]) == 4  # type: ignore[arg-type]
    assert len(result["normalized"]["rows"]) == 2  # type: ignore[index]
    assert result["normalized"]["excluded_after_cutoff"] == 1  # type: ignore[index]
    assert result["normalized"]["excluded_outside_range"] == 1  # type: ignore[index]
    assert "stale" in _validate(result).errors


def test_equivalent_as_of_instants_use_new_york_market_date(tmp_path: Path) -> None:
    rows = [{**_rows()[0], "date": "2026-01-15T00:00:00.000Z"}]
    adapter, client = _adapter(tmp_path, lambda request: httpx.Response(200, json=rows))
    request_utc = _request(
        as_of="2026-01-15T01:00:00Z",
        parameters={"start_date": "2026-01-15", "end_date": "2026-01-15", "bar_interval": "1d", "price_basis": "raw"},
    )
    request_plus_eight = {**request_utc, "as_of": "2026-01-15T09:00:00+08:00"}
    try:
        utc_result = adapter.fetch(request_utc, output_ref=OUTPUT_REF)
        plus_eight_result = adapter.fetch(request_plus_eight, output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert utc_result["normalized"]["rows"] == plus_eight_result["normalized"]["rows"] == []  # type: ignore[index]
    assert utc_result["normalized"]["excluded_after_cutoff"] == 1  # type: ignore[index]
    assert plus_eight_result["normalized"]["excluded_after_cutoff"] == 1  # type: ignore[index]


def test_partial_bad_rows_and_missing_adjustment_fields_are_limited_with_g02(
    tmp_path: Path,
) -> None:
    rows = _rows()
    rows[0].pop("adjClose")
    rows.append({"date": "bad-date", "open": 1})
    adapter, client = _adapter(tmp_path, lambda request: httpx.Response(200, json=rows))
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.quality == "limited"
    assert {"invalid_rows", "invalid_fields"} <= set(source.errors)
    assert len(result["raw_payload"]) == 3  # type: ignore[arg-type]
    assert any(gap["required_content"] == "required_field:adjusted_ohlcv" for gap in result["gaps"])  # type: ignore[index]


def test_negative_volume_and_false_adjusted_value_become_null_not_defaults(
    tmp_path: Path,
) -> None:
    rows = _rows()
    rows[0]["volume"] = -1
    rows[0]["adjClose"] = False
    adapter, client = _adapter(tmp_path, lambda request: httpx.Response(200, json=rows))
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    first = result["normalized"]["rows"][0]  # type: ignore[index]
    assert first["raw"]["volume"] is None
    assert first["adjusted"]["close"] is None
    assert first["selected"]["volume"] is None
    assert result["normalized"]["point_in_time_status"] == "not_proven"  # type: ignore[index]
    assert any(gap["gap_id"].startswith("G-02-") for gap in result["gaps"])  # type: ignore[index]


def test_inverted_ohlc_is_rejected_and_rows_are_sorted_with_raw_index(
    tmp_path: Path,
) -> None:
    later = {**_rows()[1], "volume": 100}
    earlier = _rows()[0]
    inverted = {**_rows()[0], "date": "2026-01-14T00:00:00.000Z", "low": 12.0, "high": 11.0}
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(200, json=[later, earlier, inverted]),
    )
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    rows = result["normalized"]["rows"]  # type: ignore[index]
    assert [row["market_date"] for row in rows] == ["2026-01-13", "2026-01-14"]
    assert [row["raw_index"] for row in rows] == [1, 0]
    assert "invalid_rows" in _validate(result).errors
    assert len(result["raw_payload"]) == 3  # type: ignore[arg-type]


def test_duplicate_market_date_revision_conflict_is_not_silently_selected(
    tmp_path: Path,
) -> None:
    rows = [_rows()[0], {**_rows()[0], "close": 10.25}]
    adapter, client = _adapter(tmp_path, lambda request: httpx.Response(200, json=rows))
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert "conflict" in source.errors
    assert result["normalized"]["revision_status"] == "unresolved"  # type: ignore[index]
    assert result["normalized"]["rows"] == []  # type: ignore[index]
    assert len(result["raw_payload"]) == 2  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [[], ["bad"], [{"date": "bad", "open": False, "high": 1, "low": 1, "close": 1}]],
)
def test_empty_and_all_invalid_are_distinct(tmp_path: Path, payload: object) -> None:
    adapter, client = _adapter(tmp_path, lambda request: httpx.Response(200, json=payload))
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.errors == (() if payload == [] else ("invalid",))
    assert result["normalized"]["error_reason"] == ("empty" if payload == [] else "invalid")  # type: ignore[index]


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "unauthorized"), (403, "unauthorized"), (429, "rate_limited"), (500, "external")],
)
def test_http_failures_are_sanitized(
    tmp_path: Path, status: int, expected: str
) -> None:
    secret = "do-not-echo"
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(status, text=f"body {secret}"),
        key=secret,
    )
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(result).errors == (expected,)
    assert secret not in str(result) and "body" not in str(result)
    assert result["normalized"]["http_status"] == status  # type: ignore[index]


def test_non_json_and_success_payload_credential_reflection_are_dropped(
    tmp_path: Path,
) -> None:
    responses = iter(
        [
            httpx.Response(200, text="not json"),
            httpx.Response(200, json={"error": "key synthetic-key invalid", "data": _rows()}),
        ]
    )
    adapter, client = _adapter(tmp_path, lambda request: next(responses))
    try:
        non_json = adapter.fetch(_request(), output_ref=OUTPUT_REF)
        reflected = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(non_json).errors == ("external",)
    assert _validate(reflected).errors == ("invalid",)
    assert reflected["raw_payload"] is None
    assert "synthetic-key" not in str(reflected)


def test_wrong_returned_ticker_and_nonfinite_price_are_invalid(tmp_path: Path) -> None:
    payloads = iter(
        [
            [{**_rows()[0], "ticker": "OTHER"}],
            httpx.Response(
                200,
                content=b'[{"date":"2026-01-13","open":10,"high":11,"low":9,"close":NaN,"volume":1,"adjOpen":10,"adjHigh":11,"adjLow":9,"adjClose":10,"adjVolume":1,"divCash":0,"splitFactor":1}]',
                headers={"content-type": "application/json"},
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        value = next(payloads)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    adapter, client = _adapter(tmp_path, handler)
    try:
        wrong = adapter.fetch(_request(), output_ref=OUTPUT_REF)
        nonfinite = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(wrong).errors == ("invalid",)
    assert _validate(nonfinite).errors == ("invalid",)


@pytest.mark.parametrize(
    "source_request",
    [
        _request(operation="quote"),
        _request(source="other"),
        _request(subject={"market": "HK", "exchange": "XHKG", "symbol": "SYNB", "currency": "HKD"}),
        _request(subject={"market": "US", "exchange": "XNAS", "symbol": "../SYNB", "currency": "USD"}),
        _request(subject={"market": "US", "exchange": "XNAS", "symbol": "SYN/B", "currency": "USD"}),
        _request(subject={"market": "US", "exchange": "XNAS", "symbol": "BRK.B", "currency": "USD"}),
        _request(as_of="2026-01-15T23:00:00"),
        _request(parameters={"start_date": "2026-01-14", "end_date": "2026-01-13", "bar_interval": "1d", "price_basis": "raw"}),
        _request(parameters={"start_date": "2026-01-13", "end_date": "2026-01-14", "bar_interval": "1h", "price_basis": "raw"}),
        _request(parameters={"start_date": "2026-01-13", "end_date": "2026-01-14", "bar_interval": "1d", "price_basis": "mixed"}),
        _request(required_fields=["order_book"]),
    ],
)
def test_invalid_unsupported_or_non_us_requests_never_call_http(
    tmp_path: Path, source_request: dict[str, object]
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(source_request, output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(result).errors[0] in {"invalid", "unsupported"}
    assert calls == 0


@pytest.mark.parametrize(("key", "enabled"), [("", True), ("synthetic-key", False)])
def test_missing_credential_or_disabled_source_never_calls_http(
    tmp_path: Path, key: str, enabled: bool
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(tmp_path, handler, key=key, enabled=enabled)
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(result).errors == (("unauthorized",) if not key else ("unsupported",))
    assert calls == 0


def test_unsafe_output_ref_never_calls_http(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(_request(), output_ref="../escape.json")
    finally:
        client.close()
    assert _validate(result).errors == ("invalid",)
    assert calls == 0


def test_retrieved_at_is_after_http_completion(tmp_path: Path) -> None:
    completed: datetime | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal completed
        completed = datetime.now(timezone.utc)
        return httpx.Response(200, json=_rows())

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert completed is not None and source.retrieved_at >= completed
