from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from cash_research.config import Settings
from cash_research.models import DataGap, Evidence, SourceResult
from cash_research.sources.finnhub import FinnhubAdapter


OUTPUT_REF = "data/records/rec_00000000000000000000000000000000/sources/finnhub.json"


def _settings(tmp_path: Path, *, key: str = "synthetic-key", enabled: bool = True) -> Settings:
    return Settings(
        root=tmp_path,
        enabled_sources=("finnhub",) if enabled else ("tiingo",),
        credentials={"FINNHUB_API_KEY": SecretStr(key)} if key else {},
    )


def _quote_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "request_id": "request-finnhub-quote",
        "source": "finnhub",
        "operation": "quote",
        "subject": {"market": "US", "exchange": "XNAS", "symbol": "SYNQ", "currency": "USD"},
        "as_of": "2026-01-15T15:30:00Z",
        "parameters": {},
        "required_fields": ["current_price", "currency", "observed_at"],
    }
    request.update(overrides)
    return request


def _news_request(*, market: str = "US", **overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "request_id": "request-finnhub-news",
        "source": "finnhub",
        "operation": "news",
        "subject": {"market": market, "exchange": "XNAS" if market == "US" else "XHKG", "symbol": "SYNN", "currency": "USD" if market == "US" else "HKD"},
        "as_of": "2026-01-15T16:00:00Z",
        "parameters": {"from": "2026-01-14", "to": "2026-01-15"},
        "required_fields": ["headline", "published_at", "source", "url"],
    }
    request.update(overrides)
    return request


def _adapter(
    tmp_path: Path,
    handler: object,
    *,
    key: str = "synthetic-key",
    enabled: bool = True,
) -> tuple[FinnhubAdapter, httpx.Client]:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.Client(transport=transport)
    return FinnhubAdapter(_settings(tmp_path, key=key, enabled=enabled), client=client), client


def _validate(result: dict[str, object]) -> SourceResult:
    assert {"source_result", "raw_payload", "normalized", "evidence", "gaps"} <= set(result)
    source = SourceResult.model_validate(result["source_result"])
    for item in result["evidence"]:  # type: ignore[union-attr]
        Evidence.model_validate(item)
    for item in result["gaps"]:  # type: ignore[union-attr]
        gap = DataGap.model_validate(item)
        assert gap.request_id.startswith("request-finnhub")
    return source


def test_quote_preserves_raw_fields_and_missing_provider_time(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/quote"
        assert request.url.params["symbol"] == "SYNQ"
        assert request.url.params["token"] == "synthetic-key"
        return httpx.Response(200, json={"c": 101.25, "d": 1.25, "dp": 1.25, "h": 102.0, "l": 99.5, "o": 100.0, "pc": 100.0})

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()

    source = _validate(result)
    assert source.quality == "limited"
    assert source.observed_at is None and source.available_at is None
    assert set(source.unknown_reasons) == {"observed_at", "available_at"}
    assert result["raw_payload"]["c"] == 101.25  # type: ignore[index]
    normalized = result["normalized"]
    assert normalized["actual_source"] == "finnhub:/quote"  # type: ignore[index]
    assert normalized["raw_locator"] == ""  # type: ignore[index]
    assert normalized["current_price"] == {"value": 101.25, "unit": "currency_per_share", "currency": "USD"}  # type: ignore[index]
    assert source.payload_ref == OUTPUT_REF


def test_quote_uses_returned_unix_time_but_never_as_of_as_event_time(tmp_path: Path) -> None:
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(200, json={"c": 5.0, "h": 5.1, "l": 4.9, "o": 5.0, "pc": 4.8, "d": 0.2, "dp": 4.16, "t": 1768482000}),
    )
    try:
        result = adapter.fetch(_quote_request(as_of="2026-01-20T00:00:00Z"), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.observed_at is not None
    assert source.observed_at.isoformat() == "2026-01-15T13:00:00+00:00"
    assert source.observed_at.isoformat() != "2026-01-20T00:00:00+00:00"
    assert source.available_at is None


def test_quote_after_cutoff_is_retained_raw_but_not_presented_as_requested_price(
    tmp_path: Path,
) -> None:
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(200, json={"c": 5.0, "h": 5.1, "l": 4.9, "o": 5.0, "pc": 4.8, "t": 1768485600}),
    )
    try:
        result = adapter.fetch(
            _quote_request(as_of="2026-01-15T13:00:00Z"), output_ref=OUTPUT_REF
        )
    finally:
        client.close()
    source = _validate(result)
    assert source.errors == ("stale",)
    assert result["raw_payload"]["c"] == 5.0  # type: ignore[index]
    assert result["normalized"]["usable_for_as_of"] is False  # type: ignore[index]
    assert result["normalized"]["current_price"] is None  # type: ignore[index]
    assert any("as_of" in gap["required_content"] for gap in result["gaps"])  # type: ignore[index]


