"""Offline-testable adapter for the approved AKShare China data routes.

AKShare is an optional SDK.  The adapter keeps the concrete scraped source,
provider units, raw rows, and unknown source times visible; persistence belongs
to the source router.
"""

from __future__ import annotations

import importlib
import hashlib
import math
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import ValidationError

from cash_research.artifacts import ArtifactError, reject_secrets, safe_relative_path
from cash_research.config import Settings
from cash_research.models import DataGap, Evidence, SecurityIdentity, SourceResult


_CN_TZ = ZoneInfo("Asia/Shanghai")
_SYMBOL = re.compile(r"^[0-9]{6}$")
_OPERATIONS = frozenset({"quote", "bars", "news", "profile", "statements"})
_FIELDS: dict[str, frozenset[str]] = {
    "quote": frozenset(
        {"current_price", "bid", "ask", "open", "high", "low", "volume", "currency", "observed_at"}
    ),
    "bars": frozenset({"ohlcv", "adjustment_status", "market_date", "turnover", "amount"}),
    "news": frozenset({"headline", "published_at", "source", "url", "content"}),
    "profile": frozenset({"revenue", "net_income", "reported_currency", "report_date"}),
    "statements": frozenset({"income", "balance", "cash", "report_date", "update_date", "currency"}),
}
_PARAMETERS: dict[str, frozenset[str]] = {
    "quote": frozenset(),
    "bars": frozenset({"start_date", "end_date", "bar_interval", "adjustment"}),
    "news": frozenset({"limit"}),
    "profile": frozenset({"limit_periods"}),
    "statements": frozenset({"limit_periods", "statement_types"}),
}
_STATEMENTS = {
    "balance": "资产负债表",
    "income": "利润表",
    "cash": "现金流量表",
}


