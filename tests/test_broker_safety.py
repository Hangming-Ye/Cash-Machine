from __future__ import annotations

import pytest

from sec_analysis.brokers.ibkr.flex import IbkrFlexReadOnlyClient
from sec_analysis.brokers.ibkr.readonly_client import TWS_READONLY, IbkrReadOnlyClient
from sec_analysis.brokers.ibkr.safety import (
    assert_broker_tree_is_read_only,
    assert_no_order_methods,
    public_callables,
    scan_broker_sources,
)
from sec_analysis.brokers.longbridge import LongbridgeReadOnlyClient
from sec_analysis.config import Settings
from sec_analysis.core.errors import BrokerReadOnlyError, ProviderConfigError
from sec_analysis.core.interfaces import BrokerReadOnlyClient, FlexActivityReadOnlyClient
from sec_analysis.providers.stub import StubBrokerReadOnlyClient


def test_broker_readonly_client_has_no_order_related_public_methods() -> None:
    names = {n.lower() for n in public_callables(BrokerReadOnlyClient)}
    forbidden_needles = (
        "place",
        "cancel",
        "modify",
        "submit",
        "create_order",
        "send_order",
        "order",
    )
    offenders = [n for n in names if any(needle in n for needle in forbidden_needles)]
    assert offenders == [], f"BrokerReadOnlyClient grew order-related methods: {offenders}"
    assert "get_account_summary" in names
    assert "get_positions" in names
    assert "get_executions" in names
    assert "is_connected" in names
    flex_names = {n.lower() for n in public_callables(FlexActivityReadOnlyClient)}
    flex_offenders = [n for n in flex_names if any(needle in n for needle in forbidden_needles)]
    assert flex_offenders == [], f"Flex client grew order-related methods: {flex_offenders}"
    assert TWS_READONLY is True
    assert IbkrReadOnlyClient.TWS_READONLY is True


def test_implementations_pass_safety_guard() -> None:
    assert_no_order_methods(BrokerReadOnlyClient)
    assert_no_order_methods(FlexActivityReadOnlyClient)
    assert_no_order_methods(IbkrReadOnlyClient)
    assert_no_order_methods(IbkrFlexReadOnlyClient)
    assert_no_order_methods(StubBrokerReadOnlyClient)
    assert_no_order_methods(LongbridgeReadOnlyClient)
    assert_no_order_methods(IbkrReadOnlyClient(Settings(ibkr_gateway_mode="stub")))
    assert_no_order_methods(LongbridgeReadOnlyClient(Settings(longbridge_mode="stub")))
    assert_broker_tree_is_read_only()
    assert scan_broker_sources() == []


def test_safety_rejects_place_order_lookalike() -> None:
    class EvilReadOnlyClient:
        def place_order(self) -> None:  # noqa: D102
            return None

    with pytest.raises(BrokerReadOnlyError):
        assert_no_order_methods(EvilReadOnlyClient)


def test_safety_rejects_class_not_named_readonly() -> None:
    class TradingClient:
        def get_positions(self) -> list:
            return []

    with pytest.raises(BrokerReadOnlyError, match="ReadOnly"):
        assert_no_order_methods(TradingClient)


def test_ibkr_live_modes_are_explicit_todos() -> None:
    portal = IbkrReadOnlyClient(Settings(ibkr_gateway_mode="client_portal"))
    with pytest.raises(ProviderConfigError, match="Client Portal"):
        portal.connect()
    tws = IbkrReadOnlyClient(Settings(ibkr_gateway_mode="tws"))
    with pytest.raises(ProviderConfigError, match="TWS"):
        tws.connect()


def test_ibkr_stub_mode_does_not_invent_balances() -> None:
    client = IbkrReadOnlyClient(Settings(ibkr_gateway_mode="stub", ibkr_account_id="DU123"))
    with pytest.raises(ProviderConfigError, match="does not invent"):
        client.connect()
    with pytest.raises(ProviderConfigError, match="does not invent"):
        client.get_account_summary()
    with pytest.raises(ProviderConfigError, match="does not invent"):
        client.get_positions()
    with pytest.raises(ProviderConfigError, match="does not invent"):
        client.get_executions()
    with pytest.raises(ProviderConfigError, match="does not invent"):
        client.get_flex_executions()