@pytest.mark.parametrize("current", [None, False, 0])
def test_quote_rejects_missing_false_zero_or_nonfinite_current_price(
    tmp_path: Path, current: object
) -> None:
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(200, json={"c": current, "h": 1, "l": 1, "o": 1, "pc": 1}),
    )
    try:
        result = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.quality == "failed"
    expected = (
        ("empty",)
        if current is None or (not isinstance(current, bool) and current == 0)
        else ("invalid",)
    )
    assert source.errors == expected
    assert result["raw_payload"] is not None


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_quote_rejects_nonfinite_json_numbers(tmp_path: Path, literal: str) -> None:
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(
            200,
            content=(f'{{"c":{literal},"h":1,"l":1,"o":1,"pc":1}}').encode(),
            headers={"content-type": "application/json"},
        ),
    )
    try:
        result = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(result).errors == ("invalid",)


def test_company_news_preserves_publisher_locator_and_unknown_availability(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/company-news"
        assert request.url.params["from"] == "2026-01-14"
        assert request.url.params["to"] == "2026-01-15"
        return httpx.Response(
            200,
            json=[
                {"id": 12, "datetime": 1768485600, "headline": "Synthetic update", "summary": "Summary", "source": "Synthetic Wire", "url": "https://example.test/news/12", "related": "SYNN", "category": "company"},
                {"id": 13, "headline": "No time update", "summary": "Summary", "source": "Other Wire", "url": "https://example.test/news/13", "related": "SYNN", "category": "company"},
            ],
        )

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(_news_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()

    source = _validate(result)
    assert source.quality == "limited"
    assert source.available_at is None
    evidence = [Evidence.model_validate(item) for item in result["evidence"]]  # type: ignore[union-attr]
    assert evidence[0].published_at is not None
    assert evidence[0].locator == "/0"
    assert evidence[0].source_ref == OUTPUT_REF
    assert evidence[1].published_at is None
    assert evidence[1].unknown_reasons["published_at"]
    assert all(item.unknown_reasons["available_at"] for item in evidence)
    assert result["normalized"]["publisher_urls"] == ["https://example.test/news/12", "https://example.test/news/13"]  # type: ignore[index]
    assert any(gap["required_content"] == "required_field:published_at" for gap in result["gaps"])  # type: ignore[index]


def test_company_news_excludes_after_cutoff_and_outside_window_but_keeps_raw(
    tmp_path: Path,
) -> None:
    payload = [
        {"id": 1, "datetime": 1768399200, "headline": "Inside", "source": "Wire", "url": "https://example.test/1"},
        {"id": 2, "datetime": 1768572000, "headline": "After cutoff", "source": "Wire", "url": "https://example.test/2"},
        {"id": 3, "datetime": 1768312800, "headline": "Outside start", "source": "Wire", "url": "https://example.test/3"},
    ]
    adapter, client = _adapter(
        tmp_path, lambda request: httpx.Response(200, json=payload)
    )
    try:
        result = adapter.fetch(
            _news_request(as_of="2026-01-15T16:00:00Z"), output_ref=OUTPUT_REF
        )
    finally:
        client.close()
    assert len(result["raw_payload"]) == 3  # type: ignore[arg-type]
    assert len(result["evidence"]) == 1  # type: ignore[arg-type]
    assert result["evidence"][0]["claim"] == "Inside"  # type: ignore[index]
    assert result["normalized"]["excluded_after_cutoff"] == 1  # type: ignore[index]
    assert result["normalized"]["excluded_outside_window"] == 1  # type: ignore[index]


def test_hk_company_news_keeps_official_coverage_limitation(tmp_path: Path) -> None:
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(200, json=[{"id": 1, "datetime": 1768485600, "headline": "HK synthetic", "source": "Wire", "url": "https://example.test/hk/1"}]),
    )
    try:
        result = adapter.fetch(_news_request(market="HK"), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.quality == "limited"
    assert any("North American" in gap["impact"] for gap in result["gaps"])  # type: ignore[index]


def test_general_news_partial_rows_and_limit_are_explicit(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/news"
        assert request.url.params["category"] == "general"
        assert request.url.params["minId"] == "10"
        return httpx.Response(200, json=[{"id": 11, "datetime": 1768485600, "headline": "Valid", "source": "Wire", "url": "https://example.test/11"}, "bad-row", {"id": 12, "datetime": 1768489200, "headline": "Second", "source": "Wire", "url": "https://example.test/12"}])

    request = {
        **_news_request(),
        "subject": "general market news",
        "parameters": {"category": "general", "min_id": 10, "limit": 1},
    }
    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(request, output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.quality == "limited"
    assert set(source.errors) == {"invalid_rows", "truncated"}
    assert len(result["raw_payload"]) == 3  # type: ignore[arg-type]
    assert len(result["evidence"]) == 1  # type: ignore[arg-type]
    assert result["normalized"]["returned_count"] == 3  # type: ignore[index]
    assert result["normalized"]["selected_count"] == 1  # type: ignore[index]
    assert len(result["gaps"]) == 2  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "unauthorized"), (403, "unauthorized"), (429, "rate_limited"), (500, "external")],
)
def test_http_failures_are_sanitized_without_body_or_credential(
    tmp_path: Path, status: int, expected: str
) -> None:
    secret = "do-not-echo-secret"
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(status, text=f"provider body {secret}"),
        key=secret,
    )
    try:
        result = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.quality == "failed"
    assert source.errors == (expected,)
    assert secret not in str(result)
    assert "provider body" not in str(result)
    assert result["normalized"]["http_status"] == status  # type: ignore[index]


