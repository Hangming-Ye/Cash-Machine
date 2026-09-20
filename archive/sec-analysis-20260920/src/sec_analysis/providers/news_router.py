"""Per-market news routing. Mirrors ``MarketDataRouter`` chain semantics.

CN company news → AKShare (``NEWS_ROUTE_CN``). US/HK/general → Finnhub.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Market, resolve_instrument
from sec_analysis.core.interfaces import NewsProvider
from sec_analysis.core.models import NewsItem

logger = logging.getLogger(__name__)


class NewsRouter(NewsProvider):
    """Try news providers in per-market order; fall through on empty/failure."""

    name = "router"

    def __init__(
        self,
        chains: Mapping[Market, Sequence[NewsProvider]],
        *,
        default: Sequence[NewsProvider],
    ) -> None:
        if not default:
            raise ValueError("NewsRouter needs a default provider chain")
        self._chains = {market: list(providers) for market, providers in chains.items()}
        self._default = list(default)

    def chain_for(self, market: Market) -> list[NewsProvider]:
        return list(self._chains.get(market) or self._default)

    def route_names(self) -> dict[str, list[str]]:
        names = {market.value: [p.name for p in chain] for market, chain in self._chains.items()}
        names["DEFAULT"] = [p.name for p in self._default]
        return names

    def get_news(
        self,
        symbol: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        if not symbol:
            return self._run(self._default, None, start=start, end=end, limit=limit)
        return self.get_company_news(symbol, start=start, end=end, limit=limit)

    def get_company_news(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        inst = resolve_instrument(symbol)
        return self._run(
            self.chain_for(inst.market),
            inst.symbol,
            start=start,
            end=end,
            limit=limit,
        )

    def _run(
        self,
        chain: Sequence[NewsProvider],
        symbol: str | None,
        *,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[NewsItem]:
        errors: list[str] = []
        for provider in chain:
            try:
                items = (
                    provider.get_company_news(symbol, start=start, end=end, limit=limit)
                    if symbol
                    else provider.get_news(None, start=start, end=end, limit=limit)
                )
            except ProviderConfigError:
                raise
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.info("news router skip %s: %s", provider.name, exc)
                continue
            if items:
                return items
        label = symbol or "general"
        raise ProviderError(
            f"No news provider returned headlines for {label}. "
            f"Tried: {errors or [p.name for p in chain]}"
        )