class AKShareAdapter:
    """Use an injected AKShare-compatible SDK in tests or the optional SDK at runtime."""

    def __init__(self, settings: Settings, client: object | None = None) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
        else:
            try:
                self._client = importlib.import_module("akshare")
            except ImportError:
                self._client = None

    def fetch(
        self, request: Mapping[str, object], *, output_ref: str
    ) -> dict[str, object]:
        request_id = _safe_request_id(request)
        subject: SecurityIdentity | str = "invalid request subject"
        try:
            reject_secrets(request)
            request_id, operation, subject, as_of, parameters, required_fields = _validate_request(
                request
            )
            safe_relative_path(self._settings.root, output_ref, must_exist=False)
        except (ArtifactError, ValidationError, TypeError, ValueError):
            return _failure(
                request_id=request_id,
                operation=str(request.get("operation") or "unknown"),
                subject=subject,
                reason="invalid",
                coverage="request failed source-contract validation before any SDK call",
            )

        if request.get("source") != "akshare" or "akshare" not in self._settings.enabled_sources:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="unsupported",
                coverage="AKShare is not enabled for this request",
            )
        if operation not in _OPERATIONS:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="unsupported",
                coverage="operation is outside the approved AKShare read-only adapter",
            )
        if self._client is None:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="external",
                coverage="optional AKShare SDK is unavailable",
            )

        unknown_parameters = set(parameters) - _PARAMETERS[operation]
        unknown_fields = set(required_fields) - _FIELDS[operation]
        if unknown_parameters or unknown_fields:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="unsupported",
                coverage="request asks for parameters or fields outside this approved operation",
            )

        try:
            _validate_identity(subject)
        except ValueError:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="invalid",
                coverage="subject is not an exchange-consistent mainland China six-digit security",
            )

        if operation in {"profile", "statements"} and subject.exchange == "XBSE":
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="unsupported",
                coverage="approved Sina financial statements support Shanghai and Shenzhen identifiers only",
            )

        if operation == "quote":
            return self._quote(request_id, subject, as_of, output_ref, required_fields)
        if operation == "bars":
            return self._bars(request_id, subject, as_of, parameters, output_ref, required_fields)
        if operation == "news":
            return self._news(request_id, subject, as_of, parameters, output_ref, required_fields)
        return self._financials(
            request_id, operation, subject, as_of, parameters, output_ref, required_fields
        )

    def _quote(
        self,
        request_id: str,
        subject: SecurityIdentity,
        as_of: datetime,
        output_ref: str,
        required_fields: tuple[str, ...],
    ) -> dict[str, object]:
        attempts: list[dict[str, object]] = []
        stages = (
            ("stock_bid_ask_em", {"symbol": subject.symbol}),
            ("stock_zh_a_spot_em", {}),
            ("stock_zh_a_spot", {}),
            ("stock_zh_a_spot_tx", {}),
        )
        for endpoint, kwargs in stages:
            at = _utc_now()
            fn = getattr(self._client, endpoint, None)
            if not callable(fn):
                attempts.append(_attempt(endpoint, "unavailable", at))
                continue
            try:
                raw = _records(fn(**kwargs))
                retrieved_at = _utc_now()
                reject_secrets(raw)
                normalized = _normalize_quote(endpoint, raw, subject)
                if normalized is None:
                    attempts.append(_attempt(endpoint, "invalid_or_empty", retrieved_at))
                    continue
            except Exception:
                attempts.append(_attempt(endpoint, "external_failure", _utc_now()))
                continue

            errors = ("primary_endpoint_failed",) if attempts else ()
            gaps: list[DataGap] = []
            if attempts:
                gaps.append(
                    _gap(
                        request_id,
                        "preferred direct quote endpoint",
                        attempts,
                        "quote came from a fallback with different field coverage",
                        "retain the actual fallback source and recheck the direct endpoint later",
                    )
                )
            missing = _missing_quote_fields(normalized, required_fields)
            if missing:
                gaps.append(
                    _gap(
                        request_id,
                        f"requested quote fields: {', '.join(missing)}",
                        [_attempt(endpoint, "missing_fields", retrieved_at)],
                        "the quote is usable only for the fields actually returned",
                        "retain nulls and use another approved evidence path for missing fields",
                    )
                )
            gaps.append(
                _gap(
                    request_id,
                    "quote value at the requested as_of cutoff",
                    [_attempt(endpoint, "provider_event_time_unknown", retrieved_at)],
                    "the current quote cannot be treated as a historical quote without a provider event time",
                    "use the approved daily-history path for a historical market date",
                    prefix="G-02",
                )
            )
            source = SourceResult(
                source="akshare",
                operation="quote",
                security_or_topic=subject,
                observed_at=None,
                retrieved_at=retrieved_at,
                available_at=None,
                coverage=f"one current quote row via {endpoint}; provider event time is unavailable",
                payload_ref=output_ref,
                quality="limited",
                errors=errors,
                unknown_reasons={
                    "observed_at": "selected AKShare quote route provides no reliable event timestamp",
                    "available_at": "source-specific availability timestamp is not returned",
                },
            )
            normalized.update(
                {
                    "raw_locator": "",
                    "actual_source": f"akshare:{endpoint}",
                    "identity": subject.model_dump(mode="json"),
                    "sdk_version": _sdk_version(self._client),
                    "attempted_endpoints": [item["endpoint"] for item in attempts] + [endpoint],
                    "requested_as_of": as_of.isoformat(),
                    "current_quote_only": True,
                    "usable_for_historical_as_of": False,
                    "historical_eligibility": "unknown_provider_event_time",
                }
            )
            return _result(source, raw, normalized, gaps=gaps)

        return _failure(
            request_id=request_id,
            operation="quote",
            subject=subject,
            reason="external",
            coverage="all approved AKShare quote routes failed or returned no usable matching row",
            attempts=attempts,
        )

    def _bars(
        self,
        request_id: str,
        subject: SecurityIdentity,
        as_of: datetime,
        parameters: dict[str, object],
        output_ref: str,
        required_fields: tuple[str, ...],
    ) -> dict[str, object]:
        try:
            start = _parse_date(parameters.get("start_date"), "start_date")
            end = _parse_date(parameters.get("end_date"), "end_date")
            interval = parameters.get("bar_interval", "1d")
            adjustment = parameters.get("adjustment", "raw")
            if start > end:
                raise ValueError("inverted range")
        except (TypeError, ValueError):
            return _failure(
                request_id=request_id,
                operation="bars",
                subject=subject,
                reason="invalid",
                coverage="daily bar date range is invalid",
            )
        if interval != "1d":
            return _failure(
                request_id=request_id,
                operation="bars",
                subject=subject,
                reason="unsupported",
                coverage="AKShare adapter supports approved daily history only",
            )
        if adjustment not in {"raw", "qfq", "hfq"}:
            return _failure(
                request_id=request_id,
                operation="bars",
                subject=subject,
                reason="invalid",
                coverage="adjustment must be raw, qfq, or hfq",
            )

        sdk_adjust = "" if adjustment == "raw" else str(adjustment)
        attempts: list[dict[str, object]] = []
        empty_endpoint: str | None = None
        stages = (
            (
                "stock_zh_a_hist",
                {
                    "symbol": subject.symbol,
                    "period": "daily",
                    "start_date": start.strftime("%Y%m%d"),
                    "end_date": end.strftime("%Y%m%d"),
                    "adjust": sdk_adjust,
                },
                "eastmoney",
            ),
            (
                "stock_zh_a_hist_tx",
                {
                    "symbol": _prefixed_symbol(subject),
                    "start_date": start.strftime("%Y%m%d"),
                    "end_date": end.strftime("%Y%m%d"),
                    "adjust": sdk_adjust,
                },
                "tencent",
            ),
        )
        for endpoint, kwargs, basis in stages:
            fn = getattr(self._client, endpoint, None)
            at = _utc_now()
            if not callable(fn):
                attempts.append(_attempt(endpoint, "unavailable", at))
                continue
            try:
                raw = _records(fn(**kwargs))
                retrieved_at = _utc_now()
                reject_secrets(raw)
            except Exception:
                attempts.append(_attempt(endpoint, "external_failure", _utc_now()))
                continue
            if not raw:
                attempts.append(_attempt(endpoint, "empty", retrieved_at))
                empty_endpoint = endpoint
                continue

            rows, row_gaps, excluded_cutoff, excluded_range = _normalize_bars(
                raw,
                request_id=request_id,
                basis=basis,
                subject=subject,
                start=start,
                end=end,
                as_of=as_of,
            )
            unresolved_duplicates = any(
                "duplicate or conflicting" in gap.required_content for gap in row_gaps
            )
            if not rows and not unresolved_duplicates:
                attempts.append(_attempt(endpoint, "no_valid_rows", retrieved_at))
                continue
            gaps = list(row_gaps)
            errors: list[str] = []
            if unresolved_duplicates:
                errors.append("revision_conflict")
            if attempts:
                errors.append("primary_endpoint_failed")
                gaps.append(
                    _gap(
                        request_id,
                        "preferred East Money daily history",
                        attempts,
                        "daily bars came from the Tencent fallback",
                        "retain Tencent units and recheck the preferred endpoint later",
                    )
                )
            gaps.append(
                _gap(
                    request_id,
                    "immutable point-in-time adjusted history",
                    [_attempt(endpoint, "current_history_only", retrieved_at)],
                    "qfq/hfq history may revise after later corporate actions",
                    "record G-02 and obtain a dated historical snapshot when PIT is required",
                    prefix="G-02",
                )
            )
            missing_bar_fields = _missing_bar_fields(rows, required_fields)
            if missing_bar_fields:
                gaps.append(
                    _gap(
                        request_id,
                        f"requested bar fields: {', '.join(missing_bar_fields)}",
                        [_attempt(endpoint, "missing_fields", retrieved_at)],
                        "one or more requested values are absent from normalized rows",
                        "retain unknown values and obtain the missing field from an approved path",
                    )
                )
            source = SourceResult(
                source="akshare",
                operation="bars",
                security_or_topic=subject,
                observed_at=None,
                retrieved_at=retrieved_at,
                available_at=None,
                coverage=(
                    f"requested {start.isoformat()} through {end.isoformat()}; "
                    f"{len(rows)} of {len(raw)} raw rows normalized"
                ),
                payload_ref=output_ref,
                quality="limited",
                errors=tuple(errors),
                unknown_reasons={
                    "observed_at": "daily source rows contain market dates, not event instants",
                    "available_at": "row-specific provider availability timestamps are not returned",
                },
            )
            return _result(
                source,
                raw,
                {
                    "raw_locator": "",
                    "actual_source": f"akshare:{endpoint}",
                    "identity": subject.model_dump(mode="json"),
                    "sdk_version": _sdk_version(self._client),
                    "market_timezone": "Asia/Shanghai",
                    "bar_interval": "1d",
                    "requested_start_date": start.isoformat(),
                    "requested_end_date": end.isoformat(),
                    "as_of": as_of.isoformat(),
                    "excluded_after_cutoff": excluded_cutoff,
                    "excluded_outside_range": excluded_range,
                    "price_basis": str(adjustment),
                    "volume_basis": "raw_provider_volume",
                    "adjustment_status": {
                        "basis": str(adjustment),
                        "provider": "East Money" if basis == "eastmoney" else "Tencent",
                        "history": "provider_history_may_revise_after_corporate_actions",
                        "point_in_time_status": "not_proven",
                    },
                    "revision_status": (
                        "unresolved"
                        if unresolved_duplicates
                        else "current_provider_view"
                    ),
                    "rows": rows,
                },
                gaps=gaps,
            )

        if empty_endpoint is not None:
            retrieved_at = _utc_now()
            source = SourceResult(
                source="akshare",
                operation="bars",
                security_or_topic=subject,
                observed_at=None,
                retrieved_at=retrieved_at,
                available_at=None,
                coverage=f"valid empty daily-history response via {empty_endpoint}",
                payload_ref=output_ref,
                quality="limited",
                errors=(),
                unknown_reasons={
                    "observed_at": "no daily rows returned",
                    "available_at": "no daily rows returned",
                },
            )
            return _result(
                source,
                [],
                {
                    "raw_locator": "",
                    "actual_source": f"akshare:{empty_endpoint}",
                    "error_reason": "empty",
                    "empty_is_failure": False,
                    "rows": [],
                },
                gaps=[
                    _gap(
                        request_id,
                        "daily rows for requested coverage",
                        attempts,
                        "no daily row was returned; this is distinct from retrieval failure",
                        "report the coverage gap and retry or use another approved path",
                    )
                ],
            )
        return _failure(
            request_id=request_id,
            operation="bars",
            subject=subject,
            reason="external",
            coverage="all approved AKShare daily-history routes failed or returned no usable rows",
            attempts=attempts,
        )

    def _news(
        self,
        request_id: str,
        subject: SecurityIdentity,
        as_of: datetime,
        parameters: dict[str, object],
        output_ref: str,
        required_fields: tuple[str, ...],
    ) -> dict[str, object]:
        limit = parameters.get("limit", 100)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                reason="invalid",
                coverage="news limit must be an integer from 1 through the documented maximum 100",
            )
        fn = getattr(self._client, "stock_news_em", None)
        if not callable(fn):
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                reason="external",
                coverage="approved AKShare company-news function is unavailable",
            )
        attempted_at = _utc_now()
        try:
            raw = _records(fn(symbol=subject.symbol))
            retrieved_at = _utc_now()
            reject_secrets(raw)
        except Exception:
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                reason="external",
                coverage="AKShare company-news retrieval failed",
                attempts=[_attempt("stock_news_em", "external_failure", _utc_now())],
            )
        if not raw:
            source = SourceResult(
                source="akshare",
                operation="news",
                security_or_topic=subject,
                observed_at=None,
                retrieved_at=retrieved_at,
                available_at=None,
                coverage="valid empty current-day latest-news response",
                payload_ref=output_ref,
                quality="limited",
                errors=(),
                unknown_reasons={"observed_at": "no news rows returned", "available_at": "no news rows returned"},
            )
            return _result(
                source,
                [],
                {
                    "raw_locator": "",
                    "actual_source": "akshare:stock_news_em",
                    "error_reason": "empty",
                    "empty_is_failure": False,
                    "documented_limit": "current-day latest 100 items",
                    "items": [],
                },
                gaps=[
                    _gap(
                        request_id,
                        "current company news",
                        [_attempt("stock_news_em", "valid_empty", attempted_at)],
                        "no current-day news item was returned; this is distinct from retrieval failure",
                        "report no new item and retain the source coverage limit",
                    )
                ],
            )

        items: list[dict[str, object]] = []
        evidence: list[Evidence] = []
        invalid = 0
        after_cutoff = 0
        for raw_index, row in enumerate(raw):
            headline = _text(row.get("新闻标题"))
            published = _china_datetime(row.get("发布时间"))
            url = _text(row.get("新闻链接"))
            if not headline or not published or not url:
                invalid += 1
                continue
            if published > as_of.astimezone(_CN_TZ):
                after_cutoff += 1
                continue
            if len(items) >= limit:
                continue
            item = {
                "raw_index": raw_index,
                "headline": headline,
                "content": _text(row.get("新闻内容")),
                "published_at": published.isoformat(),
                "source": _text(row.get("文章来源")),
                "url": url,
                "keyword": _text(row.get("关键词")),
                "available_at": None,
                "available_at_unknown_reason": "provider exposes publication text but no availability timestamp",
            }
            items.append(item)
            evidence.append(
                Evidence(
                    evidence_id=f"{request_id}-news-{len(items)}",
                    source_ref=output_ref,
                    locator=f"/{raw_index}",
                    published_at=published.astimezone(timezone.utc),
                    retrieved_at=retrieved_at,
                    available_at=None,
                    content_kind="third_party_view",
                    claim=headline,
                    scope=subject.canonical_id,
                    units=(),
                    limitations=(
                        "East Money search result; full article review is not claimed",
                        "endpoint documents current-day latest 100 items, not complete history",
                    ),
                    unknown_reasons={"available_at": "source does not return an availability timestamp"},
                )
            )
        gaps: list[DataGap] = []
        if invalid or after_cutoff:
            gaps.append(
                _gap(
                    request_id,
                    "news rows valid at the requested cutoff",
                    [_attempt("stock_news_em", "partial_rows", retrieved_at)],
                    f"excluded {invalid} invalid and {after_cutoff} post-cutoff rows",
                    "retain raw rows and use only rows with valid source publication times",
                )
            )
        missing_news_fields = _missing_news_fields(items, required_fields)
        if missing_news_fields:
            gaps.append(
                _gap(
                    request_id,
                    f"requested news fields: {', '.join(missing_news_fields)}",
                    [_attempt("stock_news_em", "missing_fields", retrieved_at)],
                    "usable news rows lack one or more requested fields",
                    "retain nulls and review the underlying article or another approved evidence path",
                )
            )
        observed_at = max((item.published_at for item in evidence), default=None)
        unknown_reasons = {
            "available_at": "source does not return an availability timestamp"
        }
        if observed_at is None:
            unknown_reasons["observed_at"] = "no usable publication time at the requested cutoff"
        source = SourceResult(
            source="akshare",
            operation="news",
            security_or_topic=subject,
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            available_at=None,
            coverage=f"{len(items)} usable items from {len(raw)} raw latest-news rows",
            payload_ref=output_ref,
            quality="limited",
            errors=("partial_rows",) if invalid or after_cutoff else (),
            unknown_reasons=unknown_reasons,
        )
        return _result(
            source,
            raw,
            {
                "raw_locator": "",
                "actual_source": "akshare:stock_news_em",
                "identity": subject.model_dump(mode="json"),
                "sdk_version": _sdk_version(self._client),
                "documented_limit": "current-day latest 100 items",
                "excluded_after_cutoff": after_cutoff,
                "invalid_rows": invalid,
                "items": items,
            },
            evidence=evidence,
            gaps=gaps,
        )

    def _financials(
        self,
        request_id: str,
        operation: str,
        subject: SecurityIdentity,
        as_of: datetime,
        parameters: dict[str, object],
        output_ref: str,
        required_fields: tuple[str, ...],
    ) -> dict[str, object]:
        limit = parameters.get("limit_periods", 8)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="invalid",
                coverage="limit_periods must be an integer from 1 through 100",
            )
        if operation == "profile":
            names = ["income"]
        else:
            requested = parameters.get("statement_types", list(_STATEMENTS))
            if not isinstance(requested, list) or not requested or any(
                not isinstance(item, str) or item not in _STATEMENTS for item in requested
            ):
                return _failure(
                    request_id=request_id,
                    operation=operation,
                    subject=subject,
                    reason="invalid",
                    coverage="statement_types must select income, balance, and/or cash",
                )
            names = list(dict.fromkeys(requested))
        fn = getattr(self._client, "stock_financial_report_sina", None)
        if not callable(fn):
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="external",
                coverage="approved Sina financial-report function is unavailable",
            )

        raw_by_kind: dict[str, list[dict[str, object]]] = {}
        normalized_by_kind: dict[str, list[dict[str, object]]] = {}
        attempts: list[dict[str, object]] = []
        failed: list[str] = []
        retrieved_at = _utc_now()
        for name in names:
            label = _STATEMENTS[name]
            at = _utc_now()
            try:
                rows = _records(fn(stock=_prefixed_symbol(subject), symbol=label))
                retrieved_at = _utc_now()
                reject_secrets(rows)
            except Exception:
                failed.append(name)
                attempts.append(_attempt(f"stock_financial_report_sina:{label}", "external_failure", _utc_now()))
                continue
            raw_by_kind[name] = rows
            normalized_rows = _normalize_financial_rows(rows, as_of, limit)
            normalized_by_kind[name] = normalized_rows
            if not normalized_rows:
                attempts.append(_attempt(f"stock_financial_report_sina:{label}", "empty_or_no_eligible_rows", at))

        if not raw_by_kind:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                reason="external",
                coverage="all requested Sina financial-report reads failed",
                attempts=attempts,
            )

        usable = [name for name in names if normalized_by_kind.get(name)]
        empty_or_ineligible = [name for name in names if name in raw_by_kind and name not in usable]
        unavailable = list(dict.fromkeys([*failed, *empty_or_ineligible]))
        gaps: list[DataGap] = []
        if unavailable:
            gaps.append(
                _gap(
                    request_id,
                    "all requested financial statements",
                    attempts,
                    f"missing usable statement types: {', '.join(unavailable)}",
                    "retain successful statements and retry missing approved statement types",
                )
            )
        gaps.append(
            _gap(
                request_id,
                "point-in-time financial disclosure availability",
                [_attempt("stock_financial_report_sina", "current_snapshot_only", retrieved_at)],
                "update date is retained but is not treated as a proven disclosure-availability timestamp",
                "use an original filing with a validated publication time when PIT is required",
                prefix="G-02",
            )
        )
        source = SourceResult(
            source="akshare",
            operation=operation,
            security_or_topic=subject,
            observed_at=None,
            retrieved_at=retrieved_at,
            available_at=None,
            coverage=(
                f"{len(raw_by_kind)} returned and {len(usable)} usable of {len(names)} requested Sina financial tables; "
                "historical availability is not proven"
            ),
            payload_ref=output_ref,
            quality="limited",
            errors=("partial_statements",) if unavailable else (),
            unknown_reasons={
                "observed_at": "report dates are periods, not observation instants",
                "available_at": "Sina update date is not accepted as proven disclosure availability",
            },
        )
        common: dict[str, object] = {
            "raw_locator": "",
            "actual_source": "akshare:stock_financial_report_sina",
            "identity": subject.model_dump(mode="json"),
            "sdk_version": _sdk_version(self._client),
            "point_in_time_status": "not_proven",
            "requested_as_of": as_of.isoformat(),
            "eligibility_basis": "report_period_only",
            "usable_for_historical_as_of": False,
            "update_date_semantics": "provider_update_field_retained_not_disclosure_time",
            "returned_statements": list(raw_by_kind),
            "successful_statements": usable,
            "failed_statements": failed,
            "empty_or_ineligible_statements": empty_or_ineligible,
            "rows": normalized_by_kind,
        }
        if operation == "profile":
            rows = normalized_by_kind.get("income", [])
            latest = rows[0] if rows else {}
            common.update(
                {
                    "snapshot_scope": "income_statement_only",
                    "report_date": latest.get("report_date"),
                    "reported_currency": latest.get("currency"),
                    "revenue": _financial_quantity(latest.get("raw", {}), "营业收入", "营业总收入", unit=latest.get("currency")),
                    "net_income": _financial_quantity(latest.get("raw", {}), "净利润", "归属于母公司股东的净利润", unit=latest.get("currency")),
                }
            )
            raw_payload: object = raw_by_kind.get("income", [])
        else:
            raw_payload = raw_by_kind
        missing_financial_fields = _missing_financial_fields(
            operation, common, required_fields
        )
        if missing_financial_fields:
            gaps.append(
                _gap(
                    request_id,
                    f"requested financial fields: {', '.join(missing_financial_fields)}",
                    [_attempt("stock_financial_report_sina", "missing_fields", retrieved_at)],
                    "one or more requested financial fields or statements are unavailable",
                    "retain successful tables and obtain the missing filing content from an approved path",
                )
            )
        return _result(source, raw_payload, common, gaps=gaps)


