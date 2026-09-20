"""AKShare A-share adapter — mocked only. Never hit East Money in CI."""

from __future__ import annotations

import pytest

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.instrument import Market
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.akshare_provider import (
    AkshareMarketDataProvider,
    to_akshare_a_share_code,
    to_akshare_tx_stock,
)
from sec_analysis.providers.akshare_provider.client import AKSHARE_MISSING, UPSTREAM_HINT
from sec_analysis.providers.registry import build_providers
from sec_analysis.providers.router import MarketDataRouter


class _Frame:
    """Minimal pandas-like table so tests never import pandas or akshare."""

    def __init__(self, rows: list[dict], *, empty: bool = False) -> None:
        self._rows = rows
        self.empty = empty

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return list(self._rows)


def _fast() -> RateLimiter:
    return RateLimiter(calls_per_minute=10_000, min_interval=0, sleeper=lambda _: None)


def _provider(**kwargs) -> AkshareMarketDataProvider:
    kwargs.setdefault("limiter", _fast())
    kwargs.setdefault("sleeper", lambda _: None)
    kwargs.setdefault("quote_retry_delay", 0)
    return AkshareMarketDataProvider(**kwargs)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("600519", "600519"),
        ("000001", "000001"),
        ("600519.SH", "600519"),
        ("000001.SZ", "000001"),
        ("sh600519", "600519"),
        ("sz000001", "000001"),
        ("CN:600519", "600519"),
        ("bj830799", "830799"),
        ("830799.BJ", "830799"),
    ],
)
def test_to_akshare_a_share_code(raw: str, code: str) -> None:
    assert to_akshare_a_share_code(raw) == code


@pytest.mark.parametrize(
    ("raw", "tx"),
    [
        ("600519", "sh600519"),
        ("600519.SH", "sh600519"),
        ("sh600519", "sh600519"),
        ("000001", "sz000001"),
        ("000001.SZ", "sz000001"),
        ("sz000001", "sz000001"),
        ("CN:600519", "sh600519"),
    ],
)
def test_to_akshare_tx_stock(raw: str, tx: str) -> None:
    assert to_akshare_tx_stock(raw) == tx


def test_to_akshare_rejects_non_cn() -> None:
    with pytest.raises(ProviderConfigError, match="A-share"):
        to_akshare_a_share_code("AAPL")
    with pytest.raises(ProviderConfigError, match="A-share"):
        to_akshare_a_share_code("00700.HK")


def test_quote_from_item_value_table() -> None:
    def spot(code: str):
        assert code == "600519"
        return _Frame(
            [
                {"item": "最新", "value": 1688.0},
                {"item": "买1", "value": 1687.5},
                {"item": "卖1", "value": 1688.2},
                {"item": "今开", "value": 1670.0},
                {"item": "最高", "value": 1695.0},
                {"item": "最低", "value": 1665.0},
                {"item": "昨收", "value": 1660.0},
                {"item": "成交量", "value": 123456},
            ]
        )

    quote = _provider(spot=spot).get_quote("600519.SH")
    assert quote.source == "akshare"
    assert quote.market is Market.CN
    assert quote.currency == "CNY"
    assert quote.last == 1688.0
    assert quote.bid == 1687.5
    assert quote.ask == 1688.2
    assert quote.volume == 123456
    assert quote.mic == "XSHG"


def test_quote_from_single_row_english_keys() -> None:
    quote = _provider(spot=lambda _code: [{"last": 10.52, "bid": 10.51, "ask": 10.53}]).get_quote(
        "000001"
    )
    assert quote.last == 10.52
    assert quote.symbol == "CN:000001"


