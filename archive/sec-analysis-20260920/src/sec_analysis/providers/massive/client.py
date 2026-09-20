"""Massive (Polygon) stub — later paid options path, not the current prototype.

The options prototype is yfinance only. Finnhub's options API was removed.

Planned (not implemented, do not call live yet):

* REST snapshot: ``GET /v3/snapshot/options/{underlyingAsset}``
* Contract quotes / greeks once a ``MASSIVE_API_KEY`` is supplied
* Respect Massive rate limits separately from Finnhub

Until then this class either refuses live calls or delegates to a stub
fallback provided by the factory.
"""

from __future__ import annotations

from datetime import date

from sec_analysis.core.errors import ProviderConfigError
from sec_analysis.core.interfaces import OptionsProvider
from sec_analysis.core.models import OptionChain


class MassiveOptionsProvider(OptionsProvider):
    """Extension point. Live Massive HTTP is intentionally not wired."""

    name = "massive"

    def __init__(self, api_key: str = "", fallback: OptionsProvider | None = None) -> None:
        self.api_key = api_key
        self._fallback = fallback

    def get_option_chain(
        self,
        symbol: str,
        *,
        expiration: date | None = None,
    ) -> OptionChain:
        if self._fallback is not None:
            return self._fallback.get_option_chain(symbol, expiration=expiration)
        raise ProviderConfigError(
            "Massive options client is a stub. Set OPTIONS_PROVIDER=stub|yfinance "
            "or pass a fallback. Planned path: GET /v3/snapshot/options/{underlying}."
        )
