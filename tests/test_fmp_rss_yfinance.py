from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.models import StatementKind
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.fallback import FallbackNewsProvider
from sec_analysis.providers.fmp.client import FMP_BASE_URL, FmpFundamentalsProvider
from sec_analysis.providers.massive.client import MassiveOptionsProvider
from sec_analysis.providers.rss_news.client import RssNewsProvider
from sec_analysis.providers.stub import StubOptionsProvider
from sec_analysis.providers.yfinance_provider.client import (
    YFinanceMarketDataProvider,
    YFinanceOptionsProvider,
)


@respx.mock
def test_fmp_profile_snapshot() -> None:
    respx.get(f"{FMP_BASE_URL}/stable/profile").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "companyName": "Apple Inc.",
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "mktCap": 3e12,
                    "pe": 30.1,
                    "eps": 6.4,
                    "currency": "USD",
                    "exchangeShortName": "NASDAQ",
                }
            ],
        )
    )
    provider = FmpFundamentalsProvider(
        "fmp-key",
        client=httpx.Client(base_url=FMP_BASE_URL, timeout=5.0),
        limiter=RateLimiter(calls_per_minute=10_000, min_interval=0),
    )
    snap = provider.get_fundamentals("aapl")
    assert snap.name == "Apple Inc."
    assert snap.market_cap == 3e12
    assert snap.source == "fmp"


def test_fmp_requires_key() -> None:
    with pytest.raises(ProviderConfigError, match="FMP_API_KEY"):
        FmpFundamentalsProvider("").get_fundamentals("AAPL")
    with pytest.raises(ProviderConfigError, match="FMP_API_KEY"):
        FmpFundamentalsProvider("").get_statement("AAPL", statement="income")


def _fmp() -> FmpFundamentalsProvider:
    return FmpFundamentalsProvider(
        "fmp-key",
        client=httpx.Client(base_url=FMP_BASE_URL, timeout=5.0),
        limiter=RateLimiter(calls_per_minute=10_000, min_interval=0),
    )


@respx.mock
def test_fmp_income_statement_pivots_periods() -> None:
    respx.get(f"{FMP_BASE_URL}/stable/income-statement").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2024-09-28",
                    "symbol": "AAPL",
                    "reportedCurrency": "USD",
                    "calendarYear": "2024",
                    "revenue": 391_035_000_000,
                    "netIncome": 93_736_000_000,
                    "eps": 6.11,
                    "link": "https://example.test/aapl-2024",
                },
                {
                    "date": "2023-09-30",
                    "symbol": "AAPL",
                    "reportedCurrency": "USD",
                    "calendarYear": "2023",
                    "revenue": 383_285_000_000,
                    "netIncome": 96_995_000_000,
                    "eps": 6.16,
                },
            ],
        )
    )
    report = _fmp().get_statement("aapl", statement="income", limit_periods=2)
    assert report.statement is StatementKind.INCOME
    assert report.source == "fmp"
    assert report.currency == "USD"
    assert report.sina_symbol == "income-statement"
    assert report.periods == ["2024-09-28", "2023-09-30"]
    revenue = next(line for line in report.lines if line.label == "revenue")
    assert revenue.values["2024-09-28"] == 391_035_000_000
    assert revenue.values["2023-09-30"] == 383_285_000_000


@respx.mock
def test_fmp_balance_and_cash_paths() -> None:
    respx.get(f"{FMP_BASE_URL}/stable/balance-sheet-statement").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2024-09-28",
                    "totalAssets": 364_980_000_000,
                    "reportedCurrency": "USD",
                }
            ],
        )
    )
    respx.get(f"{FMP_BASE_URL}/stable/cash-flow-statement").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2024-09-28",
                    "operatingCashFlow": 118_254_000_000,
                    "reportedCurrency": "USD",
                }
            ],
        )
    )
    balance = _fmp().get_statement("AAPL", statement="balance")
    cash = _fmp().get_statement("AAPL", statement="cash")
    assert balance.statement is StatementKind.BALANCE
    assert cash.statement is StatementKind.CASH
    assert balance.lines[0].values["2024-09-28"] == 364_980_000_000
    assert cash.lines[0].values["2024-09-28"] == 118_254_000_000


def test_fmp_unknown_statement_is_config_error() -> None:
    with pytest.raises(ProviderConfigError, match="income|balance|cash"):
        _fmp().get_statement("AAPL", statement="notes")


@respx.mock
def test_fmp_empty_statement_is_error() -> None:
    respx.get(f"{FMP_BASE_URL}/stable/income-statement").mock(
        return_value=httpx.Response(200, json=[])
    )
    with pytest.raises(ProviderError, match="invented"):
        _fmp().get_statement("AAPL", statement="income")