def test_bars_from_hist_include_volume() -> None:
    def hist(code: str, *, start_date: str, end_date: str):
        assert code == "000001"
        assert len(start_date) == 8
        return _Frame(
            [
                {
                    "日期": "2024-01-02",
                    "开盘": 9.1,
                    "最高": 9.4,
                    "最低": 9.0,
                    "收盘": 9.3,
                    "成交量": 1_000_000,
                },
                {
                    "日期": "2024-01-03",
                    "开盘": 9.3,
                    "最高": 9.5,
                    "最低": 9.2,
                    "收盘": 9.4,
                    "成交量": 1_100_000,
                },
            ]
        )

    bars = _provider(hist=hist).get_bars("sz000001", interval="1d", limit=10)
    assert len(bars) == 2
    assert bars[0].close == 9.3
    assert bars[1].volume == 1_100_000
    assert bars[0].source == "akshare"
    assert bars[0].market is Market.CN
    assert all(bar.interval == "1d" for bar in bars)


def test_empty_spot_does_not_invent_price() -> None:
    with pytest.raises(ProviderError, match="no spot row"):
        _provider(spot=lambda _code: _Frame([], empty=True)).get_quote("600519")


def test_spot_without_last_does_not_invent_price() -> None:
    with pytest.raises(ProviderError, match="no last price"):
        _provider(spot=lambda _code: [{"item": "名称", "value": "茅台"}]).get_quote("600519")


def test_empty_hist_does_not_invent_bars() -> None:
    with pytest.raises(ProviderError, match="no daily bars"):
        _provider(hist=lambda *_a, **_k: _Frame([], empty=True)).get_bars("600519")


def _tx_frame(symbol_date: str = "2024-06-03") -> _Frame:
    return _Frame(
        [
            {
                "date": symbol_date,
                "open": 1600.0,
                "high": 1620.0,
                "low": 1590.0,
                "close": 1610.0,
                "volume": 50_000,
            }
        ]
    )


def test_bars_map_tencent_hist_tx_columns() -> None:
    """stock_zh_a_hist_tx returns date/open/close/high/low/volume/turnover/amount."""

    def hist(*_a, **_k):
        raise RuntimeError("RemoteDisconnected")

    def hist_tx(symbol: str, *, start_date: str, end_date: str):
        assert symbol == "sh600519"
        return _Frame(
            [
                {
                    "date": "2026-09-17",
                    "open": 1250.0,
                    "close": 1255.0,
                    "high": 1260.0,
                    "low": 1248.0,
                    "volume": 12_000,
                    "turnover": 0.3,
                    "amount": 1.5e9,
                },
                {
                    "date": "2026-09-18",
                    "open": 1256.0,
                    "close": 1257.12,
                    "high": 1262.0,
                    "low": 1251.0,
                    "volume": 15_000,
                    "turnover": 0.4,
                    "amount": 1.8e9,
                },
            ]
        )

    bars = _provider(hist=hist, hist_tx=hist_tx).get_bars("600519", limit=5)
    assert len(bars) == 2
    assert bars[-1].close == 1257.12
    assert bars[-1].open == 1256.0
    assert bars[-1].high == 1262.0
    assert bars[-1].low == 1251.0
    assert bars[-1].volume == 15_000
    assert bars[-1].source == "akshare"


def test_bars_fallback_to_hist_tx_when_em_fails() -> None:
    def hist(code: str, *, start_date: str, end_date: str):
        assert code == "600519"
        raise RuntimeError("eastmoney hist 403")

    def hist_tx(symbol: str, *, start_date: str, end_date: str):
        assert symbol == "sh600519"
        assert len(start_date) == 8
        return _tx_frame()

    bars = _provider(hist=hist, hist_tx=hist_tx).get_bars("600519", interval="1d", limit=5)
    assert len(bars) == 1
    assert bars[0].close == 1610.0
    assert bars[0].open == 1600.0
    assert bars[0].volume == 50_000
    assert bars[0].source == "akshare"
    assert bars[0].market is Market.CN


