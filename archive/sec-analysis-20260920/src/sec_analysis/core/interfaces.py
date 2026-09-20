"""Provider and broker contracts.

Broker implementations MUST be named ``*ReadOnly*`` and MUST NOT expose
place / modify / cancel order methods. See ``sec_analysis.brokers.ibkr.safety``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from sec_analysis.core.instrument import SymbolRef
from sec_analysis.core.models import (
    AccountSummary,
    Bar,
    Execution,
    Fundamental,
    NewsItem,
    OptionChain,
    Position,
    Quote,
    StatementReport,
)


class MarketDataProvider(ABC):
    """Quotes and OHLCV bars."""

    name: str

    @abstractmethod
    def get_quote(self, symbol: SymbolRef) -> Quote:
        """Latest quote. Ticker, ``600519.SH`` / ``HK:00700``, or Instrument."""

    @abstractmethod
    def get_bars(
        self,
        symbol: SymbolRef,
        *,
        interval: str = "1d",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        """Historical bars. ``interval`` is ``1m``, ``5m``, ``1h``, ``1d``, ``1w``."""


class FundamentalsProvider(ABC):
    """Company profile / key ratios, plus optional CN financial statements."""

    name: str

    @abstractmethod
    def get_fundamentals(self, symbol: SymbolRef) -> Fundamental:
        """Latest snapshot of fundamentals for ``symbol``."""

    def get_statement(
        self,
        symbol: SymbolRef,
        *,
        statement: str = "income",
        limit_periods: int = 8,
    ) -> StatementReport:
        """Income / balance / cash statement. Default: not implemented."""
        from sec_analysis.core.errors import ProviderConfigError

        raise ProviderConfigError(
            f"{self.name} does not provide financial statements. "
            "CN A-shares: FUNDAMENTALS_ROUTE_CN=akshare (stock_financial_report_sina). "
            "US: FUNDAMENTALS_ROUTE_US=fmp (income|balance|cash)."
        )


class OptionsProvider(ABC):
    """Option-chain snapshot.

    Adapters: stub, yfinance, massive. Finnhub removed its options API — do
    not add a Finnhub options adapter that pretends to work.
    """

    name: str

    @abstractmethod
    def get_option_chain(
        self,
        symbol: str,
        *,
        expiration: date | None = None,
    ) -> OptionChain:
        """Chain snapshot. If ``expiration`` is omitted, return a small default set."""


class NewsProvider(ABC):
    """Company or general market headlines."""

    name: str

    @abstractmethod
    def get_news(
        self,
        symbol: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        """Newest-first headlines. Omit ``symbol`` for general market news."""

    def get_company_news(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        """Company-specific headlines. Default: ``get_news(symbol)``."""
        return self.get_news(symbol, start=start, end=end, limit=limit)


class BrokerReadOnlyClient(ABC):
    """Read-only broker access: account, positions, historical executions.

    Implementations MUST NOT place, modify, or cancel orders. Class names
    must include ``ReadOnly``. Safety checks live in
    ``sec_analysis.brokers.ibkr.safety``.
    """

    name: str

    @abstractmethod
    def get_account_summary(self) -> AccountSummary:
        """Account balances and buying-power snapshot."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Open positions. Does not change any position."""

    @abstractmethod
    def get_executions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Execution]:
        """Session / same-day fills only (Client Portal trades or ib_insync fills).

        Long-term history belongs on ``FlexActivityReadOnlyClient`` (T+1).
        """

    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the (possibly stubbed) session is considered connected."""


class FlexActivityReadOnlyClient(ABC):
    """IBKR Flex Web Service (Activity Flex Query).

    Flow: token + query id → SendRequest → poll GetStatement → parse XML/CSV.
    Typical **T+1**. Phase-1 recommended IBKR path (no Gateway).
    """

    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """True when a Flex token and query id are present (still may be stubbed)."""

    @abstractmethod
    def get_activity_executions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Execution]:
        """Parsed Activity Flex trades. Research data only — never submits anything."""
