from __future__ import annotations

import httpx
import pytest
import respx

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.finnhub.client import (
    FINNHUB_BASE_URL,
    FinnhubHttpClient,
    FinnhubMarketDataProvider,
    FinnhubNewsProvider,
)


def _client() -> FinnhubHttpClient:
    transport = httpx.Client(base_url=FINNHUB_BASE_URL, timeout=5.0)
    return FinnhubHttpClient(
        "test-key",
        client=transport,
        limiter=RateLimiter(calls_per_minute=10_000, min_interval=0),
        timeout=5.0,
        base_url=FINNHUB_BASE_URL,
    )


@respx.mock
def test_finnhub_quote_maps_fields() -> None:
    respx.get(f"{FINNHUB_BASE_URL}/quote").mock(
        return_value=httpx.Response(
            200,
            json={"c": 190.1, "o": 188.0, "h": 191.0, "l": 187.5, "pc": 189.0, "t": 1718472000},
        )
    )
    quote = FinnhubMarketDataProvider(_client()).get_quote("aapl")
    assert quote.symbol == "AAPL"
    assert quote.last == 190.1
    assert quote.previous_close == 189.0
    assert quote.source == "finnhub"
    assert quote.as_of.year == 2024


@respx.mock
def test_finnhub_bars_and_empty_payload() -> None:
    respx.get(f"{FINNHUB_BASE_URL}/stock/candle").mock(
        return_value=httpx.Response(
            200,
            json={
                "s": "ok",
                "t": [1718472000, 1718558400],
                "o": [1.0, 2.0],
                "h": [1.5, 2.5],
                "l": [0.5, 1.5],
                "c": [1.2, 2.2],
                "v": [10, 20],
            },
        )
    )
    bars = FinnhubMarketDataProvider(_client()).get_bars("AAPL", interval="1d", limit=10)
    assert len(bars) == 2
    assert bars[-1].close == 2.2
    assert bars[-1].volume == 20


@respx.mock
def test_finnhub_company_news() -> None:
    respx.get(f"{FINNHUB_BASE_URL}/company-news").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 99,
                    "headline": "AAPL ships new product",
                    "summary": "fixture",
                    "url": "https://example.test/aapl",
                    "source": "fixture-wire",
                    "datetime": 1718472000,
                }
            ],
        )
    )
    items = FinnhubNewsProvider(_client()).get_news("AAPL", limit=5)
    assert items[0].headline.startswith("AAPL")
    assert items[0].symbol == "AAPL"
    assert items[0].url and "aapl" in items[0].url


@respx.mock
def test_finnhub_general_news() -> None:
    respx.get(f"{FINNHUB_BASE_URL}/news").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "headline": "Markets open mixed",
                    "summary": "fixture",
                    "url": "https://example.test/mkt",
                    "source": "fixture-wire",
                    "datetime": 1718472000,
                }
            ],
        )
    )
    items = FinnhubNewsProvider(_client()).get_news(None, limit=5)
    assert items[0].headline.startswith("Markets")
    assert items[0].symbol is None


def test_finnhub_without_key_raises() -> None:
    client = FinnhubHttpClient("")
    with pytest.raises(ProviderConfigError, match="FINNHUB_API_KEY"):
        client.quote("AAPL")


@respx.mock
def test_finnhub_http_error_is_wrapped() -> None:
    respx.get(f"{FINNHUB_BASE_URL}/quote").mock(return_value=httpx.Response(429, text="slow down"))
    with pytest.raises(ProviderError, match="Finnhub request failed"):
        FinnhubMarketDataProvider(_client()).get_quote("AAPL")


@respx.mock
def test_finnhub_candle_403_is_clear_provider_error() -> None:
    respx.get(f"{FINNHUB_BASE_URL}/stock/candle").mock(
        return_value=httpx.Response(403, text="forbidden")
    )
    with pytest.raises(ProviderError, match="403") as exc:
        FinnhubMarketDataProvider(_client()).get_bars("AAPL")
    assert "invented" in str(exc.value)
    assert "Free-tier" in str(exc.value)