def test_success_payload_reflecting_credential_is_discarded(tmp_path: Path) -> None:
    secret = "do-not-persist"
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(200, json={"error": f"key {secret} invalid", "c": 100.0}),
        key=secret,
    )
    try:
        result = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.errors == ("invalid",)
    assert result["raw_payload"] is None
    assert secret not in str(result)


def test_news_url_reflecting_credential_is_discarded(tmp_path: Path) -> None:
    secret = "news-key-do-not-persist"
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "datetime": 1768485600,
                    "headline": "Synthetic",
                    "source": "Wire",
                    "url": f"https://example.test/article?token={secret}",
                }
            ],
        ),
        key=secret,
    )
    try:
        result = adapter.fetch(_news_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(result).errors == ("invalid",)
    assert result["raw_payload"] is None
    assert secret not in str(result)


def test_untrusted_retry_after_is_not_copied_to_metadata(tmp_path: Path) -> None:
    secret = "retry-secret"
    adapter, client = _adapter(
        tmp_path,
        lambda request: httpx.Response(
            429, headers={"Retry-After": f"later-{secret}"}
        ),
        key=secret,
    )
    try:
        result = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(result).errors == ("rate_limited",)
    assert "retry_after" not in result["normalized"]  # type: ignore[operator]
    assert secret not in str(result)


def test_non_json_and_all_invalid_news_are_external_or_invalid(tmp_path: Path) -> None:
    responses = iter(
        [
            httpx.Response(200, text="not json", headers={"content-type": "text/plain"}),
            httpx.Response(200, json=["bad", {"headline": "", "url": "https://example.test"}]),
        ]
    )
    adapter, client = _adapter(tmp_path, lambda request: next(responses))
    try:
        non_json = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
        invalid_news = adapter.fetch(_news_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    assert _validate(non_json).errors == ("external",)
    assert _validate(invalid_news).errors == ("invalid",)
    assert invalid_news["raw_payload"] is not None


@pytest.mark.parametrize(
    "source_request",
    [
        _quote_request(operation="bars"),
        _quote_request(source="other"),
        _quote_request(subject={"market": "CN", "exchange": "XSHG", "symbol": "600000", "currency": "CNY"}),
        _quote_request(as_of="2026-01-15T15:30:00"),
    ],
)
def test_invalid_or_unsupported_request_never_calls_http(
    tmp_path: Path, source_request: dict[str, object]
) -> None:
    calls = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(source_request, output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert source.quality == "failed"
    assert source.errors[0] in {"invalid", "unsupported"}
    assert calls == 0


def test_unsupported_required_field_never_calls_http(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(
            _quote_request(required_fields=["current_price", "analyst_target"]),
            output_ref=OUTPUT_REF,
        )
    finally:
        client.close()
    source = _validate(result)
    assert source.errors == ("unsupported",)
    assert result["normalized"]["unsupported_required_fields"] == ["analyst_target"]  # type: ignore[index]
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
        result = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
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
        result = adapter.fetch(_quote_request(), output_ref="../escape.json")
    finally:
        client.close()
    assert _validate(result).errors == ("invalid",)
    assert calls == 0


def test_retrieved_at_is_captured_after_http_completion_and_gap_attempts_are_timed(
    tmp_path: Path,
) -> None:
    completed: datetime | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal completed
        completed = datetime.now(timezone.utc)
        return httpx.Response(200, json={"c": 100.0, "h": 101.0, "l": 99.0, "o": 100.0, "pc": 99.5})

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = adapter.fetch(_quote_request(), output_ref=OUTPUT_REF)
    finally:
        client.close()
    source = _validate(result)
    assert completed is not None and source.retrieved_at >= completed
    assert all("at" in attempt for gap in result["gaps"] for attempt in gap["attempts"])  # type: ignore[index]
