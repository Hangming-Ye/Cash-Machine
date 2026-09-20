from __future__ import annotations

from typer.testing import CliRunner

from sec_analysis.cli import app

runner = CliRunner()


def test_cli_quote_against_stub() -> None:
    result = runner.invoke(app, ["quote", "AAPL"])
    assert result.exit_code == 0, result.output
    assert "AAPL" in result.output
    assert "stub" in result.output


def test_cli_quote_china_symbol() -> None:
    result = runner.invoke(app, ["quote", "600519.SH"])
    assert result.exit_code == 0, result.output
    assert "CN" in result.output
    assert "XSHG" in result.output
    assert "CNY" in result.output


def test_cli_quote_and_bars_cn_via_akshare(monkeypatch) -> None:
    from sec_analysis.core.rate_limit import RateLimiter

    monkeypatch.setenv("MARKET_DATA_ROUTE_CN", "akshare")
    monkeypatch.setenv("HISTORY_ROUTE_CN", "akshare")
    def _limiter(*_a, **_k):
        return RateLimiter(calls_per_minute=10_000, min_interval=0, sleeper=lambda _: None)

    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client.RateLimiter",
        _limiter,
    )
    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client._default_spot",
        lambda code: [{"item": "最新", "value": 1688.0, "成交量": 100}],
    )
    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client._default_hist",
        lambda code, *, start_date, end_date: [
            {
                "日期": "2024-06-01",
                "开盘": 1600,
                "最高": 1700,
                "最低": 1590,
                "收盘": 1688,
                "成交量": 2000,
            }
        ],
    )
    quoted = runner.invoke(app, ["quote", "600519"])
    assert quoted.exit_code == 0, quoted.output
    assert "akshare" in quoted.output
    assert "1688" in quoted.output
    bars = runner.invoke(app, ["bars", "sh600519", "--limit", "1"])
    assert bars.exit_code == 0, bars.output
    assert "akshare" in bars.output
    assert "1688" in bars.output


def test_cli_news_against_stub() -> None:
    result = runner.invoke(app, ["news", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "headline" in result.output.lower() or "MARKET" in result.output


def test_cli_company_news_against_stub() -> None:
    result = runner.invoke(app, ["company-news", "AAPL", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "AAPL" in result.output


def test_cli_cn_company_news_via_akshare(monkeypatch) -> None:
    from sec_analysis.core.rate_limit import RateLimiter

    monkeypatch.setenv("NEWS_ROUTE_CN", "akshare")

    def _limiter(*_a, **_k):
        return RateLimiter(calls_per_minute=10_000, min_interval=0, sleeper=lambda _: None)

    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.news.RateLimiter",
        _limiter,
    )
    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.news._default_stock_news",
        lambda code: [
            {
                "新闻标题": f"{code} fixture headline",
                "发布时间": "2024-06-15 10:00:00",
                "文章来源": "akshare-test",
            }
        ],
    )
    via_cmd = runner.invoke(app, ["company-news", "600519", "--limit", "1"])
    assert via_cmd.exit_code == 0, via_cmd.output
    assert "600519" in via_cmd.output
    assert "fixture headline" in via_cmd.output
    via_flag = runner.invoke(
        app, ["news", "--market", "CN", "--symbol", "000001", "--limit", "1"]
    )
    assert via_flag.exit_code == 0, via_flag.output
    assert "000001" in via_flag.output
    assert "fixture headline" in via_flag.output


def test_cli_news_cn_without_symbol_is_clear() -> None:
    result = runner.invoke(app, ["news", "--market", "CN"])
    assert result.exit_code != 0
    assert "symbol" in result.output.lower()


def test_cli_cn_fundamentals_via_akshare(monkeypatch) -> None:
    from sec_analysis.core.rate_limit import RateLimiter

    monkeypatch.setenv("FUNDAMENTALS_ROUTE_CN", "akshare")

    def _limiter(*_a, **_k):
        return RateLimiter(calls_per_minute=10_000, min_interval=0, sleeper=lambda _: None)

    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.fundamentals.RateLimiter",
        _limiter,
    )

    def fetch(stock: str, *, symbol: str):
        return [
            {
                "报告日": "营业收入" if symbol == "利润表" else "资产总计",
                "20231231": 100.0,
                "20221231": 90.0,
            }
        ]

    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.fundamentals._default_report",
        fetch,
    )
    income = runner.invoke(app, ["fundamentals", "600519", "--statement", "income"])
    assert income.exit_code == 0, income.output
    assert "利润表" in income.output
    assert "sh600519" in income.output
    assert "100" in income.output
    chinese = runner.invoke(app, ["fundamentals", "sz000001", "-s", "资产负债表"])
    assert chinese.exit_code == 0, chinese.output
    assert "资产负债表" in chinese.output
    assert "sz000001" in chinese.output
    alias = runner.invoke(app, ["statements", "600519", "-s", "income"])
    assert alias.exit_code == 0, alias.output
    assert "利润表" in alias.output
    assert "sh600519" in alias.output