def _validate_request(
    request: Mapping[str, object],
) -> tuple[str, str, SecurityIdentity, datetime, dict[str, object], tuple[str, ...]]:
    required = {"request_id", "source", "operation", "subject", "as_of", "parameters", "required_fields"}
    if not required <= set(request):
        raise ValueError("missing request keys")
    request_id = request["request_id"]
    operation = request["operation"]
    parameters = request["parameters"]
    fields = request["required_fields"]
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("invalid request id")
    if not isinstance(operation, str):
        raise ValueError("invalid operation")
    if not isinstance(parameters, dict):
        raise ValueError("invalid parameters")
    if not isinstance(fields, list) or any(not isinstance(item, str) for item in fields):
        raise ValueError("invalid required fields")
    subject = SecurityIdentity.model_validate(request["subject"])
    as_of = _parse_datetime(request["as_of"])
    return request_id, operation, subject, as_of, dict(parameters), tuple(fields)


def _validate_identity(subject: SecurityIdentity) -> None:
    if subject.market != "CN" or subject.currency != "CNY" or not _SYMBOL.fullmatch(subject.symbol):
        raise ValueError("invalid China identity")
    prefix = subject.symbol[0]
    expected = (
        "XSHG"
        if prefix == "6"
        else "XSHE"
        if prefix in {"0", "3"}
        else "XBSE"
        if prefix in {"4", "8"} or subject.symbol.startswith("92")
        else None
    )
    if expected is None or subject.exchange != expected:
        raise ValueError("exchange and symbol prefix conflict")


