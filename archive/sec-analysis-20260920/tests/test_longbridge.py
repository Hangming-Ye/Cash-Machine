"""Longbridge read-only broker — mocked SDK, no live OpenAPI, no write APIs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_analysis.brokers.ibkr.safety import assert_no_order_methods, scan_broker_sources
from sec_analysis.brokers.longbridge import LongbridgeReadOnlyClient, oauth_token_store
from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.models import AssetType
from sec_analysis.providers.registry import build_providers


def _settings(**kwargs) -> Settings:
    data = {
        "broker_client": "longbridge",
        "longbridge_mode": "live",
        "longbridge_auth": "token",
        "longbridge_client_id": "cid-test",
        "longbridge_account_id": "LB-TEST",
        "longbridge_app_key": "key",
        "longbridge_app_secret": "secret",
        "longbridge_access_token": "token",
        "news_provider": "stub",
        "market_data_route_us": "stub",
        "market_data_route_default": "stub",
    }
    data.update(kwargs)
    return Settings(**data)


class _Trade:
    def __init__(self) -> None:
        self.balance_calls = 0
        self.history_calls = 0

    def account_balance(self):
        self.balance_calls += 1
        return [
            SimpleNamespace(
                currency="USD",
                total_cash=1_000.0,
                net_assets=2_000.0,
                buy_power=1_500.0,
            ),
            SimpleNamespace(
                currency="HKD",
                total_cash=80_000.0,
                net_assets=250_000.0,
                buy_power=120_000.0,
            ),
        ]

    def stock_positions(self):
        return SimpleNamespace(
            channels=[
                SimpleNamespace(
                    account_channel="lb-cash",
                    positions=[
                        SimpleNamespace(
                            symbol="700.HK",
                            quantity=200,
                            cost_price=310.5,
                            currency="HKD",
                            market="HK",
                        )
                    ],
                )
            ]
        )

    def fund_positions(self):
        return {
            "channels": [
                {
                    "account_channel": "lb-fund",
                    "positions": [{"symbol": "HKD-MMF", "quantity": 10, "currency": "HKD"}],
                }
            ]
        }

    def today_executions(self):
        return [
            SimpleNamespace(
                trade_id="t-today",
                symbol="700.HK",
                side="Buy",
                quantity=50,
                price=320.0,
                trade_done_at=1718472000,
            )
        ]

    def history_executions(self, start_at=None, end_at=None):
        self.history_calls += 1
        return [
            {
                "trade_id": "t-hist",
                "symbol": "9988.HK",
                "side": "Sell",
                "quantity": 10,
                "price": 80.0,
                "trade_done_at": "2024-01-15T03:00:00+00:00",
            }
        ]


def test_live_mapping_prefers_hkd_and_includes_funds() -> None:
    trade = _Trade()
    client = LongbridgeReadOnlyClient(_settings(), trade=trade)
    summary = client.get_account_summary()
    assert summary.currency == "HKD"
    assert summary.cash == 80_000.0
    assert summary.net_liquidation == 250_000.0
    assert summary.extras["readonly"] is True
    positions = client.get_positions()
    symbols = {p.symbol for p in positions}
    assert "700.HK" in symbols
    assert "HKD-MMF" in symbols
    assert any(p.asset_type is AssetType.EQUITY for p in positions)
    today = client.get_executions()
    assert [f.execution_id for f in today] == ["t-today"]
    assert today[0].side == "buy"
    assert trade.history_calls == 0
    hist = client.get_executions(history=True)
    assert {f.execution_id for f in hist} == {"t-today", "t-hist"}
    assert trade.history_calls == 1


def test_missing_credentials_is_config_error_not_fake_balances() -> None:
    client = LongbridgeReadOnlyClient(
        Settings(broker_client="longbridge", longbridge_mode="live")
    )
    with pytest.raises(ProviderConfigError, match="LONGBRIDGE_APP_KEY") as exc:
        client.get_account_summary()
    assert "does not invent" in str(exc.value)
    with pytest.raises(ProviderConfigError, match="LONGBRIDGE_APP_KEY"):
        client.get_positions()
    with pytest.raises(ProviderConfigError, match="LONGBRIDGE_APP_KEY"):
        client.get_executions()
    assert client.is_connected() is False


def test_oauth_missing_client_id_is_config_error() -> None:
    client = LongbridgeReadOnlyClient(
        Settings(
            broker_client="longbridge",
            longbridge_mode="live",
            longbridge_auth="oauth",
        )
    )
    with pytest.raises(ProviderConfigError, match="LONGBRIDGE_CLIENT_ID"):
        client.get_account_summary()


def test_apikey_alias_uses_token_trio() -> None:
    settings = Settings(longbridge_auth="apikey")
    assert settings.longbridge_auth == "token"


def test_unset_auth_uses_token_trio_opener() -> None:
    opened: list[tuple[str, str, str]] = []

    def open_token(key: str, secret: str, token: str):
        opened.append((key, secret, token))
        return _Trade()

    client = LongbridgeReadOnlyClient(
        Settings(
            broker_client="longbridge",
            longbridge_mode="live",
            longbridge_app_key="k",
            longbridge_app_secret="s",
            longbridge_access_token="t",
        ),
        open_apikey=open_token,
    )
    client.connect()
    assert opened == [("k", "s", "t")]
    assert client.get_account_summary().extras["auth"] == "token"


def test_credentials_accept_longport_alias() -> None:
    settings = Settings(
        longbridge_app_key="",
        longport_app_key="alias-key",
        longport_app_secret="alias-secret",
        longport_access_token="alias-token",
    )
    assert settings.longbridge_credentials() == ("alias-key", "alias-secret", "alias-token")


def test_registry_selects_longbridge() -> None:
    bundle = build_providers(Settings(broker_client="longbridge", longbridge_mode="stub"))
    assert bundle.broker.name == "longbridge"
    with pytest.raises(ProviderConfigError, match="LONGBRIDGE_APP_KEY|longbridge-login"):
        bundle.broker.get_account_summary()


def test_live_balance_error_is_clear() -> None:
    class Boom:
        def account_balance(self):
            raise RuntimeError("upstream down")

    client = LongbridgeReadOnlyClient(_settings(), trade=Boom())
    with pytest.raises(ProviderError, match="account_balance"):
        client.get_account_summary()


def test_missing_sdk_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise ProviderConfigError("longbridge SDK is not installed")

    monkeypatch.setattr(
        "sec_analysis.brokers.longbridge.readonly_client._open_trade_context",
        boom,
    )
    client = LongbridgeReadOnlyClient(_settings(longbridge_auth="token"))
    with pytest.raises(ProviderConfigError, match="longbridge SDK"):
        client.connect()


def test_oauth_connect_uses_builder_callback() -> None:
    urls: list[str] = []
    trade = _Trade()

    def open_oauth(client_id: str, *, on_authorize_url=None, **_k):
        if on_authorize_url:
            on_authorize_url(f"https://openapi.longbridge.com/oauth2/authorize?client_id={client_id}")
        return trade

    client = LongbridgeReadOnlyClient(
        _settings(longbridge_auth="oauth", longbridge_client_id="cid-1"),
        open_oauth=open_oauth,
        on_authorize_url=urls.append,
    )
    summary = client.get_account_summary()
    assert urls == ["https://openapi.longbridge.com/oauth2/authorize?client_id=cid-1"]
    assert summary.extras["auth"] == "oauth"
    assert summary.cash == 80_000.0
    assert trade.balance_calls == 1


def test_oauth_login_persists_sdk_path_not_env() -> None:
    seen: list[str] = []

    def session(client_id: str, *, on_authorize_url=None, **_k):
        if on_authorize_url:
            on_authorize_url(f"https://example.test/authorize/{client_id}")
        return object(), object()

    client = LongbridgeReadOnlyClient(
        _settings(longbridge_auth="oauth", longbridge_client_id="cid-login"),
        open_oauth_session=session,
        on_authorize_url=seen.append,
    )
    result = client.login_oauth()
    assert result["client_id"] == "cid-login"
    assert result["auth"] == "oauth"
    assert result["token_store"] == str(oauth_token_store("cid-login"))
    assert "cid-login" in result["token_store"]
    assert seen == ["https://example.test/authorize/cid-login"]


def test_oauth_session_uses_from_oauth() -> None:
    calls: dict[str, object] = {}

    class FakeBuilder:
        def __init__(self, client_id: str) -> None:
            calls["client_id"] = client_id

        def build(self, on_open_url):
            on_open_url("https://openapi.longbridge.com/oauth2/authorize?client_id=fake")
            calls["oauth"] = object()
            return calls["oauth"]

    def from_oauth(oauth):
        calls["from_oauth"] = oauth
        return {"auth": "oauth"}

    from sec_analysis.brokers.longbridge.readonly_client import _open_oauth_session

    urls: list[str] = []
    oauth, config = _open_oauth_session(
        "cid-sdk",
        on_authorize_url=urls.append,
        builder_cls=FakeBuilder,
        config_from_oauth=from_oauth,
    )
    assert calls["client_id"] == "cid-sdk"
    assert calls["from_oauth"] is oauth
    assert config == {"auth": "oauth"}
    assert urls[0].startswith("https://openapi.longbridge.com/oauth2/authorize")


def test_oauth_missing_sdk_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "longbridge.openapi" or name.startswith("longbridge"):
            raise ImportError("no longbridge in test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    from sec_analysis.brokers.longbridge.readonly_client import _open_oauth_session

    with pytest.raises(ProviderConfigError, match="longbridge SDK"):
        _open_oauth_session("cid")


def test_readonly_safety() -> None:
    assert_no_order_methods(LongbridgeReadOnlyClient)
    assert_no_order_methods(LongbridgeReadOnlyClient(Settings(longbridge_mode="stub")))
    assert scan_broker_sources() == []


def test_sources_have_no_quote_session_or_write_api() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "sec_analysis" / "brokers" / "longbridge"
    blob = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for token in (
        "QuoteContext",
        "submit_order",
        "cancel_order",
        "replace_order",
        "place_order",
    ):
        assert token not in blob
    assert "account_balance" in blob
    assert "stock_positions" in blob
    assert "today_executions" in blob
    assert "history_executions" in blob


def test_default_mode_is_stub() -> None:
    assert Settings.model_fields["longbridge_mode"].default == "stub"
    assert Settings.model_fields["longbridge_auth"].default == "token"
    assert Settings.model_fields["broker_client"].default == "ibkr"
