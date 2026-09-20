"""Finnhub HTTP client — phase-1 market data and news.

Live calls require ``FINNHUB_API_KEY``. Missing key raises a clear error
(no silent stub swap). Finnhub has no options API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import SymbolRef, coerce_ticker
from sec_analysis.core.interfaces import MarketDataProvider, NewsProvider
from sec_analysis.core.models import Bar, NewsItem, Quote
from sec_analysis.core.rate_limit import RateLimiter

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

MISSING_API_KEY = (
    "FINNHUB_API_KEY is not set. Phase-1 quotes, bars, and news need a Finnhub key. "
    "Copy .env.example to .env and set FINNHUB_API_KEY (https://finnhub.io/)."
)

_RESOLUTION = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "1d": "D",
    "1w": "W",
}


def _as_utc(ts: int | float) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=UTC)


class FinnhubHttpClient:
    """Thin wrapper around Finnhub REST. Injectable ``httpx.Client`` for tests."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = 15.0,
        base_url: str = FINNHUB_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self._limiter = limiter or RateLimiter()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise ProviderConfigError(MISSING_API_KEY)
        query = dict(params or {})
        query["token"] = self.api_key
        self._limiter.wait()
        try:
            response = self._client.get(path, params=query)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 403 and path.rstrip("/").endswith("candle"):
                raise ProviderError(
                    "Finnhub candles returned HTTP 403. Free-tier keys often cannot "
                    "call /stock/candle. No bars were invented."
                ) from exc
            raise ProviderError(f"Finnhub request failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Finnhub request failed: {exc}") from exc

    def quote(self, symbol: str) -> dict[str, Any]:
        payload = self.get("/quote", {"symbol": symbol})
        if not isinstance(payload, dict):
            raise ProviderError("Finnhub quote returned a non-object payload")
        return payload

    def candles(
        self,
        symbol: str,
        *,
        resolution: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        payload = self.get(
            "/stock/candle",
            {
                "symbol": symbol,
                "resolution": resolution,
                "from": int(start.timestamp()),
                "to": int(end.timestamp()),
            },
        )
        if not isinstance(payload, dict):
            raise ProviderError("Finnhub candles returned a non-object payload")
        return payload

    def company_news(self, symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        payload = self.get(
            "/company-news",
            {
                "symbol": symbol,
                "from": start.date().isoformat(),
                "to": end.date().isoformat(),
            },
        )
        if not isinstance(payload, list):
            raise ProviderError("Finnhub company-news returned a non-list payload")
        return payload

    def general_news(self, category: str = "general") -> list[dict[str, Any]]:
        payload = self.get("/news", {"category": category})
        if not isinstance(payload, list):
            raise ProviderError("Finnhub news returned a non-list payload")
        return payload


class FinnhubMarketDataProvider(MarketDataProvider):
    name = "finnhub"

    def __init__(self, client: FinnhubHttpClient) -> None:
        self._client = client

    def get_quote(self, symbol: SymbolRef) -> Quote:
        ticker = coerce_ticker(symbol)
        raw = self._client.quote(ticker.upper())
        ts = raw.get("t") or 0
        return Quote(
            symbol=ticker.upper(),
            last=_opt_float(raw.get("c")),
            open=_opt_float(raw.get("o")),
            high=_opt_float(raw.get("h")),
            low=_opt_float(raw.get("l")),
            previous_close=_opt_float(raw.get("pc")),
            volume=_opt_float(raw.get("v") or raw.get("volume")),
            as_of=_as_utc(ts) if ts else datetime.now(tz=UTC),
            source=self.name,
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
        ticker = coerce_ticker(symbol)
        resolution = _RESOLUTION.get(interval, "D")
        end_dt = end or datetime.now(tz=UTC)
        if start is None:
            if resolution in {"D", "W"}:
                lookback = timedelta(days=max(limit, 1) + 5)
            else:
                lookback = timedelta(hours=limit)
            start = end_dt - lookback
        raw = self._client.candles(ticker.upper(), resolution=resolution, start=start, end=end_dt)
        if raw.get("s") == "no_data":
            return []
        stamps = raw.get("t") or []
        return [
            Bar(
                symbol=ticker.upper(),
                timestamp=_as_utc(stamps[i]),
                open=float(raw["o"][i]),
                high=float(raw["h"][i]),
                low=float(raw["l"][i]),
                close=float(raw["c"][i]),
                volume=float(raw["v"][i]),
                interval=interval,
                source=self.name,
            )
            for i in range(len(stamps))
        ][-limit:]


class FinnhubNewsProvider(NewsProvider):
    name = "finnhub"

    def __init__(self, client: FinnhubHttpClient) -> None:
        self._client = client

    def get_news(
        self,
        symbol: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        if symbol:
            return self.get_company_news(symbol, start=start, end=end, limit=limit)
        return self.get_general_news(limit=limit)

    def get_general_news(self, *, limit: int = 20) -> list[NewsItem]:
        raw_items = self._client.general_news("general")
        return [_row_to_news(row, symbol=None) for row in raw_items[: max(1, limit)]]

    def get_company_news(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        ticker = symbol.upper()
        end_dt = end or datetime.now(tz=UTC)
        start_dt = start or (end_dt - timedelta(days=7))
        raw_items = self._client.company_news(ticker, start_dt, end_dt)
        return [_row_to_news(row, symbol=ticker) for row in raw_items[: max(1, limit)]]


def _row_to_news(row: dict[str, Any], *, symbol: str | None) -> NewsItem:
    published = _as_utc(row.get("datetime") or 0)
    ticker = symbol or None
    related = [ticker] if ticker else []
    ident = str(row.get("id") or row.get("url") or f"{ticker or 'mkt'}-{published.isoformat()}")
    return NewsItem(
        id=ident,
        symbol=ticker,
        headline=str(row.get("headline") or "(no headline)"),
        summary=row.get("summary"),
        url=row.get("url"),
        source=str(row.get("source") or "finnhub"),
        published_at=published,
        related_symbols=related,
    )


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
