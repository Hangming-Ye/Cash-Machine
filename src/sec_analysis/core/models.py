"""Canonical domain models shared by every provider and the broker client."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sec_analysis.core.instrument import Market


class AssetType(StrEnum):
    EQUITY = "equity"
    OPTION = "option"
    ETF = "etf"
    INDEX = "index"
    CRYPTO = "crypto"
    FOREX = "forex"
    UNKNOWN = "unknown"


class Quote(BaseModel):
    symbol: str
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    volume: float | None = None
    currency: str | None = None
    as_of: datetime
    source: str
    market: Market = Market.UNKNOWN
    exchange: str | None = None
    mic: str | None = None


class Bar(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    interval: str
    source: str
    market: Market = Market.UNKNOWN
    mic: str | None = None


class Fundamental(BaseModel):
    symbol: str
    as_of: date
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    eps: float | None = None
    dividend_yield: float | None = None
    revenue: float | None = None
    net_income: float | None = None
    currency: str | None = None
    source: str
    market: Market = Market.UNKNOWN
    extras: dict[str, Any] = Field(default_factory=dict)


class StatementKind(StrEnum):
    INCOME = "income"
    BALANCE = "balance"
    CASH = "cash"


class StatementLine(BaseModel):
    """One 财报 line item with per-period amounts as published (no unit conversion)."""

    label: str
    values: dict[str, float] = Field(default_factory=dict)


class StatementReport(BaseModel):
    """A single financial statement (income / balance / cash)."""

    symbol: str
    statement: StatementKind
    sina_stock: str
    sina_symbol: str
    periods: list[str]
    lines: list[StatementLine]
    as_of: date | None = None
    currency: str = "CNY"
    source: str
    market: Market = Market.CN


class OptionContract(BaseModel):
    symbol: str
    contract_symbol: str
    expiration: date
    strike: float
    right: str
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    implied_volatility: float | None = None


class OptionChain(BaseModel):
    symbol: str
    as_of: datetime
    expirations: list[date]
    contracts: list[OptionContract]
    source: str


class NewsItem(BaseModel):
    id: str
    headline: str
    source: str
    published_at: datetime
    symbol: str | None = None
    summary: str | None = None
    url: str | None = None
    related_symbols: list[str] = Field(default_factory=list)


class Position(BaseModel):
    account_id: str
    symbol: str
    quantity: float
    average_cost: float | None = None
    market_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    currency: str = "USD"
    asset_type: AssetType = AssetType.UNKNOWN


class Execution(BaseModel):
    """A historical fill. This is research data, not an instruction to trade."""

    execution_id: str
    account_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    executed_at: datetime
    commission: float | None = None
    currency: str = "USD"


class AccountSummary(BaseModel):
    account_id: str
    as_of: datetime
    net_liquidation: float | None = None
    cash: float | None = None
    buying_power: float | None = None
    gross_position_value: float | None = None
    currency: str = "USD"
    extras: dict[str, Any] = Field(default_factory=dict)
