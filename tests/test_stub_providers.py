from __future__ import annotations

from datetime import UTC, datetime

from sec_analysis.providers.stub import (
    StubBrokerReadOnlyClient,
    StubFundamentalsProvider,
    StubMarketDataProvider,
    StubNewsProvider,
    StubOptionsProvider,
    stub_price,
)


def test_stub_quote_is_deterministic() -> None:
    a = StubMarketDataProvider().get_quote("aapl")
    b = StubMarketDataProvider().get_quote("AAPL")
    assert a.last == b.last == stub_price("AAPL")
    assert a.source == "stub"
    assert a.bid is not None and a.ask is not None
    assert a.bid < a.last < a.ask


def test_stub_bars_respect_limit() -> None:
    bars = StubMarketDataProvider().get_bars("MSFT", interval="1d", limit=3)
    assert len(bars) == 3
    assert bars[0].timestamp < bars[-1].timestamp
    assert all(bar.volume > 0 for bar in bars)


def test_stub_fundamentals_and_options() -> None:
    fund = StubFundamentalsProvider().get_fundamentals("ibm")
    assert fund.symbol == "IBM"
    assert fund.market_cap and fund.market_cap > 0
    chain = StubOptionsProvider().get_option_chain("IBM")
    assert chain.contracts
    rights = {c.right for c in chain.contracts}
    assert rights == {"call", "put"}


def test_stub_news_filters_by_window() -> None:
    start = datetime(2024, 6, 15, 14, 0, tzinfo=UTC)
    items = StubNewsProvider().get_news("AAPL", start=start, limit=10)
    assert items
    assert all(i.published_at >= start for i in items)
    assert all(i.symbol == "AAPL" for i in items)


def test_stub_broker_read_only_snapshot() -> None:
    broker = StubBrokerReadOnlyClient()
    assert broker.is_connected()
    summary = broker.get_account_summary()
    assert summary.cash is not None
    assert broker.get_positions()[0].symbol == "AAPL"
    fills = broker.get_executions()
    assert fills[0].side == "buy"
    empty = broker.get_executions(start=datetime(2025, 1, 1, tzinfo=UTC))
    assert empty == []
