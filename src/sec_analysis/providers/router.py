"""Config-driven market → provider chain. No vendor is hard-coded as primary."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Market, SymbolRef, resolve_instrument
from sec_analysis.core.interfaces import MarketDataProvider
from sec_analysis.core.models import Bar, Quote

logger = logging.getLogger(__name__)

Factory = Callable[[str], MarketDataProvider]


class MarketDataRouter(MarketDataProvider):
    """Try providers in per-market order; fall through on failure or empty result."""

    name = "router"

    def __init__(
        self,
        chains: Mapping[Market, Sequence[MarketDataProvider]],
        *,
        default: Sequence[MarketDataProvider],
        history_chains: Mapping[Market, Sequence[MarketDataProvider]] | None = None,
        history_default: Sequence[MarketDataProvider] | None = None,
    ) -> None:
        if not default:
            raise ValueError("MarketDataRouter needs a default provider chain")
        self._chains = {market: list(providers) for market, providers in chains.items()}
        self._default = list(default)
        self._history_chains = {
            market: list(providers) for market, providers in (history_chains or {}).items()
        }
        self._history_default = list(history_default) if history_default is not None else None

    def chain_for(self, market: Market) -> list[MarketDataProvider]:
        return list(self._chains.get(market) or self._default)

    def history_chain_for(self, market: Market) -> list[MarketDataProvider]:
        if self._history_default is None and not self._history_chains:
            return self.chain_for(market)
        return list(
            self._history_chains.get(market) or self._history_default or self.chain_for(market)
        )

    def route_names(self) -> dict[str, list[str]]:
        names = {market.value: [p.name for p in chain] for market, chain in self._chains.items()}
        names["DEFAULT"] = [p.name for p in self._default]
        return names

    def history_route_names(self) -> dict[str, list[str]]:
        if self._history_default is None and not self._history_chains:
            return self.route_names()
        names = {
            market.value: [p.name for p in chain] for market, chain in self._history_chains.items()
        }
        names["DEFAULT"] = [p.name for p in (self._history_default or self._default)]
        return names

    def get_quote(self, symbol: SymbolRef) -> Quote:
        inst = resolve_instrument(symbol)
        errors: list[str] = []
        for provider in self.chain_for(inst.market):
            try:
                quote = provider.get_quote(inst)
            except ProviderConfigError:
                raise
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.info("router skip %s for %s: %s", provider.name, inst.display(), exc)
                continue
            return quote.model_copy(
                update={
                    "symbol": inst.display(),
                    "source": provider.name,
                    "market": inst.market,
                    "exchange": inst.exchange or quote.exchange,
                    "mic": inst.mic or quote.mic,
                    "currency": inst.currency or quote.currency,
                }
            )
        raise ProviderError(
            f"No market-data provider returned a quote for {inst.display()} "
            f"({inst.market}). Tried: {errors or [p.name for p in self.chain_for(inst.market)]}"
        )

    def get_bars(
        self,
        symbol: SymbolRef,
        *,
        interval: str = "1d",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        inst = resolve_instrument(symbol)
        errors: list[str] = []
        chain = self.history_chain_for(inst.market)
        for provider in chain:
            try:
                bars = provider.get_bars(
                    inst, interval=interval, start=start, end=end, limit=limit
                )
            except ProviderConfigError:
                raise
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            if not bars:
                continue
            return [
                bar.model_copy(
                    update={
                        "symbol": inst.display(),
                        "market": inst.market,
                        "mic": inst.mic or bar.mic,
                    }
                )
                for bar in bars
            ]
        raise ProviderError(
            f"No market-data provider returned bars for {inst.display()} ({inst.market}). "
            f"Tried: {errors or [p.name for p in chain]}"
        )
