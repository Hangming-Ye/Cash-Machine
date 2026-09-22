"""Longbridge OAuth read-only account, position, and execution adapter."""
from __future__ import annotations

import os
import math
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from cash_research.artifacts import ArtifactError, reject_secrets, safe_relative_path
from cash_research.config import RequestBoundaryError, Settings, validate_read_request
from cash_research.models import AccountState, DataGap, PortfolioSnapshot, Position, Quantity, SecurityIdentity, SourceResult

_FIELDS = {
    "accounts": {"account_ref", "currency", "balances", "retrieved_at", "reported_at"},
    "positions": {"account_ref", "symbol", "market", "currency", "quantity", "cost_basis", "retrieved_at", "reported_at"},
    "executions": {"trade_id", "order_id", "symbol", "side", "quantity", "price", "trade_done_at", "retrieved_at"},
}


class LongbridgeOAuthReadOnlyAdapter:
    def __init__(self, settings: Settings, *, trade: Any | None = None, oauth_factory: Callable[[str, Callable[[str], None]], Any] | None = None, token_store: Path | None = None, authorization_observer: Callable[[str], None] | None = None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.settings, self._trade, self._oauth_factory, self._clock = settings, trade, oauth_factory or _open_oauth_trade, clock
        self._client_id = _setting(settings, "LONGBRIDGE_CLIENT_ID")
        self._account_ref = _setting(settings, "LONGBRIDGE_ACCOUNT_REF")
        self._secret_values = tuple(
            value.get_secret_value()
            for key, value in settings.credentials.items()
            if key not in {"LONGBRIDGE_CLIENT_ID", "LONGBRIDGE_ACCOUNT_REF"}
            and value.get_secret_value()
        )
        self._token_store = token_store or (Path.home() / ".longbridge" / "openapi" / "tokens" / self._client_id)
        self._authorization_observer = authorization_observer

    def fetch(self, request: Mapping[str, object], *, output_ref: str) -> dict[str, object]:
        now = self._now(); rid = str(request.get("request_id") or "unknown-request"); op = str(request.get("operation") or "unknown")
        try: validated = self._validate(request, output_ref)
        except (ValueError, ArtifactError, RequestBoundaryError): return _failure(rid, op, now, "invalid", "Longbridge request rejected before SDK access")
        rid, op, as_of, params, required = validated
        try: trade = self._context()
        except Exception: return _failure(rid, op, now, "configuration", "existing Longbridge OAuth login is unavailable")
        if op == "accounts": return self._accounts(trade, rid, required, output_ref, as_of)
        if op == "positions": return self._positions(trade, rid, required, output_ref, params.get("include_funds", False), as_of)
        return self._executions(trade, rid, required, output_ref, as_of, params)

    def _validate(self, request: Mapping[str, object], output_ref: str):
        reject_secrets(dict(request))
        validate_read_request(request)
        if request.get("source") != "longbridge_oauth" or "longbridge_oauth" not in self.settings.enabled_sources: raise RequestBoundaryError("disabled")
        if request.get("subject") != "authorized-portfolio": raise ValueError("subject")
        rid, op, as_raw = request.get("request_id"), request.get("operation"), request.get("as_of")
        params, required = request.get("parameters"), request.get("required_fields")
        if not isinstance(rid, str) or not rid or op not in _FIELDS or not isinstance(params, Mapping) or not isinstance(required, list): raise ValueError("shape")
        if not all(isinstance(field, str) and field for field in required): raise ValueError("fields")
        if set(required) - _FIELDS[op]: raise ValueError("fields")
        allowed = {"positions": {"include_funds"}, "executions": {"include_history", "start_at", "end_at"}, "accounts": set()}[op]
        if set(params) - allowed: raise ValueError("parameters")
        for flag in ("include_funds", "include_history"):
            if flag in params and not isinstance(params[flag], bool): raise ValueError("boolean parameter")
        if not isinstance(as_raw, str): raise ValueError("as_of")
        as_of = _aware(as_raw)
        if op == "executions":
            start = _aware(params["start_at"]) if "start_at" in params else None
            end = _aware(params["end_at"]) if "end_at" in params else None
            if start and end and start > end: raise ValueError("invalid range")
        safe_relative_path(self.settings.root, output_ref, must_exist=False)
        if Path(output_ref).suffix.lower() != ".json": raise ValueError("output")
        return rid, op, as_of, params, tuple(required)

    def _context(self):
        if self._trade is not None: return self._trade
        if not self._client_id or not self._token_store.is_file(): raise RuntimeError("missing existing OAuth store")
        def reject_url(_url: str) -> None:
            raise RuntimeError("interactive authorization is disabled for reads")
        self._trade = self._oauth_factory(self._client_id, reject_url)
        return self._trade

    def _accounts(self, trade, rid, required, output_ref, as_of):
        if not self._account_ref: return _failure(rid, "accounts", self._now(), "missing_account_identity", "protected account mapping is unavailable")
        try: raw = _dump(trade.account_balance())
        except Exception: return _failure(rid, "accounts", self._now(), "external", "Longbridge account_balance failed")
        at = self._now()
        if not _raw_safe(raw, self._secret_values): return _failure(rid, "accounts", at, "secret_reflection", "Longbridge response was unsafe to persist")
        recognized, balance_rows = _recognized_list(raw)
        if not recognized: return _failure(rid, "accounts", at, "invalid_response", "Longbridge account_balance shape was not recognized")
        account, cash_rows, excluded = _account(balance_rows, self._account_ref)
        gaps, errors = _quality_gaps(rid, at, excluded)
        if account is None:
            gaps.append(_gap(rid, at, "usable account balance rows", "recognized account_balance response was empty or unusable")); errors.append("empty")
        _historical_gap(gaps, errors, rid, at, as_of)
        missing = _missing_accounts(required, account)
        _add_missing(gaps, errors, rid, at, missing)
        return _result("accounts", rid, at, output_ref, raw, {"raw_locator": "", "auth": "oauth_existing_store", "authorization_started_by_read": False, "account_ref": self._account_ref, "as_of": as_of.isoformat(), "historical_eligibility": "current_only", "accounts": [account.model_dump(mode="json")] if account else [], "cash_rows": cash_rows, "excluded_rows": excluded, "attempted_subreads": ["account_balance"]}, gaps, errors, None)

    def _positions(self, trade, rid, required, output_ref, include_funds, as_of):
        at = self._now()
        if not self._account_ref: return _failure(rid, "positions", at, "missing_account_identity", "protected account mapping is unavailable")
        raw = {}; errors = []; gaps = []; excluded = []; positions = []; cash_rows = []; account = None
        attempted = ["account_balance", "stock_positions"] + (["fund_positions"] if include_funds else [])
        balance_ok = stock_ok = funds_ok = True
        try:
            balances = _dump(trade.account_balance()); raw["account_balance"] = balances
            recognized, balance_rows = _recognized_list(balances)
            if not recognized: raise ValueError("shape")
            account, cash_rows, account_excluded = _account(balance_rows, self._account_ref); excluded += account_excluded
            if account is None: balance_ok = False; errors.append("account_balance_empty"); gaps.append(_gap(rid, self._now(), "usable account balance rows", "account_balance returned empty or unusable rows"))
        except Exception:
            balance_ok = False; errors.append("account_balance_failed"); gaps.append(_gap(rid, self._now(), "account balance", "account_balance failed or shape was invalid"))
        try:
            stocks_raw = _dump(trade.stock_positions()); raw["stock_positions"] = stocks_raw
            recognized, stock_rows = _recognized_position_rows(stocks_raw)
            if not recognized: raise ValueError("shape")
            stock_positions, stock_excluded = _positions(stock_rows, self._account_ref, unit="shares"); positions += stock_positions; excluded += stock_excluded
        except Exception:
            stock_ok = False; errors.append("stock_positions_failed"); gaps.append(_gap(rid, self._now(), "stock positions", "stock_positions failed or shape was invalid"))
        if include_funds:
            try:
                funds_raw = _dump(trade.fund_positions()); raw["fund_positions"] = funds_raw
                recognized, fund_rows = _recognized_position_rows(funds_raw)
                if not recognized: raise ValueError("shape")
                funds, fund_excluded = _positions(fund_rows, self._account_ref, unit="fund_units"); positions += funds; excluded += fund_excluded
            except Exception:
                funds_ok = False; errors.append("fund_positions_failed"); gaps.append(_gap(rid, self._now(), "requested fund positions", "fund_positions failed or shape was invalid"))
        at = self._now()
        if raw and not _raw_safe(raw, self._secret_values): return _failure(rid, "positions", at, "secret_reflection", "Longbridge response was unsafe to persist")
        g2, e2 = _quality_gaps(rid, at, excluded); gaps += g2; errors += e2
        _historical_gap(gaps, errors, rid, at, as_of)
        complete = account is not None and balance_ok and stock_ok and funds_ok and not excluded
        snapshot = None
        if account and positions:
            snapshot = PortfolioSnapshot(snapshot_id=f"snap_{uuid.uuid4().hex}", broker="longbridge_oauth", reported_at=None, retrieved_at=at, accounts=(account,), positions=tuple(positions), coverage="explicit protected account mapping; requested position reads", complete_read=complete, confirmed_empty=False, unknown_reasons={"reported_at": "Longbridge position response exposes no snapshot timestamp"}).model_dump(mode="json")
        elif account and complete:
            snapshot = PortfolioSnapshot(snapshot_id=f"snap_{uuid.uuid4().hex}", broker="longbridge_oauth", reported_at=None, retrieved_at=at, accounts=(account,), positions=(), coverage="explicit protected account mapping; all requested position reads returned empty", complete_read=True, confirmed_empty=True, unknown_reasons={"reported_at": "Longbridge position response exposes no snapshot timestamp"}).model_dump(mode="json")
        missing = _missing_positions(required, positions, explicit_empty=complete and not positions); _add_missing(gaps, errors, rid, at, missing)
        if not raw: return _failure(rid, "positions", at, "external", "all requested Longbridge position subreads failed")
        return _result("positions", rid, at, output_ref, raw, {"raw_locator": "", "account_ref": self._account_ref, "as_of": as_of.isoformat(), "historical_eligibility": "current_only", "cash_rows": cash_rows, "positions": [p.model_dump(mode="json") for p in positions], "excluded_rows": excluded, "include_funds": include_funds, "attempted_subreads": attempted}, gaps, errors, snapshot)

    def _executions(self, trade, rid, required, output_ref, as_of, params):
        at = self._now()
        if not self._account_ref: return _failure(rid, "executions", at, "missing_account_identity", "protected account mapping is unavailable")
        start = _aware(params["start_at"]) if "start_at" in params else None
        end = _aware(params["end_at"]) if "end_at" in params else None
        raw = {}; rows = []; excluded = []; errors = []; gaps = []; today_ok = True
        try:
            today_raw = _dump(trade.today_executions()); raw["today"] = today_raw
            recognized, today_rows = _recognized_list(today_raw)
            if not recognized: raise ValueError("shape")
            parsed, skipped = _execution_rows(today_rows, as_of, self._account_ref, start=start, end=end); rows += parsed; excluded += skipped
        except Exception:
            today_ok = False; errors.append("today_executions_failed"); gaps.append(_gap(rid, self._now(), "today executions", "today_executions failed or shape was invalid"))
        history_complete = True
        if params.get("include_history"):
            try:
                kwargs = {}
                if start: kwargs["start_at"] = start
                if end: kwargs["end_at"] = end
                history_raw = _dump(trade.history_executions(**kwargs)); raw["history"] = history_raw
                if isinstance(history_raw, list): history_source_rows = history_raw
                else:
                    recognized, history_source_rows = _recognized_key_list(history_raw, "trades")
                    if not recognized: raise ValueError("shape")
                history_rows, history_excluded = _execution_rows(history_source_rows, as_of, self._account_ref, start=start, end=end); rows += history_rows; excluded += history_excluded
                if isinstance(history_raw, list):
                    history_complete = False; errors.append("history_pagination_unverified"); gaps.append(_gap(rid, at, "verifiable complete execution history pagination", "SDK returned a plain list without page or has_more metadata"))
                elif _get(history_raw, "has_more") is True:
                    history_complete = False; errors.append("history_pagination_incomplete"); gaps.append(_gap(rid, at, "complete execution history pages", "SDK response has_more is true"))
                elif _get(history_raw, "has_more") is not False:
                    history_complete = False; errors.append("history_pagination_unverified"); gaps.append(_gap(rid, at, "verifiable complete execution history pagination", "SDK response omitted an explicit boolean has_more value"))
            except Exception:
                history_complete = False; errors.append("history_executions_failed"); gaps.append(_gap(rid, at, "requested history executions", "history_executions failed"))
        at = self._now()
        if raw and not _raw_safe(raw, self._secret_values): return _failure(rid, "executions", at, "secret_reflection", "Longbridge response was unsafe to persist")
        unique: list[dict[str, object]] = []; seen: dict[str, dict[str, object]] = {}
        for row in sorted(rows, key=lambda r: str(r["trade_done_at"])):
            prior = seen.get(str(row["trade_id"]))
            if prior is None: seen[str(row["trade_id"])] = row; unique.append(row)
            elif prior != row: unique.append(row); errors.append("conflicting_trade_id"); gaps.append(_gap(rid, at, "one consistent execution per trade_id", "conflicting duplicate trade_id retained"))
        g2, e2 = _quality_gaps(rid, at, excluded); gaps += g2; errors += e2
        missing = _missing_exec(required, unique, explicit_empty=not unique and today_ok and history_complete and not excluded); _add_missing(gaps, errors, rid, at, missing)
        if not raw: return _failure(rid, "executions", at, "external", "all requested Longbridge execution subreads failed")
        return _result("executions", rid, at, output_ref, raw, {"raw_locator": "", "account_ref": self._account_ref, "history_requested": params.get("include_history", False), "history_excludes_today": True if params.get("include_history") else None, "history_pages_complete": history_complete if params.get("include_history") else None, "dedupe_key": "trade_id", "executions": unique, "excluded_rows": excluded, "attempted_subreads": ["today_executions"] + (["history_executions"] if params.get("include_history") else [])}, gaps, errors, None)

    def _now(self):
        value = self._clock()
        if value.tzinfo is None: raise ValueError("clock must be aware")
        return value


def _open_oauth_trade(client_id: str, callback):
    from longbridge.openapi import Config, OAuthBuilder, TradeContext
    oauth = OAuthBuilder(client_id).build(callback)
    return TradeContext(Config.from_oauth(oauth))


def _setting(settings, name):
    value: SecretStr | None = settings.credentials.get(name)
    return value.get_secret_value().strip() if value else (os.environ.get(name) or "").strip()


def _dump(value):
    if value is None or isinstance(value, (str, int, float, bool)): return value
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, Mapping): return {str(k): _dump(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_dump(v) for v in value]
    if hasattr(value, "__dict__"): return {k: _dump(v) for k, v in vars(value).items() if not k.startswith("_")}
    public = {}
    for name in (
        "list", "balances", "currency", "total_cash", "net_assets", "buy_power",
        "max_finance_amount", "remaining_finance_amount", "risk_level", "margin_call",
        "init_margin", "maintenance_margin",
        "cash_infos", "available_cash", "frozen_cash", "settling_cash", "withdraw_cash",
        "channels", "account_channel", "positions", "stock_info", "fund_info", "symbol", "symbol_name",
        "quantity", "available_quantity", "init_quantity", "cost_price", "market",
        "holding_units", "current_net_asset_value", "net_asset_value_day", "cost_net_asset_value",
        "has_more", "trades", "trade_id",
        "order_id", "side", "price", "trade_done_at",
    ):
        if hasattr(value, name):
            item = getattr(value, name)
            if item is not None: public[name] = _dump(item)
    if public: return public
    return str(value)


def _rows(payload, *keys):
    if isinstance(payload, list): return payload
    for key in keys:
        value = _get(payload, key)
        if value is not None: return value if isinstance(value, list) else [value]
    return []


def _recognized_list(payload):
    return (True, payload) if isinstance(payload, list) else (False, [])


def _recognized_key_list(payload, key):
    if not isinstance(payload, Mapping) or key not in payload or not isinstance(payload[key], list): return False, []
    return True, payload[key]


def _recognized_position_rows(payload):
    recognized, channels = _recognized_key_list(payload, "channels")
    if not recognized: return False, []
    rows = []
    for channel in channels:
        if not isinstance(channel, Mapping): return False, []
        found = False
        for key in ("positions", "stock_info", "fund_info", "list"):
            if key in channel:
                if not isinstance(channel[key], list): return False, []
                rows.extend(channel[key]); found = True; break
        if not found: return False, []
    return True, rows


def _get(value, key, default=None): return value.get(key, default) if isinstance(value, Mapping) else default
def _dec(value):
    try: result = Decimal(str(value)); return result if result.is_finite() else None
    except (InvalidOperation, ValueError): return None


def _account(raw, account_ref):
    balances = []; cash_rows = []; excluded = []
    for row in raw:
        if not isinstance(row, Mapping): excluded.append({"section": "account_balance", "reason": "malformed_row"}); continue
        currency = str(_get(row, "currency", ""))
        total = _dec(_get(row, "total_cash"))
        if re.fullmatch(r"[A-Z]{3}", currency) and total is not None:
            balances.append(Quantity(value=total, unit="total_cash", currency=currency)); cash_rows.append({"currency": currency, "kind": "total_cash", "value": str(total)})
        else: excluded.append({"section": "account_balance", "reason": "missing_currency_or_total_cash", "raw": row})
        for info in _rows(row, "cash_infos"):
            if not isinstance(info, Mapping): excluded.append({"section": "cash_info", "reason": "malformed_row"}); continue
            cur = str(_get(info, "currency", ""))
            for field in ("available_cash", "frozen_cash", "settling_cash", "withdraw_cash"):
                val = _dec(_get(info, field))
                if re.fullmatch(r"[A-Z]{3}", cur) and val is not None: balances.append(Quantity(value=val, unit=field, currency=cur)); cash_rows.append({"currency": cur, "kind": field, "value": str(val)})
    account = AccountState(account_ref=account_ref, base_currency=None, balances=tuple(balances)) if balances else None
    return account, cash_rows, excluded


def _positions(raw, account_ref, *, unit):
    output = []; excluded = []
    for row in raw:
            if not isinstance(row, Mapping): excluded.append({"section": unit, "reason": "malformed_row"}); continue
            symbol, currency = str(_get(row, "symbol", "")), str(_get(row, "currency", ""))
            qty = _dec(_get(row, "holding_units" if unit == "fund_units" else "quantity"))
            raw_market = _get(row, "market")
            market = symbol.rsplit(".", 1)[-1] if "." in symbol else (str(raw_market).rsplit(".", 1)[-1] if raw_market else "")
            if unit == "fund_units" and "." not in symbol and not raw_market:
                excluded.append({"section": unit, "reason": "fund_market_unavailable", "raw": row}); continue
            if not symbol or not market or not re.fullmatch(r"[A-Z]{3}", currency) or qty is None:
                excluded.append({"section": unit, "reason": "missing_identity_currency_or_quantity", "raw": row}); continue
            cost = _dec(_get(row, "cost_net_asset_value" if unit == "fund_units" else "cost_price"))
            output.append(Position(account_ref=account_ref, security=SecurityIdentity(market=market, symbol=symbol, currency=currency), quantity=Quantity(value=qty, unit=unit), cost_basis=Quantity(value=cost, unit="currency_per_unit", currency=currency) if cost is not None else None))
    return output, excluded


def _execution_rows(raw, as_of, account_ref, *, start=None, end=None):
    output = []; excluded = []
    for row in raw:
        if not isinstance(row, Mapping): excluded.append({"section": "execution", "reason": "malformed_row"}); continue
        try: when = _aware(_get(row, "trade_done_at"))
        except ValueError: excluded.append({"section": "execution", "reason": "missing_or_naive_time", "raw": row}); continue
        required = {k: _get(row, k) for k in ("trade_id", "order_id", "symbol", "quantity", "price")}
        if any(v in (None, "") for v in required.values()) or _dec(required["quantity"]) is None or _dec(required["price"]) is None:
            excluded.append({"section": "execution", "reason": "missing_required_field", "raw": row}); continue
        if when > as_of: excluded.append({"section": "execution", "reason": "after_as_of_cutoff", "raw": row}); continue
        if start and when < start: excluded.append({"section": "execution", "reason": "before_requested_range", "raw": row}); continue
        if end and when > end: excluded.append({"section": "execution", "reason": "after_requested_range", "raw": row}); continue
        side = _get(row, "side")
        output.append({**required, "side": side, "trade_done_at": when.isoformat(), "account_ref": account_ref, "unknown_reasons": {"side": "SDK Execution schema does not provide side"} if side in (None, "") else {}})
    return output, excluded


def _aware(value):
    if isinstance(value, datetime): parsed = value
    elif isinstance(value, bool): raise ValueError("bool timestamp")
    elif isinstance(value, (int, float)):
        if not math.isfinite(float(value)): raise ValueError("nonfinite timestamp")
        try: parsed = datetime.fromtimestamp(value, timezone.utc)
        except (OverflowError, OSError, ValueError) as exc: raise ValueError("timestamp range") from exc
    elif isinstance(value, str):
        try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc: raise ValueError("timestamp") from exc
    else: raise ValueError("time")
    if parsed.tzinfo is None: raise ValueError("naive")
    return parsed.astimezone(timezone.utc)


def _missing_accounts(required, account):
    checks = {"account_ref": account is not None, "currency": account is not None and bool(account.balances), "balances": account is not None and bool(account.balances), "retrieved_at": True, "reported_at": False}
    return [f for f in required if not checks[f]]
def _missing_positions(required, rows, explicit_empty):
    row_ok = explicit_empty or bool(rows)
    checks = {"account_ref": row_ok and all(p.account_ref for p in rows), "symbol": row_ok and all(p.security.symbol for p in rows), "market": row_ok and all(p.security.market for p in rows), "currency": row_ok and all(p.security.currency for p in rows), "quantity": row_ok and all(p.quantity.value is not None for p in rows), "cost_basis": row_ok and all(p.cost_basis is not None for p in rows), "retrieved_at": True, "reported_at": False}
    return [f for f in required if not checks[f]]
def _missing_exec(required, rows, explicit_empty):
    row_ok = explicit_empty or bool(rows)
    checks = {f: row_ok and all(row.get(f) not in (None, "") for row in rows) for f in _FIELDS["executions"] if f != "retrieved_at"}; checks["retrieved_at"] = True
    return [f for f in required if not checks[f]]


def _gap(rid, at, required, result): return DataGap(gap_id=f"gap_{uuid.uuid4().hex}", request_id=rid, required_content=required, attempts=({"source": "longbridge_oauth", "at": at.isoformat(), "result": result},), impact="requested broker coverage is limited", next_action="verify the existing OAuth read channel and retry the bounded read").model_dump(mode="json")
def _quality_gaps(rid, at, excluded): return ([_gap(rid, at, "valid complete provider rows", f"{len(excluded)} rows excluded")] if excluded else [], ["excluded_rows"] if excluded else [])
def _add_missing(gaps, errors, rid, at, missing):
    if missing: gaps.append(_gap(rid, at, ", ".join(missing), "required fields missing")); errors.append("required_fields_missing")


def _historical_gap(gaps, errors, rid, at, as_of):
    if as_of.date() < at.date():
        gaps.append(_gap(rid, at, "historical broker snapshot available by as_of", "Longbridge current read has no historical snapshot/availability proof")); errors.append("historical_eligibility_unknown")


def _raw_safe(raw, secret_values=()):
    try: reject_secrets(raw)
    except Exception: return False
    serialized = repr(raw)
    if any(secret in serialized for secret in secret_values): return False
    return True


def _result(op, rid, at, output_ref, raw, normalized, gaps, errors, snapshot):
    quality = "complete" if not gaps and not errors else "limited"
    source = SourceResult(source="longbridge_oauth", operation=op, security_or_topic="authorized-portfolio", observed_at=None, retrieved_at=at, available_at=None, coverage="existing OAuth read-only TradeContext; requested subreads recorded separately", payload_ref=output_ref, quality=quality, errors=tuple(dict.fromkeys(errors)), unknown_reasons={"observed_at": "provider read exposed no snapshot timestamp", "available_at": "provider read exposed no availability timestamp"})
    return {"source_result": source.model_dump(mode="json"), "raw_payload": raw, "normalized": normalized, "evidence": [], "gaps": gaps, "portfolio_snapshot": snapshot}


def _failure(rid, op, at, reason, coverage):
    source = SourceResult(source="longbridge_oauth", operation=op, security_or_topic="authorized-portfolio", observed_at=None, retrieved_at=at, available_at=None, coverage=coverage, payload_ref=None, quality="failed", errors=(reason,), unknown_reasons={"observed_at": "no usable provider data", "available_at": "no usable provider data"})
    return {"source_result": source.model_dump(mode="json"), "raw_payload": None, "normalized": {"raw_locator": None, "error_reason": reason}, "evidence": [], "gaps": [_gap(rid, at, f"Longbridge {op} data", reason)], "portfolio_snapshot": None}
