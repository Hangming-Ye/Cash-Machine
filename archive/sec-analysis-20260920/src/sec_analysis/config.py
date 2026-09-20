"""Environment-driven settings. Secrets stay in ``.env`` (never committed).

Phase-1 locked providers: Finnhub (US/HK quotes + news), Tiingo (US daily
OHLCV), FMP (US statements), AKShare (CN quotes / bars / company news / Sina
财报), IBKR and Longbridge read-only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from sec_analysis.core.instrument import Market

MarketDataName = Literal[
    "stub",
    "finnhub",
    "yfinance",
    "twelvedata",
    "eodhd",
    "tiingo",
    "akshare",
    "massive",
]
FundamentalsName = Literal["stub", "fmp", "akshare"]
OptionsName = Literal["stub", "yfinance", "massive"]
NewsName = Literal["stub", "finnhub", "rss", "akshare"]
BrokerName = Literal["stub", "ibkr", "longbridge"]
IbkrMode = Literal["stub", "client_portal", "tws"]
BrokerIbkrMode = Literal["auto", "flex", "gateway"]
LongbridgeMode = Literal["stub", "live"]
LongbridgeAuth = Literal["oauth", "token"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Phase-1 defaults
    market_data_provider: MarketDataName = "finnhub"
    news_provider: NewsName = "finnhub"
    broker_client: BrokerName = "ibkr"
    fundamentals_provider: FundamentalsName = "fmp"
    options_provider: OptionsName = "stub"

    # US/HK quotes → Finnhub. US daily bars → HISTORY_ROUTE_US=tiingo. CN → AKShare.
    market_data_route_us: str = "finnhub"
    market_data_route_hk: str = "finnhub"
    market_data_route_default: str = "finnhub"
    market_data_route_cn: str = "akshare"
    market_data_route_jp: str = "stub"
    market_data_route_kr: str = "stub"

    # Historical OHLCV. Empty → fall back to MARKET_DATA_ROUTE_* for that market.
    history_route_us: str = "tiingo"
    history_route_hk: str = ""
    history_route_cn: str = ""
    history_route_jp: str = ""
    history_route_kr: str = ""
    history_route_default: str = "tiingo"

    # CN company news → AKShare. US/HK/general → Finnhub. Comma lists like MARKET_DATA_ROUTE_*.
    news_route_cn: str = "akshare"
    news_route_us: str = "finnhub"
    news_route_hk: str = "finnhub"
    news_route_jp: str = ""
    news_route_kr: str = ""
    news_route_default: str = ""

    # CN 财报 → AKShare Sina. US statements → FMP. Bare tickers use default=fmp.
    fundamentals_route_cn: str = "akshare"
    fundamentals_route_us: str = "fmp"
    fundamentals_route_hk: str = ""
    fundamentals_route_jp: str = ""
    fundamentals_route_kr: str = ""
    fundamentals_route_default: str = "fmp"

    finnhub_api_key: str = ""
    fmp_api_key: str = ""
    massive_api_key: str = ""
    twelve_data_api_key: str = ""
    eodhd_api_key: str = ""
    tiingo_api_key: str = ""

    rss_feeds: str = "https://feeds.reuters.com/reuters/businessNews"

    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 5000
    ibkr_account_id: str = ""
    ibkr_client_id: int = 1
    ibkr_gateway_mode: IbkrMode = "stub"
    ibkr_readonly: bool = True
    # Phase-1 recommended: Flex Web Service (no Gateway).
    broker_ibkr_mode: BrokerIbkrMode = "auto"
    ibkr_flex_token: str = ""
    ibkr_flex_query_id: str = ""
    ibkr_flex_activity_query_id: str = ""
    ibkr_flex_position_query_id: str = ""
    ibkr_flex_base_url: str = ""

    # Official Longbridge names. LONGPORT_* aliases are accepted.
    # Default auth is the token trio. OAuth is opt-in (LONGBRIDGE_AUTH=oauth).
    # Do not put OAuth access tokens in .env.
    longbridge_mode: LongbridgeMode = "stub"
    longbridge_auth: LongbridgeAuth = "token"
    longbridge_client_id: str = ""
    longbridge_account_id: str = ""
    longbridge_app_key: str = ""
    longbridge_app_secret: str = ""
    longbridge_access_token: str = ""
    longport_app_key: str = ""
    longport_app_secret: str = ""
    longport_access_token: str = ""

    cache_path: str = "data/sec_analysis.sqlite"
    rate_limit_per_minute: float = Field(default=50.0, gt=0)
    http_timeout: float = Field(default=15.0, gt=0)

    @field_validator("longbridge_auth", mode="before")
    @classmethod
    def _normalize_longbridge_auth(cls, value: object) -> str:
        raw = str(value or "token").strip().lower()
        if raw in {"", "token", "apikey", "trio"}:
            return "token"
        if raw == "oauth":
            return "oauth"
        raise ValueError("LONGBRIDGE_AUTH must be oauth or token")

    @field_validator("ibkr_readonly")
    @classmethod
    def _force_readonly(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError(
                "IBKR_READONLY must stay true — this framework never opens a write session"
            )
        return True

    def ibkr_flex_any_query_id(self) -> str:
        return (
            self.ibkr_flex_query_id.strip()
            or self.ibkr_flex_activity_query_id.strip()
            or self.ibkr_flex_position_query_id.strip()
        )

    def ibkr_flex_configured(self) -> bool:
        return bool(self.ibkr_flex_token.strip() and self.ibkr_flex_any_query_id())

    def ibkr_use_flex(self) -> bool:
        """True when Flex is the IBKR read path (explicit or auto + env)."""
        mode = (self.broker_ibkr_mode or "auto").strip().lower()
        if mode == "flex":
            return True
        if mode == "gateway":
            return False
        return self.ibkr_flex_configured()

    def ibkr_flex_query_for(self, kind: str) -> str:
        if kind == "positions" and self.ibkr_flex_position_query_id.strip():
            return self.ibkr_flex_position_query_id.strip()
        activity = self.ibkr_flex_activity_query_id.strip()
        if kind in {"activity", "account", "executions"} and activity:
            return activity
        query = self.ibkr_flex_any_query_id()
        if not query:
            raise ValueError("No IBKR Flex query id is configured")
        return query

    def rss_feed_list(self) -> list[str]:
        return [part.strip() for part in self.rss_feeds.split(",") if part.strip()]

    def longbridge_credentials(self) -> tuple[str, str, str]:
        """Legacy API-key triple. Official LONGBRIDGE_* first, then LONGPORT_*."""
        key = (self.longbridge_app_key or self.longport_app_key).strip()
        secret = (self.longbridge_app_secret or self.longport_app_secret).strip()
        token = (self.longbridge_access_token or self.longport_access_token).strip()
        return key, secret, token

    def longbridge_oauth_client_id(self) -> str:
        return (self.longbridge_client_id or "").strip()

    def news_route_names(self, market: Market) -> list[str]:
        """Ordered news adapters for a market (same comma-list shape as market data)."""
        table = {
            Market.US: self.news_route_us,
            Market.CN: self.news_route_cn,
            Market.HK: self.news_route_hk,
            Market.JP: self.news_route_jp,
            Market.KR: self.news_route_kr,
            Market.UNKNOWN: self.news_route_default,
        }
        raw = (table.get(market) or "").strip()
        if not raw:
            raw = (self.news_route_default or self.news_provider or "stub").strip()
        return [part.strip() for part in raw.split(",") if part.strip()]

    def fundamentals_route_names(self, market: Market) -> list[str]:
        table = {
            Market.US: self.fundamentals_route_us,
            Market.CN: self.fundamentals_route_cn,
            Market.HK: self.fundamentals_route_hk,
            Market.JP: self.fundamentals_route_jp,
            Market.KR: self.fundamentals_route_kr,
            Market.UNKNOWN: self.fundamentals_route_default,
        }
        raw = (table.get(market) or "").strip()
        if not raw:
            raw = (self.fundamentals_route_default or self.fundamentals_provider or "stub").strip()
        return [part.strip() for part in raw.split(",") if part.strip()]

    def history_route_names(self, market: Market) -> list[str]:
        """Ordered history/OHLCV adapters. Empty → market-data chain for that market."""
        table = {
            Market.US: self.history_route_us,
            Market.CN: self.history_route_cn,
            Market.HK: self.history_route_hk,
            Market.JP: self.history_route_jp,
            Market.KR: self.history_route_kr,
            Market.UNKNOWN: self.history_route_default,
        }
        raw = (table.get(market) or "").strip()
        if not raw:
            return self.market_data_route_names(market)
        return [part.strip() for part in raw.split(",") if part.strip()]

    def market_data_route_names(self, market: Market) -> list[str]:
        table = {
            Market.US: self.market_data_route_us,
            Market.CN: self.market_data_route_cn,
            Market.HK: self.market_data_route_hk,
            Market.JP: self.market_data_route_jp,
            Market.KR: self.market_data_route_kr,
            Market.UNKNOWN: self.market_data_route_default,
        }
        raw = (table.get(market) or "").strip()
        if not raw:
            raw = (self.market_data_route_default or self.market_data_provider).strip()
        return [part.strip() for part in raw.split(",") if part.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
