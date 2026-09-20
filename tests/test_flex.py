from __future__ import annotations

import httpx
import pytest
import respx

from sec_analysis.brokers.ibkr.flex import FLEX_BASE_URL, FLEX_T_PLUS_1_NOTE, IbkrFlexReadOnlyClient
from sec_analysis.brokers.ibkr.readonly_client import IbkrReadOnlyClient
from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.interfaces import FlexActivityReadOnlyClient

SEND_OK = """
<FlexStatementResponse timestamp="15 June, 2024 10:00 AM EDT">
  <Status>Success</Status>
  <ReferenceCode>9876543210</ReferenceCode>
  <Url>https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url>
</FlexStatementResponse>
"""

PENDING = """
<FlexStatementResponse>
  <Status>Warn</Status>
  <ErrorCode>1019</ErrorCode>
  <ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage>
</FlexStatementResponse>
"""

STATEMENT = """
<FlexQueryResponse queryName="Activity" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="20240601"
                   toDate="20240614" whenGenerated="20240615;200000">
      <AccountInformation accountId="U1234567" currency="USD" name="Demo" />
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD"
                            endingCash="25000.5" netLiquidation="100000" />
      </CashReport>
      <OpenPositions>
        <OpenPosition accountId="U1234567" symbol="AAPL" position="50"
                      markPrice="190.1" costBasisPrice="150"
                      fifoPnlUnrealized="2005" positionValue="9505"
                      currency="USD" assetCategory="STK" />
      </OpenPositions>
      <Trades>
        <Trade accountId="U1234567" symbol="AAPL" tradeID="tr-1"
               buySell="BUY" quantity="10" tradePrice="189.5"
               dateTime="20240614;153000" ibCommission="-1.0"
               currency="USD" />
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

CSV_TRADES = (
    "TradeID,Symbol,Buy/Sell,Quantity,TradePrice,DateTime,Currency,AccountId\n"
    "tr-csv,MSFT,SELL,5,420.0,20240614;120000,USD,U1\n"
)


def _settings(**kwargs) -> Settings:
    data = {
        "ibkr_flex_token": "flex-token",
        "ibkr_flex_query_id": "800969",
        "broker_ibkr_mode": "flex",
        "ibkr_gateway_mode": "stub",
    }
    data.update(kwargs)
    return Settings(**data)


def _client(settings: Settings | None = None) -> IbkrFlexReadOnlyClient:
    return IbkrFlexReadOnlyClient(
        settings or _settings(),
        client=httpx.Client(timeout=5.0),
        sleeper=lambda _s: None,
        poll_attempts=3,
        poll_interval=0,
    )


def test_flex_stub_without_secrets() -> None:
    client = IbkrFlexReadOnlyClient(Settings(ibkr_gateway_mode="stub", ibkr_account_id="DU9"))
    assert isinstance(client, FlexActivityReadOnlyClient)
    assert client.is_configured() is False
    with pytest.raises(ProviderConfigError, match="does not invent"):
        client.get_activity_executions()
    assert "T+1" in FLEX_T_PLUS_1_NOTE


def test_flex_live_without_token_explains_setup() -> None:
    client = IbkrFlexReadOnlyClient(Settings(broker_ibkr_mode="flex"))
    with pytest.raises(ProviderConfigError, match="Activity Flex Query"):
        client.get_activity_executions()


@respx.mock
def test_flex_send_poll_and_parse_xml() -> None:
    respx.get(f"{FLEX_BASE_URL}/SendRequest").mock(return_value=httpx.Response(200, text=SEND_OK))
    respx.get(f"{FLEX_BASE_URL}/GetStatement").mock(
        side_effect=[
            httpx.Response(200, text=PENDING),
            httpx.Response(200, text=STATEMENT),
        ]
    )
    client = _client()
    summary = client.get_account_summary()
    assert summary.account_id == "U1234567"
    assert summary.cash == 25000.5
    assert summary.net_liquidation == 100000
    assert summary.extras["ibkr_mode"] == "flex"
    positions = client.get_positions()
    assert positions[0].symbol == "AAPL"
    assert positions[0].quantity == 50
    assert positions[0].market_price == 190.1
    fills = client.get_activity_executions()
    assert fills[0].execution_id == "tr-1"
    assert fills[0].side == "buy"
    assert fills[0].price == 189.5


@respx.mock
def test_flex_csv_statement() -> None:
    respx.get(f"{FLEX_BASE_URL}/SendRequest").mock(return_value=httpx.Response(200, text=SEND_OK))
    respx.get(f"{FLEX_BASE_URL}/GetStatement").mock(
        return_value=httpx.Response(200, text=CSV_TRADES)
    )
    fills = _client().get_activity_executions()
    assert fills[0].symbol == "MSFT"
    assert fills[0].side == "sell"
    assert fills[0].quantity == 5


@respx.mock
def test_flex_send_fail_is_clear() -> None:
    respx.get(f"{FLEX_BASE_URL}/SendRequest").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<FlexStatementResponse><Status>Fail</Status>"
                "<ErrorCode>1015</ErrorCode>"
                "<ErrorMessage>Token is invalid.</ErrorMessage></FlexStatementResponse>"
            ),
        )
    )
    with pytest.raises(ProviderError, match="1015"):
        _client().get_account_summary()


def test_broker_uses_flex_when_env_present() -> None:
    settings = _settings(broker_ibkr_mode="auto")
    assert settings.ibkr_use_flex() is True
    broker = IbkrReadOnlyClient(settings)
    broker.flex = _client(settings)
    with respx.mock:
        respx.get(f"{FLEX_BASE_URL}/SendRequest").mock(
            return_value=httpx.Response(200, text=SEND_OK)
        )
        respx.get(f"{FLEX_BASE_URL}/GetStatement").mock(
            return_value=httpx.Response(200, text=STATEMENT)
        )
        summary = broker.get_account_summary()
    assert summary.extras["ibkr_mode"] == "flex"
    assert broker.is_connected() is True


def test_broker_ibkr_mode_flex_without_token_is_config_error() -> None:
    client = IbkrReadOnlyClient(Settings(broker_ibkr_mode="flex", ibkr_gateway_mode="stub"))
    with pytest.raises(ProviderConfigError, match="IBKR_FLEX_TOKEN|Flex Web Service"):
        client.get_account_summary()


def test_gateway_mode_skips_flex_even_if_token_set() -> None:
    settings = _settings(broker_ibkr_mode="gateway")
    assert settings.ibkr_use_flex() is False
    client = IbkrReadOnlyClient(settings)
    with pytest.raises(ProviderConfigError, match="does not invent"):
        client.get_account_summary()


@respx.mock
def test_flex_poll_exhausted_does_not_invent() -> None:
    respx.get(f"{FLEX_BASE_URL}/SendRequest").mock(return_value=httpx.Response(200, text=SEND_OK))
    respx.get(f"{FLEX_BASE_URL}/GetStatement").mock(return_value=httpx.Response(200, text=PENDING))
    with pytest.raises(ProviderError, match="GetStatement attempts"):
        _client().get_account_summary()


def test_flex_query_id_overrides() -> None:
    settings = Settings(
        ibkr_flex_token="t",
        ibkr_flex_query_id="base",
        ibkr_flex_activity_query_id="act",
        ibkr_flex_position_query_id="pos",
    )
    assert settings.ibkr_flex_query_for("account") == "act"
    assert settings.ibkr_flex_query_for("positions") == "pos"
    assert settings.ibkr_flex_query_for("activity") == "act"
