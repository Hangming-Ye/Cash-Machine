from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from cash_research.config import Settings
from cash_research.models import DataGap, Evidence, SourceResult
from cash_research.sources.akshare_source import AKShareAdapter


OUTPUT_REF = "data/records/rec_00000000000000000000000000000000/sources/akshare.json"


class FakeAKShare:
    __version__ = "1.18.97"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.responses: dict[str, object] = {}

    def _call(self, name: str, **kwargs: object) -> object:
        self.calls.append((name, kwargs))
        value = self.responses.get(name, RuntimeError("synthetic failure"))
        if isinstance(value, BaseException):
            raise value
        return value

    def stock_bid_ask_em(self, **kwargs: object) -> object:
        return self._call("stock_bid_ask_em", **kwargs)

    def stock_zh_a_spot_em(self, **kwargs: object) -> object:
        return self._call("stock_zh_a_spot_em", **kwargs)

    def stock_zh_a_spot(self, **kwargs: object) -> object:
        return self._call("stock_zh_a_spot", **kwargs)

    def stock_zh_a_spot_tx(self, **kwargs: object) -> object:
        return self._call("stock_zh_a_spot_tx", **kwargs)

    def stock_zh_a_hist(self, **kwargs: object) -> object:
        return self._call("stock_zh_a_hist", **kwargs)

    def stock_zh_a_hist_tx(self, **kwargs: object) -> object:
        return self._call("stock_zh_a_hist_tx", **kwargs)

    def stock_news_em(self, **kwargs: object) -> object:
        return self._call("stock_news_em", **kwargs)

    def stock_financial_report_sina(self, **kwargs: object) -> object:
        name = f"stock_financial_report_sina:{kwargs.get('symbol')}"
        return self._call(name, **kwargs)


def _settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    return Settings(root=tmp_path, enabled_sources=("akshare",) if enabled else ("tiingo",))


def _request(operation: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "request_id": f"request-akshare-{operation}",
        "source": "akshare",
        "operation": operation,
        "subject": {
            "market": "CN",
            "exchange": "XSHE",
            "symbol": "000001",
            "currency": "CNY",
        },
        "as_of": "2026-01-15T16:00:00+08:00",
        "parameters": {},
        "required_fields": [],
    }
    value.update(overrides)
    return value


def _validate(result: dict[str, object], request_id: str) -> SourceResult:
    assert {"source_result", "raw_payload", "normalized", "evidence", "gaps"} <= set(result)
    source = SourceResult.model_validate(result["source_result"])
    for item in result["evidence"]:  # type: ignore[union-attr]
        Evidence.model_validate(item)
    for item in result["gaps"]:  # type: ignore[union-attr]
        gap = DataGap.model_validate(item)
        assert gap.request_id == request_id
        assert all("at" in attempt for attempt in gap.attempts)
    return source


