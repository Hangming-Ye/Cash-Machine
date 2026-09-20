"""Market-aware instrument identity (CN / HK / US / JP / KR).

Bare letter tickers are *not* assumed to be US. Pass ``--market`` or use a
suffix / ``MARKET:SYMBOL`` prefix.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Market(StrEnum):
    US = "US"
    CN = "CN"
    HK = "HK"
    JP = "JP"
    KR = "KR"
    UNKNOWN = "UNKNOWN"


MARKET_CURRENCY = {
    Market.US: "USD",
    Market.CN: "CNY",
    Market.HK: "HKD",
    Market.JP: "JPY",
    Market.KR: "KRW",
}

# Common MIC / exchange labels (not a vendor choice).
_SUFFIX = {
    "SH": (Market.CN, "SSE", "XSHG"),
    "SS": (Market.CN, "SSE", "XSHG"),
    "SZ": (Market.CN, "SZSE", "XSHE"),
    "BJ": (Market.CN, "BSE", "XBEI"),
    "HK": (Market.HK, "HKEX", "XHKG"),
    "T": (Market.JP, "TSE", "XTKS"),
    "TYO": (Market.JP, "TSE", "XTKS"),
    "JP": (Market.JP, "TSE", "XTKS"),
    "KS": (Market.KR, "KRX", "XKRX"),
    "KQ": (Market.KR, "KOSDAQ", "XKOS"),
    "KR": (Market.KR, "KRX", "XKRX"),
    "US": (Market.US, None, None),
    "N": (Market.US, "NYSE", "XNYS"),
    "O": (Market.US, "NASDAQ", "XNAS"),
    "OQ": (Market.US, "NASDAQ", "XNAS"),
}

_PREFIX_MARKETS = {m.value for m in Market if m is not Market.UNKNOWN}


class Instrument(BaseModel):
    """A ticker plus the market/exchange it trades on."""

    symbol: str
    market: Market = Market.UNKNOWN
    exchange: str | None = None
    mic: str | None = None
    currency: str | None = None
    raw: str = ""
    asset_type: str = "equity"

    extras: dict[str, str] = Field(default_factory=dict)

    def display(self) -> str:
        if self.raw and ("." in self.raw or ":" in self.raw):
            return self.raw
        if self.market in {Market.UNKNOWN, Market.US}:
            return self.symbol.upper()
        return f"{self.market}:{self.symbol}"

    def ticker(self) -> str:
        return self.symbol


SymbolRef = str | Instrument


def resolve_instrument(
    value: str | Instrument,
    *,
    market: Market | str | None = None,
) -> Instrument:
    if isinstance(value, Instrument):
        inst = value
    else:
        inst = parse_instrument(value)
    if market:
        forced = Market(str(market).upper())
        inst = inst.model_copy(
            update={
                "market": forced,
                "currency": inst.currency or MARKET_CURRENCY.get(forced),
            }
        )
    return inst


def coerce_ticker(value: str | Instrument) -> str:
    inst = resolve_instrument(value)
    return inst.display()


def parse_instrument(raw: str) -> Instrument:
    text = raw.strip()
    if not text:
        raise ValueError("instrument symbol is empty")

    if ":" in text and not text.startswith("http"):
        head, tail = text.split(":", 1)
        if head.upper() in _PREFIX_MARKETS and tail:
            market = Market(head.upper())
            return _with_defaults(
                Instrument(symbol=_strip_suffix(tail), market=market, raw=text)
            )

    symbol, suffix = _split_suffix(text)
    if suffix:
        market, exchange, mic = _SUFFIX[suffix]
        return _with_defaults(
            Instrument(
                symbol=symbol,
                market=market,
                exchange=exchange,
                mic=mic,
                raw=text,
            )
        )

    prefixed = _parse_sh_sz_prefix(text)
    if prefixed is not None:
        return prefixed

    if symbol.isdigit() and len(symbol) == 6:
        # A-share listing convention, not a vendor assignment.
        if symbol[0] in {"6", "9"}:
            return _with_defaults(
                Instrument(symbol=symbol, market=Market.CN, exchange="SSE", mic="XSHG", raw=text)
            )
        if symbol[0] in {"0", "3"}:
            return _with_defaults(
                Instrument(symbol=symbol, market=Market.CN, exchange="SZSE", mic="XSHE", raw=text)
            )
        if symbol[0] in {"4", "8"}:
            return _with_defaults(
                Instrument(symbol=symbol, market=Market.CN, exchange="BSE", mic="XBEI", raw=text)
            )

    return _with_defaults(Instrument(symbol=symbol, market=Market.UNKNOWN, raw=text))


def _with_defaults(inst: Instrument) -> Instrument:
    currency = inst.currency or MARKET_CURRENCY.get(inst.market)
    return inst.model_copy(update={"currency": currency})


def _split_suffix(text: str) -> tuple[str, str | None]:
    if "." not in text:
        return text, None
    head, tail = text.rsplit(".", 1)
    key = tail.upper()
    if key in _SUFFIX and head:
        return head, key
    return text, None


def _strip_suffix(text: str) -> str:
    symbol, _suffix = _split_suffix(text)
    return symbol


def _parse_sh_sz_prefix(text: str) -> Instrument | None:
    """``sh600519`` / ``sz000001`` / ``bj830999`` — common AKShare / local forms."""
    compact = text.strip().lower().replace(".", "")
    for prefix, exchange, mic in (
        ("sh", "SSE", "XSHG"),
        ("sz", "SZSE", "XSHE"),
        ("bj", "BSE", "XBEI"),
    ):
        if compact.startswith(prefix) and compact[len(prefix) :].isdigit():
            digits = compact[len(prefix) :]
            if len(digits) == 6:
                return _with_defaults(
                    Instrument(
                        symbol=digits,
                        market=Market.CN,
                        exchange=exchange,
                        mic=mic,
                        raw=text,
                    )
                )
    return None
