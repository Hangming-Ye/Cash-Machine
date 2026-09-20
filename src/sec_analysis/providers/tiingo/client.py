"""Tiingo EOD / daily OHLCV (US historical bars).

Free/starter covers ``GET /tiingo/daily/{ticker}/prices`` (daily, weekly,
monthly) with volume when the vendor publishes it. Intraday IEX is not
wired. Missing ``TIINGO_API_KEY`` is a config error — no invented bars.

US quotes and news stay on Finnhub (``MARKET_DATA_ROUTE_US`` / ``NEWS_ROUTE_US``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import SymbolRef, resolve_instrument
from sec_analysis.core.interfaces import MarketDataProvider
from sec_analysis.core.models import Bar, Quote
from sec_analysis.core.rate_limit import RateLimiter

TIINGO_BASE_URL = "https://api.tiingo.com"

MISSING_API_KEY = (
    "TIINGO_API_KEY is not set. US daily OHLCV (HISTORY_ROUTE_US=tiingo) needs a "
    "Tiingo key. Copy .env.example to .env and set TIINGO_API_KEY "
    "(https://www.tiingo.com/). No bars were invented."
)

QUOTE_IS_HISTORY_ONLY = (
    "Tiingo adapter is EOD history only (daily/weekly bars). "
    "US quotes stay on Finnhub (MARKET_DATA_ROUTE_US=finnhub)."
)

_RESAMPLE = {
    "1d": "daily",
    "1w": "weekly",
    "1mo": "monthly",
    "1mth": "monthly",
}


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ProviderError(f"Tiingo date is not ISO-8601: {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class TiingoHttpClient:
    """Thin Tiingo REST wrapper. Injectable ``httpx.Client`` for tests."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = 15.0,
        base_url: str = TIINGO_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        self._limiter = limiter or RateLimiter()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise ProviderConfigError(MISSING_API_KEY)
        query = dict(params or {})
        query["token"] = self.api_key
        headers = {"Authorization": f"Token {self.api_key}"}
        self._limiter.wait()
        try:
            response = self._client.get(path, params=query, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = (exc.response.text or "")[:200]
            if status in {401, 403}:
                raise ProviderError(
                    f"Tiingo returned HTTP {status} (check TIINGO_API_KEY / plan). "
                    f"{body}".strip()
                ) from exc
            raise ProviderError(f"Tiingo request failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Tiingo request failed: {exc}") from exc

    def daily_prices(
        self,
        ticker: str,
        *,
        start: datetime,
        end: datetime,
        resample: str = "daily",
    ) -> list[dict[str, Any]]:
        payload = self.get(
            f"/tiingo/daily/{ticker}/prices",
            {
                "startDate": start.date().isoformat(),
                "endDate": end.date().isoformat(),
                "resampleFreq": resample,
            },
        )
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("error") or payload
            raise ProviderError(f"Tiingo daily prices error for {ticker}: {detail}")
        if not isinstance(payload, list):
            raise ProviderError("Tiingo daily prices returned a non-list payload")
        return payload


class TiingoMarketDataProvider(MarketDataProvider):
    """US EOD OHLCV. Quotes are not served (Finnhub remains the quote adapter)."""

    name = "tiingo"

    def __init__(
        self,
        api_key: str = "",
        *,
        client: TiingoHttpClient | httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = 15.0,
        base_url: str = TIINGO_BASE_URL,
    ) -> None:
        if isinstance(client, TiingoHttpClient):
            self._client = client
        else:
            self._client = TiingoHttpClient(
                api_key,
                client=client,
                limiter=limiter,
                timeout=timeout,
                base_url=base_url,
            )

    def get_quote(self, symbol: SymbolRef) -> Quote:
        if not self._client.api_key:
            raise ProviderConfigError(MISSING_API_KEY)
        raise ProviderError(QUOTE_IS_HISTORY_ONLY)

    def get_bars(
        self,
        symbol: SymbolRef,
        *,
        interval: str = "1d",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        ticker = resolve_instrument(symbol).symbol.upper()
        resample = _RESAMPLE.get(interval)
        if resample is None:
            raise ProviderError(
                f"Tiingo free/starter adapter serves EOD daily (and weekly/monthly) "
                f"bars only; interval={interval!r} is not wired. Use interval=1d. "
                "No bars were invented."
            )
        end_dt = end or datetime.now(tz=UTC)
        if start is None:
            per_bar = 8 if resample == "weekly" else 32 if resample == "monthly" else 3
            span = max(limit, 1) * per_bar
            start = end_dt - timedelta(days=span + 7)
        rows = self._client.daily_prices(ticker, start=start, end=end_dt, resample=resample)
        bars: list[Bar] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            mapped = _row_to_bar(ticker, row, interval=interval)
            if mapped is not None:
                bars.append(mapped)
        if not bars:
            raise ProviderError(
                f"Tiingo daily prices returned no usable OHLCV rows for {ticker}. "
                "No bars were invented."
            )
        return bars[-max(1, limit) :]


def _row_to_bar(ticker: str, row: dict[str, Any], *, interval: str) -> Bar | None:
    stamp = row.get("date")
    open_ = _opt_float(row.get("open"))
    high = _opt_float(row.get("high"))
    low = _opt_float(row.get("low"))
    close = _opt_float(row.get("close"))
    if stamp is None or None in (open_, high, low, close):
        return None
    volume = _opt_float(row.get("volume"))
    if volume is None:
        volume = _opt_float(row.get("adjVolume"))
    if volume is None:
        volume = 0.0
    return Bar(
        symbol=ticker,
        timestamp=_as_utc(stamp),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        interval=interval,
        source="tiingo",
    )