def test_bars_empty_em_falls_back_to_tx_sz() -> None:
    def hist(code: str, *, start_date: str, end_date: str):
        assert code == "000001"
        return _Frame([], empty=True)

    def hist_tx(symbol: str, *, start_date: str, end_date: str):
        assert symbol == "sz000001"
        return _tx_frame("2024-01-15")

    bars = _provider(hist=hist, hist_tx=hist_tx).get_bars("000001.SZ", limit=3)
    assert len(bars) == 1
    assert bars[0].close == 1610.0
    assert bars[0].symbol == "000001.SZ"


def test_bars_em_and_tx_fail_does_not_invent() -> None:
    def hist(*_a, **_k):
        raise RuntimeError("em down")

    def hist_tx(*_a, **_k):
        raise RuntimeError("tx down")

    with pytest.raises(ProviderError, match="stock_zh_a_hist_tx") as exc:
        _provider(hist=hist, hist_tx=hist_tx).get_bars("600519")
    text = str(exc.value)
    assert "em down" in text
    assert "tx down" in text
    assert UPSTREAM_HINT in text


def test_quote_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def flaky(code: str):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("eastmoney connection reset")
        return [{"item": "最新", "value": 1688.0}]

    quote = _provider(spot=flaky, quote_retries=3).get_quote("600519")
    assert calls["n"] == 3
    assert quote.last == 1688.0


def test_quote_falls_back_to_spot_em_board() -> None:
    calls = {"bid": 0, "board": 0}

    def boom(_code: str):
        calls["bid"] += 1
        raise RuntimeError("JSONDecodeError empty body")

    def board():
        calls["board"] += 1
        return [
            {"代码": "000001", "最新价": 11.2},
            {"代码": "600519", "最新价": 1688.0, "今开": 1670.0, "最高": 1695.0, "最低": 1665.0},
        ]

    quote = _provider(spot=boom, spot_board=board, quote_retries=2).get_quote("600519.SH")
    assert calls["bid"] == 2
    assert calls["board"] == 1
    assert quote.last == 1688.0
    assert quote.open == 1670.0
    assert quote.currency == "CNY"


def test_quote_falls_back_to_sina_spot_sh_code() -> None:
    def boom(_code: str):
        raise RuntimeError("JSONDecodeError empty body")

    def em_board():
        raise RuntimeError("RemoteDisconnected")

    def sina():
        return [
            {
                "代码": "sh600519",
                "最新价": 1257.12,
                "买入": 1257.12,
                "卖出": 1257.13,
                "昨收": 1266.98,
                "今开": 1262.99,
                "最高": 1265.88,
                "最低": 1256.1,
                "成交量": 2_489_087,
            }
        ]

    quote = _provider(
        spot=boom, spot_board=em_board, spot_sina=sina, quote_retries=1
    ).get_quote("600519")
    assert quote.last == 1257.12
    assert quote.bid == 1257.12
    assert quote.ask == 1257.13
    assert quote.previous_close == 1266.98
    assert quote.open == 1262.99
    assert quote.volume == 2_489_087


def test_quote_falls_back_to_tx_zxj() -> None:
    def boom(*_a, **_k):
        raise RuntimeError("down")

    quote = _provider(
        spot=boom,
        spot_board=boom,
        spot_sina=boom,
        spot_tx=lambda: [{"code": "sz000001", "zxj": 11.7, "volume": 949626}],
        quote_retries=1,
    ).get_quote("000001.SZ")
    assert quote.last == 11.7
    assert quote.volume == 949626


def test_quote_spot_em_missing_code_does_not_invent() -> None:
    def boom(_code: str):
        raise RuntimeError("bid_ask down")

    def board():
        return [{"代码": "000001", "最新价": 11.2}]

    with pytest.raises(ProviderError, match="stock_zh_a_spot_em") as exc:
        _provider(spot=boom, spot_board=board, quote_retries=1).get_quote("600519")
    assert "No last/OHLC was invented" in str(exc.value)


