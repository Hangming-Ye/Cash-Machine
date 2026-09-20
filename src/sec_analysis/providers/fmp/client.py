"""Financial Modeling Prep US fundamentals (profile + three statements).

Live calls need ``FMP_API_KEY``. Missing key is a config error — no invented
figures. New keys (after 2025-08-31) only work on ``/stable/...`` — this
adapter does not call legacy ``/api/v3/...``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import SymbolRef, resolve_instrument
from sec_analysis.core.interfaces import FundamentalsProvider
from sec_analysis.core.models import (
    Fundamental,
    StatementKind,
    StatementLine,
    StatementReport,
)
from sec_analysis.core.rate_limit import RateLimiter

FMP_BASE_URL = "https://financialmodelingprep.com"

MISSING_API_KEY = (
    "FMP_API_KEY is not set. US fundamentals (FUNDAMENTALS_ROUTE_US=fmp) need an "
    "FMP key. Copy .env.example to .env and set FMP_API_KEY "
    "(https://financialmodelingprep.com/). No statement figures were invented."
)

STATEMENT_PATHS: dict[str, tuple[StatementKind, str]] = {
    "income": (StatementKind.INCOME, "income-statement"),
    "is": (StatementKind.INCOME, "income-statement"),
    "income-statement": (StatementKind.INCOME, "income-statement"),
    "pnl": (StatementKind.INCOME, "income-statement"),
    "balance": (StatementKind.BALANCE, "balance-sheet-statement"),
    "bs": (StatementKind.BALANCE, "balance-sheet-statement"),
    "balance-sheet": (StatementKind.BALANCE, "balance-sheet-statement"),
    "balance-sheet-statement": (StatementKind.BALANCE, "balance-sheet-statement"),
    "cash": (StatementKind.CASH, "cash-flow-statement"),
    "cf": (StatementKind.CASH, "cash-flow-statement"),
    "cashflow": (StatementKind.CASH, "cash-flow-statement"),
    "cash-flow": (StatementKind.CASH, "cash-flow-statement"),
    "cash-flow-statement": (StatementKind.CASH, "cash-flow-statement"),
}

_META_KEYS = {
    "date",
    "symbol",
    "reportedCurrency",
    "cik",
    "fillingDate",
    "acceptedDate",
    "calendarYear",
    "period",
    "link",
    "finalLink",
}


class FmpFundamentalsProvider(FundamentalsProvider):
    name = "fmp"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = 15.0,
        base_url: str = FMP_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self._limiter = limiter or RateLimiter()
        self._last_path = ""

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            raise ProviderConfigError(MISSING_API_KEY)
        query = dict(params or {})
        query["apikey"] = self.api_key
        self._limiter.wait()
        try:
            response = self._client.get(path, params=query)
            response.raise_for_status()
            self._last_path = path
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = (exc.response.text or "")[:200]
            if status in {401, 403}:
                raise ProviderError(
                    f"FMP stable {path} returned HTTP {status} "
                    f"(check FMP_API_KEY / plan). {body}".strip()
                ) from exc
            raise ProviderError(f"FMP request failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"FMP request failed: {exc}") from exc

    def get_fundamentals(self, symbol: SymbolRef) -> Fundamental:
        inst = resolve_instrument(symbol)
        ticker = inst.symbol.upper()
        payload = self._get("/stable/profile", {"symbol": ticker})
        rows = _as_rows(payload)
        if not rows:
            raise ProviderError(f"FMP profile empty for {ticker}")
        row: dict[str, Any] = rows[0]
        if not isinstance(row, dict):
            raise ProviderError(f"FMP profile row is not an object for {ticker}")
        return Fundamental(
            symbol=ticker,
            as_of=date.today(),
            name=row.get("companyName"),
            sector=row.get("sector"),
            industry=row.get("industry"),
            market_cap=_opt_float(row.get("mktCap")),
            pe_ratio=_opt_float(row.get("pe")),
            eps=_opt_float(row.get("eps")),
            dividend_yield=_opt_float(row.get("lastDiv")),
            currency=str(row.get("currency") or "USD"),
            source=self.name,
            market=inst.market,
            extras={
                "exchange": row.get("exchangeShortName"),
                "beta": row.get("beta"),
                "ipo_date": row.get("ipoDate"),
                "fetched_at": datetime.now(tz=UTC).isoformat(),
            },
        )

    def get_statement(
        self,
        symbol: SymbolRef,
        *,
        statement: str = "income",
        limit_periods: int = 8,
    ) -> StatementReport:
        ticker = resolve_instrument(symbol).symbol.upper()
        kind, path_name = normalize_statement(statement)
        payload = self._get(
            f"/stable/{path_name}",
            {
                "symbol": ticker,
                "period": "annual",
                "limit": max(1, limit_periods),
            },
        )
        rows = _as_rows(payload)
        if not rows:
            raise ProviderError(
                f"FMP {path_name} empty for {ticker}. No statement figures were invented."
            )
        rows = rows[: max(1, limit_periods)]
        periods: list[str] = []
        for row in rows:
            period = _period_label(row)
            if period and period not in periods:
                periods.append(period)
        if not periods:
            raise ProviderError(
                f"FMP {path_name} returned no dated periods for {ticker}. "
                "No statement figures were invented."
            )
        lines = _lines_from_rows(rows, periods)
        if not lines:
            raise ProviderError(
                f"FMP {path_name} returned no numeric lines for {ticker}. "
                "No statement figures were invented."
            )
        currency = str(rows[0].get("reportedCurrency") or "USD")
        as_of = _period_to_date(periods[0])
        return StatementReport(
            symbol=ticker,
            statement=kind,
            sina_stock=ticker,
            sina_symbol=path_name,
            periods=periods,
            lines=lines,
            as_of=as_of,
            currency=currency,
            source=self.name,
            market=resolve_instrument(symbol).market,
        )


def _as_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        nested = payload.get("data")
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, dict)]
        if any(key in payload for key in ("companyName", "symbol", "date", "revenue")):
            return [payload]
    return []


def normalize_statement(value: str) -> tuple[StatementKind, str]:
    key = value.strip().lower()
    mapped = STATEMENT_PATHS.get(key)
    if not mapped:
        raise ProviderConfigError(
            f"Unknown statement {value!r}. Use income|balance|cash."
        )
    return mapped


def _lines_from_rows(rows: list[dict[str, Any]], periods: list[str]) -> list[StatementLine]:
    labels: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key, raw in row.items():
            if key in _META_KEYS or key in seen:
                continue
            if _opt_float(raw) is None:
                continue
            seen.add(key)
            labels.append(key)
    lines: list[StatementLine] = []
    for label in labels:
        values: dict[str, float] = {}
        for row in rows:
            period = _period_label(row)
            if period is None:
                continue
            number = _opt_float(row.get(label))
            if number is None:
                continue
            values[period] = number
        if values:
            lines.append(StatementLine(label=label, values=values))
    return lines


def _period_label(row: dict[str, Any]) -> str | None:
    raw = row.get("date") or row.get("calendarYear")
    if raw is None or raw == "":
        return None
    if hasattr(raw, "strftime"):
        try:
            return raw.strftime("%Y-%m-%d")
        except Exception:
            return None
    text = str(raw).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def _period_to_date(period: str) -> date | None:
    try:
        return date.fromisoformat(period[:10])
    except ValueError:
        return None


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
