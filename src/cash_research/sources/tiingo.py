"""Read-only Tiingo US daily EOD adapter."""

from __future__ import annotations

import math
import os
import re
import uuid
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr, ValidationError

from cash_research.artifacts import ArtifactError, reject_secrets, safe_relative_path
from cash_research.config import Settings
from cash_research.models import DataGap, SecurityIdentity, SourceResult


_BASE_URL = "https://api.tiingo.com"
_TIINGO_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
_NEW_YORK = ZoneInfo("America/New_York")
_ALLOWED_FIELDS = frozenset(
    {
        "raw_ohlcv",
        "adjusted_ohlcv",
        "div_cash",
        "split_factor",
        "market_date",
        "currency",
        "bar_interval",
        "adjustment_status",
    }
)


class TiingoAdapter:
    """Fetch Tiingo EOD daily rows without mixing adjustment bases."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._settings = settings
        self._credential = _credential(settings, "TIINGO_API_KEY")
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
            (
                request_id,
                operation,
                subject,
                as_of,
                start_date,
                end_date,
                bar_interval,
                price_basis,
                required_fields,
            ) = self._validate_request(request)
            safe_relative_path(self._settings.root, output_ref, must_exist=False)
        except (ArtifactError, ValidationError, ValueError):
            return _failure(
                request_id=request_id,
                operation=str(request.get("operation") or "unknown"),
                subject=subject,
                retrieved_at=_utc_now(),
                reason="invalid",
                coverage="request failed source-contract validation before any HTTP call",
            )

        if request.get("source") != "tiingo" or "tiingo" not in self._settings.enabled_sources:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=_utc_now(),
                reason="unsupported",
                coverage="Tiingo is not enabled for this request",
            )
        if operation != "bars":
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=_utc_now(),
                reason="unsupported",
                coverage="operation is outside the approved Tiingo daily-bars adapter",
            )
        if subject.market != "US":
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=_utc_now(),
                reason="unsupported",
                coverage="Tiingo adapter is limited to approved US daily history",
            )
        if bar_interval != "1d":
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=_utc_now(),
                reason="unsupported",
                coverage="Tiingo adapter supports approved daily history only",
            )
        if price_basis not in {"raw", "adjusted"}:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=_utc_now(),
                reason="invalid",
                coverage="price_basis must select raw or adjusted fields without mixing",
            )
        unsupported_fields = sorted(set(required_fields) - _ALLOWED_FIELDS)
        if unsupported_fields:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=_utc_now(),
                reason="unsupported",
                coverage="one or more required fields are outside Tiingo EOD",
                metadata={"unsupported_required_fields": unsupported_fields},
            )
        if not self._credential:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=_utc_now(),
                reason="unauthorized",
                coverage="Tiingo credential is unavailable from explicit settings or process environment",
            )

        try:
            response = self._client.get(
                f"{_BASE_URL}/tiingo/daily/{subject.symbol}/prices",
                params={
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "resampleFreq": "daily",
                },
                headers={"Authorization": f"Token {self._credential}"},
            )
        except httpx.HTTPError:
            return _failure(
                request_id=request_id,
                operation="bars",
                subject=subject,
                retrieved_at=_utc_now(),
                reason="external",
                coverage="Tiingo transport failed without a usable response",
            )
        retrieved_at = _utc_now()
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
                operation="bars",
                subject=subject,
                retrieved_at=retrieved_at,
                reason=reason,
                coverage="Tiingo returned no usable authorized EOD payload",
                metadata=metadata,
            )
        try:
            payload = response.json()
        except ValueError:
            return _failure(
                request_id=request_id,
                operation="bars",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="external",
                coverage="Tiingo returned a non-JSON EOD response",
                metadata={"http_status": response.status_code},
            )
        try:
            reject_secrets(payload)
        except ArtifactError:
            return _failure(
                request_id=request_id,
                operation="bars",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="Tiingo payload contained credential material and was discarded",
                metadata={"http_status": response.status_code},
            )
        if _contains_secret_value(payload, self._credential):
            return _failure(
                request_id=request_id,
                operation="bars",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="Tiingo payload reflected credential material and was discarded",
                metadata={"http_status": response.status_code},
            )
        if not isinstance(payload, list):
            return _failure(
                request_id=request_id,
                operation="bars",
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="Tiingo EOD payload was not a list",
                raw_payload=payload,
                output_ref=output_ref,
                metadata={"http_status": response.status_code},
            )
        if not payload:
            return _empty_result(
                request_id=request_id,
                subject=subject,
                retrieved_at=retrieved_at,
                output_ref=output_ref,
                start_date=start_date,
                end_date=end_date,
            )
        return _rows_result(
            payload,
            request_id=request_id,
            subject=subject,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
            price_basis=price_basis,
            required_fields=required_fields,
            retrieved_at=retrieved_at,
            output_ref=output_ref,
            http_status=response.status_code,
        )

    def _validate_request(
        self, request: Mapping[str, object]
    ) -> tuple[str, str, SecurityIdentity, datetime, date, date, str, str, tuple[str, ...]]:
        request_id = _required_string(request, "request_id")
        operation = _required_string(request, "operation")
        as_of = _aware_time(request.get("as_of"))
        subject = SecurityIdentity.model_validate(request.get("subject"))
        if not _TIINGO_SYMBOL.fullmatch(subject.symbol):
            raise ValueError
        parameters = request.get("parameters")
        required_fields = request.get("required_fields")
        if not isinstance(parameters, dict):
            raise ValueError
        if not isinstance(required_fields, list) or not all(
            isinstance(field, str) and field for field in required_fields
        ):
            raise ValueError
        start_date = _date_parameter(parameters.get("start_date"))
        end_date = _date_parameter(parameters.get("end_date"))
        if start_date is None or end_date is None or start_date > end_date:
            raise ValueError
        bar_interval = parameters.get("bar_interval")
        price_basis = parameters.get("price_basis")
        if not isinstance(bar_interval, str) or not isinstance(price_basis, str):
            raise ValueError
        return (
            request_id,
            operation,
            subject,
            as_of,
            start_date,
            end_date,
            bar_interval,
            price_basis,
            tuple(required_fields),
        )


def _rows_result(
    payload: list[object],
    *,
    request_id: str,
    subject: SecurityIdentity,
    as_of: datetime,
    start_date: date,
    end_date: date,
    price_basis: str,
    required_fields: tuple[str, ...],
    retrieved_at: datetime,
    output_ref: str,
    http_status: int,
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    invalid_rows = 0
    excluded_after_cutoff = 0
    excluded_outside_range = 0
    missing_fields: Counter[str] = Counter()
    market_cutoff_date = as_of.astimezone(_NEW_YORK).date()
    for raw_index, row in enumerate(payload):
        if not isinstance(row, dict):
            invalid_rows += 1
            continue
        returned_ticker = row.get("ticker")
        if returned_ticker is not None and returned_ticker != subject.symbol:
            invalid_rows += 1
            continue
        market_date = _market_date(row.get("date"))
        if market_date is None:
            invalid_rows += 1
            continue
        if market_date > market_cutoff_date:
            excluded_after_cutoff += 1
            continue
        if not (start_date <= market_date <= end_date):
            excluded_outside_range += 1
            continue
        raw = _basis(row, adjusted=False)
        adjusted = _basis(row, adjusted=True)
        raw_valid = _valid_ohlc(raw)
        adjusted_valid = _valid_ohlc(adjusted)
        selected = raw if price_basis == "raw" else adjusted
        selected_valid = raw_valid if price_basis == "raw" else adjusted_valid
        if not selected_valid:
            invalid_rows += 1
            continue
        if not raw_valid or raw["volume"] is None:
            missing_fields["raw_ohlcv"] += 1
        if not adjusted_valid or adjusted["volume"] is None:
            missing_fields["adjusted_ohlcv"] += 1
        div_cash = _number(row.get("divCash"))
        if div_cash is None or div_cash < 0:
            div_cash = None
            missing_fields["div_cash"] += 1
        split_factor = _number(row.get("splitFactor"))
        if split_factor is None or split_factor <= 0:
            split_factor = None
            missing_fields["split_factor"] += 1
        candidates.append(
            {
                "raw_index": raw_index,
                "market_date": market_date.isoformat(),
                "raw": raw,
                "adjusted": adjusted,
                "raw_ohlc_valid": raw_valid,
                "adjusted_ohlc_valid": adjusted_valid,
                "selected": selected,
                "div_cash": div_cash,
                "split_factor": split_factor,
                "unknown_reasons": {
                    **(
                        {"selected_volume": f"{price_basis} volume missing; the other basis was not substituted"}
                        if selected["volume"] is None
                        else {}
                    )
                },
            }
        )

    if not candidates and invalid_rows == len(payload):
        return _failure(
            request_id=request_id,
            operation="bars",
            subject=subject,
            retrieved_at=retrieved_at,
            reason="invalid",
            coverage="all Tiingo rows failed identity/date/numeric validation",
            raw_payload=payload,
            output_ref=output_ref,
            required_content="required_fields:market_date,selected_ohlc",
            metadata={"http_status": http_status, "actual_source": "tiingo:/tiingo/daily/{ticker}/prices"},
        )

    counts = Counter(str(row["market_date"]) for row in candidates)
    duplicate_dates = {market_date for market_date, count in counts.items() if count > 1}
    normalized_rows = [
        row for row in candidates if str(row["market_date"]) not in duplicate_dates
    ]
    normalized_rows.sort(key=lambda row: (str(row["market_date"]), int(row["raw_index"])))
    errors: list[str] = []
    gaps: list[DataGap] = []
    if invalid_rows:
        errors.append("invalid_rows")
        gaps.append(
            _gap(
                request_id,
                "required_fields:market_date,selected_ohlc,security_identity",
                f"{invalid_rows} malformed or mismatched rows retained only in raw payload",
                "coverage is partial",
                "retry or exclude malformed rows without defaults",
                retrieved_at,
            )
        )
    for field, count in missing_fields.items():
        errors.append("invalid_fields")
        gaps.append(
            _gap(
                request_id,
                f"required_field:{field}",
                f"{count} rows have missing or invalid {field}",
                f"{field} cannot be used for every row",
                "retain nulls and obtain complete adjustment/corporate-action data",
                retrieved_at,
                catalog="G-02",
            )
        )
    if excluded_after_cutoff:
        errors.append("stale")
        gaps.append(
            _gap(
                request_id,
                "daily rows no later than the research as_of cutoff",
                f"{excluded_after_cutoff} rows were after as_of",
                "later rows were excluded from normalized history",
                "change as_of only when the research cutoff changes",
                retrieved_at,
            )
        )
    if excluded_outside_range:
        errors.append("stale")
        gaps.append(
            _gap(
                request_id,
                "daily rows within requested start_date/end_date",
                f"{excluded_outside_range} rows were outside requested coverage",
                "out-of-range rows were excluded from normalized history",
                "retry or broaden the requested dates explicitly",
                retrieved_at,
            )
        )
    revision_status = "provider_history_may_revise"
    if duplicate_dates:
        errors.append("conflict")
        revision_status = "unresolved"
        gaps.append(
            _gap(
                request_id,
                "one unambiguous version per market date",
                f"conflicting duplicate rows for {', '.join(sorted(duplicate_dates))}",
                "duplicate dates were excluded rather than selected silently",
                "preserve raw versions and resolve revision provenance",
                retrieved_at,
                catalog="G-02",
            )
        )
    required_missing = set(required_fields) & set(missing_fields)
    if required_missing and not gaps:
        raise AssertionError("required missing fields must produce gaps")
    observed_unknown = "daily rows provide market dates rather than observation instants"
    available_unknown = "provider correction cadence is not a row-specific availability timestamp"
    source = SourceResult(
        source="tiingo",
        operation="bars",
        security_or_topic=subject,
        observed_at=None,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage=(
            f"requested {start_date.isoformat()} through {end_date.isoformat()}; "
            f"{len(normalized_rows)} of {len(payload)} raw rows normalized"
        ),
        payload_ref=output_ref,
        quality="limited",
        errors=tuple(dict.fromkeys(errors)),
        unknown_reasons={"observed_at": observed_unknown, "available_at": available_unknown},
    )
    return {
        "source_result": source.model_dump(mode="json"),
        "raw_payload": payload,
        "normalized": {
            "raw_locator": "",
            "actual_source": "tiingo:/tiingo/daily/{ticker}/prices",
            "http_status": http_status,
            "identity": subject.model_dump(mode="json"),
            "bar_interval": "1d",
            "market_timezone": "America/New_York",
            "units": {
                "price": f"{subject.currency}/share",
                "volume": "shares",
                "div_cash": f"{subject.currency}/share",
                "split_factor": "ratio",
            },
            "price_basis": price_basis,
            "volume_basis": price_basis,
            "requested_start_date": start_date.isoformat(),
            "requested_end_date": end_date.isoformat(),
            "as_of": as_of.isoformat(),
            "revision_status": revision_status,
            "point_in_time_status": "not_proven",
            "adjustment_status": {
                "raw": "unadjusted_provider_fields",
                "adjusted": "split_and_dividend_adjusted_provider_fields",
                "history": "provider_history_may_revise_after_corporate_actions",
                "limitations": [
                    "retrieval contains no immutable historical revision chain",
                    "daily market date is not a row-specific availability timestamp",
                ],
            },
            "excluded_after_cutoff": excluded_after_cutoff,
            "excluded_outside_range": excluded_outside_range,
            "rows": normalized_rows,
        },
        "evidence": [],
        "gaps": [gap.model_dump(mode="json") for gap in gaps],
    }


def _empty_result(
    *,
    request_id: str,
    subject: SecurityIdentity,
    retrieved_at: datetime,
    output_ref: str,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    source = SourceResult(
        source="tiingo",
        operation="bars",
        security_or_topic=subject,
        observed_at=None,
        retrieved_at=retrieved_at,
        available_at=None,
        coverage=f"valid empty response for {start_date.isoformat()} through {end_date.isoformat()}",
        payload_ref=output_ref,
        quality="limited",
        errors=(),
        unknown_reasons={"observed_at": "no daily rows returned", "available_at": "no daily rows returned"},
    )
    gap = _gap(
        request_id,
        "daily rows for requested coverage",
        "provider returned a valid empty list",
        "no series data; this is distinct from transport failure",
        "report the coverage gap and retry or use another approved path",
        retrieved_at,
    )
    return {
        "source_result": source.model_dump(mode="json"),
        "raw_payload": [],
        "normalized": {
            "raw_locator": "",
            "actual_source": "tiingo:/tiingo/daily/{ticker}/prices",
            "error_reason": "empty",
            "empty_is_failure": False,
            "rows": [],
        },
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
        source="tiingo",
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
    normalized: dict[str, object] = {
        "raw_locator": "" if raw_payload is not None else None,
        "error_reason": reason,
    }
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


def _basis(row: Mapping[str, object], *, adjusted: bool) -> dict[str, float | None]:
    prefix = "adj" if adjusted else ""
    values = {
        "open": _number(row.get(f"{prefix}Open" if adjusted else "open")),
        "high": _number(row.get(f"{prefix}High" if adjusted else "high")),
        "low": _number(row.get(f"{prefix}Low" if adjusted else "low")),
        "close": _number(row.get(f"{prefix}Close" if adjusted else "close")),
        "volume": _number(row.get(f"{prefix}Volume" if adjusted else "volume")),
    }
    for field in ("open", "high", "low", "close"):
        if values[field] is not None and values[field] <= 0:
            values[field] = None
    if values["volume"] is not None and values["volume"] < 0:
        values["volume"] = None
    return values


def _gap(
    request_id: str,
    required: str,
    result: str,
    impact: str,
    next_action: str,
    attempted_at: datetime,
    *,
    catalog: str | None = None,
) -> DataGap:
    prefix = f"{catalog}-" if catalog else "gap_"
    return DataGap(
        gap_id=f"{prefix}{uuid.uuid4().hex}",
        request_id=request_id,
        required_content=required,
        attempts=(
            {
                "source": "tiingo",
                "at": attempted_at.isoformat(),
                "result": result,
            },
        ),
        impact=impact,
        next_action=next_action,
    )


def _market_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _valid_ohlc(values: Mapping[str, float | None]) -> bool:
    open_ = values["open"]
    high = values["high"]
    low = values["low"]
    close = values["close"]
    if None in (open_, high, low, close):
        return False
    assert open_ is not None and high is not None and low is not None and close is not None
    return low <= min(open_, close) <= max(open_, close) <= high


def _required_string(request: Mapping[str, object], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


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


def _date_parameter(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _credential(settings: Settings, name: str) -> str:
    configured = settings.credentials.get(name)
    if isinstance(configured, SecretStr):
        value = configured.get_secret_value()
        if value:
            return value
    return os.environ.get(name, "")


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