def _prefixed_symbol(subject: SecurityIdentity) -> str:
    return {"XSHG": "sh", "XSHE": "sz", "XBSE": "bj"}[str(subject.exchange)] + subject.symbol


def _normalize_quote(
    endpoint: str, rows: list[dict[str, object]], subject: SecurityIdentity
) -> dict[str, object] | None:
    if endpoint == "stock_bid_ask_em":
        values = {_text(row.get("item")): row.get("value") for row in rows}
        row = values
        last = _number(_first(row, "最新", "最新价", "last", "close"), positive=True)
        bid = _number(_first(row, "buy_1", "买一"), positive=True)
        ask = _number(_first(row, "sell_1", "卖一"), positive=True)
        volume_value = _number(_first(row, "总手", "volume"), positive=False)
        volume = _volume(volume_value, "lots", factor=100)
    else:
        match = _match_security(rows, subject.symbol)
        if match is None:
            return None
        row = match
        last = _number(_first(row, "最新价", "最新", "zxj", "last", "trade", "close"), positive=True)
        bid = _number(_first(row, "买入", "买1", "bid", "buy"), positive=True)
        ask = _number(_first(row, "卖出", "卖1", "ask", "sell"), positive=True)
        volume_value = _number(_first(row, "成交量", "volume"), positive=False)
        if endpoint == "stock_zh_a_spot_em":
            volume = _volume(volume_value, "lots", factor=100)
        else:
            volume = {
                "value": volume_value,
                "unit": "unknown_provider_volume_unit",
                "unknown_reason": "fallback quote documentation does not establish a shared volume unit",
            }
    if last is None:
        return None
    return {
        "current_price": {"value": last, "unit": "currency_per_share", "currency": "CNY"},
        "bid": _price(bid),
        "ask": _price(ask),
        "open": _price(_number(_first(row, "今开", "开盘", "open"), positive=True)),
        "high": _price(_number(_first(row, "最高", "high"), positive=True)),
        "low": _price(_number(_first(row, "最低", "low"), positive=True)),
        "volume": volume,
        "event_time": None,
        "event_time_unknown_reason": "provider route has no reliable quote event timestamp",
    }