def test_cli_quote_without_finnhub_key_is_clear(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "finnhub")
    monkeypatch.setenv("MARKET_DATA_ROUTE_US", "finnhub")
    monkeypatch.setenv("MARKET_DATA_ROUTE_DEFAULT", "finnhub")
    monkeypatch.setenv("FINNHUB_API_KEY", "")
    result = runner.invoke(app, ["quote", "AAPL", "--market", "US"])
    assert result.exit_code != 0
    assert "FINNHUB_API_KEY" in result.output


def test_cli_account_against_stub() -> None:
    result = runner.invoke(app, ["account"])
    assert result.exit_code == 0, result.output
    assert "Account" in result.output
    assert "AAPL" in result.output
    assert "stub" in result.output.lower()


def test_cli_account_longbridge_needs_credentials() -> None:
    result = runner.invoke(app, ["account", "--broker", "longbridge"])
    assert result.exit_code != 0
    assert "LONGBRIDGE_APP_KEY" in result.output or "longbridge-login" in result.output
    assert "250000" not in result.output
    assert "700.HK" not in result.output
    fills = runner.invoke(app, ["executions", "--broker", "longbridge"])
    assert fills.exit_code != 0
    assert "does not invent" in fills.output


def test_cli_longbridge_login_prints_authorize_url(monkeypatch) -> None:
    from sec_analysis.brokers.longbridge import LongbridgeReadOnlyClient

    monkeypatch.setenv("LONGBRIDGE_CLIENT_ID", "cid-cli")
    monkeypatch.setenv("LONGBRIDGE_AUTH", "oauth")

    def fake_login(self, *, on_authorize_url=None):
        callback = on_authorize_url or getattr(self, "_on_authorize_url", None)
        if callback:
            callback("https://openapi.longbridge.com/oauth2/authorize?client_id=cid-cli")
        return {
            "client_id": "cid-cli",
            "token_store": "/home/user/.longbridge/openapi/tokens/cid-cli",
            "auth": "oauth",
        }

    monkeypatch.setattr(LongbridgeReadOnlyClient, "login_oauth", fake_login)
    result = runner.invoke(app, ["longbridge-login"])
    assert result.exit_code == 0, result.output
    assert "openapi.longbridge.com/oauth2/authorize" in result.output
    assert "cid-cli" in result.output
    assert ".longbridge/openapi/tokens" in result.output
    assert "do not copy" in result.output.lower() or "not" in result.output.lower()


def test_cli_longbridge_login_needs_client_id(monkeypatch) -> None:
    monkeypatch.setenv("LONGBRIDGE_CLIENT_ID", "")
    result = runner.invoke(app, ["longbridge-login"])
    assert result.exit_code != 0
    assert "LONGBRIDGE_CLIENT_ID" in result.output


def test_cli_us_bars_via_tiingo(monkeypatch) -> None:
    import httpx
    import respx

    from sec_analysis.providers.tiingo.client import TIINGO_BASE_URL

    monkeypatch.setenv("HISTORY_ROUTE_US", "tiingo")
    monkeypatch.setenv("HISTORY_ROUTE_DEFAULT", "tiingo")
    monkeypatch.setenv("TIINGO_API_KEY", "tiingo-test-key")
    with respx.mock:
        respx.get(f"{TIINGO_BASE_URL}/tiingo/daily/AAPL/prices").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "date": "2024-06-14T00:00:00.000Z",
                        "open": 211.0,
                        "high": 214.0,
                        "low": 210.5,
                        "close": 213.4,
                        "volume": 51_200_000,
                    }
                ],
            )
        )
        result = runner.invoke(app, ["bars", "AAPL", "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert "tiingo" in result.output
    assert "213.4" in result.output


def test_cli_us_bars_missing_tiingo_key(monkeypatch) -> None:
    monkeypatch.setenv("HISTORY_ROUTE_US", "tiingo")
    monkeypatch.setenv("HISTORY_ROUTE_DEFAULT", "tiingo")
    monkeypatch.setenv("TIINGO_API_KEY", "")
    result = runner.invoke(app, ["bars", "AAPL", "--market", "US", "--limit", "1"])
    assert result.exit_code != 0
    assert "TIINGO_API_KEY" in result.output


def test_cli_us_fundamentals_via_fmp(monkeypatch) -> None:
    import httpx
    import respx

    from sec_analysis.providers.fmp.client import FMP_BASE_URL

    monkeypatch.setenv("FUNDAMENTALS_ROUTE_US", "fmp")
    monkeypatch.setenv("FUNDAMENTALS_ROUTE_DEFAULT", "fmp")
    monkeypatch.setenv("FMP_API_KEY", "fmp-test-key")
    with respx.mock:
        respx.get(f"{FMP_BASE_URL}/stable/income-statement").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "date": "2024-09-28",
                        "reportedCurrency": "USD",
                        "revenue": 391_035_000_000,
                        "netIncome": 93_736_000_000,
                    }
                ],
            )
        )
        respx.get(f"{FMP_BASE_URL}/stable/balance-sheet-statement").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "date": "2024-09-28",
                        "totalAssets": 364_980_000_000,
                        "reportedCurrency": "USD",
                    }
                ],
            )
        )
        respx.get(f"{FMP_BASE_URL}/stable/cash-flow-statement").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "date": "2024-09-28",
                        "operatingCashFlow": 118_254_000_000,
                        "reportedCurrency": "USD",
                    }
                ],
            )
        )
        income = runner.invoke(app, ["fundamentals", "AAPL", "--statement", "income"])
        balance = runner.invoke(app, ["fundamentals", "AAPL", "-s", "balance"])
        cash = runner.invoke(app, ["fundamentals", "AAPL", "--statement", "cash"])
    assert income.exit_code == 0, income.output
    assert "fmp" in income.output
    assert "391035000000" in income.output
    assert balance.exit_code == 0, balance.output
    assert "364980000000" in balance.output
    assert cash.exit_code == 0, cash.output
    assert "118254000000" in cash.output


