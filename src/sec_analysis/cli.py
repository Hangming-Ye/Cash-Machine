"""Command-line entry: ``sec-analysis quote AAPL``, ``news``, ``account``."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderError
from sec_analysis.core.instrument import Market, resolve_instrument
from sec_analysis.providers.fundamentals_router import FundamentalsRouter
from sec_analysis.providers.news_router import NewsRouter
from sec_analysis.providers.registry import ProviderBundle, build_providers
from sec_analysis.providers.router import MarketDataRouter

app = typer.Typer(
    name="sec-analysis",
    help="Read-only securities analysis CLI. Never places or cancels orders.",
    no_args_is_help=True,
)
console = Console()


def _settings(*, broker: str | None = None) -> Settings:
    settings = Settings()
    if broker:
        settings = settings.model_copy(update={"broker_client": broker})
    return settings


def _bundle(*, broker: str | None = None) -> ProviderBundle:
    return build_providers(_settings(broker=broker))


def _instrument(symbol: str, market: str | None):
    return resolve_instrument(symbol, market=market)


def _fail(exc: Exception) -> None:
    console.print(f"[red]{exc}[/red]")
    raise typer.Exit(code=1) from exc


@app.command()
def quote(
    symbol: str = typer.Argument(
        ..., help="Ticker, e.g. AAPL, 600519, 000001.SZ, sh600519, 00700.HK"
    ),
    market: str | None = typer.Option(
        None, "--market", "-m", help="US, CN, HK, JP, KR (do not assume US)"
    ),
) -> None:
    """Print a quote via the market router (Finnhub US/HK, AKShare CN)."""
    inst = _instrument(symbol, market)
    try:
        q = _bundle().market_data.get_quote(inst)
    except ProviderError as exc:
        _fail(exc)
    table = Table(title=f"Quote {q.symbol}  {q.market} ({q.source})")
    table.add_column("Field")
    table.add_column("Value")
    for label, value in [
        ("market", q.market),
        ("mic", q.mic),
        ("last", q.last),
        ("bid", q.bid),
        ("ask", q.ask),
        ("open", q.open),
        ("high", q.high),
        ("low", q.low),
        ("prev close", q.previous_close),
        ("volume", q.volume),
        ("currency", q.currency),
        ("as of", q.as_of.isoformat()),
    ]:
        table.add_row(label, "—" if value is None else str(value))
    console.print(table)


@app.command()
def bars(
    symbol: str = typer.Argument(..., help="Ticker"),
    market: str | None = typer.Option(None, "--market", "-m"),
    interval: str = typer.Option("1d", help="1m, 5m, 1h, 1d, 1w"),
    limit: int = typer.Option(5, min=1, max=500),
) -> None:
    """Print recent OHLCV bars (US daily → Tiingo; CN daily → AKShare)."""
    inst = _instrument(symbol, market)
    try:
        rows = _bundle().market_data.get_bars(inst, interval=interval, limit=limit)
    except ProviderError as exc:
        _fail(exc)
    if not rows:
        console.print(f"No bars for {inst.display()}")
        raise typer.Exit(code=1)
    table = Table(title=f"Bars {inst.display()} {interval}  {rows[0].market} ({rows[0].source})")
    for col in ("time", "open", "high", "low", "close", "volume"):
        table.add_column(col)
    for bar in rows:
        table.add_row(
            bar.timestamp.isoformat(),
            str(bar.open),
            str(bar.high),
            str(bar.low),
            str(bar.close),
            str(bar.volume),
        )
    console.print(table)


def _print_news(items: list, title: str) -> None:
    if not items:
        console.print("No news items.")
        raise typer.Exit(code=0)
    table = Table(title=title)
    table.add_column("when")
    table.add_column("headline")
    table.add_column("source")
    for item in items:
        table.add_row(item.published_at.isoformat(), item.headline, item.source)
    console.print(table)


@app.command()
def news(
    symbol: str | None = typer.Option(
        None, "--symbol", "-s", help="Company ticker; omit for Finnhub general news"
    ),
    market: str | None = typer.Option(
        None, "--market", "-m", help="US, CN, HK, JP, KR (do not assume US)"
    ),
    limit: int = typer.Option(5, min=1, max=50),
) -> None:
    """Finnhub general news, or company news when --symbol is set.

    A-shares: ``news --market CN --symbol 600519`` (AKShare ``stock_news_em``).
    Same path: ``company-news 600519``. US/HK stay on Finnhub.
    """
    try:
        if symbol:
            inst = _instrument(symbol, market)
            items = _bundle().news.get_company_news(inst.display(), limit=limit)
            source = items[0].source if items else "news"
            _print_news(items, f"Company news {inst.display()} ({source})")
            return
        if market and str(market).upper() == "CN":
            raise ProviderError(
                "CN news via AKShare needs a symbol. "
                "Example: sec-analysis news --market CN --symbol 600519"
            )
        items = _bundle().news.get_news(None, limit=limit)
    except ProviderError as exc:
        _fail(exc)
    source = items[0].source if items else "finnhub"
    _print_news(items, f"General news ({source})")


@app.command("company-news")
def company_news(
    symbol: str = typer.Argument(..., help="Ticker, e.g. AAPL or 600519"),
    market: str | None = typer.Option(
        None, "--market", "-m", help="US, CN, HK (A-shares → AKShare)"
    ),
    limit: int = typer.Option(5, min=1, max=50),
) -> None:
    """Company news. CN A-shares use AKShare; US/HK use Finnhub."""
    inst = _instrument(symbol, market)
    try:
        items = _bundle().news.get_company_news(inst.display(), limit=limit)
    except ProviderError as exc:
        _fail(exc)
    source = items[0].source if items else "news"
    _print_news(items, f"Company news {inst.display()} ({source})")


@app.command()
def fundamentals(
    symbol: str = typer.Argument(..., help="Ticker, e.g. AAPL or 600519"),
    market: str | None = typer.Option(
        None, "--market", "-m", help="US, CN, HK (A-share 财报 → AKShare Sina)"
    ),
    statement: str | None = typer.Option(
        None,
        "--statement",
        "-s",
        help="income|balance|cash or 利润表|资产负债表|现金流量表",
    ),
    periods: int = typer.Option(4, "--periods", min=1, max=16),
) -> None:
    """US snapshot/statements via FMP, or CN 财报 via AKShare Sina."""
    inst = _instrument(symbol, market)
    bundle = _bundle()
    try:
        if statement or inst.market is Market.CN:
            kind = statement or "income"
            report = bundle.fundamentals.get_statement(
                inst.display(), statement=kind, limit_periods=periods
            )
            _print_statement(report)
            return
        snap = bundle.fundamentals.get_fundamentals(inst.display())
    except ProviderError as exc:
        _fail(exc)
    table = Table(title=f"Fundamentals {snap.symbol}  ({snap.source})")
    table.add_column("Field")
    table.add_column("Value")
    for label, value in [
        ("name", snap.name),
        ("sector", snap.sector),
        ("industry", snap.industry),
        ("market cap", snap.market_cap),
        ("P/E", snap.pe_ratio),
        ("EPS", snap.eps),
        ("as of", snap.as_of.isoformat()),
    ]:
        table.add_row(label, "—" if value is None else str(value))
    console.print(table)


def _print_statement(report) -> None:
    if getattr(report, "source", "") == "fmp":
        title = f"FMP {report.statement.value} {report.symbol} ({report.source})"
    else:
        title = (
            f"{report.sina_symbol} {report.sina_stock}  {report.statement.value} ({report.source})"
        )
    table = Table(title=title)
    table.add_column("item")
    for period in report.periods:
        table.add_column(period, justify="right")
    if not report.lines:
        console.print(f"No statement rows for {report.symbol}")
        raise typer.Exit(code=1)
    for line in report.lines:
        table.add_row(
            line.label,
            *[
                "—" if period not in line.values else str(line.values[period])
                for period in report.periods
            ],
        )
    console.print(table)
    if report.as_of:
        console.print(f"Latest period {report.as_of.isoformat()}  currency={report.currency}")


@app.command("statements")
def statements(
    symbol: str = typer.Argument(..., help="A-share ticker, e.g. 600519 or 000001.SZ"),
    market: str | None = typer.Option(None, "--market", "-m", help="Force CN if needed"),
    statement: str = typer.Option(
        "income",
        "--statement",
        "-s",
        help="income|balance|cash or 利润表|资产负债表|现金流量表",
    ),
    periods: int = typer.Option(4, "--periods", min=1, max=16),
) -> None:
    """Print a CN financial statement via AKShare Sina (same path as fundamentals --statement)."""
    inst = _instrument(symbol, market or "CN")
    try:
        report = _bundle().fundamentals.get_statement(
            inst.display(), statement=statement, limit_periods=periods
        )
    except ProviderError as exc:
        _fail(exc)
    _print_statement(report)


@app.command("options")
def options_cmd(
    symbol: str = typer.Argument(..., help="Underlying ticker"),
) -> None:
    """Print a short option-chain snapshot (configured options provider; default stub)."""
    chain = _bundle().options.get_option_chain(symbol)
    console.print(
        f"[bold]{chain.symbol}[/bold] chain via {chain.source}  "
        f"expirations={len(chain.expirations)} contracts={len(chain.contracts)}"
    )
    table = Table()
    for col in ("expiry", "right", "strike", "last", "bid", "ask", "oi"):
        table.add_column(col)
    for c in chain.contracts[:12]:
        table.add_row(
            c.expiration.isoformat(),
            c.right,
            str(c.strike),
            "—" if c.last is None else str(c.last),
            "—" if c.bid is None else str(c.bid),
            "—" if c.ask is None else str(c.ask),
            "—" if c.open_interest is None else str(c.open_interest),
        )
    console.print(table)


@app.command("longbridge-login")
def longbridge_login() -> None:
    """Run Longbridge OAuth 2.0 login. Prints the authorize URL. Token stays on disk."""
    from sec_analysis.brokers.longbridge import LongbridgeReadOnlyClient

    settings = _settings(broker="longbridge")
    client = LongbridgeReadOnlyClient(
        settings,
        on_authorize_url=lambda url: console.print(
            f"[bold]Open this URL to authorize Longbridge:[/bold] {url}"
        ),
    )
    try:
        result = client.login_oauth()
    except ProviderError as exc:
        _fail(exc)
    console.print(
        f"OAuth client_id={result['client_id']}. "
        f"Token stored at [bold]{result['token_store']}[/bold] "
        "(SDK default — do not copy it into .env)."
    )
    console.print(
        "Read-only next: [bold]sec-analysis account --broker longbridge[/bold] "
        "with LONGBRIDGE_MODE=live."
    )


@app.command()
def account(
    broker: str | None = typer.Option(
        None,
        "--broker",
        "-b",
        help="ibkr | longbridge | stub (default: BROKER_CLIENT)",
    ),
) -> None:
    """Print a read-only account snapshot (IBKR or Longbridge). Never trades."""
    bundle = _bundle(broker=broker)
    broker = bundle.broker
    try:
        summary = broker.get_account_summary()
        positions = broker.get_positions()
    except ProviderError as exc:
        _fail(exc)
    table = Table(title=f"Account {summary.account_id}  ({broker.name})")
    table.add_column("Field")
    table.add_column("Value")
    extras = summary.extras or {}
    mode = extras.get("ibkr_mode") or extras.get("mode") or broker.name
    for label, value in [
        ("connected", broker.is_connected()),
        ("mode", mode),
        ("net liq", summary.net_liquidation),
        ("cash", summary.cash),
        ("buying power", summary.buying_power),
        ("gross positions", summary.gross_position_value),
        ("currency", summary.currency),
        ("as of", summary.as_of.isoformat()),
        ("note", extras.get("note")),
    ]:
        if value is None:
            continue
        table.add_row(label, str(value))
    console.print(table)
    if positions:
        pos_table = Table(title="Positions (read-only)")
        for col in ("symbol", "qty", "avg cost", "mkt", "value", "uPnL"):
            pos_table.add_column(col)
        for p in positions:
            pos_table.add_row(
                p.symbol,
                str(p.quantity),
                "—" if p.average_cost is None else str(p.average_cost),
                "—" if p.market_price is None else str(p.market_price),
                "—" if p.market_value is None else str(p.market_value),
                "—" if p.unrealized_pnl is None else str(p.unrealized_pnl),
            )
        console.print(pos_table)
    if broker.name == "longbridge":
        console.print(
            "Fills: [bold]sec-analysis executions --broker longbridge[/bold]. "
            "Past days: [bold]sec-analysis executions --broker longbridge --history[/bold]."
        )
    elif extras.get("ibkr_mode") == "flex":
        console.print(
            "IBKR phase-1 is Flex Web Service (T+1). "
            "Fills: [bold]sec-analysis executions --broker ibkr[/bold] "
            "or [bold]sec-analysis executions --flex[/bold]."
        )
    else:
        console.print(
            "Session fills: [bold]sec-analysis executions[/bold]. "
            "Flex Activity (T+1, recommended): [bold]sec-analysis executions --flex[/bold]."
        )


@app.command()
def executions(
    broker: str | None = typer.Option(
        None, "--broker", "-b", help="ibkr | longbridge | stub"
    ),
    flex: bool = typer.Option(
        False,
        "--flex",
        help="IBKR Activity Flex Query history (typical T+1). Not Longbridge.",
    ),
    history: bool = typer.Option(
        False,
        "--history",
        help="Longbridge history_executions (past fills). Not IBKR Flex.",
    ),
) -> None:
    """Print read-only fills. Session/day by default."""
    if flex and history:
        _fail(ProviderError("Use --flex (IBKR) or --history (Longbridge), not both."))
    bundle = _bundle(broker=broker)
    try:
        if flex:
            fills = bundle.flex.get_activity_executions()
        elif history:
            if bundle.broker.name != "longbridge":
                raise ProviderError(
                    "--history is Longbridge-only. For IBKR long history use --flex."
                )
            fills = bundle.broker.get_executions(history=True)  # type: ignore[call-arg]
        else:
            fills = bundle.broker.get_executions()
    except ProviderError as exc:
        _fail(exc)
    title = "Flex Activity executions (T+1)" if flex else "Session executions"
    if not fills:
        console.print(f"No rows for {title}.")
        raise typer.Exit(code=0)
    table = Table(title=title)
    for col in ("id", "when", "symbol", "side", "qty", "price"):
        table.add_column(col)
    for fill in fills:
        table.add_row(
            fill.execution_id,
            fill.executed_at.isoformat(),
            fill.symbol,
            fill.side,
            str(fill.quantity),
            str(fill.price),
        )
    console.print(table)
    if flex:
        console.print("Typical Flex delay is T+1. Same-day trades use the session blotter.")


@app.command()
def providers() -> None:
    """Show configured names vs resolved implementations."""
    settings = Settings()
    bundle = build_providers(settings)
    table = Table(title="Phase-1 providers (Finnhub quotes/news + Tiingo US bars + FMP + AKShare)")
    table.add_column("slot")
    table.add_column("config")
    table.add_column("implementation")
    table.add_row("market_data", settings.market_data_provider, bundle.market_data.name)
    table.add_row("fundamentals", settings.fundamentals_provider, bundle.fundamentals.name)
    table.add_row("options", settings.options_provider, bundle.options.name)
    table.add_row("news", settings.news_provider, bundle.news.name)
    table.add_row("broker", settings.broker_client, bundle.broker.name)
    table.add_row("flex", "ibkr-flex (phase-1 recommended, T+1)", bundle.flex.name)
    console.print(table)
    md = bundle.market_data
    if isinstance(md, MarketDataRouter):
        routes = Table(title="Market-data routes")
        routes.add_column("market")
        routes.add_column("ordered adapters")
        for key, names in md.route_names().items():
            routes.add_row(key, ", ".join(names))
        console.print(routes)
        console.print(
            "CN A-shares default to AKShare (East Money scrape). "
            "US/HK quotes use Finnhub. US daily bars use HISTORY_ROUTE_US=tiingo. "
            "Override with MARKET_DATA_ROUTE_* / HISTORY_ROUTE_*."
        )
        history = Table(title="History / OHLCV routes")
        history.add_column("market")
        history.add_column("ordered adapters")
        for key, names in md.history_route_names().items():
            history.add_row(key, ", ".join(names))
        console.print(history)
    news = bundle.news
    if isinstance(news, NewsRouter):
        routes = Table(title="News routes")
        routes.add_column("market")
        routes.add_column("adapter")
        for key, names in news.route_names().items():
            routes.add_row(key, ", ".join(names))
        console.print(routes)
        console.print(
            "CN company news: AKShare stock_news_em. "
            "CN 财报: AKShare stock_financial_report_sina. "
            "US statements: FMP income|balance|cash. "
            "General / US / HK news: Finnhub. "
            "Account: --broker ibkr|longbridge (read-only)."
        )
    fundamentals = bundle.fundamentals
    if isinstance(fundamentals, FundamentalsRouter):
        routes = Table(title="Fundamentals routes")
        routes.add_column("market")
        routes.add_column("adapter")
        for key, names in fundamentals.route_names().items():
            routes.add_row(key, ", ".join(names))
        console.print(routes)


@app.command()
def routes() -> None:
    """Show per-market market-data provider chains (you choose the order)."""
    providers()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