def _normalize_bars(
    raw: list[dict[str, object]],
    *,
    request_id: str,
    basis: str,
    subject: SecurityIdentity,
    start: date,
    end: date,
    as_of: datetime,
) -> tuple[list[dict[str, object]], list[DataGap], int, int]:
    rows: list[dict[str, object]] = []
    invalid: list[int] = []
    after_cutoff = 0
    outside = 0
    cutoff = as_of.astimezone(_CN_TZ).date()
    for raw_index, row in enumerate(raw):
        if basis == "eastmoney":
            row_symbol = _text(row.get("股票代码"))
            if row_symbol and row_symbol != subject.symbol:
                invalid.append(raw_index)
                continue
            market_date = _date_value(row.get("日期"))
            open_value = _number(row.get("开盘"), positive=True)
            high = _number(row.get("最高"), positive=True)
            low = _number(row.get("最低"), positive=True)
            close = _number(row.get("收盘"), positive=True)
            volume = _volume(_number(row.get("成交量"), positive=False), "lots", factor=100)
            amount = _number(row.get("成交额"), positive=False)
            turnover = _number(row.get("换手率"), positive=False)
            turnover_value = {"value": turnover, "unit": "percent"}
        else:
            market_date = _date_value(row.get("date"))
            open_value = _number(row.get("open"), positive=True)
            high = _number(row.get("high"), positive=True)
            low = _number(row.get("low"), positive=True)
            close = _number(row.get("close"), positive=True)
            volume = _volume(_number(row.get("volume"), positive=False), "shares", factor=1)
            amount = _number(row.get("amount"), positive=False)
            turnover = _number(row.get("turnover"), positive=False)
            turnover_value = {"value": turnover, "unit": "fraction"}
        if market_date is None:
            invalid.append(raw_index)
            continue
        if market_date < start or market_date > end:
            outside += 1
            continue
        if market_date > cutoff:
            after_cutoff += 1
            continue
        if None in {open_value, high, low, close} or low > high or not (low <= open_value <= high) or not (low <= close <= high):
            invalid.append(raw_index)
            continue
        rows.append(
            {
                "raw_index": raw_index,
                "market_date": market_date.isoformat(),
                "open": {"value": open_value, "unit": "currency_per_share", "currency": "CNY"},
                "high": {"value": high, "unit": "currency_per_share", "currency": "CNY"},
                "low": {"value": low, "unit": "currency_per_share", "currency": "CNY"},
                "close": {"value": close, "unit": "currency_per_share", "currency": "CNY"},
                "volume": volume,
                "amount": {"value": amount, "unit": "CNY"},
                "turnover": turnover_value,
                "observed_at": None,
                "observed_at_unknown_reason": "daily source supplies a market date, not an instant",
            }
        )
    gaps: list[DataGap] = []
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row["market_date"])
        counts[key] = counts.get(key, 0) + 1
    duplicate_dates = sorted(key for key, count in counts.items() if count > 1)
    if duplicate_dates:
        rows = [row for row in rows if str(row["market_date"]) not in duplicate_dates]
        gaps.append(
            _gap(
                request_id,
                "daily rows without duplicate or conflicting market dates",
                [_attempt("daily_history", "revision_conflict", _utc_now())],
                f"excluded unresolved duplicate dates: {', '.join(duplicate_dates)}",
                "retain raw rows and resolve the source revision before using those dates",
            )
        )
    rows.sort(key=lambda item: str(item["market_date"]))
    if invalid:
        now = _utc_now()
        gaps.append(
            _gap(
                request_id,
                "valid daily OHLC rows",
                [_attempt("daily_history", "invalid_rows", now)],
                f"raw row indexes failed identity, numeric, or OHLC checks: {invalid}",
                "retain raw rows and exclude invalid rows from calculations",
            )
        )
    return rows, gaps, after_cutoff, outside