def test_quote_uses_bid_ask_and_does_not_invent_event_time(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_bid_ask_em"] = pd.DataFrame(
        {"item": ["最新", "buy_1", "sell_1", "总手"], "value": [10.2, 10.1, 10.3, 1234]}
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(
        _request("quote", required_fields=["current_price", "bid", "ask"]),
        output_ref=OUTPUT_REF,
    )
    source = _validate(result, "request-akshare-quote")
    assert source.quality == "limited"
    assert source.observed_at is None and source.available_at is None
    assert result["normalized"]["actual_source"] == "akshare:stock_bid_ask_em"  # type: ignore[index]
    assert result["normalized"]["requested_as_of"] == "2026-01-15T16:00:00+08:00"  # type: ignore[index]
    assert result["normalized"]["usable_for_historical_as_of"] is False  # type: ignore[index]
    assert result["normalized"]["historical_eligibility"] == "unknown_provider_event_time"  # type: ignore[index]
    assert result["normalized"]["current_price"]["value"] == 10.2  # type: ignore[index]
    assert result["normalized"]["volume"] == {"value": 123400, "unit": "shares", "original_value": 1234.0, "original_unit": "lots"}  # type: ignore[index]
    assert sdk.calls == [("stock_bid_ask_em", {"symbol": "000001"})]


def test_quote_fallback_preserves_actual_source_and_attempts(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_zh_a_spot_em"] = pd.DataFrame(
        [{"代码": "000001", "最新价": 11.5, "成交量": 20, "今开": 11.0, "最高": 12.0, "最低": 10.8}]
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(
        _request("quote"), output_ref=OUTPUT_REF
    )
    source = _validate(result, "request-akshare-quote")
    assert source.errors == ("primary_endpoint_failed",)
    assert result["normalized"]["actual_source"] == "akshare:stock_zh_a_spot_em"  # type: ignore[index]
    assert [call[0] for call in sdk.calls] == ["stock_bid_ask_em", "stock_zh_a_spot_em"]
    assert result["gaps"][0]["attempts"][0]["endpoint"] == "stock_bid_ask_em"  # type: ignore[index]


def test_missing_requested_quote_field_is_a_named_gap(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_bid_ask_em"] = pd.DataFrame(
        {"item": ["最新", "buy_1"], "value": [10.2, 10.1]}
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(
        _request("quote", required_fields=["current_price", "ask"]), output_ref=OUTPUT_REF
    )
    assert result["normalized"]["ask"]["value"] is None  # type: ignore[index]
    assert any("ask" in gap["required_content"] for gap in result["gaps"])  # type: ignore[index]


def test_secret_like_raw_quote_is_not_returned_or_persistable(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_bid_ask_em"] = pd.DataFrame(
        [{"item": "最新", "value": 10.2, "Authorization": "Bearer synthetic-secret"}]
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(
        _request("quote"), output_ref=OUTPUT_REF
    )
    assert _validate(result, "request-akshare-quote").quality == "failed"
    assert result["raw_payload"] is None


def test_invalid_or_exchange_inconsistent_symbol_makes_no_sdk_call(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    request = _request(
        "quote",
        subject={"market": "CN", "exchange": "XSHG", "symbol": "000001", "currency": "CNY"},
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    assert _validate(result, "request-akshare-quote").quality == "failed"
    assert result["normalized"]["error_reason"] == "invalid"  # type: ignore[index]
    assert sdk.calls == []


def test_eastmoney_bars_keep_lots_and_explicit_share_conversion(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_zh_a_hist"] = pd.DataFrame(
        [
            {"日期": "2026-01-14", "股票代码": "000001", "开盘": 10, "最高": 12, "最低": 9, "收盘": 11, "成交量": 25, "成交额": Decimal("27000.50"), "换手率": 1.2},
            {"日期": "2026-01-16", "股票代码": "000001", "开盘": 11, "最高": 12, "最低": 10, "收盘": 11.5, "成交量": 30, "成交额": 33000, "换手率": 1.3},
        ]
    )
    request = _request(
        "bars",
        parameters={"start_date": "2026-01-13", "end_date": "2026-01-16", "bar_interval": "1d", "adjustment": "qfq"},
        required_fields=["ohlcv", "adjustment_status", "market_date"],
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    source = _validate(result, "request-akshare-bars")
    assert source.quality == "limited"
    assert len(result["raw_payload"]) == 2  # type: ignore[arg-type]
    row = result["normalized"]["rows"][0]  # type: ignore[index]
    assert row["market_date"] == "2026-01-14"
    assert row["volume"] == {"value": 2500.0, "unit": "shares", "original_value": 25.0, "original_unit": "lots"}
    assert result["normalized"]["excluded_after_cutoff"] == 1  # type: ignore[index]
    assert result["normalized"]["adjustment_status"]["basis"] == "qfq"  # type: ignore[index]
    assert sdk.calls[0] == ("stock_zh_a_hist", {"symbol": "000001", "period": "daily", "start_date": "20260113", "end_date": "20260116", "adjust": "qfq"})


def test_tencent_bar_fallback_keeps_share_volume_and_fraction_turnover(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_zh_a_hist_tx"] = pd.DataFrame(
        [{"date": "2026-01-14", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 2500, "turnover": 0.0012, "amount": 27000}]
    )
    request = _request("bars", parameters={"start_date": "2026-01-14", "end_date": "2026-01-14", "bar_interval": "1d", "adjustment": "raw"})
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    row = result["normalized"]["rows"][0]  # type: ignore[index]
    assert result["normalized"]["actual_source"] == "akshare:stock_zh_a_hist_tx"  # type: ignore[index]
    assert row["volume"] == {"value": 2500.0, "unit": "shares", "original_value": 2500.0, "original_unit": "shares"}
    assert row["turnover"] == {"value": 0.0012, "unit": "fraction"}
    assert sdk.calls[-1][1]["symbol"] == "sz000001"


def test_bad_ohlc_and_nan_are_raw_but_not_normalized(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_zh_a_hist"] = pd.DataFrame(
        [
            {"日期": "2026-01-14", "股票代码": "000001", "开盘": 15, "最高": 12, "最低": 9, "收盘": 11, "成交量": 2, "成交额": float("nan")},
            {"日期": "2026-01-13", "股票代码": "000001", "开盘": 10, "最高": 12, "最低": 9, "收盘": 11, "成交量": 2, "成交额": float("nan")},
        ]
    )
    request = _request("bars", parameters={"start_date": "2026-01-13", "end_date": "2026-01-14", "bar_interval": "1d", "adjustment": "raw"})
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    assert result["raw_payload"][0]["成交额"] is None  # type: ignore[index]
    assert [row["market_date"] for row in result["normalized"]["rows"]] == ["2026-01-13"]  # type: ignore[index]
    assert any(gap["required_content"] == "valid daily OHLC rows" for gap in result["gaps"])  # type: ignore[index]


def test_requested_ohlcv_reports_missing_volume_instead_of_silently_passing(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_zh_a_hist"] = pd.DataFrame(
        [{"日期": "2026-01-14", "股票代码": "000001", "开盘": 10, "最高": 12, "最低": 9, "收盘": 11, "成交量": float("nan"), "成交额": 27000}]
    )
    request = _request(
        "bars",
        parameters={"start_date": "2026-01-14", "end_date": "2026-01-14", "bar_interval": "1d", "adjustment": "raw"},
        required_fields=["ohlcv"],
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    assert result["normalized"]["rows"][0]["volume"]["value"] is None  # type: ignore[index]
    assert any("ohlcv.volume" in gap["required_content"] for gap in result["gaps"])  # type: ignore[index]


def test_duplicate_market_dates_are_raw_but_excluded_as_unresolved_conflict(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_zh_a_hist"] = pd.DataFrame(
        [
            {"日期": "2026-01-13", "股票代码": "000001", "开盘": 10, "最高": 12, "最低": 9, "收盘": 11, "成交量": 2},
            {"日期": "2026-01-14", "股票代码": "000001", "开盘": 10, "最高": 12, "最低": 9, "收盘": 11, "成交量": 2},
            {"日期": "2026-01-14", "股票代码": "000001", "开盘": 10, "最高": 13, "最低": 9, "收盘": 12, "成交量": 3},
        ]
    )
    request = _request("bars", parameters={"start_date": "2026-01-13", "end_date": "2026-01-14", "bar_interval": "1d", "adjustment": "raw"})
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    assert len(result["raw_payload"]) == 3  # type: ignore[arg-type]
    assert [row["market_date"] for row in result["normalized"]["rows"]] == ["2026-01-13"]  # type: ignore[index]
    assert result["normalized"]["revision_status"] == "unresolved"  # type: ignore[index]
    assert SourceResult.model_validate(result["source_result"]).errors == ("revision_conflict",)
    assert any("duplicate or conflicting" in gap["required_content"] for gap in result["gaps"])  # type: ignore[index]


def test_empty_daily_history_is_distinct_from_all_failed(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_zh_a_hist"] = pd.DataFrame()
    sdk.responses["stock_zh_a_hist_tx"] = pd.DataFrame()
    request = _request("bars", parameters={"start_date": "2026-01-13", "end_date": "2026-01-14", "bar_interval": "1d", "adjustment": "raw"})
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    source = _validate(result, "request-akshare-bars")
    assert source.quality == "limited" and source.errors == ()
    assert source.payload_ref == OUTPUT_REF
    assert result["raw_payload"] == []
    assert result["normalized"]["empty_is_failure"] is False  # type: ignore[index]


def test_news_naive_china_time_is_cut_off_and_latest_100_limit_recorded(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_news_em"] = pd.DataFrame(
        [
            {"关键词": "000001", "新闻标题": "Earlier", "新闻内容": "Body", "发布时间": "2026-01-15 15:00:00", "文章来源": "EastMoney", "新闻链接": "https://example.invalid/1"},
            {"关键词": "000001", "新闻标题": "Future", "新闻内容": "Body", "发布时间": "2026-01-15 17:00:00", "文章来源": "EastMoney", "新闻链接": "https://example.invalid/2"},
        ]
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(
        _request("news", parameters={"limit": 100}, required_fields=["headline", "published_at", "url"]),
        output_ref=OUTPUT_REF,
    )
    source = _validate(result, "request-akshare-news")
    assert len(result["raw_payload"]) == 2  # type: ignore[arg-type]
    assert len(result["normalized"]["items"]) == 1  # type: ignore[index]
    assert result["normalized"]["items"][0]["published_at"].endswith("+08:00")  # type: ignore[index]
    assert result["normalized"]["documented_limit"] == "current-day latest 100 items"  # type: ignore[index]
    assert source.available_at is None
    assert len(result["evidence"]) == 1  # type: ignore[arg-type]


def test_empty_news_is_clean_limited_result_not_failed(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_news_em"] = pd.DataFrame()
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(_request("news"), output_ref=OUTPUT_REF)
    source = _validate(result, "request-akshare-news")
    assert source.quality == "limited" and source.errors == ()
    assert result["raw_payload"] == []
    assert result["normalized"]["empty_is_failure"] is False  # type: ignore[index]


def test_all_news_failure_has_no_raw_payload(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(_request("news"), output_ref=OUTPUT_REF)
    source = _validate(result, "request-akshare-news")
    assert source.quality == "failed"
    assert result["raw_payload"] is None
    assert result["normalized"]["error_reason"] == "external"  # type: ignore[index]


@pytest.mark.parametrize(
    "rows",
    [
        [{"新闻标题": None, "发布时间": "not-a-time", "新闻链接": None}],
        [{"新闻标题": "Future", "发布时间": "2026-01-15 17:00:00", "新闻链接": "https://example.invalid/future"}],
    ],
)
def test_all_nonempty_news_rows_excluded_remains_valid_limited_result(
    tmp_path: Path, rows: list[dict[str, object]]
) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_news_em"] = pd.DataFrame(rows)
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(
        _request("news", required_fields=["headline"]), output_ref=OUTPUT_REF
    )
    source = _validate(result, "request-akshare-news")
    assert source.quality == "limited" and source.observed_at is None
    assert source.unknown_reasons["observed_at"]
    assert result["raw_payload"]
    assert result["normalized"]["items"] == []  # type: ignore[index]


def test_three_statements_preserve_report_update_currency_and_partial_failure(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    common = {"报告日": "20251231", "更新日期": "2026-03-20 T18:00:00", "币种": "CNY", "类型": "合并期末"}
    sdk.responses["stock_financial_report_sina:资产负债表"] = pd.DataFrame([{**common, "货币资金": 10}])
    sdk.responses["stock_financial_report_sina:利润表"] = pd.DataFrame([{**common, "营业收入": 20, "净利润": 3}])
    request = _request("statements", parameters={"limit_periods": 4}, required_fields=["income", "balance", "cash"])
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    source = _validate(result, "request-akshare-statements")
    assert source.quality == "limited"
    assert set(result["raw_payload"]) == {"balance", "income"}  # type: ignore[arg-type]
    assert result["normalized"]["successful_statements"] == ["balance", "income"]  # type: ignore[index]
    assert result["normalized"]["failed_statements"] == ["cash"]  # type: ignore[index]
    assert result["normalized"]["point_in_time_status"] == "not_proven"  # type: ignore[index]
    assert result["normalized"]["rows"]["income"][0]["update_date_is_disclosure_time"] is False  # type: ignore[index]
    assert any("cash" in gap["required_content"] for gap in result["gaps"])  # type: ignore[index]


def test_profile_is_income_statement_snapshot_not_new_profile_endpoint(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_financial_report_sina:利润表"] = pd.DataFrame(
        [{"报告日": "20251231", "更新日期": "2026-03-20 T18:00:00", "币种": "CNY", "营业收入": 20, "净利润": 3}]
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(_request("profile"), output_ref=OUTPUT_REF)
    assert _validate(result, "request-akshare-profile").quality == "limited"
    assert result["normalized"]["snapshot_scope"] == "income_statement_only"  # type: ignore[index]
    assert result["normalized"]["revenue"] == {"value": 20.0, "unit": "CNY"}  # type: ignore[index]
    assert [call[0] for call in sdk.calls] == ["stock_financial_report_sina:利润表"]


def test_profile_preserves_negative_net_income_and_marks_historical_limit(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_financial_report_sina:利润表"] = pd.DataFrame(
        [{"报告日": "20251231", "更新日期": "2026-03-20 T18:00:00", "币种": "CNY", "营业收入": 20, "净利润": -3.5}]
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(
        _request("profile", required_fields=["net_income"]), output_ref=OUTPUT_REF
    )
    assert result["normalized"]["net_income"] == {"value": -3.5, "unit": "CNY"}  # type: ignore[index]
    assert result["normalized"]["requested_as_of"] == "2026-01-15T16:00:00+08:00"  # type: ignore[index]
    assert result["normalized"]["usable_for_historical_as_of"] is False  # type: ignore[index]


def test_returned_empty_financial_table_is_not_reported_as_successful(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_financial_report_sina:利润表"] = pd.DataFrame()
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(
        _request("statements", parameters={"statement_types": ["income"]}, required_fields=["income"]),
        output_ref=OUTPUT_REF,
    )
    source = _validate(result, "request-akshare-statements")
    assert source.quality == "limited"
    assert result["normalized"]["returned_statements"] == ["income"]  # type: ignore[index]
    assert result["normalized"]["successful_statements"] == []  # type: ignore[index]
    assert result["normalized"]["empty_or_ineligible_statements"] == ["income"]  # type: ignore[index]
    assert any("income" in gap["required_content"] for gap in result["gaps"])  # type: ignore[index]


def test_beijing_financials_are_explicitly_unsupported_without_sdk_call(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    request = _request("statements", subject={"market": "CN", "exchange": "XBSE", "symbol": "430047", "currency": "CNY"})
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(request, output_ref=OUTPUT_REF)
    assert _validate(result, "request-akshare-statements").quality == "failed"
    assert result["normalized"]["error_reason"] == "unsupported"  # type: ignore[index]
    assert sdk.calls == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"source": "finnhub"}, "unsupported"),
        ({"operation": "accounts"}, "unsupported"),
        ({"parameters": {"start_date": "2026-01-14", "end_date": "2026-01-15", "bar_interval": "1h", "adjustment": "raw"}}, "unsupported"),
        ({"required_fields": ["invented_field"]}, "unsupported"),
    ],
)
def test_unsupported_request_never_calls_sdk(tmp_path: Path, change: dict[str, object], reason: str) -> None:
    sdk = FakeAKShare()
    base = _request("bars", parameters={"start_date": "2026-01-14", "end_date": "2026-01-15", "bar_interval": "1d", "adjustment": "raw"})
    base.update(change)
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(base, output_ref=OUTPUT_REF)
    assert SourceResult.model_validate(result["source_result"]).quality == "failed"
    assert result["normalized"]["error_reason"] == reason  # type: ignore[index]
    assert sdk.calls == []


def test_disabled_source_invalid_output_ref_and_secret_request_never_call_sdk(tmp_path: Path) -> None:
    for adapter, request, output_ref in (
        (AKShareAdapter(_settings(tmp_path, enabled=False), client=FakeAKShare()), _request("quote"), OUTPUT_REF),
        (AKShareAdapter(_settings(tmp_path), client=FakeAKShare()), _request("quote"), "../escape.json"),
        (AKShareAdapter(_settings(tmp_path), client=FakeAKShare()), _request("quote", parameters={"apiKey": "secret"}), OUTPUT_REF),
    ):
        result = adapter.fetch(request, output_ref=output_ref)
        assert SourceResult.model_validate(result["source_result"]).quality == "failed"
        assert adapter._client.calls == []  # type: ignore[attr-defined]


def test_dataframe_values_are_json_safe_without_concealing_unknowns(tmp_path: Path) -> None:
    sdk = FakeAKShare()
    sdk.responses["stock_financial_report_sina:利润表"] = pd.DataFrame(
        [{"报告日": datetime(2025, 12, 31), "更新日期": pd.Timestamp("2026-03-20 18:00"), "币种": "CNY", "营业收入": Decimal("20.25"), "净利润": pd.NA}]
    )
    result = AKShareAdapter(_settings(tmp_path), client=sdk).fetch(_request("profile"), output_ref=OUTPUT_REF)
    raw = result["raw_payload"][0]  # type: ignore[index]
    assert raw["报告日"] == "2025-12-31T00:00:00"
    assert raw["营业收入"] == "20.25"
    assert raw["净利润"] is None
    assert result["normalized"]["report_date"] == "2025-12-31"  # type: ignore[index]
    assert result["normalized"]["net_income"]["value"] is None  # type: ignore[index]
    assert result["normalized"]["net_income"]["unknown_reason"]  # type: ignore[index]
