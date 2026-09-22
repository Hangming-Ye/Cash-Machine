"""Read-only FMP stable profile and annual-statement adapter."""

from __future__ import annotations

import math
import os
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from cash_research.artifacts import ArtifactError, reject_secrets, safe_relative_path
from cash_research.config import Settings
from cash_research.models import DataGap, Evidence, SecurityIdentity, SourceResult


_BASE_URL = "https://financialmodelingprep.com"
_SYMBOL = re.compile(r"^[A-Z0-9.-]+$")
_PROFILE_FIELDS = {
    "company_name",
    "price",
    "market_cap",
    "beta",
    "last_dividend",
    "currency",
    "exchange",
    "industry",
    "sector",
    "ipo_date",
}
_PROVIDER_EXCHANGE_TO_MIC = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "AMEX": "XASE",
    "NYSE AMERICAN": "XASE",
}
_STATEMENT_PATHS = {
    "income": "/stable/income-statement",
    "balance": "/stable/balance-sheet-statement",
    "cash": "/stable/cash-flow-statement",
}
_STATEMENT_META_FIELDS = {
    "reported_currency": "reportedCurrency",
    "filing_date": "filingDate",
    "accepted_date": "acceptedDate",
    "fiscal_year": "fiscalYear",
    "date": "date",
    "period": "period",
    "link": "link",
    "final_link": "finalLink",
}
_STATEMENT_RAW_META = {
    "date",
    "symbol",
    "reportedCurrency",
    "cik",
    "filingDate",
    "acceptedDate",
    "fiscalYear",
    "period",
    "link",
    "finalLink",
}


