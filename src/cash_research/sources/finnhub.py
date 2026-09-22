"""Read-only Finnhub quote and news adapter."""

from __future__ import annotations

import math
import os
import uuid
from collections.abc import Mapping
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from cash_research.artifacts import ArtifactError, reject_secrets, safe_relative_path
from cash_research.config import Settings
from cash_research.models import DataGap, Evidence, SecurityIdentity, SourceResult


_BASE_URL = "https://finnhub.io/api/v1"
_GENERAL_CATEGORIES = frozenset({"general", "forex", "crypto", "merger"})


class FinnhubAdapter:
    """Fetch only the approved Finnhub quote and news operations."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._settings = settings
        self._credential = _credential(settings, "FINNHUB_API_KEY")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

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
            request_id, operation, subject, as_of, parameters, required_fields = self._validate_request(request)
            safe_relative_path(self._settings.root, output_ref, must_exist=False)
        except (ArtifactError, ValidationError, ValueError):
            retrieved_at = datetime.now(timezone.utc)
            return _failure(
                request_id=request_id,
                operation=str(request.get("operation") or "unknown"),
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="request failed source-contract validation before any HTTP call",
            )

        if request.get("source") != "finnhub" or "finnhub" not in self._settings.enabled_sources:
            retrieved_at = datetime.now(timezone.utc)
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="unsupported",
                coverage="Finnhub is not enabled for this request",
            )
        if operation not in {"quote", "news"}:
            retrieved_at = datetime.now(timezone.utc)
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="unsupported",
                coverage="operation is outside the approved Finnhub quote/news adapter",
            )
        if isinstance(subject, SecurityIdentity) and subject.market not in {"US", "HK"}:
            retrieved_at = datetime.now(timezone.utc)
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="unsupported",
                coverage="Finnhub adapter is limited to approved US/HK routing",
            )
        if not self._credential:
            retrieved_at = datetime.now(timezone.utc)
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="unauthorized",
                coverage="Finnhub credential is unavailable from explicit settings or process environment",
            )

        supported_fields = (
            {"current_price", "currency", "observed_at", "open", "high", "low", "previous_close", "change", "percent_change"}
            if operation == "quote"
            else {"headline", "published_at", "source", "url"}
        )
        unsupported_fields = sorted(set(required_fields) - supported_fields)
        if unsupported_fields:
            retrieved_at = datetime.now(timezone.utc)
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="unsupported",
                coverage="one or more required fields are outside this Finnhub operation",
                metadata={"unsupported_required_fields": unsupported_fields},
            )

        if operation == "quote":
            if not isinstance(subject, SecurityIdentity):
                retrieved_at = datetime.now(timezone.utc)
                return _failure(
                    request_id=request_id,
                    operation=operation,
                    subject=subject,
                    retrieved_at=retrieved_at,
                    reason="invalid",
                    coverage="quote requires a disambiguated security identity",
                )
            response_or_result = self._get(
                path="/quote",
                params={"symbol": subject.symbol, "token": self._credential},
                request_id=request_id,
                operation=operation,
                subject=subject,
            )
            if isinstance(response_or_result, dict):
                return response_or_result
            response, retrieved_at = response_or_result
            return _quote_result(
                response,
                request_id=request_id,
                subject=subject,
                as_of=as_of,
                required_fields=required_fields,
                retrieved_at=retrieved_at,
                output_ref=output_ref,
            )

        return self._news(
            request_id=request_id,
            subject=subject,
            as_of=as_of,
            parameters=parameters,
            required_fields=required_fields,
            output_ref=output_ref,
        )

    def _validate_request(
        self, request: Mapping[str, object]
    ) -> tuple[str, str, SecurityIdentity | str, datetime, dict[str, object], tuple[str, ...]]:
        request_id = _required_string(request, "request_id")
        operation = _required_string(request, "operation")
        as_of = _aware_time(request.get("as_of"))
        parameters = request.get("parameters")
        required_fields = request.get("required_fields")
        if not isinstance(parameters, dict):
            raise ValueError
        if not isinstance(required_fields, list) or not all(
            isinstance(field, str) and field for field in required_fields
        ):
            raise ValueError
        raw_subject = request.get("subject")
        if isinstance(raw_subject, Mapping):
            subject: SecurityIdentity | str = SecurityIdentity.model_validate(raw_subject)
        elif operation == "news" and isinstance(raw_subject, str) and raw_subject:
            subject = raw_subject
        else:
            raise ValueError
        return request_id, operation, subject, as_of, parameters, tuple(required_fields)

    def _get(
        self,
        *,
        path: str,
        params: dict[str, object],
        request_id: str,
        operation: str,
        subject: SecurityIdentity | str,
    ) -> tuple[httpx.Response, datetime] | dict[str, object]:
        try:
            response = self._client.get(f"{_BASE_URL}{path}", params=params)
        except httpx.HTTPError:
            retrieved_at = datetime.now(timezone.utc)
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="external",
                coverage="Finnhub transport failed without a usable response",
            )
        retrieved_at = datetime.now(timezone.utc)
        if response.status_code >= 400:
            reason = (
                "unauthorized"
                if response.status_code in {401, 403}
                else "rate_limited"
                if response.status_code == 429
                else "external"
            )
            metadata: dict[str, object] = {"http_status": response.status_code}
            retry_after = _safe_retry_after(response.headers.get("retry-after"))
            if reason == "rate_limited" and retry_after is not None:
                metadata["retry_after"] = retry_after
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason=reason,
                coverage="Finnhub returned no usable authorized source payload",
                metadata=metadata,
            )
        return response, retrieved_at

    def _news(
        self,
        *,
        request_id: str,
        subject: SecurityIdentity | str,
        as_of: datetime,
        parameters: dict[str, object],
        required_fields: tuple[str, ...],
        output_ref: str,
    ) -> dict[str, object]:
        window_start: date | None = None
        window_end: date | None = None
        if isinstance(subject, SecurityIdentity):
            start = _date_parameter(parameters.get("from"))
            end = _date_parameter(parameters.get("to"))
            if start is None or end is None or start > end:
                return _failure(
                    request_id=request_id,
                    operation="news",
                    subject=subject,
                    retrieved_at=datetime.now(timezone.utc),
                    reason="invalid",
                    coverage="company news requires an ordered from/to date range",
                )
            path = "/company-news"
            window_start, window_end = start, end
            params: dict[str, object] = {
                "symbol": subject.symbol,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "token": self._credential,
            }
            coverage = f"company news requested from {start.isoformat()} through {end.isoformat()}"
        else:
            category = parameters.get("category", "general")
            min_id = parameters.get("min_id", 0)
            if (
                not isinstance(category, str)
                or category not in _GENERAL_CATEGORIES
                or isinstance(min_id, bool)
                or not isinstance(min_id, int)
                or min_id < 0
            ):
                return _failure(
                    request_id=request_id,
                    operation="news",
                    subject=subject,
                    retrieved_at=datetime.now(timezone.utc),
                    reason="invalid",
                    coverage="general news category or min_id is invalid",
                )
            path = "/news"
            params = {"category": category, "minId": min_id, "token": self._credential}
            coverage = f"general news category={category} after provider id {min_id}"
        limit = parameters.get("limit")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                retrieved_at=datetime.now(timezone.utc),
                reason="invalid",
                coverage="news limit must be a positive integer",
            )

        response_or_result = self._get(
            path=path,
            params=params,
            request_id=request_id,
            operation="news",
            subject=subject,
        )
        if isinstance(response_or_result, dict):
            return response_or_result
        response, retrieved_at = response_or_result
        try:
            payload = response.json()
        except ValueError:
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="external",
                coverage="Finnhub returned a non-JSON news response",
                metadata={"http_status": response.status_code},
            )
        try:
            reject_secrets(payload)
        except ArtifactError:
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="Finnhub news payload contained credential material and was discarded",
                metadata={"http_status": response.status_code},
            )
        if _contains_secret_value(payload, self._credential):
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="Finnhub news payload reflected credential material and was discarded",
                metadata={"http_status": response.status_code},
            )
        if not isinstance(payload, list):
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="Finnhub news payload was not a list",
                raw_payload=payload,
                output_ref=output_ref,
                metadata={"http_status": response.status_code},
            )
        if not payload:
            return _empty_news(
                request_id=request_id,
                subject=subject,
                retrieved_at=retrieved_at,
                output_ref=output_ref,
                coverage=coverage,
                actual_source=f"finnhub:{path}",
            )

        evidence: list[Evidence] = []
        publisher_urls: list[str] = []
        invalid_rows = 0
        excluded_after_cutoff = 0
        excluded_outside_window = 0
        missing_required_dates = 0
        published_times: list[datetime] = []
        for index, row in enumerate(payload):
            if not isinstance(row, dict):
                invalid_rows += 1
                continue
            headline = row.get("headline")
            publisher = row.get("source")
            url = row.get("url")
            if not all(isinstance(value, str) and value for value in (headline, publisher, url)):
                invalid_rows += 1
                continue
            published_at = _unix_time(row.get("datetime"))
            unknown_reasons = {"available_at": "Finnhub does not expose aggregator availability time"}
            if published_at is None:
                unknown_reasons["published_at"] = "news published timestamp was missing or invalid"
                if "published_at" in required_fields:
                    missing_required_dates += 1
            else:
                if published_at > as_of:
                    excluded_after_cutoff += 1
                    continue
                if (
                    window_start is not None
                    and window_end is not None
                    and not (window_start <= published_at.date() <= window_end)
                ):
                    excluded_outside_window += 1
                    continue
                published_times.append(published_at)
            evidence.append(
                Evidence(
                    evidence_id=f"evidence_{uuid.uuid4().hex}",
                    source_ref=output_ref,
                    locator=f"/{index}",
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    available_at=None,
                    content_kind="third_party_view",
                    claim=headline,
                    scope=(subject.canonical_id if isinstance(subject, SecurityIdentity) else subject),
                    units=(),
                    limitations=("news headline/summary is third-party material, not verified fact",),
                    unknown_reasons=unknown_reasons,
                )
            )
            publisher_urls.append(url)
        if not evidence and invalid_rows == len(payload):
            return _failure(
                request_id=request_id,
                operation="news",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="all Finnhub news rows failed required field validation",
                raw_payload=payload,
                output_ref=output_ref,
                required_content="required_fields:headline,source,url",
                metadata={"http_status": response.status_code, "actual_source": f"finnhub:{path}"},
            )

        selected = evidence[:limit] if isinstance(limit, int) else evidence
        errors: list[str] = []
        gaps: list[DataGap] = []
        if invalid_rows:
            errors.append("invalid_rows")
            gaps.append(
                _gap(
                    request_id,
                    "required_fields:headline,source,url",
                    f"{invalid_rows} malformed rows were retained only in raw payload",
                    "coverage is partial",
                    "retry or supplement malformed items from another approved channel",
                    retrieved_at,
                )
            )
        if missing_required_dates:
            errors.append("invalid_fields")
            gaps.append(
                _gap(
                    request_id,
                    "required_field:published_at",
                    f"{missing_required_dates} selected news rows have unknown publication time",
                    "time-dependent use of those rows is limited",
                    "retain null time and seek a source with explicit publication time",
                    retrieved_at,
                )
            )
        if excluded_after_cutoff:
            errors.append("stale")
            gaps.append(
                _gap(
                    request_id,
                    "news published no later than the research as_of cutoff",
                    f"{excluded_after_cutoff} rows were published after as_of",
                    "later news was excluded from normalized evidence",
                    "use a later as_of only when the research cutoff changes",
                    retrieved_at,
                )
            )
        if excluded_outside_window:
            errors.append("stale")
            gaps.append(
                _gap(
                    request_id,
                    "company news within the requested from/to window",
                    f"{excluded_outside_window} rows were outside the requested dates",
                    "out-of-window news was excluded from normalized evidence",
                    "retry or broaden the requested window explicitly",
                    retrieved_at,
                )
            )
        if len(selected) < len(evidence):
            errors.append("truncated")
            gaps.append(
                _gap(
                    request_id,
                    "all usable news rows",
                    f"caller limit selected {len(selected)} of {len(evidence)} usable rows",
                    "returned evidence is intentionally truncated",
                    "read the preserved raw payload or issue a broader request",
                    retrieved_at,
                )
            )
        if isinstance(subject, SecurityIdentity) and subject.market == "HK":
            gaps.append(
                _gap(
                    request_id,
                    "verified HK company-news entitlement and coverage",
                    "official company-news documentation describes North American coverage",
                    "North American documented coverage does not prove complete HK news",
                    "retain returned items but verify HK coverage in live validation",
                    retrieved_at,
                )
            )
        observed_at = max(published_times) if published_times else None
        unknown = {"available_at": "Finnhub does not expose aggregator availability time"}
        if observed_at is None:
            unknown["observed_at"] = "no usable published timestamp was returned"
        source = SourceResult(
            source="finnhub",
            operation="news",
            security_or_topic=subject,
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            available_at=None,
            coverage=(
                f"{coverage}; {len(selected)} of {len(payload)} raw rows selected; "
                f"{excluded_after_cutoff} after-cutoff and {excluded_outside_window} out-of-window rows excluded"
            ),
            payload_ref=output_ref,
            quality="limited" if errors or gaps or observed_at is None else "limited",
            errors=tuple(errors),
            unknown_reasons=unknown,
        )
        return {
            "source_result": source.model_dump(mode="json"),
            "raw_payload": payload,
            "normalized": {
                "raw_locator": "",
                "actual_source": f"finnhub:{path}",
                "http_status": response.status_code,
                "returned_count": len(payload),
                "usable_count": len(evidence),
                "selected_count": len(selected),
                "excluded_after_cutoff": excluded_after_cutoff,
                "excluded_outside_window": excluded_outside_window,
                "publisher_urls": publisher_urls[: len(selected)],
            },
            "evidence": [item.model_dump(mode="json") for item in selected],
            "gaps": [item.model_dump(mode="json") for item in gaps],
        }


def _quote_result(
    response: httpx.Response,
    *,
    request_id: str,
    subject: SecurityIdentity,
    as_of: datetime,
    required_fields: tuple[str, ...],
    retrieved_at: datetime,
    output_ref: str,
) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError:
        return _failure(
            request_id=request_id,
            operation="quote",
            subject=subject,
            retrieved_at=retrieved_at,
            reason="external",
            coverage="Finnhub returned a non-JSON quote response",
            metadata={"http_status": response.status_code},
        )
    try:
        reject_secrets(payload)
    except ArtifactError:
        return _failure(
            request_id=request_id,
            operation="quote",
            subject=subject,
            retrieved_at=retrieved_at,
            reason="invalid",
            coverage="Finnhub quote payload contained credential material and was discarded",
            metadata={"http_status": response.status_code},
        )
    credential = response.request.url.params.get("token", "")
    if _contains_secret_value(payload, credential):
        return _failure(
            request_id=request_id,
            operation="quote",
            subject=subject,
            retrieved_at=retrieved_at,
            reason="invalid",
            coverage="Finnhub quote payload reflected credential material and was discarded",
            metadata={"http_status": response.status_code},
        )
    if not isinstance(payload, dict):
        return _failure(
            request_id=request_id,
            operation="quote",
            subject=subject,
            retrieved_at=retrieved_at,
            reason="invalid",
            coverage="Finnhub quote payload was not an object",
            raw_payload=payload,
            output_ref=output_ref,
            metadata={"http_status": response.status_code},
        )
    returned_symbol = payload.get("symbol")
    if returned_symbol is not None and returned_symbol != subject.symbol:
        return _failure(
            request_id=request_id,
            operation="quote",
            subject=subject,
            retrieved_at=retrieved_at,
            reason="invalid",
            coverage="Finnhub response identity did not match the requested security",
            raw_payload=payload,
            output_ref=output_ref,
            metadata={"http_status": response.status_code, "returned_symbol": "mismatch"},
        )
    current_raw = payload.get("c")
    current = _number(current_raw)
    if current is None or current <= 0:
        reason = (
            "empty"
            if current_raw is None
            or (not isinstance(current_raw, bool) and current_raw == 0)
            else "invalid"
        )
        return _failure(
            request_id=request_id,
            operation="quote",
            subject=subject,
            retrieved_at=retrieved_at,
            reason=reason,
            coverage="Finnhub quote contained no usable positive current price",
            raw_payload=payload,
            output_ref=output_ref,
            required_content="required_field:current_price",
            metadata={"http_status": response.status_code, "actual_source": "finnhub:/quote"},
        )
    fields: dict[str, float | None] = {}
    invalid_fields: list[str] = []
    for key in ("c", "d", "dp", "h", "l", "o", "pc"):
        raw = payload.get(key)
        value = _number(raw)
        fields[key] = value
        if raw is not None and value is None:
            invalid_fields.append(key)
    observed_at = _unix_time(payload.get("t"))
    unknown = {"available_at": "Finnhub quote availability time was not separately supplied"}
    gaps: list[DataGap] = []
    errors: list[str] = []
    if observed_at is None:
        unknown["observed_at"] = "Finnhub quote timestamp was absent or invalid"
        gaps.append(
            _gap(
                request_id,
                "required_field:observed_at",
                "quote timestamp absent or invalid",
                "quote is only a retrieval-time snapshot",
                "retain null unless a verified provider timestamp is returned",
                retrieved_at,
            )
        )
    usable_for_as_of = None if observed_at is None else observed_at <= as_of
    if observed_at is not None and observed_at > as_of:
        errors.append("stale")
        gaps.append(
            _gap(
                request_id,
                "quote observed no later than the research as_of cutoff",
                "provider quote was observed after as_of",
                "current_price is not usable as the requested historical quote",
                "obtain a historical observation from an approved source",
                retrieved_at,
            )
        )
    if invalid_fields:
        errors.append("invalid_fields")
        gaps.append(
            _gap(
                request_id,
                "valid numeric quote fields requested by the caller",
                "one or more optional quote fields were non-numeric",
                "affected fields remain null",
                "retry without inventing numeric defaults",
                retrieved_at,
            )
        )
    required_to_key = {
        "current_price": "c",
        "open": "o",
        "high": "h",
        "low": "l",
        "previous_close": "pc",
        "change": "d",
        "percent_change": "dp",
    }
    for field in required_fields:
        key = required_to_key.get(field)
        if key is not None and fields[key] is None:
            gaps.append(
                _gap(
                    request_id,
                    f"required_field:{field}",
                    "required quote field missing or invalid",
                    f"{field} remains unknown",
                    "retry without substituting a default",
                    retrieved_at,
                )
            )
    source = SourceResult(
        source="finnhub",
        operation="quote",
        security_or_topic=subject,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage="one Finnhub quote snapshot",
        payload_ref=output_ref,
        quality="limited",
        errors=tuple(errors),
        unknown_reasons=unknown,
    )
    normalized_fields = {
        key: {"value": value, "unit": "percent" if key == "dp" else "currency_per_share", "currency": subject.currency}
        for key, value in fields.items()
    }
    return {
        "source_result": source.model_dump(mode="json"),
        "raw_payload": payload,
        "normalized": {
            "raw_locator": "",
            "actual_source": "finnhub:/quote",
            "http_status": response.status_code,
            "identity": subject.model_dump(mode="json"),
            "current_price": normalized_fields["c"] if usable_for_as_of is not False else None,
            "fields": normalized_fields,
            "provider_timestamp": observed_at.isoformat() if observed_at else None,
            "usable_for_as_of": usable_for_as_of,
            "as_of": as_of.isoformat(),
        },
        "evidence": [],
        "gaps": [item.model_dump(mode="json") for item in gaps],
    }


def _empty_news(
    *,
    request_id: str,
    subject: SecurityIdentity | str,
    retrieved_at: datetime,
    output_ref: str,
    coverage: str,
    actual_source: str,
) -> dict[str, object]:
    source = SourceResult(
        source="finnhub",
        operation="news",
        security_or_topic=subject,
        observed_at=None,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage=f"valid empty response for {coverage}",
        payload_ref=output_ref,
        quality="limited",
        errors=(),
        unknown_reasons={"observed_at": "no news items returned", "available_at": "no news items returned"},
    )
    gap = _gap(
        request_id,
        "news items for the requested coverage",
        "provider returned a valid empty list",
        "no news evidence; this is distinct from transport failure",
        "continue independent work or supplement when relevant",
        retrieved_at,
    )
    return {
        "source_result": source.model_dump(mode="json"),
        "raw_payload": [],
        "normalized": {"raw_locator": "", "actual_source": actual_source, "error_reason": "empty", "empty_is_failure": False},
        "evidence": [],
        "gaps": [gap.model_dump(mode="json")],
    }


def _failure(
    *,
    request_id: str,
    operation: str,
    subject: SecurityIdentity | str,
    retrieved_at: datetime,
    reason: str,
    coverage: str,
    raw_payload: object | None = None,
    output_ref: str | None = None,
    required_content: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    source = SourceResult(
        source="finnhub",
        operation=operation,
        security_or_topic=subject,
        observed_at=None,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage=coverage,
        payload_ref=output_ref if raw_payload is not None else None,
        quality="failed",
        errors=(reason,),
        unknown_reasons={"observed_at": "no usable source result", "available_at": "no usable source result"},
    )
    normalized: dict[str, object] = {"raw_locator": "" if raw_payload is not None else None, "error_reason": reason}
    normalized.update(metadata or {})
    gap = _gap(
        request_id,
        required_content or f"usable {operation} source result",
        reason,
        coverage,
        "report the source limitation and retry or use another approved evidence path",
        retrieved_at,
    )
    return {
        "source_result": source.model_dump(mode="json"),
        "raw_payload": raw_payload,
        "normalized": normalized,
        "evidence": [],
        "gaps": [gap.model_dump(mode="json")],
    }


def _gap(
    request_id: str,
    required: str,
    result: str,
    impact: str,
    next_action: str,
    attempted_at: datetime,
) -> DataGap:
    return DataGap(
        gap_id=f"gap_{uuid.uuid4().hex}",
        request_id=request_id,
        required_content=required,
        attempts=(
            {
                "source": "finnhub",
                "at": attempted_at.isoformat(),
                "result": result,
            },
        ),
        impact=impact,
        next_action=next_action,
    )


def _credential(settings: Settings, name: str) -> str:
    configured = settings.credentials.get(name)
    if isinstance(configured, SecretStr):
        value = configured.get_secret_value()
        if value:
            return value
    return os.environ.get(name, "")


def _safe_request_id(request: Mapping[str, object]) -> str:
    value = request.get("request_id")
    return value if isinstance(value, str) and value else "unavailable"


def _required_string(request: Mapping[str, object], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _aware_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


def _date_parameter(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _unix_time(value: object) -> datetime | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _contains_secret_value(value: object, secret: str) -> bool:
    if not secret:
        return False
    if isinstance(value, str):
        return secret in value
    if isinstance(value, Mapping):
        return any(_contains_secret_value(item, secret) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret_value(item, secret) for item in value)
    return False


def _safe_retry_after(value: str | None) -> int | str | None:
    if value is None:
        return None
    if value.isdecimal():
        return int(value)
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()
