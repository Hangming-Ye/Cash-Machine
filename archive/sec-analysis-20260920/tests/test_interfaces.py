from __future__ import annotations

import inspect

from sec_analysis.core.interfaces import (
    BrokerReadOnlyClient,
    FlexActivityReadOnlyClient,
    FundamentalsProvider,
    MarketDataProvider,
    NewsProvider,
    OptionsProvider,
)
from sec_analysis.providers.fundamentals_router import FundamentalsRouter
from sec_analysis.providers.news_router import NewsRouter
from sec_analysis.providers.registry import build_providers
from sec_analysis.providers.router import MarketDataRouter
from sec_analysis.providers.stub import (
    StubBrokerReadOnlyClient,
    StubFundamentalsProvider,
    StubMarketDataProvider,
    StubNewsProvider,
    StubOptionsProvider,
)


def _abstract_names(cls: type) -> set[str]:
    return set(cls.__abstractmethods__)


def test_interface_contracts_are_stable() -> None:
    assert _abstract_names(MarketDataProvider) == {"get_quote", "get_bars"}
    assert _abstract_names(FundamentalsProvider) == {"get_fundamentals"}
    assert _abstract_names(OptionsProvider) == {"get_option_chain"}
    assert _abstract_names(NewsProvider) == {"get_news"}
    assert _abstract_names(BrokerReadOnlyClient) == {
        "get_account_summary",
        "get_positions",
        "get_executions",
        "is_connected",
    }
    assert _abstract_names(FlexActivityReadOnlyClient) == {
        "is_configured",
        "get_activity_executions",
    }


def test_stubs_are_concrete_implementations() -> None:
    assert not inspect.isabstract(StubMarketDataProvider)
    assert not inspect.isabstract(StubFundamentalsProvider)
    assert not inspect.isabstract(StubOptionsProvider)
    assert not inspect.isabstract(StubNewsProvider)
    assert not inspect.isabstract(StubBrokerReadOnlyClient)


def test_bundle_satisfies_interfaces(stub_settings) -> None:
    bundle = build_providers(stub_settings)
    assert isinstance(bundle.market_data, MarketDataProvider)
    assert isinstance(bundle.market_data, MarketDataRouter)
    assert isinstance(bundle.fundamentals, FundamentalsProvider)
    assert isinstance(bundle.fundamentals, FundamentalsRouter)
    assert isinstance(bundle.options, OptionsProvider)
    assert isinstance(bundle.news, NewsProvider)
    assert isinstance(bundle.news, NewsRouter)
    assert isinstance(bundle.broker, BrokerReadOnlyClient)
    assert isinstance(bundle.flex, FlexActivityReadOnlyClient)
