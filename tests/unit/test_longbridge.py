from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

from cash_research.config import Settings
from cash_research.models import PortfolioSnapshot, SourceResult
from cash_research.sources.longbridge_readonly import LongbridgeOAuthReadOnlyAdapter


NOW = datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)


def settings(tmp_path: Path, **values: str) -> Settings:
    credentials = {
        "LONGBRIDGE_CLIENT_ID": "synthetic-client",
        "LONGBRIDGE_ACCOUNT_REF": "SYNTH-LB-A",
        **values,
    }
    return Settings.model_validate({"root": tmp_path, "enabled_sources": ["longbridge_oauth"], "credentials": credentials})


def request(operation: str, **parameters: object) -> dict[str, object]:
    fields = {
        "accounts": ["account_ref", "currency", "balances"],
        "positions": ["account_ref", "symbol", "quantity", "currency"],
        "executions": ["trade_id", "order_id", "symbol", "quantity", "price", "trade_done_at"],
    }[operation]
    return {"request_id": f"fixture-{operation}", "source": "longbridge_oauth", "operation": operation, "subject": "authorized-portfolio", "as_of": "2026-09-21T04:00:00Z", "parameters": parameters, "required_fields": fields}


class FakeTrade:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.balance = [NS(currency="HKD", total_cash="40000", net_assets="100000", cash_infos=[NS(currency="HKD", available_cash="25000", frozen_cash="1000", settling_cash="14000"), NS(currency="USD", available_cash="500", frozen_cash="0", settling_cash="50")])]
        self.stocks = NS(channels=[NS(account_channel="lb-channel", positions=[NS(symbol="700.HK", quantity="100", available_quantity="80", currency="HKD", cost_price="307.5")])])
        self.funds = NS(channels=[])
        self.today = [NS(trade_id="T1", order_id="O1", symbol="700.HK", side="Buy", quantity="20", price="320", trade_done_at=datetime(2026, 9, 21, 2, 10, tzinfo=timezone.utc))]
        self.history = NS(has_more=False, trades=[NS(trade_id="T0", order_id="O0", symbol="700.HK", side="Buy", quantity="80", price="307.5", trade_done_at=datetime(2026, 9, 18, 7, 0, tzinfo=timezone.utc))])

    def account_balance(self): self.calls.append("account_balance"); return self.balance
    def stock_positions(self): self.calls.append("stock_positions"); return self.stocks
    def fund_positions(self): self.calls.append("fund_positions"); return self.funds
    def today_executions(self): self.calls.append("today_executions"); return self.today
    def history_executions(self, **kwargs): self.calls.append("history_executions"); return self.history


def adapter(tmp_path: Path, trade: FakeTrade, **kwargs: object) -> LongbridgeOAuthReadOnlyAdapter:
    return LongbridgeOAuthReadOnlyAdapter(settings(tmp_path), trade=trade, clock=lambda: NOW, **kwargs)


def test_accounts_preserve_all_cash_currencies_without_invented_time(tmp_path: Path) -> None:
    trade = FakeTrade()
    result = adapter(tmp_path, trade).fetch(request("accounts"), output_ref="data/records/accounts/raw.json")
    source = SourceResult.model_validate(result["source_result"])
    assert source.observed_at is None and source.available_at is None
    assert {row["currency"] for row in result["normalized"]["cash_rows"]} == {"HKD", "USD"}
    assert result["normalized"]["account_ref"] == "SYNTH-LB-A"
    assert trade.calls == ["account_balance"]
    assert result["portfolio_snapshot"] is None


def test_positions_join_explicit_account_and_confirm_nonempty(tmp_path: Path) -> None:
    trade = FakeTrade()
    result = adapter(tmp_path, trade).fetch(request("positions"), output_ref="data/records/positions/raw.json")
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    assert snapshot.positions[0].account_ref == "SYNTH-LB-A"
    assert snapshot.positions[0].quantity.unit == "shares"
    assert snapshot.reported_at is None and snapshot.confirmed_empty is False
    assert trade.calls == ["account_balance", "stock_positions"]


