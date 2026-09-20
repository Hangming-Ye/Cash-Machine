"""Force stub providers so tests never touch live HTTP or a real broker."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MARKET_DATA_PROVIDER", "stub")
os.environ.setdefault("MARKET_DATA_ROUTE_US", "stub")
os.environ.setdefault("MARKET_DATA_ROUTE_HK", "stub")
os.environ.setdefault("MARKET_DATA_ROUTE_CN", "stub")
os.environ.setdefault("MARKET_DATA_ROUTE_JP", "stub")
os.environ.setdefault("MARKET_DATA_ROUTE_KR", "stub")
os.environ.setdefault("MARKET_DATA_ROUTE_DEFAULT", "stub")
os.environ.setdefault("HISTORY_ROUTE_US", "stub")
os.environ.setdefault("HISTORY_ROUTE_DEFAULT", "stub")
# Empty CN/HK/JP/KR history falls back to MARKET_DATA_ROUTE_* (stub in CI).
os.environ.setdefault("HISTORY_ROUTE_HK", "")
os.environ.setdefault("HISTORY_ROUTE_CN", "")
os.environ.setdefault("HISTORY_ROUTE_JP", "")
os.environ.setdefault("HISTORY_ROUTE_KR", "")
os.environ.setdefault("FUNDAMENTALS_PROVIDER", "stub")
os.environ.setdefault("FUNDAMENTALS_ROUTE_CN", "stub")
os.environ.setdefault("FUNDAMENTALS_ROUTE_US", "stub")
os.environ.setdefault("FUNDAMENTALS_ROUTE_DEFAULT", "stub")
os.environ.setdefault("TIINGO_API_KEY", "")
os.environ.setdefault("OPTIONS_PROVIDER", "stub")
os.environ.setdefault("NEWS_PROVIDER", "stub")
os.environ.setdefault("NEWS_ROUTE_US", "stub")
os.environ.setdefault("NEWS_ROUTE_HK", "stub")
os.environ.setdefault("NEWS_ROUTE_CN", "stub")
os.environ.setdefault("NEWS_ROUTE_DEFAULT", "stub")
os.environ.setdefault("BROKER_CLIENT", "stub")
os.environ.setdefault("LONGBRIDGE_MODE", "stub")
os.environ.setdefault("LONGBRIDGE_AUTH", "token")
os.environ.setdefault("LONGBRIDGE_CLIENT_ID", "")
os.environ.setdefault("LONGBRIDGE_APP_KEY", "")
os.environ.setdefault("LONGBRIDGE_APP_SECRET", "")
os.environ.setdefault("LONGBRIDGE_ACCESS_TOKEN", "")
os.environ.setdefault("LONGPORT_APP_KEY", "")
os.environ.setdefault("LONGPORT_APP_SECRET", "")
os.environ.setdefault("LONGPORT_ACCESS_TOKEN", "")
os.environ.setdefault("FINNHUB_API_KEY", "")
os.environ.setdefault("FMP_API_KEY", "")
os.environ.setdefault("MASSIVE_API_KEY", "")
os.environ.setdefault("IBKR_GATEWAY_MODE", "stub")
os.environ.setdefault("IBKR_READONLY", "true")
os.environ.setdefault("BROKER_IBKR_MODE", "auto")
os.environ.setdefault("IBKR_FLEX_TOKEN", "")
os.environ.setdefault("IBKR_FLEX_QUERY_ID", "")
os.environ.setdefault("IBKR_FLEX_ACTIVITY_QUERY_ID", "")
os.environ.setdefault("IBKR_FLEX_POSITION_QUERY_ID", "")


@pytest.fixture
def stub_settings():
    from sec_analysis.config import Settings

    return Settings(
        market_data_provider="stub",
        market_data_route_us="stub",
        market_data_route_hk="stub",
        market_data_route_cn="stub",
        market_data_route_jp="stub",
        market_data_route_kr="stub",
        market_data_route_default="stub",
        history_route_us="stub",
        history_route_hk="",
        history_route_cn="",
        history_route_jp="",
        history_route_kr="",
        history_route_default="stub",
        fundamentals_provider="stub",
        fundamentals_route_cn="stub",
        fundamentals_route_us="stub",
        fundamentals_route_default="stub",
        options_provider="stub",
        news_provider="stub",
        news_route_us="stub",
        news_route_hk="stub",
        news_route_cn="stub",
        news_route_default="stub",
        broker_client="stub",
        longbridge_mode="stub",
    )
