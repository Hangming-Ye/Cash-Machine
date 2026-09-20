"""SecAnalysisClient façade — mocked routers/brokers only."""

from __future__ import annotations

import inspect

import pytest

from sec_analysis.client import SecAnalysisClient
from sec_analysis.core.errors import ProviderConfigError
from sec_analysis.providers.registry import build_providers
from sec_analysis.providers.stub import StubFundamentalsProvider


def test_facade_read_paths_use_injected_bundle(stub_settings) -> None:
    bundle = build_providers(stub_settings)
    client = SecAnalysisClient(stub_settings, bundle=bundle)
    quote = client.quote("AAPL")
    assert quote.source == "stub"
    assert quote.last is not None
    bars = client.bars("MSFT", limit=2)
    assert len(bars) == 2
    general = client.news(limit=2)
    assert general[0].source == "stub"
    company = client.company_news("AAPL", limit=1)
    assert company[0].symbol == "AAPL"
    snap = client.fundamentals("IBM")
    assert snap.source == "stub"
    summary = client.account()
    assert summary.account_id
    assert client.positions()
    assert client.executions()
    assert client.is_connected() is True


def test_facade_resolves_cn_symbol_for_quote(stub_settings) -> None:
    client = SecAnalysisClient(stub_settings, bundle=build_providers(stub_settings))
    quote = client.quote("600519")
    assert quote.market.value == "CN"
    assert quote.currency == "CNY"


def test_facade_cn_news_without_symbol_is_config_error(stub_settings) -> None:
    client = SecAnalysisClient(stub_settings, bundle=build_providers(stub_settings))
    with pytest.raises(ProviderConfigError, match="symbol"):
        client.news(market="CN")


def test_facade_statement_on_stub_does_not_invent(stub_settings) -> None:
    from sec_analysis.providers.fundamentals_router import FundamentalsRouter

    client = SecAnalysisClient(stub_settings, bundle=build_providers(stub_settings))
    with pytest.raises(ProviderConfigError, match="does not provide"):
        client.statement("600519", statement="income")
    assert isinstance(client._bundle.fundamentals, FundamentalsRouter)


def test_facade_history_requires_longbridge(stub_settings) -> None:
    client = SecAnalysisClient(stub_settings, bundle=build_providers(stub_settings))
    with pytest.raises(ProviderConfigError, match="Longbridge"):
        client.executions(history=True)
    with pytest.raises(ProviderConfigError, match="not both"):
        client.executions(history=True, flex=True)
    with pytest.raises(ProviderConfigError, match="does not invent"):
        client.executions(flex=True)


def test_facade_routes_are_introspection(stub_settings) -> None:
    client = SecAnalysisClient(stub_settings, bundle=build_providers(stub_settings))
    routes = client.routes()
    assert routes["broker"] == "stub"
    assert routes["market_data"]["CN"] == ["stub"]
    assert routes["history"]["US"] == ["stub"]
    assert routes["news"]["CN"] == ["stub"]
    assert routes["fundamentals"]["CN"] == ["stub"]


def test_facade_has_no_order_methods() -> None:
    names = {n.lower() for n, attr in inspect.getmembers(SecAnalysisClient) if callable(attr)}
    forbidden = ("place", "cancel", "modify", "submit", "create_order", "send_order")
    offenders = [n for n in names if any(needle in n for needle in forbidden)]
    assert offenders == []
    required = (
        "quote",
        "bars",
        "news",
        "company_news",
        "fundamentals",
        "statement",
        "account",
    )
    for name in required:
        assert name in names


def test_facade_from_settings(stub_settings) -> None:
    client = SecAnalysisClient.from_settings(stub_settings)
    assert client.quote("AAPL").source == "stub"


def test_facade_statement_delegates_to_router(stub_settings) -> None:
    from datetime import date

    from sec_analysis.core.instrument import Market
    from sec_analysis.core.models import StatementKind, StatementLine, StatementReport
    from sec_analysis.providers.fundamentals_router import FundamentalsRouter

    class FakeFund(StubFundamentalsProvider):
        name = "akshare"

        def get_statement(self, symbol, *, statement="income", limit_periods=8):
            return StatementReport(
                symbol="CN:600519",
                statement=StatementKind.INCOME,
                sina_stock="sh600519",
                sina_symbol="利润表",
                periods=["2023-12-31"],
                lines=[StatementLine(label="营业收入", values={"2023-12-31": 1.0})],
                as_of=date(2023, 12, 31),
                source="akshare",
                market=Market.CN,
            )

    bundle = build_providers(stub_settings)
    assert isinstance(bundle.fundamentals, FundamentalsRouter)
    bundle.fundamentals._chains[Market.CN] = [FakeFund()]
    client = SecAnalysisClient(stub_settings, bundle=bundle)
    report = client.statement("600519", statement="利润表")
    assert report.sina_stock == "sh600519"
    assert report.lines[0].values["2023-12-31"] == 1.0


def test_facade_news_with_symbol_uses_company_path(stub_settings) -> None:
    client = SecAnalysisClient(stub_settings, bundle=build_providers(stub_settings))
    items = client.news("600519", market="CN", limit=1)
    assert items
    assert items[0].source == "stub"


def test_facade_account_longbridge_missing_creds_is_clear(stub_settings) -> None:
    client = SecAnalysisClient(stub_settings, bundle=build_providers(stub_settings))
    with pytest.raises(ProviderConfigError, match="LONGBRIDGE_APP_KEY|longbridge-login"):
        client.account(broker="longbridge")
