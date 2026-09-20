"""Optional yfinance adapters (bars / volume + option-chain snapshot).

``yfinance`` is an extra: ``uv sync --extra yfinance``. Tests inject a fake
ticker factory so CI does not need the dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import SymbolRef, coerce_ticker
from sec_analysis.core.interfaces import MarketDataProvider, OptionsProvider
from sec_analysis.core.models import Bar, OptionChain, OptionContract, Quote


def _default_ticker(symbol: str) -> Any:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ProviderConfigError(
            "yfinance is not installed. Install the extra: pip install 'sec-analysis[yfinance]'"
        ) from exc
    return yf.Ticker(symbol)


class YFinanceMarketDataProvider(MarketDataProvider):
    name = "yfinance"

    def __init__(self, ticker_factory: Callable[[str], Any] | None = None) -> None:
        self._ticker_factory = ticker_factory or _default_ticker

    def get_quote(self, symbol: SymbolRef) -> Quote:
        ticker = self._ticker_factory(coerce_ticker(symbol).upper())
        info = _safe_fast_info(ticker)
        last = _first_float(info, "last_price", "lastPrice", "regularMarketPrice")
        return Quote(
            symbol=coerce_ticker(symbol).upper(),
            last=last,
            bid=_first_float(info, "bid"),
            ask=_first_float(info, "ask"),
            open=_first_float(info, "open", "regularMarketOpen"),
            high=_first_float(info, "day_high", "dayHigh"),
            low=_first_float(info, "day_low", "dayLow"),
            previous_close=_first_float(info, "previous_close", "previousClose"),
            volume=_first_float(info, "last_volume", "volume"),
            as_of=datetime.now(tz=UTC),
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
        ticker = self._ticker_factory(coerce_ticker(symbol).upper())
        period = "1y" if interval in {"1d", "1w"} else "5d"
        try:
            frame = ticker.history(period=period, interval=_yf_interval(interval))
        except Exception as exc:  # yfinance raises various types
            raise ProviderError(f"yfinance history failed: {exc}") from exc
        bars: list[Bar] = []
        if frame is None:
            return bars
        rows = list(frame.itertuples()) if hasattr(frame, "itertuples") else []
        for row in rows[-limit:]:
            ts = _as_datetime(getattr(row, "Index", None))
            bars.append(
                Bar(
                    symbol=coerce_ticker(symbol).upper(),
                    timestamp=ts,
                    open=float(row.Open),
                    high=float(row.High),
                    low=float(row.Low),
                    close=float(row.Close),
                    volume=float(getattr(row, "Volume", 0) or 0),
                    interval=interval,
                    source=self.name,
                )
            )
        if start:
            bars = [b for b in bars if b.timestamp >= start]
        if end:
            bars = [b for b in bars if b.timestamp <= end]
        return bars


class YFinanceOptionsProvider(OptionsProvider):
    name = "yfinance"

    def __init__(self, ticker_factory: Callable[[str], Any] | None = None) -> None:
        self._ticker_factory = ticker_factory or _default_ticker

    def get_option_chain(
        self,
        symbol: str,
        *,
        expiration: date | None = None,
    ) -> OptionChain:
        ticker = self._ticker_factory(symbol.upper())
        try:
            expirations = [date.fromisoformat(str(x)) for x in list(ticker.options or [])]
        except Exception as exc:
            raise ProviderError(f"yfinance options listing failed: {exc}") from exc
        if not expirations:
            return OptionChain(
                symbol=symbol.upper(),
                as_of=datetime.now(tz=UTC),
                expirations=[],
                contracts=[],
                source=self.name,
            )
        chosen = expiration if expiration in expirations else expirations[0]
        chain = ticker.option_chain(chosen.isoformat())
        contracts: list[OptionContract] = []
        contracts.extend(_rows_to_contracts(symbol, chosen, "call", getattr(chain, "calls", None)))
        contracts.extend(_rows_to_contracts(symbol, chosen, "put", getattr(chain, "puts", None)))
        return OptionChain(
            symbol=symbol.upper(),
            as_of=datetime.now(tz=UTC),
            expirations=expirations,
            contracts=contracts,
            source=self.name,
        )


def _as_datetime(value: Any) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return datetime.now(tz=UTC)


def _yf_interval(interval: str) -> str:
    return {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "1d": "1d",
        "1w": "1wk",
    }.get(interval, "1d")


def _safe_fast_info(ticker: Any) -> dict[str, Any]:
    raw = getattr(ticker, "fast_info", None) or getattr(ticker, "info", None) or {}
    if hasattr(raw, "items"):
        return dict(raw)
    return {}


def _first_float(info: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = info.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _rows_to_contracts(
    symbol: str,
    expiration: date,
    right: str,
    frame: Any,
) -> list[OptionContract]:
    if frame is None:
        return []
    records = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame)
    out: list[OptionContract] = []
    for row in records:
        out.append(
            OptionContract(
                symbol=symbol.upper(),
                contract_symbol=str(row.get("contractSymbol") or ""),
                expiration=expiration,
                strike=float(row.get("strike") or 0),
                right=right,
                last=_opt(row.get("lastPrice")),
                bid=_opt(row.get("bid")),
                ask=_opt(row.get("ask")),
                volume=_opt(row.get("volume")),
                open_interest=_opt(row.get("openInterest")),
                implied_volatility=_opt(row.get("impliedVolatility")),
            )
        )
    return out


def _opt(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
