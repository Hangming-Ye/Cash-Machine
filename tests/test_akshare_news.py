"""AKShare A-share company news — mocked only. Never hit East Money in CI."""

from __future__ import annotations

import pytest

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Market
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.akshare_provider import AkshareNewsProvider
from sec_analysis.providers.akshare_provider.client import UPSTREAM_HINT
from sec_analysis.providers.akshare_provider.news import GENERAL_NEWS_HINT
from sec_analysis.providers.news_router import NewsRouter
from sec_analysis.providers.registry import build_providers
from sec_analysis.providers.stub import StubNewsProvider


class _Frame:
    def __init__(self, rows: list[dict], *, empty: bool = False) -> None:
        self._rows = rows
        self.empty = empty

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return list(self._rows)


def _fast() -> RateLimiter:
    return RateLimiter(calls_per_minute=10_000, min_interval=0, sleeper=lambda _: None)


def _news(**kwargs) -> AkshareNewsProvider:
    return AkshareNewsProvider(limiter=_fast(), **kwargs)


def _rows() -> list[dict]:
    return [
        {
            "关键词": "600519",
            "新闻标题": "贵州茅台发布经营进展",
            "新闻内容": "fixture body",
            "发布时间": "2024-06-15 09:30:00",
            "文章来源": "证券时报",
            "新闻链接": "https://example.test/mt-1",
        },
        {
            "title": "Second headline",
            "datetime": "2024-06-14 18:00:00",
            "source": "eastmoney",
            "url": "https://example.test/mt-2",
        },
    ]


def test_company_news_maps_eastmoney_columns() -> None:
    items = _news(fetch=lambda code: _Frame(_rows()) if code == "600519" else []).get_company_news(
        "600519.SH", limit=10
    )
    assert len(items) == 2
    assert items[0].headline == "贵州茅台发布经营进展"
    assert items[0].symbol == "600519"
    assert items[0].source == "证券时报"
    assert items[0].url == "https://example.test/mt-1"
    assert items[0].published_at.year == 2024


def test_general_news_is_rejected() -> None:
    with pytest.raises(ProviderConfigError, match="stock_news_em"):
        _news(fetch=lambda _c: _rows()).get_news(None)
    assert "company-news" in GENERAL_NEWS_HINT


def test_empty_table_does_not_invent_headlines() -> None:
    with pytest.raises(ProviderError, match="no usable headlines"):
        _news(fetch=lambda _c: _Frame([], empty=True)).get_company_news("000001")


def test_rows_without_title_are_dropped() -> None:
    payload = [{"新闻内容": "body only", "发布时间": "2024-01-01"}]
    with pytest.raises(ProviderError, match="no usable headlines"):
        _news(fetch=lambda _c: payload).get_company_news("600519")


def test_upstream_break_is_clear() -> None:
    def boom(_code: str):
        raise RuntimeError("HTTP 429 too many requests")

    with pytest.raises(ProviderError, match="rate-limited") as exc:
        _news(fetch=boom).get_company_news("sz000001")
    assert UPSTREAM_HINT in str(exc.value)


def test_injected_fetch_never_imports_akshare(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise AssertionError("CI must not import akshare / hit East Money")

    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client._load_akshare",
        fail,
    )
    items = _news(fetch=lambda _c: _rows()).get_company_news("600519", limit=1)
    assert items[0].headline


def test_news_router_sends_cn_to_akshare() -> None:
    ak = _news(fetch=lambda _c: _rows())
    stub = StubNewsProvider()
    router = NewsRouter({Market.CN: [ak], Market.US: [stub]}, default=[stub])
    cn = router.get_company_news("600519")
    assert cn[0].headline.startswith("贵州茅台")
    us = router.get_company_news("AAPL")
    assert us[0].source == "stub"
    general = router.get_news(None, limit=1)
    assert general[0].source == "stub"


def test_registry_cn_news_route_is_akshare() -> None:
    settings = Settings(
        news_provider="finnhub",
        news_route_cn="akshare",
        news_route_us="finnhub",
        news_route_hk="finnhub",
        news_route_default="finnhub",
        finnhub_api_key="test-key",
        broker_client="stub",
        market_data_route_us="stub",
        market_data_route_default="stub",
    )
    bundle = build_providers(settings)
    assert isinstance(bundle.news, NewsRouter)
    assert bundle.news.route_names()["CN"] == ["akshare"]
    assert bundle.news.route_names()["US"] == ["finnhub"]
    assert bundle.news.route_names()["DEFAULT"] == ["finnhub"]


def test_news_routes_are_comma_lists_like_market_data() -> None:
    settings = Settings(news_route_cn="akshare,stub", news_provider="finnhub")
    assert settings.news_route_names(Market.CN) == ["akshare", "stub"]
    assert settings.market_data_route_names(Market.CN)  # same list shape


def test_news_router_falls_through_then_errors() -> None:
    class Boom(StubNewsProvider):
        name = "boom"

        def get_company_news(self, symbol, **kwargs):
            raise ProviderError("scrape down")

    router = NewsRouter({Market.CN: [Boom(), StubNewsProvider()]}, default=[StubNewsProvider()])
    items = router.get_company_news("600519")
    assert items[0].source == "stub"
