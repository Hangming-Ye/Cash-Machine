"""Read-only programmatic façade.

Composes the existing routers and broker adapters. Does not place, modify,
or cancel orders. Inject ``bundle`` in tests so CI never hits live vendors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Instrument, SymbolRef, resolve_instrument
from sec_analysis.core.models import (
    AccountSummary,
    Bar,
    Execution,
    Fundamental,
    NewsItem,
    Position,
    Quote,
    StatementReport,
)
from sec_analysis.providers.fundamentals_router import FundamentalsRouter
from sec_analysis.providers.news_router import NewsRouter
from sec_analysis.providers.registry import ProviderBundle, build_providers
from sec_analysis.providers.router import MarketDataRouter


class SecAnalysisClient:
    """Unified read API: quote, bars, news, 财报, account.

    Reads ``Settings`` / ``.env`` unless you pass ``settings`` or ``bundle``.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        bundle: ProviderBundle | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self._bundle = bundle or build_providers(self.settings)
        self._broker_cache: dict[str, ProviderBundle] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> SecAnalysisClient:
        return cls(settings)

    def _instrument(self, symbol: SymbolRef, market: str | None = None) -> Instrument:
        return resolve_instrument(symbol, market=market)

    def _providers(self, *, broker: str | None = None) -> ProviderBundle:
        if not broker or broker == self.settings.broker_client:
            return self._bundle
        if broker not in self._broker_cache:
            extra = self.settings.model_copy(update={"broker_client": broker})
            self._broker_cache[broker] = build_providers(extra)
        return self._broker_cache[broker]

    def quote(self, symbol: SymbolRef, *, market: str | None = None) -> Quote:
        inst = self._instrument(symbol, market)
        return self._bundle.market_data.get_quote(inst)

    def bars(
        self,
        symbol: SymbolRef,
        *,
        market: str | None = None,
        interval: str = "1d",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        inst = self._instrument(symbol, market)
        return self._bundle.market_data.get_bars(
            inst, interval=interval, start=start, end=end, limit=limit
        )

    def news(
        self,
        symbol: str | None = None,
        *,
        market: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        if symbol:
            return self.company_news(symbol, market=market, start=start, end=end, limit=limit)
        if market and str(market).upper() == "CN":
            raise ProviderConfigError(
                "CN news via AKShare needs a symbol. "
                "Example: client.company_news('600519') or client.news('600519', market='CN')."
            )
        return self._bundle.news.get_news(None, start=start, end=end, limit=limit)

    def company_news(
        self,
        symbol: SymbolRef,
        *,
        market: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        inst = self._instrument(symbol, market)
        return self._bundle.news.get_company_news(
            inst.display(), start=start, end=end, limit=limit
        )

    def fundamentals(self, symbol: SymbolRef, *, market: str | None = None) -> Fundamental:
        inst = self._instrument(symbol, market)
        return self._bundle.fundamentals.get_fundamentals(inst)

    def statement(
        self,
        symbol: SymbolRef,
        *,
        statement: str = "income",
        market: str | None = None,
        limit_periods: int = 8,
    ) -> StatementReport:
        inst = self._instrument(symbol, market)
        return self._bundle.fundamentals.get_statement(
            inst, statement=statement, limit_periods=limit_periods
        )

    def account(self, *, broker: str | None = None) -> AccountSummary:
        return self._providers(broker=broker).broker.get_account_summary()

    def positions(self, *, broker: str | None = None) -> list[Position]:
        return self._providers(broker=broker).broker.get_positions()

    def executions(
        self,
        *,
        broker: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        history: bool = False,
        flex: bool = False,
    ) -> list[Execution]:
        if flex and history:
            raise ProviderConfigError(
                "Use flex=True (IBKR) or history=True (Longbridge), not both."
            )
        bundle = self._providers(broker=broker)
        if flex:
            return bundle.flex.get_activity_executions(start=start, end=end)
        if history:
            if bundle.broker.name != "longbridge":
                raise ProviderConfigError(
                    "history=True is Longbridge-only. For IBKR long history use flex=True."
                )
            return bundle.broker.get_executions(start=start, end=end, history=True)
        return bundle.broker.get_executions(start=start, end=end)

    def is_connected(self, *, broker: str | None = None) -> bool:
        return self._providers(broker=broker).broker.is_connected()

    def longbridge_login(self) -> dict[str, str]:
        """OAuth 2.0 browser login. Token is stored by the SDK, not in ``.env``."""
        broker = self._providers(broker="longbridge").broker
        login = getattr(broker, "login_oauth", None)
        if not callable(login):
            raise ProviderConfigError("Longbridge OAuth login is not available on this broker.")
        return login()

    def routes(self) -> dict[str, Any]:
        """Configured adapter names (introspection; no live calls)."""
        md = self._bundle.market_data
        news = self._bundle.news
        fund = self._bundle.fundamentals
        return {
            "market_data": md.route_names() if isinstance(md, MarketDataRouter) else [md.name],
            "history": (
                md.history_route_names() if isinstance(md, MarketDataRouter) else [md.name]
            ),
            "news": news.route_names() if isinstance(news, NewsRouter) else [news.name],
            "fundamentals": (
                fund.route_names() if isinstance(fund, FundamentalsRouter) else [fund.name]
            ),
            "broker": self._bundle.broker.name,
            "flex": self._bundle.flex.name,
        }


# Re-export errors so callers can import from one module.
__all__ = ["ProviderConfigError", "ProviderError", "SecAnalysisClient"]
