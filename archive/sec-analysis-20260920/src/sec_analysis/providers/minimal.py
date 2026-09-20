"""Unwired live adapters. Present so markets can be routed later without
pretending a US-only stack is enough.

Each class is a stub/TODO. Factory may fall back to the deterministic stub
when a key or extra is missing.
"""

from __future__ import annotations

from datetime import datetime

from sec_analysis.core.errors import ProviderConfigError
from sec_analysis.core.instrument import SymbolRef, coerce_ticker
from sec_analysis.core.interfaces import MarketDataProvider
from sec_analysis.core.models import Bar, Quote


class UnwiredMarketDataProvider(MarketDataProvider):
    """Shared skeleton: refuse live calls until a vendor is chosen and wired."""

    name = "unwired"
    documented_endpoint = ""

    def __init__(self, api_key: str = "", *, requires_key: bool = True) -> None:
        self.api_key = api_key
        self.requires_key = requires_key

    def get_quote(self, symbol: SymbolRef) -> Quote:
        self._guard(coerce_ticker(symbol))
        raise ProviderConfigError(self._todo("quote"))

    def get_bars(
        self,
        symbol: SymbolRef,
        *,
        interval: str = "1d",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        self._guard(coerce_ticker(symbol))
        raise ProviderConfigError(self._todo("bars"))

    def _guard(self, ticker: str) -> None:
        if self.requires_key and not self.api_key:
            raise ProviderConfigError(
                f"{self.name} API key is empty; not calling live HTTP for {ticker}"
            )

    def _todo(self, action: str) -> str:
        hint = f" Planned: {self.documented_endpoint}." if self.documented_endpoint else ""
        return (
            f"TODO: {self.name} {action} is not wired.{hint} "
            "Choose this adapter per market in MARKET_DATA_ROUTE_* before we deep-implement it."
        )


class TwelveDataMarketDataProvider(UnwiredMarketDataProvider):
    name = "twelvedata"
    documented_endpoint = "GET https://api.twelvedata.com/quote"


class EodhdMarketDataProvider(UnwiredMarketDataProvider):
    name = "eodhd"
    documented_endpoint = "GET https://eodhd.com/api/real-time/{ticker}"


class MassiveMarketDataProvider(UnwiredMarketDataProvider):
    name = "massive"
    documented_endpoint = "GET /v2/aggs/ticker/{ticker}/prev"
