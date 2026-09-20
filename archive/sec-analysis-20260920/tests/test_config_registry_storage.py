from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sec_analysis.config import Settings, clear_settings_cache
from sec_analysis.providers.registry import build_providers
from sec_analysis.providers.stub import StubMarketDataProvider, StubNewsProvider, stub_price
from sec_analysis.storage.cache import SqliteCache


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "finnhub")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "12")
    settings = Settings()
    assert settings.market_data_provider == "finnhub"
    assert settings.rate_limit_per_minute == 12
    assert settings.rss_feed_list()


def test_settings_cache_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("NEWS_PROVIDER", "rss")
    from sec_analysis.config import get_settings

    first = get_settings()
    second = get_settings()
    assert first is second
    assert first.news_provider == "rss"
    clear_settings_cache()


def test_phase1_defaults_are_finnhub_and_ibkr() -> None:
    assert Settings.model_fields["market_data_provider"].default == "finnhub"
    assert Settings.model_fields["news_provider"].default == "finnhub"
    assert Settings.model_fields["broker_client"].default == "ibkr"
    assert Settings.model_fields["market_data_route_us"].default == "finnhub"
    assert Settings.model_fields["market_data_route_cn"].default == "akshare"
    assert Settings.model_fields["fundamentals_provider"].default == "fmp"
    assert Settings.model_fields["ibkr_readonly"].default is True
    assert Settings.model_fields["news_route_cn"].default == "akshare"
    assert Settings.model_fields["fundamentals_route_cn"].default == "akshare"
    assert Settings.model_fields["fundamentals_route_us"].default == "fmp"
    assert Settings.model_fields["history_route_us"].default == "tiingo"
    assert Settings.model_fields["history_route_default"].default == "tiingo"
    assert Settings.model_fields["longbridge_mode"].default == "stub"
    assert Settings.model_fields["longbridge_auth"].default == "token"
    assert Settings.model_fields["broker_ibkr_mode"].default == "auto"


def test_ibkr_flex_mode_helpers() -> None:
    empty = Settings(broker_ibkr_mode="auto")
    assert empty.ibkr_flex_configured() is False
    assert empty.ibkr_use_flex() is False
    ready = Settings(
        broker_ibkr_mode="auto",
        ibkr_flex_token="tok",
        ibkr_flex_query_id="800969",
    )
    assert ready.ibkr_flex_configured() is True
    assert ready.ibkr_use_flex() is True
    forced = Settings(broker_ibkr_mode="flex")
    assert forced.ibkr_use_flex() is True
    skipped = Settings(
        broker_ibkr_mode="gateway",
        ibkr_flex_token="tok",
        ibkr_flex_query_id="800969",
    )
    assert skipped.ibkr_use_flex() is False


def test_ibkr_readonly_cannot_be_disabled() -> None:
    with pytest.raises(ValidationError, match="IBKR_READONLY"):
        Settings(ibkr_readonly=False)


def test_finnhub_options_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(options_provider="finnhub")
    settings = Settings(options_provider="yfinance")
    settings.options_provider = "finnhub"  # bypass model validation
    from sec_analysis.providers.registry import _options

    with pytest.raises(ValueError, match="removed"):
        _options(settings)


def test_finnhub_without_key_is_a_clear_error() -> None:
    from sec_analysis.core.errors import ProviderConfigError

    settings = Settings(
        market_data_provider="finnhub",
        market_data_route_us="finnhub",
        market_data_route_default="finnhub",
        news_provider="finnhub",
        news_route_default="finnhub",
        news_route_us="finnhub",
        news_route_hk="finnhub",
        broker_client="ibkr",
        finnhub_api_key="",
        ibkr_gateway_mode="stub",
    )
    bundle = build_providers(settings)
    from sec_analysis.providers.news_router import NewsRouter

    assert isinstance(bundle.news, NewsRouter)
    assert bundle.news.route_names()["DEFAULT"] == ["finnhub"]
    assert bundle.broker.name == "ibkr"
    with pytest.raises(ProviderConfigError, match="FINNHUB_API_KEY"):
        bundle.market_data.get_quote("AAPL")
    with pytest.raises(ProviderConfigError, match="FINNHUB_API_KEY"):
        bundle.news.get_news(None)


def test_sqlite_cache_roundtrip(tmp_path: Path) -> None:
    cache = SqliteCache(tmp_path / "cache.sqlite")
    bars = StubMarketDataProvider().get_bars("AAPL", limit=2)
    news = StubNewsProvider().get_news("AAPL", limit=2)
    assert cache.put_bars(bars) == 2
    assert cache.put_news(news) == 2
    loaded_bars = cache.get_bars("AAPL")
    loaded_news = cache.get_news("AAPL")
    assert loaded_bars[0].close == bars[0].close
    assert loaded_news[0].headline == news[0].headline
    from sec_analysis.providers.stub import StubBrokerReadOnlyClient

    fills = StubBrokerReadOnlyClient().get_executions()
    assert cache.put_executions(fills) == 1
    assert cache.get_executions("DU000000")[0].price == fills[0].price
    cache.close()
    assert stub_price("AAPL") > 0