@respx.mock
def test_fmp_uses_stable_not_legacy_v3() -> None:
    v3 = respx.get(url__regex=r".*/api/v3/.*").mock(
        return_value=httpx.Response(403, text="Legacy Endpoint")
    )
    respx.get(f"{FMP_BASE_URL}/stable/profile").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "companyName": "Apple Inc.",
                    "sector": "Technology",
                    "mktCap": 3e12,
                    "currency": "USD",
                }
            ],
        )
    )
    respx.get(f"{FMP_BASE_URL}/stable/income-statement").mock(
        return_value=httpx.Response(
            200,
            json=[{"date": "2024-09-28", "revenue": 100.0, "reportedCurrency": "USD"}],
        )
    )
    provider = _fmp()
    snap = provider.get_fundamentals("AAPL")
    assert snap.name == "Apple Inc."
    assert provider._last_path == "/stable/profile"
    report = provider.get_statement("AAPL", statement="income")
    assert report.lines[0].values["2024-09-28"] == 100.0
    assert provider._last_path == "/stable/income-statement"
    assert v3.call_count == 0


def test_rss_filters_by_symbol() -> None:
    def fake_parse(_url: str):
        return {
            "feed": {"title": "Fixture Wire"},
            "entries": [
                {
                    "id": "1",
                    "title": "AAPL beats estimates",
                    "link": "https://example.test/1",
                    "summary": "earnings",
                    "published": "Sat, 15 Jun 2024 12:00:00 GMT",
                },
                {
                    "id": "2",
                    "title": "Oil prices slip",
                    "link": "https://example.test/2",
                    "summary": "energy",
                    "published": "Sat, 15 Jun 2024 13:00:00 GMT",
                },
            ],
        }

    items = RssNewsProvider(
        ["https://example.test/feed.xml"],
        parse=fake_parse,
        limiter=RateLimiter(calls_per_minute=10_000, min_interval=0),
    ).get_news("AAPL", limit=10)
    assert len(items) == 1
    assert items[0].symbol == "AAPL"
    assert "beats" in items[0].headline


class _FakeHistory:
    def __init__(self) -> None:
        self.Open = 10.0
        self.High = 11.0
        self.Low = 9.5
        self.Close = 10.5
        self.Volume = 1000
        self.Index = date(2024, 6, 14)

    def itertuples(self):
        return [self]


class _FakeChain:
    calls = [
        {
            "contractSymbol": "AAPL240920C00200000",
            "strike": 200,
            "lastPrice": 3.2,
            "bid": 3.1,
            "ask": 3.3,
            "volume": 10,
            "openInterest": 50,
            "impliedVolatility": 0.25,
        }
    ]
    puts = []


class _FakeTicker:
    options = ["2024-09-20"]
    fast_info = {"last_price": 190.0, "bid": 189.9, "ask": 190.1, "last_volume": 123}

    def history(self, period: str, interval: str):
        return _FakeHistory()

    def option_chain(self, _exp: str) -> _FakeChain:
        return _FakeChain()


def test_yfinance_adapters_use_injected_ticker() -> None:
    factory = lambda _symbol: _FakeTicker()  # noqa: E731
    quote = YFinanceMarketDataProvider(factory).get_quote("AAPL")
    assert quote.last == 190.0
    bars = YFinanceMarketDataProvider(factory).get_bars("AAPL", limit=5)
    assert bars[0].close == 10.5
    chain = YFinanceOptionsProvider(factory).get_option_chain("AAPL")
    assert chain.contracts[0].right == "call"
    assert chain.expirations[0] == date(2024, 9, 20)


def test_yfinance_missing_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("no yfinance in test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ProviderConfigError, match="yfinance"):
        YFinanceMarketDataProvider().get_quote("AAPL")


def test_news_fallback_uses_secondary_when_primary_empty() -> None:
    class EmptyNews:
        name = "empty"

        def get_news(self, symbol=None, **_kw):
            return []

    from sec_analysis.providers.stub import StubNewsProvider

    items = FallbackNewsProvider(EmptyNews(), StubNewsProvider(), name="empty").get_news("AAPL")
    assert items
    assert items[0].source == "stub"


def test_massive_is_extension_point() -> None:
    with pytest.raises(ProviderConfigError, match="Massive"):
        MassiveOptionsProvider(api_key="").get_option_chain("AAPL")
    chain = MassiveOptionsProvider(fallback=StubOptionsProvider()).get_option_chain("AAPL")
    assert chain.source == "stub"
