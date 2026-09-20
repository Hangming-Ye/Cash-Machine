"""AKShare A-share market data (phase-1 China route).

Uses unofficial scrape helpers from ``akshare``:

* Spot (preferred): ``stock_bid_ask_em(symbol)`` — retried with short backoff
* Spot fallback 2: ``stock_zh_a_spot_em()`` filtered to the 6-digit code
* Spot fallback 3: Sina ``stock_zh_a_spot()`` (codes ``sh600519`` / ``sz000001``)
* Spot last resort: Tencent ``stock_zh_a_spot_tx()`` (``zxj`` last; no bid/ask)
* Daily bars: ``stock_zh_a_hist`` (retried), then
  ``stock_zh_a_hist_tx(symbol="sh600519"|"sz000001")`` if EM hist fails

Failures raise; we never invent last / OHLC / volume.

Symbol forms accepted and normalized to a 6-digit code (what East Money
functions expect): ``600519``, ``000001``, ``600519.SH``, ``000001.SZ``,
``sh600519``, ``sz000001``, ``CN:600519``. Tencent hist wants ``sh`` / ``sz``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Instrument, Market, SymbolRef, resolve_instrument
from sec_analysis.core.interfaces import MarketDataProvider
from sec_analysis.core.models import Bar, Quote
from sec_analysis.core.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

AKSHARE_MISSING = (
    "akshare is not installed. A-share quotes, news, and 财报 need the extra: "
    "uv sync --extra akshare"
)

UPSTREAM_HINT = (
    "AKShare scrapes East Money and is often rate-limited or broken. "
    "Wait and retry; do not treat a failure as a zero/fake price."
)

EASTMONEY_OUTAGE = (
    "East Money spot/hist (stock_bid_ask_em, stock_zh_a_spot_em, stock_zh_a_hist) "
    "often return an empty JSON body or RemoteDisconnected. Quotes then try Sina "
    "stock_zh_a_spot and Tencent stock_zh_a_spot_tx. Daily bars use "
    "stock_zh_a_hist_tx(sh/sz). No last price is invented."
)


def to_akshare_a_share_code(value: SymbolRef) -> str:
    """Return the 6-digit code ``stock_zh_a_hist`` / ``stock_bid_ask_em`` expect."""
    inst = resolve_instrument(value)
    digits = "".join(ch for ch in inst.symbol if ch.isdigit())
    if inst.market not in {Market.CN, Market.UNKNOWN} or len(digits) != 6:
        raise ProviderConfigError(
            "AKShare A-share adapter only accepts China A-share codes "
            f"(e.g. 600519, 000001.SZ, sh600519). Got {inst.display()!r}."
        )
    if inst.market is Market.UNKNOWN:
        inst = resolve_instrument(digits)
        if inst.market is not Market.CN:
            raise ProviderConfigError(
                f"AKShare A-share adapter cannot infer an A-share listing from {inst.display()!r}."
            )
    return digits


def to_akshare_tx_stock(value: SymbolRef) -> str:
    """``stock_zh_a_hist_tx`` wants ``sh600519`` / ``sz000001`` (``bj`` allowed)."""
    inst = resolve_instrument(value)
    code = to_akshare_a_share_code(inst)
    inst = resolve_instrument(code if inst.market is Market.UNKNOWN else inst)
    if inst.exchange == "BSE" or inst.mic == "XBEI" or code[0] in {"4", "8"}:
        return f"bj{code}"
    if inst.exchange == "SSE" or inst.mic == "XSHG" or code[0] in {"6", "9"}:
        return f"sh{code}"
    if inst.exchange == "SZSE" or inst.mic == "XSHE" or code[0] in {"0", "3"}:
        return f"sz{code}"
    raise ProviderConfigError(
        f"Cannot map {inst.display()!r} to a Tencent sh/sz/bj stock id."
    )


def to_akshare_sina_stock(value: SymbolRef) -> str:
    """``stock_financial_report_sina`` wants ``sh600519`` / ``sz000001``."""
    inst = resolve_instrument(value)
    code = to_akshare_a_share_code(inst)
    inst = resolve_instrument(code if inst.market is Market.UNKNOWN else inst)
    if inst.exchange == "BSE" or inst.mic == "XBEI" or (code[0] in {"4", "8"}):
        raise ProviderConfigError(
            "AKShare Sina 财报 covers SSE/SZSE (sh/sz) only. "
            f"Beijing listings are not wired. Got {inst.display()!r}."
        )
    return to_akshare_tx_stock(inst)


def _load_akshare() -> Any:
    try:
        import akshare as ak
    except ImportError as exc:
        raise ProviderConfigError(AKSHARE_MISSING) from exc
    return ak


def _default_spot(code: str) -> Any:
    return _load_akshare().stock_bid_ask_em(symbol=code)


def _default_hist(
    code: str,
    *,
    start_date: str,
    end_date: str,
) -> Any:
    return _load_akshare().stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="",
    )


def _default_hist_tx(
    tx_symbol: str,
    *,
    start_date: str,
    end_date: str,
) -> Any:
    return _load_akshare().stock_zh_a_hist_tx(
        symbol=tx_symbol,
        start_date=start_date,
        end_date=end_date,
        adjust="",
    )


def _default_spot_board() -> Any:
    """Full A-share board. Heavier than ``stock_bid_ask_em``."""
    return _load_akshare().stock_zh_a_spot_em()


def _default_spot_sina() -> Any:
    """Sina full A-share board. Codes look like ``sh600519`` / ``sz000001``."""
    return _load_akshare().stock_zh_a_spot()


def _default_spot_tx() -> Any:
    """Tencent full A-share board. Has last (``zxj``), not a full bid/ask book."""
    return _load_akshare().stock_zh_a_spot_tx()


def _bind_fallback(
    injected: Callable[..., Any] | None,
    primary_is_default: bool,
    default_fn: Callable[..., Any],
) -> tuple[Callable[..., Any] | None, bool]:
    if injected is not None:
        return injected, True
    if primary_is_default:
        return default_fn, True
    return None, False


_MD_ATTEMPTS = 3
_MD_RETRY_DELAY = 0.4
_HEAVY_ATTEMPTS = 2
_HEAVY_CACHE_SEC = 90.0
SPOT_EM_HINT = (
    "stock_zh_a_spot_em downloads the full A-share board and is heavier "
    "than stock_bid_ask_em; it is only used after bid_ask retries fail."
)
SINA_SPOT_HINT = (
    "stock_zh_a_spot is a Sina full-board scrape (~5k rows; codes sh600519/sz000001). "
    "Heavier than bid_ask; Sina may temporarily ban repeat calls."
)


class AkshareMarketDataProvider(MarketDataProvider):
    """China A-shares only. Inject ``spot`` / ``spot_board`` / ``hist`` in tests."""

    name = "akshare"

    def __init__(
        self,
        *,
        spot: Callable[[str], Any] | None = None,
        spot_board: Callable[[], Any] | None = None,
        spot_sina: Callable[[], Any] | None = None,
        spot_tx: Callable[[], Any] | None = None,
        hist: Callable[..., Any] | None = None,
        hist_tx: Callable[..., Any] | None = None,
        limiter: RateLimiter | None = None,
        md_retries: int = _MD_ATTEMPTS,
        md_retry_delay: float = _MD_RETRY_DELAY,
        quote_retries: int | None = None,
        quote_retry_delay: float | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._spot = spot or _default_spot
        self._hist = hist or _default_hist
        # Live fallbacks only when the primary is also the live default, or
        # when tests inject the fallback callable. Injected-only tests stay offline.
        if hist_tx is not None:
            self._hist_tx = hist_tx
            self._tx_fallback = True
        elif hist is None:
            self._hist_tx = _default_hist_tx
            self._tx_fallback = True
        else:
            self._hist_tx = None
            self._tx_fallback = False
        live_spot = spot is None
        self._spot_board, self._board_fallback = _bind_fallback(
            spot_board, live_spot, _default_spot_board
        )
        self._spot_sina, self._sina_fallback = _bind_fallback(
            spot_sina, live_spot, _default_spot_sina
        )
        self._spot_tx, self._tx_spot_fallback = _bind_fallback(
            spot_tx, live_spot, _default_spot_tx
        )
        self._board_cache: dict[str, tuple[float, Any]] = {}
        self._limiter = limiter or RateLimiter(calls_per_minute=20, min_interval=0.5)
        retries = md_retries if quote_retries is None else quote_retries
        delay = md_retry_delay if quote_retry_delay is None else quote_retry_delay
        self._md_retries = max(1, int(retries))
        self._md_retry_delay = max(0.0, float(delay))
        self._sleep = sleeper or time.sleep

    def _retry(
        self,
        label: str,
        code: str,
        fn: Callable[[], Any],
        *,
        attempts: int | None = None,
    ) -> Any:
        last: BaseException | None = None
        total = max(1, int(attempts or self._md_retries))
        for attempt in range(1, total + 1):
            self._limiter.wait()
            try:
                return fn()
            except ProviderConfigError:
                raise
            except Exception as exc:
                last = exc
                if attempt < total:
                    logger.info(
                        "AKShare %s retry %s/%s for %s: %s",
                        label,
                        attempt,
                        total,
                        code,
                        exc,
                    )
                    self._sleep(self._md_retry_delay * attempt)
        assert last is not None
        raise last

    def _cached_board(self, key: str, fetch: Callable[[], Any]) -> Any:
        now = time.monotonic()
        hit = self._board_cache.get(key)
        if hit and now - hit[0] < _HEAVY_CACHE_SEC:
            return hit[1]
        payload = fetch()
        self._board_cache[key] = (now, payload)
        return payload

    def get_quote(self, symbol: SymbolRef) -> Quote:
        inst = resolve_instrument(symbol)
        code = to_akshare_a_share_code(inst)
        stages: list[tuple[str, bool, Callable[[], Quote], int]] = [
            (
                "stock_bid_ask_em",
                True,
                lambda: _quote_from_spot(code, self._spot(code)),
                self._md_retries,
            ),
            (
                "stock_zh_a_spot_em",
                self._board_fallback and self._spot_board is not None,
                lambda: _quote_from_board(
                    code, self._cached_board("em", self._spot_board)
                ),
                self._md_retries,
            ),
            (
                "stock_zh_a_spot",
                self._sina_fallback and self._spot_sina is not None,
                lambda: _quote_from_board(
                    code, self._cached_board("sina", self._spot_sina)
                ),
                _HEAVY_ATTEMPTS,
            ),
            (
                "stock_zh_a_spot_tx",
                self._tx_spot_fallback and self._spot_tx is not None,
                lambda: _quote_from_tx_board(
                    code, self._cached_board("tx", self._spot_tx)
                ),
                _HEAVY_ATTEMPTS,
            ),
        ]
        errors: list[str] = []
        for name, enabled, fetch, attempts in stages:
            if not enabled:
                continue
            try:
                quote = self._retry(name, code, fetch, attempts=attempts)
            except ProviderConfigError:
                raise
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                logger.info("AKShare quote skip %s for %s: %s", name, code, exc)
                continue
            return _tag_quote(quote, inst)
        raise ProviderError(
            f"AKShare quote failed for {code} after "
            f"{' | '.join(errors) or 'no enabled spot adapters'}. "
            f"{SINA_SPOT_HINT} {EASTMONEY_OUTAGE} "
            f"No last/OHLC was invented. {UPSTREAM_HINT}"
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
        if interval != "1d":
            raise ProviderConfigError(
                f"AKShare phase-1 bars only support daily (1d). Got {interval!r}."
            )
        inst = resolve_instrument(symbol)
        code = to_akshare_a_share_code(inst)
        end_dt = end or datetime.now(tz=UTC)
        start_dt = start or (end_dt - timedelta(days=max(limit, 1) * 2 + 10))
        start_date = start_dt.strftime("%Y%m%d")
        end_date = end_dt.strftime("%Y%m%d")
        try:
            bars, via_tx = self._bars_em_or_tx(inst, code, start_date, end_date, interval)
        except ProviderConfigError:
            raise
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"AKShare daily hist failed for {code} after retries: {exc}. "
                f"No OHLC was invented. {UPSTREAM_HINT}"
            ) from exc
        tagged = [
            bar.model_copy(update={"symbol": inst.display(), "market": Market.CN, "mic": inst.mic})
            for bar in bars[-limit:]
        ]
        if via_tx:
            logger.info("AKShare daily bars for %s used stock_zh_a_hist_tx fallback", code)
        return tagged

    def _hist_bars(
        self,
        fetch: Callable[..., Any],
        symbol: str,
        code: str,
        start_date: str,
        end_date: str,
        interval: str,
        label: str,
    ) -> list[Bar]:
        def once() -> list[Bar]:
            payload = fetch(symbol, start_date=start_date, end_date=end_date)
            bars = _bars_from_hist(code, payload, interval=interval)
            if not bars:
                raise ProviderError(
                    f"AKShare returned no daily bars for {symbol}. {UPSTREAM_HINT}"
                )
            return bars

        return self._retry(label, symbol, once)

    def _bars_em_or_tx(
        self,
        inst: Instrument,
        code: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> tuple[list[Bar], bool]:
        try:
            bars = self._hist_bars(
                self._hist, code, code, start_date, end_date, interval, "daily hist"
            )
            return bars, False
        except ProviderConfigError:
            raise
        except Exception as em_error:
            if not self._tx_fallback or self._hist_tx is None:
                if isinstance(em_error, ProviderError):
                    raise em_error
                raise ProviderError(
                    f"AKShare daily hist failed for {code} after {self._md_retries} "
                    f"attempts: {em_error}. No OHLC was invented. {UPSTREAM_HINT}"
                ) from em_error
            tx_symbol = to_akshare_tx_stock(inst)
            logger.info(
                "AKShare East Money hist failed for %s (%s); trying stock_zh_a_hist_tx(%s)",
                code,
                em_error,
                tx_symbol,
            )
            try:
                bars = self._hist_bars(
                    self._hist_tx,
                    tx_symbol,
                    code,
                    start_date,
                    end_date,
                    interval,
                    "hist_tx",
                )
                return bars, True
            except ProviderConfigError:
                raise
            except Exception as tx_exc:
                raise ProviderError(
                    f"AKShare daily hist failed for {code} after retries "
                    f"(East Money stock_zh_a_hist: {em_error}); "
                    f"Tencent stock_zh_a_hist_tx({tx_symbol}) also failed: {tx_exc}. "
                    f"No OHLC was invented. {UPSTREAM_HINT}"
                ) from tx_exc


def _records(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        return [payload]
    if hasattr(payload, "empty") and bool(payload.empty):
        return []
    frame = payload
    index = getattr(frame, "index", None)
    name = getattr(index, "name", None)
    if name in {"date", "日期", "时间"} and hasattr(frame, "reset_index"):
        try:
            frame = frame.reset_index()
        except Exception:
            frame = payload
    if hasattr(frame, "to_dict"):
        rows = frame.to_dict("records")
        return list(rows) if rows else []
    raise ProviderError("AKShare returned an unrecognized table shape")


def _tag_quote(quote: Quote, inst: Instrument) -> Quote:
    return quote.model_copy(
        update={
            "symbol": inst.display(),
            "market": Market.CN,
            "exchange": inst.exchange,
            "mic": inst.mic,
            "currency": "CNY",
        }
    )


def _match_a_share_row(rows: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    """Match ``600519``, ``sh600519``, ``sz000001``, or a bare 6-digit ``代码``."""
    aliases = {code, f"sh{code}", f"sz{code}", f"bj{code}"}
    for row in rows:
        raw = row.get("代码") or row.get("code") or row.get("symbol")
        if raw is None:
            continue
        text = str(raw).strip().lower()
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits == code or text in aliases:
            return row
    return None


def _quote_from_board(code: str, payload: Any) -> Quote:
    """Pick one row from EM or Sina full-board spot."""
    match = _match_a_share_row(_records(payload), code)
    if match is None:
        raise ProviderError(
            f"AKShare board spot had no row for {code}. {SPOT_EM_HINT} {UPSTREAM_HINT}"
        )
    last = _first_num(match, "最新价", "最新", "last", "trade", "close", "收盘")
    if last is None:
        raise ProviderError(
            f"AKShare board spot row for {code} had no last price. "
            f"{SPOT_EM_HINT} {UPSTREAM_HINT}"
        )
    return Quote(
        symbol=code,
        last=last,
        bid=_first_num(match, "买入", "买1", "buy", "bid"),
        ask=_first_num(match, "卖出", "卖1", "sell", "ask"),
        open=_first_num(match, "今开", "开盘", "open"),
        high=_first_num(match, "最高", "high"),
        low=_first_num(match, "最低", "low"),
        previous_close=_first_num(match, "昨收", "previous_close", "settlement"),
        volume=_first_num(match, "成交量", "volume"),
        currency="CNY",
        as_of=datetime.now(tz=UTC),
        source="akshare",
        market=Market.CN,
    )


def _quote_from_tx_board(code: str, payload: Any) -> Quote:
    """Tencent ``stock_zh_a_spot_tx``: ``code=sh600519``, last=``zxj``."""
    match = _match_a_share_row(_records(payload), code)
    if match is None:
        raise ProviderError(
            f"AKShare stock_zh_a_spot_tx had no row for {code}. {UPSTREAM_HINT}"
        )
    last = _first_num(match, "zxj", "最新价", "最新", "last", "price")
    if last is None:
        raise ProviderError(
            f"AKShare stock_zh_a_spot_tx row for {code} had no last (zxj). {UPSTREAM_HINT}"
        )
    return Quote(
        symbol=code,
        last=last,
        volume=_first_num(match, "volume", "成交量"),
        currency="CNY",
        as_of=datetime.now(tz=UTC),
        source="akshare",
        market=Market.CN,
    )


def _quote_from_spot(code: str, payload: Any) -> Quote:
    rows = _records(payload)
    if not rows:
        raise ProviderError(f"AKShare returned no spot row for {code}. {UPSTREAM_HINT}")
    pairs = _item_value_map(rows)
    last = _first_num(pairs, "最新", "最新价", "last", "price", "latest")
    if last is None and len(rows) == 1:
        last = _first_num(rows[0], "最新", "最新价", "last", "close", "收盘")
    if last is None:
        raise ProviderError(
            f"AKShare spot for {code} had no last price. {UPSTREAM_HINT}"
        )
    return Quote(
        symbol=code,
        last=last,
        bid=_first_num(pairs, "buy_1", "买1", "bid"),
        ask=_first_num(pairs, "sell_1", "卖1", "ask"),
        open=_first_num(pairs, "今开", "开盘", "open"),
        high=_first_num(pairs, "最高", "high"),
        low=_first_num(pairs, "最低", "low"),
        previous_close=_first_num(pairs, "昨收", "previous_close"),
        volume=_first_num(pairs, "总手", "成交量", "volume"),
        currency="CNY",
        as_of=datetime.now(tz=UTC),
        source="akshare",
        market=Market.CN,
    )


def _item_value_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for row in rows:
        key = row.get("item") or row.get("项目") or row.get("name")
        if key is None:
            mapped.update({str(k): v for k, v in row.items()})
            continue
        mapped[str(key)] = row.get("value", row.get("值"))
    return mapped


def _bars_from_hist(code: str, payload: Any, *, interval: str) -> list[Bar]:
    """Map EM Chinese cols or Tencent ``date/open/close/high/low/volume`` into Bar."""
    bars: list[Bar] = []
    for row in _records(payload):
        ts = _as_day(
            row.get("日期")
            or row.get("date")
            or row.get("时间")
            or row.get("index")
        )
        ohlc = (
            _first_num(row, "开盘", "open"),
            _first_num(row, "最高", "high"),
            _first_num(row, "最低", "low"),
            _first_num(row, "收盘", "close"),
        )
        if ts is None or any(part is None for part in ohlc):
            continue
        open_, high, low, close = ohlc
        bars.append(
            Bar(
                symbol=code,
                timestamp=ts,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=_first_num(row, "成交量", "volume") or 0.0,
                interval=interval,
                source="akshare",
                market=Market.CN,
            )
        )
    return bars


def _as_day(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value).replace("/", "-")[:10]
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _first_num(row: dict[str, Any], *keys: str) -> float | None:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        if key in row:
            value = row[key]
        elif key.lower() in lowered:
            value = lowered[key.lower()]
        else:
            continue
        if value is None or value == "" or value == "--":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _is_rate_limit(exc: BaseException) -> bool:
    text = str(exc).lower()
    needles = ("429", "rate limit", "too many", "频繁", "访问过快", "banned", "blocked")
    return any(needle in text for needle in needles)


def _upstream_message(action: str, code: str, exc: BaseException) -> str:
    kind = "rate-limited" if _is_rate_limit(exc) else "upstream error"
    return f"AKShare {action} {kind} for {code}: {exc}. {UPSTREAM_HINT}"


def _quote_exhausted_message(code: str, attempts: int, exc: BaseException | None) -> str:
    detail = f"{exc}" if exc is not None else "unknown error"
    kind = "rate-limited" if exc is not None and _is_rate_limit(exc) else "upstream error"
    return (
        f"AKShare East Money spot (stock_bid_ask_em) {kind} for {code} "
        f"after {attempts} attempts: {detail}. "
        f"No last/OHLC was invented. {UPSTREAM_HINT}"
    )
