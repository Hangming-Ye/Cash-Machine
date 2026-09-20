from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Market
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.registry import build_providers
from sec_analysis.providers.tiingo.client import (
    TIINGO_BASE_URL,
    TiingoHttpClient,
    TiingoMarketDataProvider,
)


def _provider() -> TiingoMarketDataProvider:
    return TiingoMarketDataProvider(
        client=TiingoHttpClient(
            "tiingo-key",
            client=httpx.Client(base_url=TIINGO_BASE_URL, timeout=5.0),
            limiter=RateLimiter(calls_per_minute=10_000, min_interval=0),
            timeout=5.0,
            base_url=TIINGO_BASE_URL,
        )
    )


@respx.mock
def test_tiingo_daily_bars_map_ohlcv() -> None:
    respx.get(f"{TIINGO_BASE_URL}/tiingo/daily/AAPL/prices").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2024-06-13T00:00:00.000Z",
                    "open": 210.0,
                    "high": 212.5,
                    "low": 209.0,
                    "close": 211.2,
                    "volume": 48_000_000,
                    "adjClose": 211.2,
                    "adjVolume": 48_000_000,
                },
                {
                    "date": "2024-06-14T00:00:00.000Z",
                    "open": 211.0,
                    "high": 214.0,
                    "low": 210.5,
                    "close": 213.4,
                    "volume": 51_200_000,
                },
            ],
        )
    )
    bars = _provider().get_bars("AAPL", interval="1d", limit=5)
    assert len(bars) == 2
    assert bars[-1].symbol == "AAPL"
    assert bars[-1].close == 213.4
    assert bars[-1].volume == 51_200_000
    assert bars[-1].source == "tiingo"
    assert bars[0].timestamp == datetime(2024, 6, 13, tzinfo=UTC)


@respx.mock
def test_tiingo_skips_incomplete_rows_and_limits() -> None:
    respx.get(f"{TIINGO_BASE_URL}/tiingo/daily/MSFT/prices").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"date": "2024-06-12T00:00:00.000Z", "open": 1, "high": 2, "low": 0.5},
                {
                    "date": "2024-06-13T00:00:00.000Z",
                    "open": 420.0,
                    "high": 422.0,
                    "low": 418.0,
                    "close": 421.0,
                    "volume": 10,
                },
                {
                    "date": "2024-06-14T00:00:00.000Z",
                    "open": 421.0,
                    "high": 425.0,
                    "low": 420.0,
                    "close": 424.0,
                    "adjVolume": 20,
                },
            ],
        )
    )
    bars = _provider().get_bars("MSFT", limit=1)
    assert len(bars) == 1
    assert bars[0].close == 424.0
    assert bars[0].volume == 20


def test_tiingo_missing_key_is_config_error() -> None:
    with pytest.raises(ProviderConfigError, match="TIINGO_API_KEY"):
        TiingoMarketDataProvider("").get_bars("AAPL")
    with pytest.raises(ProviderConfigError, match="TIINGO_API_KEY"):
        TiingoMarketDataProvider("").get_quote("AAPL")


def test_tiingo_quote_is_history_only() -> None:
    with pytest.raises(ProviderError, match="EOD history"):
        TiingoMarketDataProvider("key").get_quote("AAPL")


def test_tiingo_rejects_intraday() -> None:
    with pytest.raises(ProviderError, match="interval='1m'"):
        TiingoMarketDataProvider("key").get_bars("AAPL", interval="1m")


@respx.mock
def test_tiingo_empty_payload_is_error() -> None:
    respx.get(f"{TIINGO_BASE_URL}/tiingo/daily/AAPL/prices").mock(
        return_value=httpx.Response(200, json=[])
    )
    with pytest.raises(ProviderError, match="No bars were invented"):
        _provider().get_bars("AAPL")


@respx.mock
def test_tiingo_http_403_is_clear() -> None:
    respx.get(f"{TIINGO_BASE_URL}/tiingo/daily/AAPL/prices").mock(
        return_value=httpx.Response(403, text="plan")
    )
    with pytest.raises(ProviderError, match="TIINGO_API_KEY"):
        _provider().get_bars("AAPL")


def test_us_history_route_prefers_tiingo_quotes_stay_finnhub() -> None:
    settings = Settings(
        market_data_route_us="finnhub",
        market_data_route_default="finnhub",
        history_route_us="tiingo",
        history_route_default="tiingo",
        news_route_us="finnhub",
        fundamentals_route_us="fmp",
        finnhub_api_key="fh",
        tiingo_api_key="tg",
        fmp_api_key="fmp",
        broker_client="stub",
    )
    bundle = build_providers(settings)
    assert bundle.market_data.route_names()["US"] == ["finnhub"]
    assert bundle.market_data.history_route_names()["US"] == ["tiingo"]
    assert bundle.market_data.history_route_names()["DEFAULT"] == ["tiingo"]
    assert bundle.fundamentals.route_names()["US"] == ["fmp"]
    with pytest.raises(ProviderConfigError, match="TIINGO_API_KEY"):
        build_providers(
            settings.model_copy(update={"tiingo_api_key": ""})
        ).market_data.get_bars("AAPL")


def test_cn_history_falls_back_to_market_data_route() -> None:
    settings = Settings(
        market_data_route_cn="akshare",
        history_route_cn="",
        history_route_us="tiingo",
        market_data_route_us="finnhub",
        broker_client="stub",
    )
    assert settings.history_route_names(Market.CN) == ["akshare"]
    assert settings.history_route_names(Market.US) == ["tiingo"]
