from __future__ import annotations

import pytest

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Market, parse_instrument, resolve_instrument
from sec_analysis.providers.minimal import (
    EodhdMarketDataProvider,
    TwelveDataMarketDataProvider,
)
from sec_analysis.providers.registry import build_providers
from sec_analysis.providers.router import MarketDataRouter
from sec_analysis.providers.stub import StubMarketDataProvider


@pytest.mark.parametrize(
    ("raw", "market", "mic"),
    [
        ("600519.SH", Market.CN, "XSHG"),
        ("000001.SZ", Market.CN, "XSHE"),
        ("600519", Market.CN, "XSHG"),
        ("sh600519", Market.CN, "XSHG"),
        ("sz000001", Market.CN, "XSHE"),
        ("bj830799", Market.CN, "XBEI"),
        ("830799", Market.CN, "XBEI"),
        ("00700.HK", Market.HK, "XHKG"),
        ("HK:00700", Market.HK, None),
        ("7203.T", Market.JP, "XTKS"),
        ("005930.KS", Market.KR, "XKRX"),
        ("US:AAPL", Market.US, None),
        ("AAPL", Market.UNKNOWN, None),
    ],
)
def test_parse_instrument_markets(raw: str, market: Market, mic: str | None) -> None:
    inst = parse_instrument(raw)
    assert inst.market is market
    assert inst.mic == mic


def test_bare_ticker_is_not_assumed_us() -> None:
    assert parse_instrument("AAPL").market is Market.UNKNOWN
    forced = resolve_instrument("AAPL", market="US")
    assert forced.market is Market.US
    assert forced.currency == "USD"


def test_router_uses_per_market_chain() -> None:
    class Tagged(StubMarketDataProvider):
        def __init__(self, tag: str) -> None:
            self.name = tag

    cn = Tagged("cn-only")
    us = Tagged("us-only")
    router = MarketDataRouter(
        {Market.CN: [cn], Market.US: [us], Market.HK: [us], Market.JP: [us], Market.KR: [us]},
        default=[us],
    )
    assert router.get_quote("600519.SH").source == "cn-only"
    assert router.get_quote("600519.SH").market is Market.CN
    assert router.get_quote("600519.SH").currency == "CNY"
    assert router.get_quote(resolve_instrument("AAPL", market="US")).source == "us-only"


def test_router_falls_through_on_failure() -> None:
    class Boom(StubMarketDataProvider):
        name = "boom"

        def get_quote(self, symbol):
            raise ProviderError("nope")

    router = MarketDataRouter(
        {Market.CN: [Boom(), StubMarketDataProvider()]},
        default=[StubMarketDataProvider()],
    )
    quote = router.get_quote("000001.SZ")
    assert quote.source == "stub"
    assert quote.market is Market.CN


def test_router_errors_when_chain_exhausted() -> None:
    class Boom(StubMarketDataProvider):
        name = "boom"

        def get_quote(self, symbol):
            raise ProviderError("nope")

    router = MarketDataRouter({Market.HK: [Boom()]}, default=[Boom()])
    with pytest.raises(ProviderError, match="00700"):
        router.get_quote("00700.HK")


def test_default_bundle_routes_are_stub(stub_settings) -> None:
    bundle = build_providers(stub_settings)
    assert isinstance(bundle.market_data, MarketDataRouter)
    names = bundle.market_data.route_names()
    assert names["CN"] == ["stub"]
    assert names["US"] == ["stub"]
    quote = bundle.market_data.get_quote("7203.T")
    assert quote.market is Market.JP
    assert quote.currency == "JPY"


def test_settings_route_lists_are_opt_in() -> None:
    settings = Settings(
        market_data_provider="stub",
        market_data_route_us="",
        market_data_route_default="",
        market_data_route_cn="akshare,eodhd",
    )
    assert settings.market_data_route_names(Market.CN) == ["akshare", "eodhd"]
    assert settings.market_data_route_names(Market.US) == ["stub"]


def test_unwired_asia_adapters_exist() -> None:
    with pytest.raises(ProviderConfigError, match="TODO"):
        TwelveDataMarketDataProvider("key").get_quote("AAPL")
    with pytest.raises(ProviderConfigError, match="TODO"):
        EodhdMarketDataProvider("key").get_quote("7203.T")
