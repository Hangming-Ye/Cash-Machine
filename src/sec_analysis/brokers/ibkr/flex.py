"""IBKR Flex Web Service — phase-1 read-only account / positions / trades.

Flow (no Client Portal Gateway):

1. ``GET .../SendRequest?t=TOKEN&q=QUERY_ID&v=3``
2. Poll ``GET .../GetStatement?t=TOKEN&q=REFERENCE_CODE&v=3`` until ready
3. Parse XML (default) or CSV if the query is configured that way

Typical **T+1**. This class is ``*ReadOnly*`` and must never grow write APIs.
Never commit ``IBKR_FLEX_TOKEN``.
"""

from __future__ import annotations

import csv
import io
import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.interfaces import FlexActivityReadOnlyClient
from sec_analysis.core.models import AccountSummary, AssetType, Execution, Position

logger = logging.getLogger(__name__)

FLEX_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"

FLEX_T_PLUS_1_NOTE = (
    "Flex Activity statements are typically T+1. Same-session fills are usually absent."
)

MISSING_FLEX = (
    "IBKR Flex Web Service is not configured. In Client Portal: Settings → "
    "Reporting → Flex Web Service (generate a token) and create an Activity "
    "Flex Query (suggested sections: Account Information, Open Positions, "
    "Trades, Cash Report). Then set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID "
    "(optional IBKR_FLEX_ACTIVITY_QUERY_ID / IBKR_FLEX_POSITION_QUERY_ID). "
    "BROKER_IBKR_MODE=flex. This client does not invent balances, positions, or fills. "
    + FLEX_T_PLUS_1_NOTE
    + " Never commit the token."
)

_RETRYABLE = {"1001", "1018", "1019", "1014"}


