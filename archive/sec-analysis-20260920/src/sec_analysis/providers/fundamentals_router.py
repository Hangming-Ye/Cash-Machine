"""Per-market fundamentals routing. Mirrors ``MarketDataRouter`` / ``NewsRouter``.

CN A-share 财报 → AKShare Sina. US statements → FMP (FUNDAMENTALS_ROUTE_US=fmp).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Market, SymbolRef, resolve_instrument
from sec_analysis.core.interfaces import FundamentalsProvider
from sec_analysis.core.models import Fundamental, StatementReport

logger = logging.getLogger(__name__)


class FundamentalsRouter(FundamentalsProvider):
    name = "router"

    def __init__(
        self,
        chains: Mapping[Market, Sequence[FundamentalsProvider]],
        *,
        default: Sequence[FundamentalsProvider],
    ) -> None:
        if not default:
            raise ValueError("FundamentalsRouter needs a default provider chain")
        self._chains = {market: list(providers) for market, providers in chains.items()}
        self._default = list(default)

    def chain_for(self, market: Market) -> list[FundamentalsProvider]:
        return list(self._chains.get(market) or self._default)

    def route_names(self) -> dict[str, list[str]]:
        names = {market.value: [p.name for p in chain] for market, chain in self._chains.items()}
        names["DEFAULT"] = [p.name for p in self._default]
        return names

    def get_fundamentals(self, symbol: SymbolRef) -> Fundamental:
        inst = resolve_instrument(symbol)
        errors: list[str] = []
        for provider in self.chain_for(inst.market):
            try:
                snap = provider.get_fundamentals(inst)
            except ProviderConfigError:
                raise
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.info("fundamentals router skip %s: %s", provider.name, exc)
                continue
            return snap
        raise ProviderError(
            f"No fundamentals provider returned a snapshot for {inst.display()}. "
            f"Tried: {errors or [p.name for p in self.chain_for(inst.market)]}"
        )

    def get_statement(
        self,
        symbol: SymbolRef,
        *,
        statement: str = "income",
        limit_periods: int = 8,
    ) -> StatementReport:
        inst = resolve_instrument(symbol)
        errors: list[str] = []
        for provider in self.chain_for(inst.market):
            try:
                return provider.get_statement(
                    inst, statement=statement, limit_periods=limit_periods
                )
            except ProviderConfigError:
                raise
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.info("statement router skip %s: %s", provider.name, exc)
                continue
        raise ProviderError(
            f"No fundamentals provider returned a {statement} statement for {inst.display()}. "
            f"Tried: {errors or [p.name for p in self.chain_for(inst.market)]}"
        )