def _normalize_financial_rows(
    rows: list[dict[str, object]], as_of: datetime, limit: int
) -> list[dict[str, object]]:
    cutoff = as_of.astimezone(_CN_TZ).date()
    normalized: list[dict[str, object]] = []
    for raw_index, row in enumerate(rows):
        report_date = _compact_date(row.get("报告日"))
        if report_date is None or report_date > cutoff:
            continue
        normalized.append(
            {
                "raw_index": raw_index,
                "report_date": report_date.isoformat(),
                "update_date": _text(row.get("更新日期")),
                "update_date_is_disclosure_time": False,
                "currency": _text(row.get("币种")),
                "statement_type": _text(row.get("类型")),
                "raw": row,
            }
        )
    normalized.sort(key=lambda item: str(item["report_date"]), reverse=True)
    return normalized[:limit]


def _financial_quantity(raw: object, *names: str, unit: object) -> dict[str, object]:
    mapping = raw if isinstance(raw, Mapping) else {}
    value = _signed_number(_first(mapping, *names))
    if value is None:
        return {"value": None, "unit": unit or "unknown_currency", "unknown_reason": "field absent or non-numeric in the selected income statement row"}
    return {"value": value, "unit": unit or "unknown_currency"}


def _missing_quote_fields(
    normalized: Mapping[str, object], required_fields: tuple[str, ...]
) -> list[str]:
    missing: list[str] = []
    for field in required_fields:
        if field == "currency":
            continue
        if field == "observed_at":
            missing.append(field)
            continue
        value = normalized.get(field)
        if value is None or (isinstance(value, Mapping) and value.get("value") is None):
            missing.append(field)
    return missing