class IbkrFlexReadOnlyClient(FlexActivityReadOnlyClient):
    """Read-only Flex façade. Inject ``client`` / ``sleeper`` in tests."""

    name = "ibkr-flex"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] | None = None,
        poll_attempts: int = 8,
        poll_interval: float = 1.5,
        base_url: str = FLEX_BASE_URL,
    ) -> None:
        self.settings = settings or Settings()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=self.settings.http_timeout,
            headers={"User-Agent": "sec-analysis/0.1 (read-only Flex)"},
        )
        self._sleeper = sleeper or (lambda seconds: __import__("time").sleep(seconds))
        self._poll_attempts = max(1, poll_attempts)
        self._poll_interval = max(0.0, poll_interval)
        self._base_url = (self.settings.ibkr_flex_base_url or base_url).rstrip("/")
        self._cache: dict[str, ET.Element | list[dict[str, str]]] = {}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def is_configured(self) -> bool:
        token = self.settings.ibkr_flex_token.strip()
        return bool(token and self.settings.ibkr_flex_any_query_id())

    def get_account_summary(self) -> AccountSummary:
        root = self._statement("account")
        return _account_from_statement(root, fallback_id=self.settings.ibkr_account_id)

    def get_positions(self) -> list[Position]:
        root = self._statement("positions")
        return _positions_from_statement(root)

    def get_activity_executions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Execution]:
        root = self._statement("activity", start=start, end=end)
        fills = _executions_from_statement(root)
        if start:
            fills = [row for row in fills if row.executed_at >= start]
        if end:
            fills = [row for row in fills if row.executed_at <= end]
        return fills

    def _statement(
        self,
        kind: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> ET.Element | list[dict[str, str]]:
        if not self.is_configured():
            raise ProviderConfigError(MISSING_FLEX)
        query_id = self.settings.ibkr_flex_query_for(kind)
        cache_key = f"{query_id}:{start}:{end}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        payload = self._fetch_statement(query_id, start=start, end=end)
        self._cache[cache_key] = payload
        return payload

    def _fetch_statement(
        self,
        query_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> ET.Element | list[dict[str, str]]:
        reference = self._send_request(query_id, start=start, end=end)
        last_error = "Flex GetStatement returned no payload"
        for attempt in range(self._poll_attempts):
            text = self._http_get(
                "/GetStatement",
                {"t": self.settings.ibkr_flex_token, "q": reference, "v": "3"},
            )
            parsed = _parse_payload(text)
            if isinstance(parsed, _FlexPending):
                last_error = parsed.message
                if attempt + 1 < self._poll_attempts:
                    self._sleeper(self._poll_interval)
                    continue
                break
            return parsed
        raise ProviderError(
            f"{last_error} after {self._poll_attempts} GetStatement attempts. "
            "No balances, positions, or fills were invented. " + FLEX_T_PLUS_1_NOTE
        )

    def _send_request(
        self,
        query_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> str:
        params: dict[str, str] = {
            "t": self.settings.ibkr_flex_token,
            "q": query_id,
            "v": "3",
        }
        if start and end:
            params["fd"] = start.strftime("%Y%m%d")
            params["td"] = end.strftime("%Y%m%d")
        text = self._http_get("/SendRequest", params)
        root = _xml_root(text)
        status = (_child_text(root, "Status") or "").strip()
        if status.lower() != "success":
            code = _child_text(root, "ErrorCode") or ""
            message = _child_text(root, "ErrorMessage") or text[:200]
            raise ProviderError(
                f"Flex SendRequest failed (status={status or 'unknown'} "
                f"code={code}): {message}. No figures were invented."
            )
        reference = (_child_text(root, "ReferenceCode") or "").strip()
        if not reference:
            raise ProviderError("Flex SendRequest succeeded but ReferenceCode is empty.")
        return reference

    def _http_get(self, path: str, params: dict[str, str]) -> str:
        url = f"{self._base_url}{path}"
        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            raise ProviderError(f"Flex HTTP failed: {exc}") from exc


class _FlexPending:
    def __init__(self, message: str) -> None:
        self.message = message


def _parse_payload(text: str) -> ET.Element | list[dict[str, str]] | _FlexPending:
    stripped = text.lstrip()
    if stripped.startswith("<"):
        root = _xml_root(text)
        tag = root.tag.split("}")[-1]
        if tag == "FlexStatementResponse":
            status = (_child_text(root, "Status") or "").strip().lower()
            code = (_child_text(root, "ErrorCode") or "").strip()
            message = _child_text(root, "ErrorMessage") or "Flex statement not ready"
            if status in {"warn", "fail"} and code in _RETRYABLE:
                return _FlexPending(f"Flex GetStatement {code}: {message}")
            if status != "success":
                raise ProviderError(
                    f"Flex GetStatement failed (status={status or 'unknown'} "
                    f"code={code}): {message}. No figures were invented."
                )
            raise ProviderError("Flex GetStatement returned Success without a statement body.")
        return root
    if "," in stripped or "\t" in stripped:
        return _csv_rows(text)
    raise ProviderError("Flex GetStatement returned neither XML nor CSV. No figures were invented.")


def _xml_root(text: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProviderError(f"Flex XML parse failed: {exc}") from exc


def _child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if child.tag.split("}")[-1] == name:
            if child.text and child.text.strip():
                return child.text.strip()
            return None
    return node.attrib.get(name)


def _attr(node: ET.Element, *names: str) -> str | None:
    for name in names:
        if name in node.attrib and node.attrib[name] not in (None, ""):
            return str(node.attrib[name])
    text = _child_text(node, names[0]) if names else None
    return text


def _walk(root: ET.Element | list[dict[str, str]], *tags: str) -> list[ET.Element]:
    if isinstance(root, list):
        return []
    found: list[ET.Element] = []
    wanted = {tag.lower() for tag in tags}
    for node in root.iter():
        if node.tag.split("}")[-1].lower() in wanted:
            found.append(node)
    return found


def _num(value: str | None) -> float | None:
    if value is None or value == "" or value == "--":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _as_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    text = value.strip().replace("T", ";")
    for fmt in (
        "%Y%m%d;%H%M%S",
        "%Y-%m-%d;%H:%M:%S",
        "%Y%m%d",
        "%Y-%m-%d",
        "%Y%m%d;%H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _account_from_statement(
    root: ET.Element | list[dict[str, str]], *, fallback_id: str
) -> AccountSummary:
    if isinstance(root, list):
        return _account_from_csv(root, fallback_id=fallback_id)
    info = _walk(root, "AccountInformation")
    cash_rows = _walk(root, "CashReportCurrency")
    picked = None
    for row in cash_rows:
        if str(_attr(row, "currency") or "").upper() == "USD":
            picked = row
            break
    if picked is None and cash_rows:
        picked = cash_rows[0]
    account = (
        (_attr(info[0], "accountId", "account_id") if info else None)
        or (_attr(picked, "accountId", "ClientAccountID") if picked is not None else None)
        or fallback_id
        or "IBKR-FLEX"
    )
    currency = (
        (_attr(picked, "currency") if picked is not None else None)
        or (_attr(info[0], "currency") if info else None)
        or "USD"
    )
    generated = None
    statements = _walk(root, "FlexStatement")
    if statements:
        generated = _attr(statements[0], "whenGenerated", "toDate")
    return AccountSummary(
        account_id=str(account),
        as_of=_as_dt(generated),
        net_liquidation=_num(
            _attr(picked, "netLiquidation", "endingSettledCash") if picked is not None else None
        ),
        cash=_num(
            _attr(picked, "endingCash", "endingSettledCash", "slbNetCash")
            if picked is not None
            else None
        ),
        currency=str(currency),
        extras={
            "ibkr_mode": "flex",
            "source": "ibkr-flex",
            "readonly": True,
            "note": FLEX_T_PLUS_1_NOTE,
        },
    )


def _positions_from_statement(root: ET.Element | list[dict[str, str]]) -> list[Position]:
    if isinstance(root, list):
        return _positions_from_csv(root)
    rows: list[Position] = []
    for node in _walk(root, "OpenPosition"):
        symbol = _attr(node, "symbol")
        qty = _num(_attr(node, "position", "quantity"))
        if not symbol or qty is None:
            continue
        rows.append(
            Position(
                account_id=str(_attr(node, "accountId") or ""),
                symbol=str(symbol),
                quantity=qty,
                average_cost=_num(_attr(node, "costBasisPrice", "averageCost")),
                market_price=_num(_attr(node, "markPrice", "marketPrice")),
                market_value=_num(_attr(node, "positionValue", "marketValue")),
                unrealized_pnl=_num(_attr(node, "fifoPnlUnrealized", "unrealizedPnl")),
                currency=str(_attr(node, "currency") or "USD"),
                asset_type=AssetType.EQUITY
                if str(_attr(node, "assetCategory") or "").upper() in {"STK", "EQUITY"}
                else AssetType.UNKNOWN,
            )
        )
    return rows


def _executions_from_statement(root: ET.Element | list[dict[str, str]]) -> list[Execution]:
    if isinstance(root, list):
        return _executions_from_csv(root)
    rows: list[Execution] = []
    for node in _walk(root, "Trade"):
        ident = _attr(node, "tradeID", "ibExecID", "execution_id")
        symbol = _attr(node, "symbol")
        price = _num(_attr(node, "tradePrice", "price"))
        qty = _num(_attr(node, "quantity"))
        if not ident or not symbol or price is None or qty is None:
            continue
        rows.append(
            Execution(
                execution_id=str(ident),
                account_id=str(_attr(node, "accountId") or ""),
                symbol=str(symbol),
                side=str(_attr(node, "buySell", "side") or "unknown").lower(),
                quantity=qty,
                price=price,
                executed_at=_as_dt(_attr(node, "dateTime", "tradeDate")),
                commission=_num(_attr(node, "ibCommission", "commission")),
                currency=str(_attr(node, "currency") or "USD"),
            )
        )
    return rows


def _csv_rows(text: str) -> list[dict[str, str]]:
    sample = text.lstrip()
    dialect = csv.Sniffer().sniff(sample[:1024], delimiters=",\t;")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return [{str(k).strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]


def _row_get(row: dict[str, str], *names: str) -> str | None:
    lower = {k.lower(): v for k, v in row.items()}
    for name in names:
        value = row.get(name) or lower.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _account_from_csv(rows: list[dict[str, str]], *, fallback_id: str) -> AccountSummary:
    picked = rows[0] if rows else {}
    return AccountSummary(
        account_id=str(
            _row_get(picked, "AccountId", "accountId", "ClientAccountID")
            or fallback_id
            or "IBKR-FLEX"
        ),
        as_of=datetime.now(tz=UTC),
        cash=_num(_row_get(picked, "endingCash", "EndingCash", "Cash")),
        net_liquidation=_num(_row_get(picked, "netLiquidation", "NetLiquidation")),
        currency=str(_row_get(picked, "currency", "Currency") or "USD"),
        extras={"ibkr_mode": "flex", "source": "ibkr-flex", "readonly": True, "format": "csv"},
    )


def _positions_from_csv(rows: list[dict[str, str]]) -> list[Position]:
    out: list[Position] = []
    for row in rows:
        symbol = _row_get(row, "Symbol", "symbol")
        qty = _num(_row_get(row, "Position", "quantity", "Quantity"))
        if not symbol or qty is None:
            continue
        out.append(
            Position(
                account_id=str(_row_get(row, "AccountId", "accountId") or ""),
                symbol=symbol,
                quantity=qty,
                average_cost=_num(_row_get(row, "CostBasisPrice", "costBasisPrice")),
                market_price=_num(_row_get(row, "MarkPrice", "markPrice")),
                currency=str(_row_get(row, "Currency", "currency") or "USD"),
            )
        )
    return out


def _executions_from_csv(rows: list[dict[str, str]]) -> list[Execution]:
    out: list[Execution] = []
    for row in rows:
        ident = _row_get(row, "TradeID", "tradeID", "ibExecID")
        symbol = _row_get(row, "Symbol", "symbol")
        price = _num(_row_get(row, "TradePrice", "tradePrice", "Price"))
        qty = _num(_row_get(row, "Quantity", "quantity"))
        if not ident or not symbol or price is None or qty is None:
            continue
        out.append(
            Execution(
                execution_id=ident,
                account_id=str(_row_get(row, "AccountId", "accountId") or ""),
                symbol=symbol,
                side=str(_row_get(row, "Buy/Sell", "buySell", "Side") or "unknown").lower(),
                quantity=qty,
                price=price,
                executed_at=_as_dt(_row_get(row, "DateTime", "dateTime", "TradeDate")),
                currency=str(_row_get(row, "Currency", "currency") or "USD"),
            )
        )
    return out
