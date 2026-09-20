"""Deterministic fake providers for tests and offline CLI smoke."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

from sec_analysis.core.instrument import SymbolRef, resolve_instrument
from sec_analysis.core.interfaces import (
    BrokerReadOnlyClient,
    FundamentalsProvider,
    MarketDataProvider,
    NewsProvider,
    OptionsProvider,
)
from sec_analysis.core.models import (
    AccountSummary,
    AssetType,
    Bar,
    Execution,
    Fundamental,
    NewsItem,
    OptionChain,
    OptionContract,
    Position,
    Quote,
)

SOURCE = "stub"


def _stable_int(seed: str, modulo: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulo


def stub_price(symbol: str) -> float:
    """Stable mid-style price in [50.00, 999.99]."""
    cents = _stable_int(symbol.upper(), 95000)
    return round(50.0 + cents / 100.0, 2)


class StubMarketDataProvider(MarketDataProvider):
    name = "stub"

    def get_quote(self, symbol: SymbolRef) -> Quote:
        inst = resolve_instrument(symbol)
        last = stub_price(inst.symbol)
        return Quote(
            symbol=inst.display(),
            last=last,
            bid=round(last - 0.05, 2),
            ask=round(last + 0.05, 2),
            open=round(last * 0.99, 2),
            high=round(last * 1.02, 2),
            low=round(last * 0.97, 2),
            previous_close=round(last * 0.995, 2),
            volume=float(1_000_000 + _stable_int(f"vol:{inst.symbol}", 9_000_000)),
            as_of=datetime(2024, 6, 15, 20, 0, tzinfo=UTC),
            source=SOURCE,
            market=inst.market,
            exchange=inst.exchange,
            mic=inst.mic,
            currency=inst.currency,
        )

    def get_bars(
        self,
        symbol: SymbolRef,
        *,
        interval: str = "1d",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        inst = resolve_instrument(symbol)
        end = end or datetime(2024, 6, 15, tzinfo=UTC)
        close = stub_price(inst.symbol)
        bars: list[Bar] = []
        count = max(1, min(limit, 500))
        if interval.endswith("d") or interval == "1w":
            step = timedelta(days=1)
        else:
            step = timedelta(hours=1)
        for i in range(count):
            ts = end - step * (count - 1 - i)
            drift = 1 + ((i % 7) - 3) * 0.004
            c = round(close * drift, 2)
            bars.append(
                Bar(
                    symbol=inst.display(),
                    timestamp=ts,
                    open=round(c * 0.998, 2),
                    high=round(c * 1.01, 2),
                    low=round(c * 0.99, 2),
                    close=c,
                    volume=float(800_000 + i * 1000),
                    interval=interval,
                    source=SOURCE,
                    market=inst.market,
                    mic=inst.mic,
                )
            )
        if start is not None:
            bars = [b for b in bars if b.timestamp >= start]
        return bars


class StubFundamentalsProvider(FundamentalsProvider):
    name = "stub"

    def get_fundamentals(self, symbol: SymbolRef) -> Fundamental:
        inst = resolve_instrument(symbol)
        last = stub_price(inst.symbol)
        return Fundamental(
            symbol=inst.display(),
            as_of=date(2024, 3, 31),
            name=f"{inst.symbol.upper()} Test Corp",
            sector="Technology",
            industry="Software",
            market_cap=round(last * 1_500_000_000, 2),
            pe_ratio=22.5,
            pb_ratio=6.1,
            eps=round(last / 22.5, 2),
            dividend_yield=0.012,
            revenue=48_000_000_000.0,
            net_income=12_000_000_000.0,
            source=SOURCE,
            market=inst.market,
            currency=inst.currency,
        )


class StubOptionsProvider(OptionsProvider):
    name = "stub"

    def get_option_chain(
        self,
        symbol: str,
        *,
        expiration: date | None = None,
    ) -> OptionChain:
        exp = expiration or date(2024, 9, 20)
        spot = stub_price(symbol)
        strikes = [round(spot * m, 0) for m in (0.9, 1.0, 1.1)]
        contracts: list[OptionContract] = []
        for strike in strikes:
            for right in ("call", "put"):
                contracts.append(
                    OptionContract(
                        symbol=symbol.upper(),
                        contract_symbol=f"{symbol.upper()}{exp:%y%m%d}{right[0].upper()}{int(strike):08d}",
                        expiration=exp,
                        strike=float(strike),
                        right=right,
                        last=round(abs(spot - strike) * 0.12 + 1.25, 2),
                        bid=1.1,
                        ask=1.4,
                        volume=120.0,
                        open_interest=450.0,
                        implied_volatility=0.28,
                    )
                )
        return OptionChain(
            symbol=symbol.upper(),
            as_of=datetime(2024, 6, 15, 20, 0, tzinfo=UTC),
            expirations=[exp],
            contracts=contracts,
            source=SOURCE,
        )


class StubNewsProvider(NewsProvider):
    name = "stub"

    def get_news(
        self,
        symbol: str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        ticker = (symbol or "MARKET").upper()
        base = datetime(2024, 6, 15, 16, 0, tzinfo=UTC)
        items: list[NewsItem] = []
        for i in range(max(1, min(limit, 20))):
            published = base - timedelta(hours=i)
            if start and published < start:
                continue
            if end and published > end:
                continue
            items.append(
                NewsItem(
                    id=f"stub-{ticker}-{i}",
                    symbol=None if symbol is None else ticker,
                    headline=f"{ticker} stub headline #{i + 1}",
                    summary="Deterministic fixture used when no live news key is configured.",
                    url=f"https://example.test/news/{ticker.lower()}/{i}",
                    source=SOURCE,
                    published_at=published,
                    related_symbols=[ticker] if symbol else [],
                )
            )
        return items


class StubBrokerReadOnlyClient(BrokerReadOnlyClient):
    """Offline stand-in so ``sec-analysis account`` works without IBKR."""

    name = "stub"

    def __init__(self, account_id: str = "DU000000") -> None:
        self._account_id = account_id
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected

    def get_account_summary(self) -> AccountSummary:
        return AccountSummary(
            account_id=self._account_id,
            as_of=datetime(2024, 6, 15, 20, 0, tzinfo=UTC),
            net_liquidation=125_000.0,
            cash=42_500.0,
            buying_power=80_000.0,
            gross_position_value=82_500.0,
            extras={"mode": "stub"},
        )

    def get_positions(self) -> list[Position]:
        return [
            Position(
                account_id=self._account_id,
                symbol="AAPL",
                quantity=100,
                average_cost=180.0,
                market_price=190.0,
                market_value=19_000.0,
                unrealized_pnl=1_000.0,
                asset_type=AssetType.EQUITY,
            )
        ]

    def get_executions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Execution]:
        fill = Execution(
            execution_id="stub-fill-1",
            account_id=self._account_id,
            symbol="AAPL",
            side="buy",
            quantity=100,
            price=180.0,
            executed_at=datetime(2024, 5, 2, 14, 31, tzinfo=UTC),
            commission=1.0,
        )
        rows = [fill]
        if start:
            rows = [e for e in rows if e.executed_at >= start]
        if end:
            rows = [e for e in rows if e.executed_at <= end]
        return rows