def _missing_bar_fields(
    rows: list[dict[str, object]], required_fields: tuple[str, ...]
) -> list[str]:
    missing: list[str] = []
    for field in required_fields:
        if field in {"adjustment_status", "market_date"}:
            continue
        if field == "ohlcv":
            if any(
                not isinstance(row.get("volume"), Mapping)
                or row["volume"].get("value") is None  # type: ignore[union-attr]
                for row in rows
            ):
                missing.append("ohlcv.volume")
            continue
        if any(
            not isinstance(row.get(field), Mapping)
            or row[field].get("value") is None  # type: ignore[union-attr]
            for row in rows
        ):
            missing.append(field)
    return missing


def _missing_news_fields(
    items: list[dict[str, object]], required_fields: tuple[str, ...]
) -> list[str]:
    if not items:
        return list(required_fields)
    return [field for field in required_fields if any(not item.get(field) for item in items)]


def _missing_financial_fields(
    operation: str,
    normalized: Mapping[str, object],
    required_fields: tuple[str, ...],
) -> list[str]:
    if operation == "profile":
        missing: list[str] = []
        for field in required_fields:
            value = normalized.get(field)
            if value is None or (isinstance(value, Mapping) and value.get("value") is None):
                missing.append(field)
        return missing
    successful = set(normalized.get("successful_statements", []))
    missing = [field for field in required_fields if field in _STATEMENTS and field not in successful]
    rows = normalized.get("rows")
    flat_rows: list[Mapping[str, object]] = []
    if isinstance(rows, Mapping):
        for table in rows.values():
            if isinstance(table, list):
                flat_rows.extend(item for item in table if isinstance(item, Mapping))
    field_names = {"report_date": "report_date", "update_date": "update_date", "currency": "currency"}
    for field, key in field_names.items():
        if field in required_fields and (not flat_rows or any(not row.get(key) for row in flat_rows)):
            missing.append(field)
    return list(dict.fromkeys(missing))


