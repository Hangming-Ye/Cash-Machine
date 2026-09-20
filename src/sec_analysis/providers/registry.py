"""Build adapters and wrap market data in a per-market router.

Phase-1: Finnhub for US/HK quotes and news; Tiingo for US daily OHLCV;
FMP for US statements; AKShare for China A-share quotes, bars, company
news, and Sina 财报; IBKR / Longbridge read-only.
Missing keys or extras raise; we never invent prices, bars, or headlines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sec_analysis.config import Settings
from sec_analysis.core.instrument import Market
from sec_analysis.core.interfaces import (
    BrokerReadOnlyClient,
    FlexActivityReadOnlyClient,
    FundamentalsProvider,
    MarketDataProvider,
    NewsProvider,
    OptionsProvider,
)
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.fallback import FallbackNewsProvider
from sec_analysis.providers.finnhub.client import (
    FinnhubHttpClient,
    FinnhubMarketDataProvider,
    FinnhubNewsProvider,
)
from sec_analysis.providers.fmp.client import FmpFundamentalsProvider
from sec_analysis.providers.fundamentals_router import FundamentalsRouter
from sec_analysis.providers.massive.client import MassiveOptionsProvider
from sec_analysis.providers.minimal import (
    EodhdMarketDataProvider,
    MassiveMarketDataProvider,
    TwelveDataMarketDataProvider,
)
from sec_analysis.providers.news_router import NewsRouter
from sec_analysis.providers.router import MarketDataRouter
from sec_analysis.providers.rss_news.client import RssNewsProvider
from sec_analysis.providers.stub import (
    StubBrokerReadOnlyClient,
    StubFundamentalsProvider,
    StubMarketDataProvider,
    StubNewsProvider,
    StubOptionsProvider,
)
from sec_analysis.providers.tiingo.client import TiingoMarketDataProvider
from sec_analysis.providers.yfinance_provider.client import (
    YFinanceMarketDataProvider,
    YFinanceOptionsProvider,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProviderBundle:
    market_data: MarketDataProvider
    fundamentals: FundamentalsProvider
    options: OptionsProvider
    news: NewsProvider
    broker: BrokerReadOnlyClient
    flex: FlexActivityReadOnlyClient


def build_providers(settings: Settings | None = None) -> ProviderBundle:
    settings = settings or Settings()
    limiter = RateLimiter(calls_per_minute=settings.rate_limit_per_minute)
    broker = _broker(settings)
    flex = getattr(broker, "flex", None)
    if flex is None:
        from sec_analysis.brokers.ibkr.flex import IbkrFlexReadOnlyClient

        flex = IbkrFlexReadOnlyClient(settings)
    return ProviderBundle(
        market_data=_market_data_router(settings, limiter),
        fundamentals=_fundamentals(settings, limiter),
        options=_options(settings),
        news=_news(settings, limiter),
        broker=broker,
        flex=flex,
    )


def _market_data_router(settings: Settings, limiter: RateLimiter) -> MarketDataRouter:
    cache: dict[str, MarketDataProvider] = {}

    def resolve(name: str) -> MarketDataProvider:
        if name not in cache:
            cache[name] = _market_data_named(name, settings, limiter)
        return cache[name]

    default_names = settings.market_data_route_names(Market.UNKNOWN)
    default = [resolve(name) for name in default_names] or [StubMarketDataProvider()]
    chains = {
        market: [resolve(name) for name in settings.market_data_route_names(market)] or default
        for market in (Market.US, Market.CN, Market.HK, Market.JP, Market.KR)
    }
    history_default_names = settings.history_route_names(Market.UNKNOWN)
    history_default = [resolve(name) for name in history_default_names] or default
    history_chains = {
        market: [resolve(name) for name in settings.history_route_names(market)] or history_default
        for market in (Market.US, Market.CN, Market.HK, Market.JP, Market.KR)
    }
    return MarketDataRouter(
        chains,
        default=default,
        history_chains=history_chains,
        history_default=history_default,
    )


def _market_data_named(
    name: str, settings: Settings, limiter: RateLimiter
) -> MarketDataProvider:
    if name == "stub":
        return StubMarketDataProvider()
    if name == "yfinance":
        return YFinanceMarketDataProvider()
    if name == "finnhub":
        return FinnhubMarketDataProvider(
            FinnhubHttpClient(
                settings.finnhub_api_key,
                limiter=limiter,
                timeout=settings.http_timeout,
            )
        )
    if name == "twelvedata":
        if not settings.twelve_data_api_key:
            logger.warning("twelvedata selected but TWELVE_DATA_API_KEY is empty; using stub")
            return StubMarketDataProvider()
        return TwelveDataMarketDataProvider(settings.twelve_data_api_key)
    if name == "eodhd":
        if not settings.eodhd_api_key:
            logger.warning("eodhd selected but EODHD_API_KEY is empty; using stub")
            return StubMarketDataProvider()
        return EodhdMarketDataProvider(settings.eodhd_api_key)
    if name == "tiingo":
        return TiingoMarketDataProvider(
            settings.tiingo_api_key,
            limiter=limiter,
            timeout=settings.http_timeout,
        )
    if name == "akshare":
        from sec_analysis.providers.akshare_provider import AkshareMarketDataProvider

        return AkshareMarketDataProvider()
    if name == "massive":
        if not settings.massive_api_key:
            logger.warning("massive selected but MASSIVE_API_KEY is empty; using stub")
            return StubMarketDataProvider()
        return MassiveMarketDataProvider(settings.massive_api_key)
    raise ValueError(f"Unknown market-data adapter: {name}")


def _fundamentals(settings: Settings, limiter: RateLimiter) -> FundamentalsProvider:
    cache: dict[str, FundamentalsProvider] = {}

    def resolve(name: str) -> FundamentalsProvider:
        key = name or settings.fundamentals_provider
        if key not in cache:
            cache[key] = _fundamentals_named(key, settings, limiter)
        return cache[key]

    default_names = settings.fundamentals_route_names(Market.UNKNOWN)
    default = [resolve(name) for name in default_names] or [StubFundamentalsProvider()]
    chains = {
        market: [resolve(name) for name in settings.fundamentals_route_names(market)] or default
        for market in (Market.US, Market.CN, Market.HK, Market.JP, Market.KR)
    }
    return FundamentalsRouter(chains, default=default)


def _fundamentals_named(
    name: str, settings: Settings, limiter: RateLimiter
) -> FundamentalsProvider:
    if name == "stub":
        return StubFundamentalsProvider()
    if name == "fmp":
        return FmpFundamentalsProvider(
            settings.fmp_api_key,
            limiter=limiter,
            timeout=settings.http_timeout,
        )
    if name == "akshare":
        from sec_analysis.providers.akshare_provider import AkshareFundamentalsProvider

        return AkshareFundamentalsProvider()
    raise ValueError(f"Unknown fundamentals adapter: {name}")


def _options(settings: Settings) -> OptionsProvider:
    name = str(settings.options_provider)
    if name == "finnhub":
        raise ValueError(
            "Finnhub options API was removed. Use OPTIONS_PROVIDER=stub|yfinance|massive. "
            "Do not add a fake Finnhub options path."
        )
    if name == "stub":
        return StubOptionsProvider()
    if name == "yfinance":
        try:
            import yfinance  # noqa: F401
        except ImportError:
            logger.warning("yfinance extra is not installed; options using stub")
            return StubOptionsProvider()
        return YFinanceOptionsProvider()
    if name == "massive":
        logger.warning("OPTIONS_PROVIDER=massive is an unwired stub")
        return MassiveOptionsProvider(
            api_key=settings.massive_api_key,
            fallback=StubOptionsProvider(),
        )
    raise ValueError(f"Unknown OPTIONS_PROVIDER: {name}")


def _news(settings: Settings, limiter: RateLimiter) -> NewsProvider:
    cache: dict[str, NewsProvider] = {}

    def resolve(name: str) -> NewsProvider:
        key = name or settings.news_provider
        if key not in cache:
            cache[key] = _news_named(key, settings, limiter)
        return cache[key]

    default_names = settings.news_route_names(Market.UNKNOWN)
    default = [resolve(name) for name in default_names] or [StubNewsProvider()]
    chains = {
        market: [resolve(name) for name in settings.news_route_names(market)] or default
        for market in (Market.US, Market.CN, Market.HK, Market.JP, Market.KR)
    }
    return NewsRouter(chains, default=default)


def _news_named(name: str, settings: Settings, limiter: RateLimiter) -> NewsProvider:
    stub = StubNewsProvider()
    if name == "stub":
        return stub
    if name == "rss":
        rss = RssNewsProvider(settings.rss_feed_list(), limiter=limiter)
        return FallbackNewsProvider(rss, stub, name="rss")
    if name == "finnhub":
        client = FinnhubHttpClient(
            settings.finnhub_api_key,
            limiter=limiter,
            timeout=settings.http_timeout,
        )
        return FinnhubNewsProvider(client)
    if name == "akshare":
        from sec_analysis.providers.akshare_provider import AkshareNewsProvider

        return AkshareNewsProvider()
    raise ValueError(f"Unknown news adapter: {name}")


def _broker(settings: Settings) -> BrokerReadOnlyClient:
    name = settings.broker_client
    if name == "stub":
        return StubBrokerReadOnlyClient(account_id=settings.ibkr_account_id or "DU000000")
    if name == "ibkr":
        from sec_analysis.brokers.ibkr.readonly_client import IbkrReadOnlyClient

        return IbkrReadOnlyClient(settings)
    if name == "longbridge":
        from sec_analysis.brokers.longbridge import LongbridgeReadOnlyClient

        return LongbridgeReadOnlyClient(settings)
    raise ValueError(f"Unknown BROKER_CLIENT: {name}")