class FmpStableAdapter:
    """Fetch only the approved FMP stable profile and annual statements."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        timeout: float = 15.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._credential = _credential(settings)
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch(
        self, request: Mapping[str, object], *, output_ref: str
    ) -> dict[str, object]:
        request_id = _safe_request_id(request)
        subject: SecurityIdentity | str = "invalid request subject"
        try:
            reject_secrets(request)
            request_id, operation, subject, as_of, parameters, required_fields = (
                self._validate_request(request)
            )
            safe_relative_path(self._settings.root, output_ref, must_exist=False)
        except (ArtifactError, ValidationError, ValueError):
            return _failure(
                request_id=request_id,
                operation=str(request.get("operation") or "unknown"),
                subject=subject,
                retrieved_at=self._clock(),
                reason="invalid",
                coverage="request failed source-contract validation before any HTTP call",
            )

        if request.get("source") != "fmp_stable" or "fmp_stable" not in self._settings.enabled_sources:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=self._clock(),
                reason="unsupported",
                coverage="FMP stable is not enabled for this request",
            )
        if operation not in {"profile", "statements"}:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=self._clock(),
                reason="unsupported",
                coverage="operation is outside the approved FMP profile/statements adapter",
            )
        if subject.market != "US":
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=self._clock(),
                reason="unsupported",
                coverage="FMP stable adapter is limited to the approved US route",
            )
        if not self._credential:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=self._clock(),
                reason="unauthorized",
                coverage="FMP credential is unavailable from explicit settings or process environment",
            )
        if operation == "statements":
            return self._statements(
                request_id=request_id,
                subject=subject,
                as_of=as_of,
                parameters=parameters,
                required_fields=required_fields,
                output_ref=output_ref,
            )
        return self._profile(
            request_id=request_id,
            subject=subject,
            as_of=as_of,
            parameters=parameters,
            required_fields=required_fields,
            output_ref=output_ref,
        )

    def _validate_request(
        self, request: Mapping[str, object]
    ) -> tuple[str, str, SecurityIdentity, datetime, dict[str, object], tuple[str, ...]]:
        request_id = _required_string(request, "request_id")
        operation = _required_string(request, "operation")
        subject = SecurityIdentity.model_validate(request.get("subject"))
        if not _SYMBOL.fullmatch(subject.symbol.upper()):
            raise ValueError
        as_of = _aware_time(request.get("as_of"))
        parameters = request.get("parameters")
        required_fields = request.get("required_fields")
        if not isinstance(parameters, dict):
            raise ValueError
        if not isinstance(required_fields, list) or not all(
            isinstance(field, str) and field for field in required_fields
        ):
            raise ValueError
        return request_id, operation, subject, as_of, parameters, tuple(required_fields)

    def _profile(
        self,
        *,
        request_id: str,
        subject: SecurityIdentity,
        as_of: datetime,
        parameters: dict[str, object],
        required_fields: tuple[str, ...],
        output_ref: str,
    ) -> dict[str, object]:
        if parameters:
            return _failure(
                request_id=request_id,
                operation="profile",
                subject=subject,
                retrieved_at=self._clock(),
                reason="invalid",
                coverage="profile does not accept statement parameters",
            )
        unsupported = sorted(set(required_fields) - _PROFILE_FIELDS)
        if unsupported:
            return _failure(
                request_id=request_id,
                operation="profile",
                subject=subject,
                retrieved_at=self._clock(),
                reason="unsupported",
                coverage="one or more required fields are outside the FMP profile operation",
                metadata={"unsupported_required_fields": unsupported},
            )
        response_or_failure = self._get(
            path="/stable/profile",
            params={"symbol": subject.symbol.upper()},
            request_id=request_id,
            operation="profile",
            subject=subject,
        )
        if isinstance(response_or_failure, dict):
            return response_or_failure
        payload, retrieved_at = response_or_failure
        if isinstance(payload, list) and not payload:
            return _limited_empty(
                request_id=request_id,
                operation="profile",
                subject=subject,
                retrieved_at=retrieved_at,
                output_ref=output_ref,
                raw_payload=payload,
                required_content="company profile",
            )
        if not isinstance(payload, list) or not isinstance(payload[0], dict):
            return _rejected_payload(
                request_id=request_id,
                operation="profile",
                subject=subject,
                retrieved_at=retrieved_at,
                output_ref=output_ref,
                raw_payload=payload,
                reason="invalid_response",
                coverage="FMP profile response did not match the documented list/object shape",
                normalized={"profile": None},
            )
        row = payload[0]
        exchange_match = _exchange_match(subject.exchange, row.get("exchange"))
        returned_currency = _text(row.get("currency"))
        currency_match = (
            None
            if returned_currency is None
            else returned_currency == subject.currency
        )
        if (
            row.get("symbol") != subject.symbol.upper()
            or exchange_match is False
            or currency_match is False
        ):
            return _rejected_payload(
                request_id=request_id,
                operation="profile",
                subject=subject,
                retrieved_at=retrieved_at,
                output_ref=output_ref,
                raw_payload=payload,
                reason="wrong_security",
                coverage="FMP response identity did not match the requested security",
                normalized={
                    "profile": None,
                    "returned_identity": {
                        "symbol": row.get("symbol"),
                        "exchange": row.get("exchange"),
                        "currency": row.get("currency"),
                    },
                },
            )
        profile = {
            "symbol": row.get("symbol"),
            "company_name": _text(row.get("companyName")),
            "price": _finite_number(row.get("price")),
            "market_cap": _finite_number(row.get("marketCap")),
            "beta": _finite_number(row.get("beta")),
            "last_dividend": _finite_number(row.get("lastDividend")),
            "currency": _text(row.get("currency")),
            "exchange": _text(row.get("exchange")),
            "industry": _text(row.get("industry")),
            "sector": _text(row.get("sector")),
            "ipo_date": _text(row.get("ipoDate")),
        }
        unknown_reasons = {
            field: "FMP profile field was absent or unusable"
            for field, value in profile.items()
            if field != "symbol" and value is None
        }
        missing = sorted(field for field in required_fields if profile.get(field) is None)
        historical = as_of.date() < retrieved_at.date()
        gaps: list[dict[str, object]] = []
        if missing:
            gaps.append(
                _gap(
                    request_id=request_id,
                    required_content=f"profile fields: {', '.join(missing)}",
                    attempted_at=retrieved_at,
                    result="fields absent or unusable",
                    impact="profile coverage is limited",
                    next_action="retain null values and supplement the missing fields",
                )
            )
        if exchange_match is None:
            gaps.append(
                _gap(
                    request_id=request_id,
                    required_content="verified exchange identity",
                    attempted_at=retrieved_at,
                    result="provider exchange missing or not in the explicit alias map",
                    impact="profile exchange identity is unverified",
                    next_action="retain the raw provider exchange and verify identity before use",
                )
            )
        if currency_match is None:
            gaps.append(
                _gap(
                    request_id=request_id,
                    required_content="verified profile currency identity",
                    attempted_at=retrieved_at,
                    result="provider currency missing",
                    impact="profile currency identity is unverified",
                    next_action="retain null currency and verify identity before use",
                )
            )
        gaps.append(
            _gap(
                request_id=request_id,
                required_content="profile availability at the research cutoff",
                attempted_at=retrieved_at,
                result="profile has no provider observation, availability timestamp, or archival version",
                impact="profile cannot be treated as point-in-time historical evidence",
                next_action="use it only as a current retrieved profile or obtain dated original disclosures",
            )
        )
        if historical:
            gaps.append(
                _gap(
                    request_id=request_id,
                    required_content="historically available company profile",
                    attempted_at=retrieved_at,
                    result="current profile has no version or availability timestamp",
                    impact="current profile cannot be used as a historical-as-of snapshot",
                    next_action="use dated original disclosures for historical analysis",
                )
            )
        usable_profile = None if historical else profile
        evidence = Evidence(
            evidence_id=f"ev_{uuid.uuid4().hex}",
            source_ref=output_ref,
            locator="/0",
            published_at=None,
            retrieved_at=retrieved_at,
            available_at=None,
            content_kind="third_party_view",
            claim="FMP returned a current company profile for the requested symbol",
            scope="current provider profile; no historical version",
            units=tuple(
                unit
                for unit in (
                    f"{profile['currency']}/share" if profile["currency"] else None,
                    profile["currency"],
                )
                if unit
            ),
            limitations=("profile has no provider observation or availability timestamp",),
            unknown_reasons={
                "published_at": "profile is not a dated publication",
                "available_at": "provider did not expose profile availability time",
            },
        )
        quality = "limited" if gaps else "complete"
        source_result = SourceResult(
            source="fmp_stable",
            operation="profile",
            security_or_topic=subject,
            observed_at=None,
            retrieved_at=retrieved_at,
            available_at=None,
            coverage="current stable profile; provider observation/availability time unknown",
            payload_ref=output_ref,
            quality=quality,
            errors=tuple("missing_required_fields" for _ in [0] if missing),
            unknown_reasons={
                "observed_at": "profile response has no observation timestamp",
                "available_at": "profile response has no availability timestamp",
            },
        )
        return {
            "source_result": source_result.model_dump(mode="json"),
            "raw_payload": payload,
            "normalized": {
                "raw_locator": "",
                "endpoint": "/stable/profile",
                "profile": usable_profile,
                "excluded_current_profile": profile if historical else None,
                "historical_eligible": False,
                "requested_exchange": subject.exchange,
                "provider_exchange": row.get("exchange"),
                "exchange_identity_status": (
                    "verified" if exchange_match is True else "unverified"
                ),
                "currency_identity_status": (
                    "verified" if currency_match is True else "unverified"
                ),
                "unknown_reasons": unknown_reasons,
            },
            "evidence": [evidence.model_dump(mode="json")],
            "gaps": gaps,
        }

    def _statements(
        self,
        *,
        request_id: str,
        subject: SecurityIdentity,
        as_of: datetime,
        parameters: dict[str, object],
        required_fields: tuple[str, ...],
        output_ref: str,
    ) -> dict[str, object]:
        period = parameters.get("period", "annual")
        limit = parameters.get("limit", 8)
        statement_types = parameters.get(
            "statement_types", ["income", "balance", "cash"]
        )
        if (
            period != "annual"
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or not isinstance(statement_types, list)
            or not statement_types
            or not all(isinstance(item, str) for item in statement_types)
            or len(set(statement_types)) != len(statement_types)
            or not set(statement_types) <= _STATEMENT_PATHS.keys()
        ):
            return _failure(
                request_id=request_id,
                operation="statements",
                subject=subject,
                retrieved_at=self._clock(),
                reason="invalid",
                coverage="statements require unique approved types, annual period, and positive integer limit",
            )
        if set(required_fields) & {"historical_revision_chain", "point_in_time_history"}:
            return _failure(
                request_id=request_id,
                operation="statements",
                subject=subject,
                retrieved_at=self._clock(),
                reason="unsupported",
                coverage="FMP current stable statements do not prove archival PIT history",
            )

        raw_payload: dict[str, object] = {}
        normalized_statements: dict[str, list[dict[str, object]]] = {}
        excluded_rows: dict[str, list[dict[str, object]]] = {}
        row_exclusions: dict[str, dict[str, int]] = {}
        failed: dict[str, str] = {}
        gaps: list[dict[str, object]] = []
        evidence: list[dict[str, object]] = []
        retrieval_times: list[datetime] = []

        for statement_type in statement_types:
            path = _STATEMENT_PATHS[statement_type]
            response_or_failure = self._get(
                path=path,
                params={
                    "symbol": subject.symbol.upper(),
                    "period": "annual",
                    "limit": limit,
                },
                request_id=request_id,
                operation="statements",
                subject=subject,
            )
            if isinstance(response_or_failure, dict):
                failed_result = SourceResult.model_validate(
                    response_or_failure["source_result"]
                )
                reason = failed_result.errors[0]
                failed[statement_type] = reason
                raw_payload[statement_type] = None
                retrieval_times.append(failed_result.retrieved_at)
                gaps.append(
                    _gap(
                        request_id=request_id,
                        required_content=f"annual {statement_type} statement",
                        attempted_at=failed_result.retrieved_at,
                        result=reason,
                        impact=f"{statement_type} statement unavailable",
                        next_action="report partial coverage and retry the same stable endpoint when appropriate",
                    )
                )
                continue

            payload, retrieved_at = response_or_failure
            retrieval_times.append(retrieved_at)
            raw_payload[statement_type] = payload
            if not isinstance(payload, list):
                failed[statement_type] = "invalid_response"
                gaps.append(
                    _gap(
                        request_id=request_id,
                        required_content=f"documented annual {statement_type} response shape",
                        attempted_at=retrieved_at,
                        result="response was not a list",
                        impact=f"{statement_type} statement unavailable for normalization",
                        next_action="retain raw response and report provider shape drift",
                    )
                )
                continue
            if not payload:
                failed[statement_type] = "empty"
                gaps.append(
                    _gap(
                        request_id=request_id,
                        required_content=f"annual {statement_type} statement",
                        attempted_at=retrieved_at,
                        result="empty or unusable response",
                        impact=f"{statement_type} statement unavailable",
                        next_action="report the empty source response and continue independent work",
                    )
                )
                continue

            normalized_rows: list[dict[str, object]] = []
            excluded: list[dict[str, object]] = []
            for index, raw_row in enumerate(payload):
                if not isinstance(raw_row, dict):
                    excluded.append({"index": index, "reason": "row_not_object"})
                    continue
                if raw_row.get("symbol") != subject.symbol.upper():
                    excluded.append(
                        {
                            "index": index,
                            "reason": "wrong_security",
                            "returned_symbol": raw_row.get("symbol"),
                        }
                    )
                    continue
                row = _normalize_statement_row(raw_row)
                if _definitely_future(raw_row, as_of):
                    excluded.append(
                        {
                            "index": index,
                            "reason": "after_as_of_cutoff",
                            "date_raw": raw_row.get("date"),
                            "filing_date_raw": raw_row.get("filingDate"),
                            "accepted_date_raw": raw_row.get("acceptedDate"),
                        }
                    )
                    continue
                normalized_rows.append(row)
                evidence.append(
                    Evidence(
                        evidence_id=f"ev_{uuid.uuid4().hex}",
                        source_ref=output_ref,
                        locator=f"/{statement_type}/{index}",
                        published_at=None,
                        retrieved_at=retrieved_at,
                        available_at=None,
                        content_kind="disclosure_fact",
                        claim=f"FMP returned an annual {statement_type} row for {row['date_raw'] or row['fiscal_year_raw']}",
                        scope=f"{subject.symbol} annual {statement_type}; PIT history not proven",
                        units=tuple(
                            [str(row["reported_currency"])]
                            if row["reported_currency"]
                            else []
                        ),
                        limitations=(
                            "filingDate is date-only",
                            "acceptedDate timezone is not supplied",
                            "provider archival revision history is not proven",
                        ),
                        unknown_reasons={
                            "published_at": "filingDate has date precision only",
                            "available_at": "acceptedDate has no timezone and archival ordering is unproven",
                        },
                    ).model_dump(mode="json")
                )
            normalized_statements[statement_type] = normalized_rows
            excluded_rows[statement_type] = excluded
            if excluded:
                reason_counts: dict[str, int] = {}
                for item in excluded:
                    reason = str(item["reason"])
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                row_exclusions[statement_type] = reason_counts
                gaps.append(
                    _gap(
                        request_id=request_id,
                        required_content=f"all requested {statement_type} rows valid at the cutoff",
                        attempted_at=retrieved_at,
                        result=f"excluded rows: {reason_counts}",
                        impact=f"{statement_type} coverage excludes one or more returned rows",
                        next_action="retain raw rows and resolve identity/shape/cutoff exclusions",
                    )
                )
            if not normalized_rows:
                excluded_reasons = {str(item["reason"]) for item in excluded}
                failed[statement_type] = (
                    "after_as_of_cutoff"
                    if excluded_reasons and excluded_reasons <= {"after_as_of_cutoff"}
                    else "invalid_rows"
                    if excluded
                    else "no_usable_rows"
                )
                gaps.append(
                    _gap(
                        request_id=request_id,
                        required_content=f"usable annual {statement_type} rows at the requested cutoff",
                        attempted_at=retrieved_at,
                        result=failed[statement_type],
                        impact=f"{statement_type} statement excluded from normalized historical analysis",
                        next_action="retain raw rows and verify identity/filing provenance",
                    )
                )
                continue

            missing_fields = sorted(
                field
                for field in required_fields
                if not all(_statement_field_present(row, field) for row in normalized_rows)
            )
            if missing_fields:
                gaps.append(
                    _gap(
                        request_id=request_id,
                        required_content=f"{statement_type} fields: {', '.join(missing_fields)}",
                        attempted_at=retrieved_at,
                        result="fields absent or unusable",
                        impact=f"{statement_type} statement coverage is limited",
                        next_action="retain nulls and inspect the original filing",
                    )
                )

        retrieved_at = max(retrieval_times) if retrieval_times else self._clock()
        successful = [
            name for name in statement_types if normalized_statements.get(name)
        ]
        any_raw = any(value is not None for value in raw_payload.values())
        if not successful and not any_raw:
            return _failure(
                request_id=request_id,
                operation="statements",
                subject=subject,
                retrieved_at=retrieved_at,
                reason=(next(iter(failed.values())) if failed else "external"),
                coverage="all requested FMP statement endpoints failed",
                metadata={"failed_statements": failed},
            )

        hard_invalid_all = (
            not successful
            and any_raw
            and bool(failed)
            and all(reason in {"invalid_response", "invalid_rows"} for reason in failed.values())
        )
        quality = (
            "failed"
            if hard_invalid_all
            else "complete"
            if len(successful) == len(statement_types) and not gaps
            else "limited"
        )
        errors = [f"{name}:{reason}" for name, reason in failed.items()]
        errors.extend(f"{name}:excluded_rows" for name in row_exclusions if name not in failed)
        source_result = SourceResult(
            source="fmp_stable",
            operation="statements",
            security_or_topic=subject,
            observed_at=None,
            retrieved_at=retrieved_at,
            available_at=None,
            coverage=(
                f"annual stable statements requested={statement_types}; "
                f"successful={successful}; failed={sorted(failed)}"
            ),
            payload_ref=output_ref,
            quality=quality,
            errors=tuple(errors),
            unknown_reasons={
                "observed_at": "fiscal period end is date-only and is not an observation instant",
                "available_at": "acceptedDate is timezone-less and archival revision history is unproven",
            },
        )
        return {
            "source_result": source_result.model_dump(mode="json"),
            "raw_payload": raw_payload,
            "normalized": {
                "raw_locator": "",
                "period": "annual",
                "requested_statement_types": statement_types,
                "successful_statements": successful,
                "failed_statements": failed,
                "row_exclusions": row_exclusions,
                "point_in_time_status": "not_proven_no_archival_versions",
                "statements": normalized_statements,
                "excluded_rows": excluded_rows,
            },
            "evidence": evidence,
            "gaps": gaps,
        }

    def _get(
        self,
        *,
        path: str,
        params: dict[str, object],
        request_id: str,
        operation: str,
        subject: SecurityIdentity,
    ) -> tuple[object, datetime] | dict[str, object]:
        query = dict(params)
        query["apikey"] = self._credential
        try:
            response = self._client.get(f"{_BASE_URL}{path}", params=query)
        except httpx.HTTPError:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=self._clock(),
                reason="external",
                coverage="FMP transport failed without a usable response",
            )
        retrieved_at = self._clock()
        if response.status_code >= 400:
            reason = (
                "unauthorized"
                if response.status_code in {401, 403}
                else "rate_limited"
                if response.status_code == 429
                else "external"
            )
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason=reason,
                coverage="FMP returned no usable authorized source payload",
                metadata={"http_status": response.status_code},
            )
        try:
            payload = response.json()
        except ValueError:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="external",
                coverage="FMP returned a non-JSON response",
            )
        if _error_reason(payload) is not None:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason=_error_reason(payload) or "external",
                coverage="FMP returned an error object instead of source data",
            )
        try:
            reject_secrets(payload)
        except ArtifactError:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="external",
                coverage="FMP response was rejected by credential-safety screening",
            )
        if _contains_text(payload, self._credential):
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="external",
                coverage="FMP response reflected credential material and was discarded",
            )
        return payload, retrieved_at


def _credential(settings: Settings) -> str:
    value: SecretStr | None = settings.credentials.get("FMP_API_KEY")
    if value is not None:
        return value.get_secret_value().strip()
    return (os.environ.get("FMP_API_KEY") or "").strip()


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError
    return item


def _safe_request_id(request: Mapping[str, object]) -> str:
    value = request.get("request_id")
    return value if isinstance(value, str) and value else "unavailable"


def _aware_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _finite_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _contains_text(value: object, text: str) -> bool:
    if not text:
        return False
    if isinstance(value, Mapping):
        return any(_contains_text(key, text) or _contains_text(item, text) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_text(item, text) for item in value)
    return isinstance(value, str) and text in value


def _error_reason(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    message = payload.get("Error Message") or payload.get("error") or payload.get("message")
    if not isinstance(message, str):
        return None
    lowered = message.lower()
    if "api key" in lowered or "unauthorized" in lowered or "forbidden" in lowered:
        return "unauthorized"
    if "limit" in lowered or "too many" in lowered:
        return "rate_limited"
    return "external"


def _exchange_match(requested: str | None, provider: object) -> bool | None:
    if requested is None:
        return True
    returned = _text(provider)
    if returned is None:
        return None
    if returned.upper() == requested.upper():
        return True
    mapped = _PROVIDER_EXCHANGE_TO_MIC.get(returned.upper())
    if mapped is None:
        return None
    return mapped == requested.upper()


def _normalize_statement_row(row: Mapping[str, object]) -> dict[str, object]:
    values = {
        key: number
        for key, raw in row.items()
        if key not in _STATEMENT_RAW_META
        and (number := _finite_number(raw)) is not None
    }
    reported_currency = _text(row.get("reportedCurrency"))
    unknown_reasons: dict[str, str] = {}
    if reported_currency is None:
        unknown_reasons["reported_currency"] = "FMP statement omitted reportedCurrency"
    return {
        "date_raw": _text(row.get("date")),
        "symbol": _text(row.get("symbol")),
        "reported_currency": reported_currency,
        "cik": _text(row.get("cik")),
        "filing_date_raw": _text(row.get("filingDate")),
        "accepted_date_raw": _text(row.get("acceptedDate")),
        "accepted_date_timezone": None,
        "fiscal_year_raw": _text(row.get("fiscalYear")),
        "period": _text(row.get("period")),
        "link": _text(row.get("link")),
        "final_link": _text(row.get("finalLink")),
        "values": values,
        "unknown_reasons": unknown_reasons,
    }


def _date_prefix(value: object) -> str | None:
    text = _text(value)
    if text is None or len(text) < 10:
        return None
    candidate = text[:10]
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def _definitely_future(row: Mapping[str, object], as_of: datetime) -> bool:
    cutoff = as_of.date().isoformat()
    dates = [
        value
        for value in (
            _date_prefix(row.get("filingDate")),
            _date_prefix(row.get("acceptedDate")),
        )
        if value is not None
    ]
    return any(value > cutoff for value in dates)


def _statement_field_present(row: Mapping[str, object], field: str) -> bool:
    raw_name = _STATEMENT_META_FIELDS.get(field)
    if raw_name is not None:
        normalized_name = {
            "reportedCurrency": "reported_currency",
            "filingDate": "filing_date_raw",
            "acceptedDate": "accepted_date_raw",
            "fiscalYear": "fiscal_year_raw",
            "date": "date_raw",
            "finalLink": "final_link",
        }.get(raw_name, raw_name)
        return row.get(normalized_name) not in (None, "")
    values = row.get("values")
    return isinstance(values, Mapping) and values.get(field) is not None


def _gap(
    *,
    request_id: str,
    required_content: str,
    attempted_at: datetime,
    result: str,
    impact: str,
    next_action: str,
) -> dict[str, object]:
    return DataGap(
        gap_id=f"gap_{uuid.uuid4().hex}",
        request_id=request_id,
        required_content=required_content,
        attempts=(
            {
                "source": "fmp_stable",
                "at": attempted_at.isoformat(),
                "result": result,
            },
        ),
        impact=impact,
        next_action=next_action,
    ).model_dump(mode="json")


def _failure(
    *,
    request_id: str,
    operation: str,
    subject: SecurityIdentity | str,
    retrieved_at: datetime,
    reason: str,
    coverage: str,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    source_result = SourceResult(
        source="fmp_stable",
        operation=operation,
        security_or_topic=subject,
        observed_at=None,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage=coverage,
        payload_ref=None,
        quality="failed",
        errors=(reason,),
        unknown_reasons={
            "observed_at": "operation returned no usable source data",
            "available_at": "operation returned no usable source data",
        },
    )
    return {
        "source_result": source_result.model_dump(mode="json"),
        "raw_payload": None,
        "normalized": {"raw_locator": None, "error_reason": reason, **(metadata or {})},
        "evidence": [],
        "gaps": [
            _gap(
                request_id=request_id,
                required_content=f"FMP {operation} source data",
                attempted_at=retrieved_at,
                result=reason,
                impact=coverage,
                next_action="report the source gap and retry the existing channel when appropriate",
            )
        ],
    }


def _limited_empty(
    *,
    request_id: str,
    operation: str,
    subject: SecurityIdentity,
    retrieved_at: datetime,
    output_ref: str,
    raw_payload: object,
    required_content: str,
) -> dict[str, object]:
    source_result = SourceResult(
        source="fmp_stable",
        operation=operation,
        security_or_topic=subject,
        observed_at=None,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage="FMP returned a valid but empty/unusable response",
        payload_ref=output_ref,
        quality="limited",
        errors=(),
        unknown_reasons={
            "observed_at": "no usable row was returned",
            "available_at": "no usable row was returned",
        },
    )
    return {
        "source_result": source_result.model_dump(mode="json"),
        "raw_payload": raw_payload,
        "normalized": {"raw_locator": "", "empty": True},
        "evidence": [],
        "gaps": [
            _gap(
                request_id=request_id,
                required_content=required_content,
                attempted_at=retrieved_at,
                result="empty or unusable response",
                impact="requested source content is unavailable",
                next_action="continue independent work or retry the same approved source",
            )
        ],
    }


def _rejected_payload(
    *,
    request_id: str,
    operation: str,
    subject: SecurityIdentity,
    retrieved_at: datetime,
    output_ref: str,
    raw_payload: object,
    reason: str,
    coverage: str,
    normalized: dict[str, object],
) -> dict[str, object]:
    source_result = SourceResult(
        source="fmp_stable",
        operation=operation,
        security_or_topic=subject,
        observed_at=None,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage=coverage,
        payload_ref=output_ref,
        quality="failed",
        errors=(reason,),
        unknown_reasons={
            "observed_at": "rejected payload cannot establish requested security time",
            "available_at": "rejected payload cannot establish requested security availability",
        },
    )
    return {
        "source_result": source_result.model_dump(mode="json"),
        "raw_payload": raw_payload,
        "normalized": {"raw_locator": "", "error_reason": "invalid", **normalized},
        "evidence": [],
        "gaps": [
            _gap(
                request_id=request_id,
                required_content=f"FMP {operation} data for the requested security",
                attempted_at=retrieved_at,
                result=reason,
                impact=coverage,
                next_action="retain raw evidence, resolve identity, and retry",
            )
        ],
    }