def test_cli_us_fundamentals_missing_fmp_key(monkeypatch) -> None:
    monkeypatch.setenv("FUNDAMENTALS_ROUTE_US", "fmp")
    monkeypatch.setenv("FUNDAMENTALS_ROUTE_DEFAULT", "fmp")
    monkeypatch.setenv("FMP_API_KEY", "")
    result = runner.invoke(app, ["fundamentals", "AAPL", "--statement", "income"])
    assert result.exit_code != 0
    assert "FMP_API_KEY" in result.output


def test_cli_ibkr_account_without_flex_token_is_config_error(monkeypatch) -> None:
    monkeypatch.setenv("BROKER_CLIENT", "ibkr")
    monkeypatch.setenv("BROKER_IBKR_MODE", "flex")
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "")
    account = runner.invoke(app, ["account", "--broker", "ibkr"])
    assert account.exit_code != 0
    assert "Flex" in account.output or "IBKR_FLEX" in account.output
    assert "250000" not in account.output
    fills = runner.invoke(app, ["executions", "--broker", "ibkr"])
    assert fills.exit_code != 0
    assert "does not invent" in fills.output or "IBKR_FLEX" in fills.output


def test_cli_ibkr_account_via_flex(monkeypatch) -> None:
    import httpx
    import respx

    from sec_analysis.brokers.ibkr.flex import FLEX_BASE_URL

    send_ok = (
        "<FlexStatementResponse><Status>Success</Status>"
        "<ReferenceCode>9876543210</ReferenceCode></FlexStatementResponse>"
    )
    statement = (
        "<FlexQueryResponse><FlexStatements>"
        '<FlexStatement accountId="U1234567" whenGenerated="20240615;200000">'
        '<AccountInformation accountId="U1234567" currency="USD"/>'
        '<CashReportCurrency currency="USD" endingCash="25000.5" netLiquidation="100000"/>'
        '<OpenPosition symbol="AAPL" position="50" markPrice="190.1" currency="USD"'
        ' accountId="U1234567" assetCategory="STK"/>'
        '<Trade tradeID="tr-1" symbol="AAPL" buySell="BUY" quantity="10"'
        ' tradePrice="189.5" dateTime="20240614;153000" currency="USD"/>'
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )

    monkeypatch.setenv("BROKER_CLIENT", "ibkr")
    monkeypatch.setenv("BROKER_IBKR_MODE", "flex")
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "flex-token")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "800969")
    with respx.mock:
        respx.get(f"{FLEX_BASE_URL}/SendRequest").mock(
            return_value=httpx.Response(200, text=send_ok)
        )
        respx.get(f"{FLEX_BASE_URL}/GetStatement").mock(
            return_value=httpx.Response(200, text=statement)
        )
        account = runner.invoke(app, ["account", "--broker", "ibkr"])
        fills = runner.invoke(app, ["executions", "--broker", "ibkr"])
    assert account.exit_code == 0, account.output
    assert "flex" in account.output.lower()
    assert "U1234567" in account.output
    assert "AAPL" in account.output
    assert "25000" in account.output
    assert fills.exit_code == 0, fills.output
    assert "tr-1" in fills.output


def test_cli_providers_and_bars() -> None:
    shown = runner.invoke(app, ["providers"])
    assert shown.exit_code == 0, shown.output
    assert "market_data" in shown.output
    assert "ROUTE" in shown.output or "CN" in shown.output
    bars = runner.invoke(app, ["bars", "MSFT", "--limit", "2"])
    assert bars.exit_code == 0, bars.output
    fund = runner.invoke(app, ["fundamentals", "IBM"])
    assert fund.exit_code == 0, fund.output
    opts = runner.invoke(app, ["options", "AAPL"])
    assert opts.exit_code == 0, opts.output
    session = runner.invoke(app, ["executions"])
    assert session.exit_code == 0, session.output
    flex = runner.invoke(app, ["executions", "--flex"])
    assert flex.exit_code != 0
    assert "does not invent" in flex.output or "IBKR_FLEX" in flex.output
