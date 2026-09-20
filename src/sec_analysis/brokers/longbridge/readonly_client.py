"""Longbridge OpenAPI read-only account adapter (Hong Kong).

Phase-1 surface: account balances, stock/fund positions, today fills, and
historical fills. This module never opens a market-data quote session and
never sends write trade requests.

Default auth is the token trio (``LONGBRIDGE_AUTH=token`` or unset):

* ``LONGBRIDGE_APP_KEY`` / ``LONGBRIDGE_APP_SECRET`` / ``LONGBRIDGE_ACCESS_TOKEN``
* ``LONGPORT_*`` aliases still work (``apikey`` is accepted as an alias of ``token``)

Opt-in OAuth 2.0 (``LONGBRIDGE_AUTH=oauth``):

* ``LONGBRIDGE_CLIENT_ID`` — from ``POST /oauth2/register`` (public client; no secret)
* Token file: ``~/.longbridge/openapi/tokens/<client_id>`` (SDK default).
  Do not put OAuth access tokens in ``.env``.

``LONGBRIDGE_MODE=stub`` (default) or missing config raise a config error —
this client never invents balances, positions, or fills. Never commit secrets.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.interfaces import BrokerReadOnlyClient
from sec_analysis.core.models import AccountSummary, AssetType, Execution, Position

logger = logging.getLogger(__name__)

SDK_MISSING = (
    "longbridge SDK is not installed. Live HK account reads need: "
    "uv sync --extra longbridge  (longbridge>=4.0 for OAuthBuilder)"
)

STUB_HINT = (
    "LONGBRIDGE_MODE=stub. Token trio (default): LONGBRIDGE_AUTH=token (or unset) plus "
    "LONGBRIDGE_APP_KEY, LONGBRIDGE_APP_SECRET, LONGBRIDGE_ACCESS_TOKEN "
    "(LONGPORT_* aliases work), then LONGBRIDGE_MODE=live. "
    "OAuth: LONGBRIDGE_AUTH=oauth, LONGBRIDGE_CLIENT_ID, then "
    "uv run sec-analysis longbridge-login. OAuth tokens live at "
    "~/.longbridge/openapi/tokens/<client_id> — do not put them in .env. "
    "This client does not invent balances, positions, or fills."
)

OAUTH_CLIENT_HINT = (
    "LONGBRIDGE_CLIENT_ID is not set. OAuth 2.0 needs a client_id from "
    "POST https://openapi.longbridge.com/oauth2/register. "
    "Then: uv run sec-analysis longbridge-login. "
    "This client does not invent balances, positions, or fills."
)

TOKEN_HINT = (
    "LONGBRIDGE_AUTH=token (default) but LONGBRIDGE_APP_KEY, LONGBRIDGE_APP_SECRET, and "
    "LONGBRIDGE_ACCESS_TOKEN are not set (LONGPORT_* aliases work). "
    "Then LONGBRIDGE_MODE=live. Or use LONGBRIDGE_AUTH=oauth with LONGBRIDGE_CLIENT_ID "
    "and uv run sec-analysis longbridge-login. "
    "This client does not invent balances, positions, or fills."
)

CREDS_HINT = STUB_HINT

OnAuthorizeUrl = Callable[[str], None]


class LongbridgeReadOnlyClient(BrokerReadOnlyClient):
    """Read-only Longbridge façade. Inject ``trade`` in tests."""

    name = "longbridge"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        trade: Any | None = None,
        on_authorize_url: OnAuthorizeUrl | None = None,
        open_oauth: Callable[..., Any] | None = None,
        open_oauth_session: Callable[..., Any] | None = None,
        open_apikey: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self._trade = trade
        self._account_id = self.settings.longbridge_account_id or "LB-PENDING"
        self._connected = trade is not None
        self._on_authorize_url = on_authorize_url or _default_on_authorize_url
        self._open_oauth = open_oauth or _open_trade_context_oauth
        self._open_oauth_session = open_oauth_session or _open_oauth_session
        self._open_apikey = open_apikey or _open_trade_context

    def connect(self) -> None:
        if self._trade is not None:
            self._connected = True
            return
        if self.settings.longbridge_mode != "live":
            raise ProviderConfigError(STUB_HINT)
        if self.settings.longbridge_auth == "oauth":
            client_id = self.settings.longbridge_oauth_client_id()
            if not client_id:
                raise ProviderConfigError(OAUTH_CLIENT_HINT)
            self._trade = self._open_oauth(
                client_id, on_authorize_url=self._on_authorize_url
            )
        else:
            self._require_token()
            self._trade = self._open_apikey(*self.settings.longbridge_credentials())
        self._connected = True

    def login_oauth(self, *, on_authorize_url: OnAuthorizeUrl | None = None) -> dict[str, str]:
        """Run ``OAuthBuilder`` and persist the SDK token file. No account reads."""
        client_id = self.settings.longbridge_oauth_client_id()
        if not client_id:
            raise ProviderConfigError(OAUTH_CLIENT_HINT)
        callback = on_authorize_url or self._on_authorize_url
        self._open_oauth_session(client_id, on_authorize_url=callback)
        store = oauth_token_store(client_id)
        return {
            "client_id": client_id,
            "token_store": str(store),
            "auth": "oauth",
        }

    def is_connected(self) -> bool:
        return self._connected

    def get_account_summary(self) -> AccountSummary:
        ctx = self._require_trade()
        try:
            payload = ctx.account_balance()
        except Exception as exc:
            raise ProviderError(f"Longbridge account_balance failed: {exc}") from exc
        summary = _summary_from_balances(self._account_id, payload)
        extras = dict(summary.extras or {})
        extras["auth"] = self.settings.longbridge_auth
        extras["readonly"] = True
        return summary.model_copy(update={"extras": extras})

    def get_positions(self) -> list[Position]:
        ctx = self._require_trade()
        rows: list[Position] = []
        try:
            rows.extend(_positions_from_stock(self._account_id, ctx.stock_positions()))
        except Exception as exc:
            raise ProviderError(f"Longbridge stock_positions failed: {exc}") from exc
        try:
            rows.extend(_positions_from_fund(self._account_id, ctx.fund_positions()))
        except Exception as exc:
            logger.info("Longbridge fund_positions skipped: %s", exc)
        return rows

    def get_executions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        history: bool = False,
    ) -> list[Execution]:
        ctx = self._require_trade()
        rows: list[Execution] = []
        try:
            rows.extend(_executions_from(self._account_id, ctx.today_executions()))
        except Exception as exc:
            raise ProviderError(f"Longbridge today_executions failed: {exc}") from exc
        want_history = history or start is not None
        if want_history:
            end_dt = end or datetime.now(tz=UTC)
            start_dt = start or (end_dt - timedelta(days=30))
            try:
                rows.extend(
                    _executions_from(
                        self._account_id,
                        ctx.history_executions(start_at=start_dt, end_at=end_dt),
                    )
                )
            except Exception as exc:
                raise ProviderError(f"Longbridge history_executions failed: {exc}") from exc
        seen: set[str] = set()
        unique: list[Execution] = []
        for fill in rows:
            if fill.execution_id in seen:
                continue
            if start and fill.executed_at < start:
                continue
            if end and fill.executed_at > end:
                continue
            seen.add(fill.execution_id)
            unique.append(fill)
        return unique

    def _require_token(self) -> None:
        if not all(self.settings.longbridge_credentials()):
            raise ProviderConfigError(TOKEN_HINT)

    def _require_trade(self) -> Any:
        if self._trade is None:
            self.connect()
        if self._trade is None:
            raise ProviderConfigError(STUB_HINT)
        return self._trade


def oauth_token_store(client_id: str) -> Path:
    """SDK default token path. Never write this path into ``.env``."""
    return Path.home() / ".longbridge" / "openapi" / "tokens" / client_id


def _default_on_authorize_url(url: str) -> None:
    print(f"Open this URL to authorize Longbridge: {url}")


def _open_oauth_session(
    client_id: str,
    *,
    on_authorize_url: OnAuthorizeUrl | None = None,
    builder_cls: Any | None = None,
    config_from_oauth: Any | None = None,
) -> tuple[Any, Any]:
    builder = builder_cls
    from_oauth = config_from_oauth
    if builder is None or from_oauth is None:
        try:
            from longbridge.openapi import Config, OAuthBuilder
        except ImportError as exc:
            raise ProviderConfigError(SDK_MISSING) from exc
        builder = builder or OAuthBuilder
        from_oauth = from_oauth or Config.from_oauth
    callback = on_authorize_url or _default_on_authorize_url
    try:
        oauth = builder(client_id).build(callback)
        config = from_oauth(oauth)
    except ProviderConfigError:
        raise
    except Exception as exc:
        raise ProviderError(f"Longbridge OAuth failed: {exc}") from exc
    return oauth, config


def _open_trade_context_oauth(
    client_id: str,
    *,
    on_authorize_url: OnAuthorizeUrl | None = None,
    builder_cls: Any | None = None,
    config_from_oauth: Any | None = None,
    trade_cls: Any | None = None,
) -> Any:
    oauth, config = _open_oauth_session(
        client_id,
        on_authorize_url=on_authorize_url,
        builder_cls=builder_cls,
        config_from_oauth=config_from_oauth,
    )
    cls = trade_cls
    if cls is None:
        try:
            from longbridge.openapi import TradeContext
        except ImportError as exc:
            raise ProviderConfigError(SDK_MISSING) from exc
        cls = TradeContext
    return cls(config)


def _open_trade_context(app_key: str, app_secret: str, access_token: str) -> Any:
    try:
        from longbridge.openapi import Config, TradeContext
    except ImportError as exc:
        raise ProviderConfigError(SDK_MISSING) from exc
    if hasattr(Config, "from_apikey"):
        config = Config.from_apikey(app_key, app_secret, access_token)
    else:
        config = Config(app_key=app_key, app_secret=app_secret, access_token=access_token)
    return TradeContext(config)


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _as_list(payload: Any, *keys: str) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    for key in keys:
        value = payload.get(key) if isinstance(payload, dict) else getattr(payload, key, None)
        if value is None:
            continue
        return value if isinstance(value, list) else [value]
    return [payload]


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) and value:
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(int(ts), tz=UTC)
    if isinstance(value, str) and value:
        text = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return datetime.now(tz=UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(tz=UTC)


def _summary_from_balances(account_id: str, payload: Any) -> AccountSummary:
    rows = _as_list(payload, "list", "balances")
    if not rows:
        raise ProviderError("Longbridge account_balance returned no currencies")
    picked = None
    for row in rows:
        if str(_get(row, "currency") or "").upper() == "HKD":
            picked = row
            break
    picked = picked or rows[0]
    extras = {
        "mode": "live",
        "currencies": [str(_get(r, "currency") or "") for r in rows],
        "readonly": True,
    }
    return AccountSummary(
        account_id=account_id,
        as_of=datetime.now(tz=UTC),
        net_liquidation=_num(_get(picked, "net_assets", "net_liquidation")),
        cash=_num(_get(picked, "total_cash", "cash")),
        buying_power=_num(_get(picked, "buy_power", "buying_power")),
        currency=str(_get(picked, "currency") or "HKD"),
        extras=extras,
    )


def _positions_from_stock(account_id: str, payload: Any) -> list[Position]:
    channels = _as_list(payload, "channels", "list")
    rows: list[Position] = []
    for channel in channels:
        account = str(_get(channel, "account_channel", "account_id") or account_id)
        for item in _as_list(channel, "positions", "stock_info", "list"):
            symbol = _get(item, "symbol")
            qty = _num(_get(item, "quantity"))
            if not symbol or qty is None:
                continue
            rows.append(
                Position(
                    account_id=account,
                    symbol=str(symbol),
                    quantity=qty,
                    average_cost=_num(_get(item, "cost_price", "average_cost")),
                    currency=str(_get(item, "currency") or "HKD"),
                    asset_type=AssetType.EQUITY,
                )
            )
    return rows


def _positions_from_fund(account_id: str, payload: Any) -> list[Position]:
    channels = _as_list(payload, "channels", "list")
    rows: list[Position] = []
    for channel in channels:
        account = str(_get(channel, "account_channel", "account_id") or account_id)
        for item in _as_list(channel, "positions", "fund_info", "list"):
            symbol = _get(item, "symbol")
            qty = _num(_get(item, "quantity", "holding"))
            if not symbol or qty is None:
                continue
            rows.append(
                Position(
                    account_id=account,
                    symbol=str(symbol),
                    quantity=qty,
                    average_cost=_num(
                        _get(item, "cost_price", "current_net_asset_value", "net_asset_value")
                    ),
                    currency=str(_get(item, "currency") or "HKD"),
                    asset_type=AssetType.UNKNOWN,
                )
            )
    return rows


def _executions_from(account_id: str, payload: Any) -> list[Execution]:
    rows: list[Execution] = []
    for item in _as_list(payload, "trades", "list"):
        ident = _get(item, "trade_id", "execution_id", "id")
        symbol = _get(item, "symbol")
        price = _num(_get(item, "price"))
        qty = _num(_get(item, "quantity"))
        if not ident or not symbol or price is None or qty is None:
            continue
        side = str(_get(item, "side") or "unknown").lower()
        rows.append(
            Execution(
                execution_id=str(ident),
                account_id=account_id,
                symbol=str(symbol),
                side=side,
                quantity=qty,
                price=price,
                executed_at=_as_dt(_get(item, "trade_done_at", "executed_at", "timestamp")),
                currency=str(_get(item, "currency") or "HKD"),
            )
        )
    return rows