def test_explicit_empty_positions_require_all_requested_reads(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.stocks = NS(channels=[])
    result = adapter(tmp_path, trade).fetch(request("positions"), output_ref="data/records/empty/raw.json")
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    assert snapshot.confirmed_empty and snapshot.complete_read

    trade = FakeTrade(); trade.stocks = NS(channels=[])
    def fail_funds(): trade.calls.append("fund_positions"); raise RuntimeError("private")
    trade.fund_positions = fail_funds  # type: ignore[method-assign]
    result = adapter(tmp_path, trade).fetch(request("positions", include_funds=True), output_ref="data/records/partial/raw.json")
    assert result["portfolio_snapshot"] is None
    assert result["source_result"]["quality"] == "limited"
    assert "fund_positions_failed" in result["source_result"]["errors"]


def test_fund_units_are_not_labeled_shares(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.stocks = NS(channels=[])
    trade.funds = NS(channels=[NS(positions=[NS(symbol="FUND.HK", holding_units="3", currency="HKD", cost_net_asset_value="10")])])
    result = adapter(tmp_path, trade).fetch(request("positions", include_funds=True), output_ref="data/records/fund/raw.json")
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    assert snapshot.positions[0].quantity.unit == "fund_units"


def test_executions_merge_today_history_and_dedupe_identical(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.history.trades.append(trade.today[0])
    result = adapter(tmp_path, trade).fetch(request("executions", include_history=True, start_at="2026-09-18T00:00:00Z", end_at="2026-09-21T04:00:00Z"), output_ref="data/records/executions/raw.json")
    assert [row["trade_id"] for row in result["normalized"]["executions"]] == ["T0", "T1"]
    assert result["normalized"]["history_excludes_today"] is True
    assert all(row["account_ref"] == "SYNTH-LB-A" for row in result["normalized"]["executions"])
    assert trade.calls == ["today_executions", "history_executions"]


def test_conflicting_duplicate_and_has_more_are_limited(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.history.has_more = True
    trade.history.trades = [NS(**{**trade.today[0].__dict__, "price": "319"})]
    result = adapter(tmp_path, trade).fetch(request("executions", include_history=True), output_ref="data/records/conflict/raw.json")
    assert result["source_result"]["quality"] == "limited"
    assert "conflicting_trade_id" in result["source_result"]["errors"]
    assert "history_pagination_incomplete" in result["source_result"]["errors"]
    assert len(result["normalized"]["executions"]) == 2


def test_real_sdk_plain_history_list_is_pagination_unverified(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.history = trade.history.trades
    result = adapter(tmp_path, trade).fetch(request("executions", include_history=True), output_ref="data/records/list-history/raw.json")
    assert result["normalized"]["history_pages_complete"] is False
    assert "history_pagination_unverified" in result["source_result"]["errors"]


def test_future_and_naive_execution_times_are_excluded(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.today = [NS(trade_id="F", order_id="O", symbol="700.HK", side="Buy", quantity="1", price="1", trade_done_at=datetime(2026, 9, 22, tzinfo=timezone.utc)), NS(trade_id="N", order_id="N", symbol="700.HK", side="Buy", quantity="1", price="1", trade_done_at=datetime(2026, 9, 20))]
    result = adapter(tmp_path, trade).fetch(request("executions"), output_ref="data/records/time/raw.json")
    assert result["normalized"]["executions"] == []
    assert result["normalized"]["excluded_rows"]


def test_missing_account_mapping_never_creates_snapshot(tmp_path: Path) -> None:
    trade = FakeTrade()
    no_account = Settings.model_validate({"root": tmp_path, "enabled_sources": ["longbridge_oauth"], "credentials": {"LONGBRIDGE_CLIENT_ID": "client"}})
    result = LongbridgeOAuthReadOnlyAdapter(no_account, trade=trade, clock=lambda: NOW).fetch(request("positions"), output_ref="data/records/no-account/raw.json")
    assert result["portfolio_snapshot"] is None
    assert result["source_result"]["quality"] == "failed"


def test_partial_stock_failure_is_not_empty(tmp_path: Path) -> None:
    trade = FakeTrade()
    def fail(): trade.calls.append("stock_positions"); raise RuntimeError("token=private")
    trade.stock_positions = fail  # type: ignore[method-assign]
    result = adapter(tmp_path, trade).fetch(request("positions"), output_ref="data/records/fail/raw.json")
    assert result["portfolio_snapshot"] is None and "account_balance" in result["raw_payload"]
    assert "private" not in str(result)


def test_positions_with_empty_account_balance_cannot_be_complete_or_snapshot(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.balance = []
    result = adapter(tmp_path, trade).fetch(request("positions"), output_ref="data/records/no-balance/raw.json")
    assert result["portfolio_snapshot"] is None
    assert result["source_result"]["quality"] == "limited"
    assert "account_balance_empty" in result["source_result"]["errors"]


def test_unknown_field_order_watchlist_and_bad_path_make_no_calls(tmp_path: Path) -> None:
    trade = FakeTrade(); api = adapter(tmp_path, trade)
    bad = request("accounts"); bad["required_fields"] = ["unknown"]
    for req, path in ((bad, "data/records/x/raw.json"), ({**request("accounts"), "operation": "submit_order"}, "data/records/x/raw.json"), ({**request("accounts"), "operation": "watchlist"}, "data/records/x/raw.json"), (request("accounts"), "../escape.json")):
        assert api.fetch(req, output_ref=path)["source_result"]["quality"] == "failed"
    assert trade.calls == []


def test_default_oauth_factory_refuses_missing_store_and_never_opens_authorization(tmp_path: Path) -> None:
    opened: list[str] = []
    api = LongbridgeOAuthReadOnlyAdapter(settings(tmp_path), oauth_factory=lambda client_id, callback: callback("https://authorize.invalid"), token_store=tmp_path / "missing", authorization_observer=opened.append, clock=lambda: NOW)
    result = api.fetch(request("accounts"), output_ref="data/records/oauth/raw.json")
    assert result["source_result"]["quality"] == "failed"
    assert opened == []


def test_read_surface_calls_no_order_quote_or_watchlist_methods(tmp_path: Path) -> None:
    trade = FakeTrade(); adapter(tmp_path, trade).fetch(request("accounts"), output_ref="data/records/read/raw.json")
    assert set(trade.calls) <= {"account_balance", "stock_positions", "fund_positions", "today_executions", "history_executions"}


def test_sdk_style_slot_objects_are_serialized_by_public_field_allowlist(tmp_path: Path) -> None:
    class Cash:
        __slots__ = ("currency", "available_cash", "frozen_cash", "settling_cash")
        def __init__(self): self.currency, self.available_cash, self.frozen_cash, self.settling_cash = "USD", "2", "0", "1"
    class Balance:
        __slots__ = ("currency", "total_cash", "net_assets", "cash_infos")
        def __init__(self): self.currency, self.total_cash, self.net_assets, self.cash_infos = "USD", "3", "4", [Cash()]
    trade = FakeTrade(); trade.balance = [Balance()]
    result = adapter(tmp_path, trade).fetch(request("accounts"), output_ref="data/records/slots/raw.json")
    assert result["normalized"]["cash_rows"][0] == {"currency": "USD", "kind": "total_cash", "value": "3"}


def test_malformed_or_none_position_shapes_never_confirm_empty(tmp_path: Path) -> None:
    for malformed in (None, {}, {"channels": [{}]}, {"channels": "bad"}):
        trade = FakeTrade(); trade.stocks = malformed
        result = adapter(tmp_path, trade).fetch(request("positions"), output_ref="data/records/malformed/raw.json")
        assert result["portfolio_snapshot"] is None
        assert "stock_positions_failed" in result["source_result"]["errors"]


def test_empty_account_response_is_limited_even_without_required_fields(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.balance = []
    req = request("accounts"); req["required_fields"] = []
    result = adapter(tmp_path, trade).fetch(req, output_ref="data/records/empty-account/raw.json")
    assert result["source_result"]["quality"] == "limited"
    assert result["normalized"]["accounts"] == []


def test_invalid_flags_range_and_nested_required_fields_make_no_sdk_calls(tmp_path: Path) -> None:
    trade = FakeTrade(); api = adapter(tmp_path, trade)
    requests = [
        request("positions", include_funds="yes"),
        request("executions", include_history="yes"),
        request("executions", start_at="2026-09-21T05:00:00Z", end_at="2026-09-21T04:00:00Z"),
    ]
    nested = request("accounts"); nested["required_fields"] = [["currency"]]
    requests.append(nested)
    for item in requests:
        assert api.fetch(item, output_ref="data/records/invalid-input/raw.json")["source_result"]["quality"] == "failed"
    assert trade.calls == []


def test_today_failure_still_attempts_requested_history(tmp_path: Path) -> None:
    trade = FakeTrade()
    def fail_today(): trade.calls.append("today_executions"); raise RuntimeError("private")
    trade.today_executions = fail_today  # type: ignore[method-assign]
    result = adapter(tmp_path, trade).fetch(request("executions", include_history=True), output_ref="data/records/today-fail/raw.json")
    assert trade.calls == ["today_executions", "history_executions"]
    assert [row["trade_id"] for row in result["normalized"]["executions"]] == ["T0"]
    assert "today_executions_failed" in result["source_result"]["errors"]


def test_response_secret_key_or_bearer_value_is_not_persisted(tmp_path: Path) -> None:
    for unsafe in ([{"currency": "HKD", "total_cash": "1", "access_token": "secret"}], [{"currency": "HKD", "total_cash": "1", "note": "Bearer abcdefghijklmnop"}]):
        trade = FakeTrade(); trade.balance = unsafe
        result = adapter(tmp_path, trade).fetch(request("accounts"), output_ref="data/records/unsafe/raw.json")
        assert result["raw_payload"] is None
        assert result["source_result"]["errors"] == ["secret_reflection"]


def test_lowercase_currency_is_excluded_without_uppercase_invention(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.balance = [NS(currency="hkd", total_cash="1", cash_infos=[])]
    result = adapter(tmp_path, trade).fetch(request("accounts"), output_ref="data/records/currency/raw.json")
    assert result["normalized"]["accounts"] == []
    assert result["source_result"]["quality"] == "limited"


def test_real_sdk_execution_without_side_is_retained_with_unknown_reason(tmp_path: Path) -> None:
    class Execution:
        __slots__ = ("trade_id", "order_id", "symbol", "quantity", "price", "trade_done_at")
        def __init__(self):
            self.trade_id, self.order_id, self.symbol = "REAL-T", "REAL-O", "700.HK"
            self.quantity, self.price = "1", "300"
            self.trade_done_at = datetime(2026, 9, 21, 2, tzinfo=timezone.utc)
    trade = FakeTrade(); trade.today = [Execution()]
    result = adapter(tmp_path, trade).fetch(request("executions"), output_ref="data/records/real-execution/raw.json")
    row = result["normalized"]["executions"][0]
    assert row["trade_id"] == "REAL-T" and row["side"] is None
    assert row["unknown_reasons"]["side"]


def test_real_sdk_fund_isin_without_market_is_raw_limited_not_false_empty(tmp_path: Path) -> None:
    class Fund:
        __slots__ = ("symbol", "current_net_asset_value", "net_asset_value_day", "currency", "cost_net_asset_value", "holding_units")
        def __init__(self):
            self.symbol, self.currency = "HK0000000001", "HKD"
            self.current_net_asset_value, self.cost_net_asset_value, self.holding_units = "11", "10", "3"
            self.net_asset_value_day = datetime(2026, 9, 20, tzinfo=timezone.utc)
    trade = FakeTrade(); trade.stocks = NS(channels=[]); trade.funds = NS(channels=[NS(positions=[Fund()])])
    result = adapter(tmp_path, trade).fetch(request("positions", include_funds=True), output_ref="data/records/real-fund/raw.json")
    assert result["portfolio_snapshot"] is None
    assert any(row["reason"] == "fund_market_unavailable" for row in result["normalized"]["excluded_rows"])
    assert "holding_units" in result["raw_payload"]["fund_positions"]["channels"][0]["positions"][0]


def test_request_bearer_value_is_rejected_before_sdk(tmp_path: Path) -> None:
    trade = FakeTrade(); req = request("accounts"); req["parameters"] = {"note": "Bearer abcdefghijklmnop"}
    result = adapter(tmp_path, trade).fetch(req, output_ref="data/records/request-secret/raw.json")
    assert result["source_result"]["quality"] == "failed"
    assert trade.calls == []


def test_actual_configured_secret_reflection_is_dropped(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.balance = [{"currency": "HKD", "total_cash": "1", "note": "actual-refresh-secret"}]
    configured = settings(tmp_path, LONGBRIDGE_REFRESH_TOKEN="actual-refresh-secret")
    result = LongbridgeOAuthReadOnlyAdapter(configured, trade=trade, clock=lambda: NOW).fetch(request("accounts"), output_ref="data/records/reflection/raw.json")
    assert result["raw_payload"] is None
    assert result["source_result"]["errors"] == ["secret_reflection"]


def test_today_and_history_both_obey_requested_range(tmp_path: Path) -> None:
    trade = FakeTrade()
    result = adapter(tmp_path, trade).fetch(request("executions", include_history=True, start_at="2026-09-18T00:00:00Z", end_at="2026-09-20T23:59:59Z"), output_ref="data/records/range/raw.json")
    assert [row["trade_id"] for row in result["normalized"]["executions"]] == ["T0"]
    assert any(row["reason"] == "after_requested_range" for row in result["normalized"]["excluded_rows"])


def test_existing_store_path_reaches_and_refuses_authorization_callback(tmp_path: Path) -> None:
    store = tmp_path / "oauth-token"; store.write_text("synthetic-not-a-token", encoding="utf-8")
    attempts: list[str] = []
    def factory(client_id, callback):
        attempts.append(client_id)
        callback("https://authorize.invalid")
        raise AssertionError("callback must refuse")
    api = LongbridgeOAuthReadOnlyAdapter(settings(tmp_path), oauth_factory=factory, token_store=store, clock=lambda: NOW)
    result = api.fetch(request("accounts"), output_ref="data/records/oauth-callback/raw.json")
    assert attempts == ["synthetic-client"]
    assert result["source_result"]["quality"] == "failed"
    assert result["source_result"]["errors"] == ["configuration"]


def test_history_mapping_without_boolean_has_more_is_unverified(tmp_path: Path) -> None:
    trade = FakeTrade(); trade.history = {"trades": trade.history.trades, "has_more": "false"}
    result = adapter(tmp_path, trade).fetch(request("executions", include_history=True), output_ref="data/records/nonbool-page/raw.json")
    assert "history_pagination_unverified" in result["source_result"]["errors"]
