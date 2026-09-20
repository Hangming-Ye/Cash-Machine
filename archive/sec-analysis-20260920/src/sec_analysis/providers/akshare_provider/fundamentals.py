"""AKShare A-share financial statements (phase-1 CN fundamentals route).

Primary: ``akshare.stock_financial_report_sina(stock="sh600519", symbol="利润表")``
(and 资产负债表 / 现金流量表). Sina scrape — unofficial and unstable.

``stock_financial_abstract`` is not used (different table, extra scrape risk).
Failures raise; we never invent figures.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Market, SymbolRef, resolve_instrument
from sec_analysis.core.interfaces import FundamentalsProvider
from sec_analysis.core.models import Fundamental, StatementKind, StatementLine, StatementReport
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.akshare_provider.client import (
    _load_akshare,
    _records,
    to_akshare_sina_stock,
)

SINA_HINT = (
    "AKShare stock_financial_report_sina scrapes Sina Finance and is often "
    "rate-limited or broken. Wait and retry; do not treat a failure as a zero/fake figure."
)

STATEMENT_TO_SINA: dict[str, str] = {
    "income": "利润表",
    "is": "利润表",
    "lrb": "利润表",
    "pnl": "利润表",
    "利润表": "利润表",
    "balance": "资产负债表",
    "bs": "资产负债表",
    "fzb": "资产负债表",
    "资产负债表": "资产负债表",
    "cash": "现金流量表",
    "cf": "现金流量表",
    "cashflow": "现金流量表",
    "llb": "现金流量表",
    "现金流量表": "现金流量表",
}

SINA_TO_KIND = {
    "利润表": StatementKind.INCOME,
    "资产负债表": StatementKind.BALANCE,
    "现金流量表": StatementKind.CASH,
}

_PERIOD = re.compile(r"^(19|20)\d{6}$")
_LABEL_KEYS = ("报告日", "项目", "科目", "报表项目", "item", "name", "index")


def normalize_statement(value: str) -> str:
    key = value.strip()
    sina = STATEMENT_TO_SINA.get(key) or STATEMENT_TO_SINA.get(key.lower())
    if not sina:
        allowed = "income|balance|cash (or 利润表|资产负债表|现金流量表)"
        raise ProviderConfigError(f"Unknown statement {value!r}. Use {allowed}.")
    return sina


def _default_report(stock: str, *, symbol: str) -> Any:
    return _load_akshare().stock_financial_report_sina(stock=stock, symbol=symbol)


class AkshareFundamentalsProvider(FundamentalsProvider):
    """China A-share 财报. Inject ``fetch`` in tests."""

    name = "akshare"

    def __init__(
        self,
        *,
        fetch: Callable[..., Any] | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._fetch = fetch or _default_report
        self._limiter = limiter or RateLimiter(calls_per_minute=20, min_interval=0.5)

    def get_fundamentals(self, symbol: SymbolRef) -> Fundamental:
        report = self.get_statement(symbol, statement="income", limit_periods=4)
        latest = report.periods[0] if report.periods else None
        revenue = _line_value(report, latest, "营业收入", "营业总收入", "一、营业总收入")
        net_income = _line_value(
            report,
            latest,
            "净利润",
            "四、净利润",
            "归属于母公司股东的净利润",
            "归属于母公司所有者的净利润",
        )
        inst = resolve_instrument(symbol)
        return Fundamental(
            symbol=inst.display(),
            as_of=report.as_of or date.today(),
            revenue=revenue,
            net_income=net_income,
            currency="CNY",
            source=self.name,
            market=Market.CN,
            extras={
                "sina_stock": report.sina_stock,
                "statement": report.statement.value,
                "period": latest,
                "note": "Snapshot from 利润表 only. Use --statement for the full report.",
            },
        )

    def get_statement(
        self,
        symbol: SymbolRef,
        *,
        statement: str = "income",
        limit_periods: int = 8,
    ) -> StatementReport:
        inst = resolve_instrument(symbol)
        stock = to_akshare_sina_stock(inst)
        sina = normalize_statement(statement)
        self._limiter.wait()
        try:
            payload = self._fetch(stock, symbol=sina)
        except ProviderConfigError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"AKShare Sina {sina} failed for {stock}: {exc}. {SINA_HINT}"
            ) from exc
        report = _report_from_table(
            inst=inst,
            stock=stock,
            sina=sina,
            payload=payload,
            limit_periods=limit_periods,
        )
        if not report.lines or not report.periods:
            raise ProviderError(
                f"AKShare Sina {sina} returned no usable rows for {stock}. {SINA_HINT}"
            )
        return report


def _report_from_table(
    *,
    inst: Any,
    stock: str,
    sina: str,
    payload: Any,
    limit_periods: int,
) -> StatementReport:
    rows = _statement_records(payload)
    if not rows:
        raise ProviderError(f"AKShare Sina {sina} returned an empty table for {stock}. {SINA_HINT}")
    orientation = _detect_orientation(rows)
    if orientation == "periods_as_rows":
        lines, periods = _from_period_rows(rows)
    else:
        lines, periods = _from_item_rows(rows)
    periods = _sort_periods(periods)[: max(1, limit_periods)]
    keep = set(periods)
    trimmed = [
        StatementLine(label=line.label, values={p: v for p, v in line.values.items() if p in keep})
        for line in lines
        if any(p in line.values for p in periods)
    ]
    as_of = _period_to_date(periods[0]) if periods else None
    return StatementReport(
        symbol=inst.display(),
        statement=SINA_TO_KIND[sina],
        sina_stock=stock,
        sina_symbol=sina,
        periods=periods,
        lines=trimmed,
        as_of=as_of,
        source="akshare",
        market=Market.CN,
    )


def _statement_records(payload: Any) -> list[dict[str, Any]]:
    frame = payload
    if hasattr(frame, "reset_index"):
        index = getattr(frame, "index", None)
        named = getattr(index, "name", None)
        first = None
        try:
            first = index[0]
        except Exception:
            first = None
        if named or isinstance(first, str):
            try:
                frame = frame.reset_index()
            except Exception:
                pass
    return _records(frame)


def _detect_orientation(rows: list[dict[str, Any]]) -> str:
    labels = [_row_label(row) for row in rows[:12]]
    dated = sum(1 for label in labels if label and _is_period(label))
    if dated >= max(2, len([x for x in labels if x]) // 2):
        return "periods_as_rows"
    return "items_as_rows"


def _from_item_rows(rows: list[dict[str, Any]]) -> tuple[list[StatementLine], list[str]]:
    periods: set[str] = set()
    lines: list[StatementLine] = []
    for row in rows:
        label = _row_label(row)
        if not label or _is_period(label):
            continue
        values: dict[str, float] = {}
        for key, raw in row.items():
            period = _as_period(key)
            if period is None:
                continue
            number = _as_float(raw)
            if number is None:
                continue
            values[period] = number
            periods.add(period)
        if values:
            lines.append(StatementLine(label=label, values=values))
    return lines, list(periods)


def _from_period_rows(rows: list[dict[str, Any]]) -> tuple[list[StatementLine], list[str]]:
    by_item: dict[str, dict[str, float]] = {}
    periods: list[str] = []
    for row in rows:
        period = _as_period(_row_label(row))
        if period is None:
            continue
        periods.append(period)
        for key, raw in row.items():
            if str(key) in _LABEL_KEYS or _as_period(key):
                continue
            number = _as_float(raw)
            if number is None:
                continue
            by_item.setdefault(str(key), {})[period] = number
    lines = [StatementLine(label=label, values=values) for label, values in by_item.items()]
    return lines, list(dict.fromkeys(periods))


def _row_label(row: dict[str, Any]) -> str | None:
    for key in _LABEL_KEYS:
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    for key, value in row.items():
        if _as_period(key) is None and value not in (None, ""):
            return str(value).strip()
    return None


def _is_period(value: Any) -> bool:
    return _as_period(value) is not None


def _as_period(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except Exception:
            return None
    text = str(value).strip().replace("/", "").replace("-", "").replace(".", "")
    if _PERIOD.match(text[:8] if len(text) >= 8 else text):
        ymd = text[:8]
        return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "" or value == "--":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN from empty Sina section headers
        return None
    return number


def _sort_periods(periods: list[str]) -> list[str]:
    return sorted(set(periods), reverse=True)


def _period_to_date(period: str) -> date | None:
    try:
        return date.fromisoformat(period)
    except ValueError:
        return None


def _line_value(report: StatementReport, period: str | None, *labels: str) -> float | None:
    if not period:
        return None
    wanted = {label.lower() for label in labels}
    for line in report.lines:
        if line.label in labels or line.label.lower() in wanted:
            if period in line.values:
                return line.values[period]
    for line in report.lines:
        if any(label in line.label for label in labels):
            if period in line.values:
                return line.values[period]
    return None