def test_hist_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def flaky(code: str, *, start_date: str, end_date: str):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("RemoteDisconnected")
        return _Frame(
            [
                {
                    "日期": "2024-01-03",
                    "开盘": 9.3,
                    "最高": 9.5,
                    "最低": 9.2,
                    "收盘": 9.4,
                    "成交量": 1_100_000,
                }
            ]
        )

    bars = _provider(hist=flaky, quote_retries=3).get_bars("600519", limit=2)
    assert calls["n"] == 3
    assert bars[0].close == 9.4


def test_quote_retries_then_clear_error_no_zeros() -> None:
    def boom(_code: str):
        raise RuntimeError("eastmoney connection reset")

    with pytest.raises(ProviderError, match="No last/OHLC was invented") as exc:
        _provider(spot=boom, quote_retries=2).get_quote("600519")
    assert "stock_bid_ask_em" in str(exc.value)
    assert "0.0" not in str(exc.value) or "invented" in str(exc.value)


def test_upstream_break_is_clear() -> None:
    def boom(_code: str):
        raise RuntimeError("eastmoney connection reset")

    with pytest.raises(ProviderError, match="stock_bid_ask_em") as exc:
        _provider(spot=boom).get_quote("600519")
    assert UPSTREAM_HINT in str(exc.value)
    assert "No last/OHLC was invented" in str(exc.value)


def test_rate_limit_message_is_explicit() -> None:
    def boom(_code: str):
        raise RuntimeError("HTTP 429 too many requests")

    with pytest.raises(ProviderError, match="rate-limited") as exc:
        _provider(spot=boom).get_quote("600519")
    assert UPSTREAM_HINT in str(exc.value)


def test_missing_extra_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> None:
        raise ProviderConfigError(AKSHARE_MISSING)

    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client._load_akshare",
        missing,
    )
    with pytest.raises(ProviderConfigError, match="uv sync --extra akshare"):
        AkshareMarketDataProvider(limiter=_fast()).get_quote("600519")


def test_injected_callables_never_import_akshare(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise AssertionError("CI must not import akshare / hit East Money")

    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client._load_akshare",
        fail,
    )
    quote = _provider(spot=lambda _c: [{"最新": 100.0}]).get_quote("600519")
    assert quote.last == 100.0


def test_intraday_interval_rejected() -> None:
    with pytest.raises(ProviderConfigError, match="daily"):
        _provider(hist=lambda *_a, **_k: []).get_bars("600519", interval="1m")


def test_cn_route_default_is_akshare() -> None:
    assert Settings.model_fields["market_data_route_cn"].default == "akshare"


def test_router_cn_uses_akshare_not_finnhub() -> None:
    settings = Settings(
        market_data_provider="finnhub",
        market_data_route_cn="akshare",
        market_data_route_us="finnhub",
        market_data_route_hk="finnhub",
        market_data_route_default="finnhub",
        news_provider="stub",
        broker_client="stub",
        finnhub_api_key="test-key",
    )
    bundle = build_providers(settings)
    assert isinstance(bundle.market_data, MarketDataRouter)
    assert bundle.market_data.route_names()["CN"] == ["akshare"]
    assert bundle.market_data.route_names()["US"] == ["finnhub"]
    assert bundle.market_data.route_names()["HK"] == ["finnhub"]


def test_router_quote_cn_via_injected_akshare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client._default_spot",
        lambda code: [{"item": "最新", "value": 1700.0}] if code == "600519" else [],
    )
    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client.RateLimiter",
        lambda *a, **k: _fast(),
    )
    settings = Settings(
        market_data_route_cn="akshare",
        market_data_route_us="stub",
        market_data_route_default="stub",
        news_provider="stub",
        broker_client="stub",
    )
    quote = build_providers(settings).market_data.get_quote("600519")
    assert quote.source == "akshare"
    assert quote.last == 1700.0
    assert quote.currency == "CNY"
