"""AKShare Sina 财报 — mocked only. Never hit Sina in CI."""

from __future__ import annotations

import pytest

from sec_analysis.config import Settings
from sec_analysis.core.errors import ProviderConfigError, ProviderError
from sec_analysis.core.models import StatementKind
from sec_analysis.core.rate_limit import RateLimiter
from sec_analysis.providers.akshare_provider import (
    AkshareFundamentalsProvider,
    normalize_statement,
    to_akshare_sina_stock,
)
from sec_analysis.providers.akshare_provider.fundamentals import SINA_HINT
from sec_analysis.providers.fundamentals_router import FundamentalsRouter
from sec_analysis.providers.registry import build_providers
from sec_analysis.providers.stub import StubFundamentalsProvider


class _Frame:
    def __init__(self, rows: list[dict], *, empty: bool = False, index_name: str | None = None):
        self._rows = rows
        self.empty = empty
        self.index = _Index(index_name, rows)

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return list(self._rows)

    def reset_index(self):
        return self


class _Index:
    def __init__(self, name: str | None, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def __getitem__(self, idx: int):
        if not self._rows:
            raise IndexError
        return self._rows[idx].get(self.name or "报告日")


def _fast() -> RateLimiter:
    return RateLimiter(calls_per_minute=10_000, min_interval=0, sleeper=lambda _: None)


def _provider(**kwargs) -> AkshareFundamentalsProvider:
    return AkshareFundamentalsProvider(limiter=_fast(), **kwargs)


def _income_rows() -> list[dict]:
    return [
        {"报告日": "营业收入", "20231231": 147_694_000_000.0, "20221231": 127_554_000_000.0},
        {"报告日": "净利润", "20231231": 74_734_000_000.0, "20221231": 62_720_000_000.0},
        {"报告日": "营业成本", "20231231": 1.0, "20221231": "--"},
    ]


@pytest.mark.parametrize(
    ("raw", "stock"),
    [
        ("600519", "sh600519"),
        ("600519.SH", "sh600519"),
        ("sh600519", "sh600519"),
        ("CN:600519", "sh600519"),
        ("000001", "sz000001"),
        ("000001.SZ", "sz000001"),
        ("sz000001", "sz000001"),
    ],
)
def test_to_akshare_sina_stock(raw: str, stock: str) -> None:
    assert to_akshare_sina_stock(raw) == stock


def test_sina_stock_rejects_beijing() -> None:
    with pytest.raises(ProviderConfigError, match="Beijing"):
        to_akshare_sina_stock("830799")


@pytest.mark.parametrize(
    ("alias", "sina"),
    [
        ("income", "利润表"),
        ("利润表", "利润表"),
        ("lrb", "利润表"),
        ("balance", "资产负债表"),
        ("资产负债表", "资产负债表"),
        ("cash", "现金流量表"),
        ("现金流量表", "现金流量表"),
    ],
)
def test_normalize_statement_aliases(alias: str, sina: str) -> None:
    assert normalize_statement(alias) == sina


def test_income_statement_from_item_rows() -> None:
    def fetch(stock: str, *, symbol: str):
        assert stock == "sh600519"
        assert symbol == "利润表"
        return _Frame(_income_rows())

    report = _provider(fetch=fetch).get_statement("600519", statement="income")
    assert report.statement is StatementKind.INCOME
    assert report.sina_stock == "sh600519"
    assert report.sina_symbol == "利润表"
    assert report.periods[0] == "2023-12-31"
    revenue = next(line for line in report.lines if line.label == "营业收入")
    assert revenue.values["2023-12-31"] == 147_694_000_000.0
    cost = next(line for line in report.lines if line.label == "营业成本")
    assert "2022-12-31" not in cost.values
    assert cost.values["2023-12-31"] == 1.0
    snap = _provider(fetch=fetch).get_fundamentals("600519.SH")
    assert snap.revenue == 147_694_000_000.0
    assert snap.net_income == 74_734_000_000.0
    assert snap.currency == "CNY"
    assert snap.pe_ratio is None


def test_statement_omits_nan_section_headers() -> None:
    def fetch(stock: str, *, symbol: str):
        return _Frame(
            [
                {"报告日": "流动资产", "20231231": float("nan"), "20221231": float("nan")},
                {"报告日": "货币资金", "20231231": 53.0, "20221231": 48.0},
            ]
        )

    report = _provider(fetch=fetch).get_statement("600519", statement="balance")
    labels = [line.label for line in report.lines]
    assert "流动资产" not in labels
    cash = next(line for line in report.lines if line.label == "货币资金")
    assert cash.values["2023-12-31"] == 53.0


def test_balance_from_period_rows() -> None:
    def fetch(stock: str, *, symbol: str):
        assert stock == "sz000001"
        assert symbol == "资产负债表"
        return _Frame(
            [
                {"报告日": "20231231", "资产总计": 100.0, "负债合计": 40.0},
                {"报告日": "20221231", "资产总计": 90.0, "负债合计": 38.0},
            ]
        )

    report = _provider(fetch=fetch).get_statement("000001", statement="资产负债表", limit_periods=2)
    assert report.statement is StatementKind.BALANCE
    assets = next(line for line in report.lines if line.label == "资产总计")
    assert assets.values["2023-12-31"] == 100.0


def test_empty_table_does_not_invent_numbers() -> None:
    with pytest.raises(ProviderError, match="empty table"):
        _provider(fetch=lambda *_a, **_k: _Frame([], empty=True)).get_statement("600519")


def test_upstream_break_is_clear() -> None:
    def boom(stock: str, *, symbol: str):
        raise RuntimeError("sina 429 too many")

    with pytest.raises(ProviderError, match="Sina") as exc:
        _provider(fetch=boom).get_statement("600519", statement="cash")
    assert SINA_HINT in str(exc.value)


def test_injected_fetch_never_imports_akshare(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise AssertionError("CI must not import akshare / hit Sina")

    monkeypatch.setattr(
        "sec_analysis.providers.akshare_provider.client._load_akshare",
        fail,
    )
    report = _provider(fetch=lambda *_a, **_k: _Frame(_income_rows())).get_statement("sh600519")
    assert report.lines


def test_registry_cn_fundamentals_route_is_akshare() -> None:
    settings = Settings(
        fundamentals_provider="stub",
        fundamentals_route_cn="akshare",
        fundamentals_route_us="stub",
        fundamentals_route_default="stub",
        news_provider="stub",
        broker_client="stub",
        market_data_route_us="stub",
        market_data_route_default="stub",
    )
    bundle = build_providers(settings)
    assert isinstance(bundle.fundamentals, FundamentalsRouter)
    assert bundle.fundamentals.route_names()["CN"] == ["akshare"]
    assert bundle.fundamentals.route_names()["US"] == ["stub"]


def test_stub_statement_does_not_fabricate() -> None:
    with pytest.raises(ProviderConfigError, match="does not provide"):
        StubFundamentalsProvider().get_statement("AAPL", statement="income")