def _result(
    source: SourceResult,
    raw_payload: object,
    normalized: dict[str, object],
    *,
    evidence: list[Evidence] | None = None,
    gaps: list[DataGap] | None = None,
) -> dict[str, object]:
    return {
        "source_result": source.model_dump(mode="json"),
        "raw_payload": raw_payload,
        "normalized": normalized,
        "evidence": [item.model_dump(mode="json") for item in evidence or []],
        "gaps": [item.model_dump(mode="json") for item in gaps or []],
    }


def _failure(
    *,
    request_id: str,
    operation: str,
    subject: SecurityIdentity | str,
    reason: str,
    coverage: str,
    attempts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    retrieved_at = _utc_now()
    source = SourceResult(
        source="akshare",
        operation=operation,
        security_or_topic=subject,
        observed_at=None,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage=coverage,
        payload_ref=None,
        quality="failed",
        errors=(reason,),
        unknown_reasons={"observed_at": "no usable source result", "available_at": "no usable source result"},
    )
    gap = _gap(
        request_id,
        f"usable {operation} source result",
        attempts or [_attempt("request_boundary", reason, retrieved_at)],
        coverage,
        "report the limitation and retry or use another approved evidence path",
    )
    return _result(
        source,
        None,
        {"raw_locator": None, "error_reason": reason},
        gaps=[gap],
    )


def _gap(
    request_id: str,
    required_content: str,
    attempts: list[dict[str, object]],
    impact: str,
    next_action: str,
    *,
    prefix: str = "G-01",
) -> DataGap:
    digest = hashlib.sha256(f"{required_content}\0{impact}".encode("utf-8")).hexdigest()[:8]
    return DataGap(
        gap_id=f"{prefix}-{request_id}-{digest}",
        request_id=request_id,
        required_content=required_content,
        attempts=tuple(attempts),
        impact=impact,
        next_action=next_action,
    )


def _attempt(endpoint: str, outcome: str, at: datetime) -> dict[str, object]:
    return {"source": "akshare", "endpoint": endpoint, "outcome": outcome, "at": at.isoformat()}


def _records(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [_json_safe_mapping(value)]
    if isinstance(value, list):
        return [_json_safe_mapping(item) for item in value if isinstance(item, Mapping)]
    if hasattr(value, "to_dict"):
        raw = value.to_dict(orient="records")  # type: ignore[call-arg]
        return [_json_safe_mapping(item) for item in raw if isinstance(item, Mapping)]
    raise ValueError("unrecognized AKShare table shape")


def _json_safe_mapping(value: Mapping[object, object]) -> dict[str, object]:
    return {str(key): _json_safe(item) for key, item in value.items()}


def _json_safe(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            return str(value)
    return value


def _match_security(rows: list[dict[str, object]], symbol: str) -> dict[str, object] | None:
    allowed = {symbol, f"sh{symbol}", f"sz{symbol}", f"bj{symbol}"}
    for row in rows:
        value = _text(_first(row, "代码", "code", "symbol"))
        if value and value.lower() in allowed:
            return row
    return None


def _first(mapping: Mapping[object, object], *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _number(value: object, *, positive: bool) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        return None
    return number


def _signed_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _price(value: float | None) -> dict[str, object]:
    if value is None:
        return {"value": None, "unit": "currency_per_share", "currency": "CNY", "unknown_reason": "field absent or invalid"}
    return {"value": value, "unit": "currency_per_share", "currency": "CNY"}


def _volume(value: float | None, original_unit: str, *, factor: int) -> dict[str, object]:
    if value is None:
        return {"value": None, "unit": "shares", "original_value": None, "original_unit": original_unit, "unknown_reason": "provider volume absent or invalid"}
    return {"value": value * factor, "unit": "shares", "original_value": value, "original_unit": original_unit}


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, (str, datetime)):
        raise ValueError("invalid datetime")
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("datetime must be aware")
    return parsed


def _china_datetime(value: object) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" T", "T"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=_CN_TZ) if parsed.tzinfo is None else parsed.astimezone(_CN_TZ)


def _parse_date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} required")
    return date.fromisoformat(value)


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _compact_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        if re.fullmatch(r"[0-9]{8}", text):
            return datetime.strptime(text, "%Y%m%d").date()
        try:
            return date.fromisoformat(text)
        except ValueError:
            return datetime.fromisoformat(text.replace(" T", "T")).date()
    except ValueError:
        return None


def _sdk_version(client: object) -> str | None:
    value = getattr(client, "__version__", None)
    return str(value) if value is not None else None


def _safe_request_id(request: Mapping[str, object]) -> str:
    value = request.get("request_id")
    return value if isinstance(value, str) and value else "invalid-request"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
