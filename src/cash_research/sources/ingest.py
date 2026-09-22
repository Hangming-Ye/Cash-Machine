"""Local-file import for attributable text material and complete numeric series."""

from __future__ import annotations

import csv
import base64
import hashlib
import io
import json
import math
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from cash_research.artifacts import ArtifactError, reject_secrets, safe_relative_path
from cash_research.config import Settings
from cash_research.models import DataGap, Evidence, SecurityIdentity, SourceResult


_CONTENT_KINDS = {
    "disclosure_fact",
    "third_party_view",
    "research_hypothesis",
    "calculation_result",
}
_TEXT_EXTENSIONS = {".txt", ".md", ".json"}
_OPAQUE_EXTENSIONS = {".pdf"}
_SERIES_EXTENSIONS = {".csv", ".json"}
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|authorization)\s*[:=]\s*\S+"
)


class MaterialValidationError(ValueError):
    """A sanitized material defect with an explicit evidence gap."""

    def __init__(self, required_content: str, result: str, impact: str, next_action: str) -> None:
        super().__init__(required_content)
        self.required_content = required_content
        self.result = result
        self.impact = impact
        self.next_action = next_action


class MaterialIngestAdapter:
    """Validate already-obtained local material without network access or persistence."""

    def __init__(
        self,
        settings: Settings,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(
        self, request: Mapping[str, object], *, output_ref: str
    ) -> dict[str, object]:
        request_id = _safe_request_id(request)
        operation = str(request.get("operation") or "unknown")
        subject: SecurityIdentity | str = "invalid ingest subject"
        try:
            reject_secrets(request)
            (
                request_id,
                source,
                operation,
                subject,
                as_of,
                parameters,
                required_fields,
                input_path,
            ) = self._validate_request(request, output_ref)
        except (ArtifactError, ValidationError, ValueError):
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=_aware_now(self._clock),
                reason="invalid",
                coverage="ingest request failed validation before reading usable material",
            )

        retrieved_at = _aware_now(self._clock)
        try:
            if source == "user_provided_material" and operation == "text_ingest":
                return self._text_result(
                    request_id=request_id,
                    subject=subject,
                    as_of=as_of,
                    parameters=parameters,
                    required_fields=required_fields,
                    input_path=input_path,
                    output_ref=output_ref,
                    retrieved_at=retrieved_at,
                )
            if source == "user_provided_series" and operation == "series_ingest":
                if not isinstance(subject, SecurityIdentity):
                    raise ValueError
                return self._series_result(
                    request_id=request_id,
                    subject=subject,
                    as_of=as_of,
                    parameters=parameters,
                    required_fields=required_fields,
                    input_path=input_path,
                    output_ref=output_ref,
                    retrieved_at=retrieved_at,
                )
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="unsupported",
                coverage="operation is outside local text/series ingest",
            )
        except MaterialValidationError as exc:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="local material failed a time, coverage, or schema boundary",
                required_content=exc.required_content,
                attempt_result=exc.result,
                impact=exc.impact,
                next_action=exc.next_action,
            )
        except (ArtifactError, UnicodeDecodeError, json.JSONDecodeError, OSError, ValidationError, ValueError):
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="local material was malformed, unsafe, or inconsistent with declared metadata",
            )

    def _validate_request(
        self, request: Mapping[str, object], output_ref: str
    ) -> tuple[
        str,
        str,
        str,
        SecurityIdentity | str,
        datetime,
        dict[str, object],
        tuple[str, ...],
        Path,
    ]:
        request_id = _required_string(request, "request_id")
        source = _required_string(request, "source")
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
        if len(set(required_fields)) != len(required_fields):
            raise ValueError

        raw_subject = request.get("subject")
        if isinstance(raw_subject, Mapping):
            subject: SecurityIdentity | str = SecurityIdentity.model_validate(raw_subject)
        elif isinstance(raw_subject, str) and raw_subject:
            subject = raw_subject
        else:
            raise ValueError

        if not isinstance(output_ref, str):
            raise ValueError
        output_parts = PurePosixPath(output_ref.replace("\\", "/")).parts
        if not output_parts or output_parts[0] != "data" or any(
            part.lower() in {"tmp", "temp", "draft", "drafts"} for part in output_parts
        ):
            raise ValueError
        output_path = safe_relative_path(
            self._settings.root, output_ref, must_exist=False
        )
        _reject_reparse_components(self._settings.root, output_ref)
        if output_path.exists():
            raise ValueError
        input_ref = _required_string(parameters, "path")
        input_path = safe_relative_path(self._settings.root, input_ref)
        _reject_reparse_components(self._settings.root, input_ref)
        if input_path == output_path:
            raise ValueError
        return (
            request_id,
            source,
            operation,
            subject,
            as_of,
            parameters,
            tuple(required_fields),
            input_path,
        )

    def _text_result(
        self,
        *,
        request_id: str,
        subject: SecurityIdentity | str,
        as_of: datetime,
        parameters: dict[str, object],
        required_fields: tuple[str, ...],
        input_path: Path,
        output_ref: str,
        retrieved_at: datetime,
    ) -> dict[str, object]:
        suffix = input_path.suffix.lower()
        if suffix not in _TEXT_EXTENSIONS | _OPAQUE_EXTENSIONS:
            raise ValueError
        raw_bytes = input_path.read_bytes()
        metadata = _material_metadata(parameters, as_of)
        material_scope = parameters.get("material_scope")
        if material_scope not in {"complete_document", "excerpt"}:
            raise ValueError
        if suffix == ".pdf":
            return self._opaque_pdf_result(
                request_id=request_id,
                subject=subject,
                metadata=metadata,
                material_scope=material_scope,
                required_fields=required_fields,
                input_path=input_path,
                output_ref=output_ref,
                retrieved_at=retrieved_at,
                raw_bytes=raw_bytes,
            )
        text = raw_bytes.decode("utf-8")
        if suffix == ".json":
            parsed = json.loads(text)
            reject_secrets(parsed)
        _reject_material_secrets(text, self._settings)

        limitations = list(metadata["limitations"])
        limitations.append("ingest validation preserves material but does not establish semantic truth")
        limitations.append("document completeness follows the supplied material_scope declaration")
        if material_scope == "excerpt":
            limitations.append("provided material is an excerpt and not a complete source document")

        raw_payload = {
            "input_ref": input_path.relative_to(self._settings.root).as_posix(),
            "media_type": _media_type(input_path),
            "encoding": "utf-8",
            "size": len(raw_bytes),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "content_utf8": text,
        }
        normalized: dict[str, object] = {
            "raw_locator": "/content_utf8",
            "source_locator": "/content_utf8",
            "original_locator": metadata["locator"],
            "origin_url": metadata["origin_url"],
            "source_name": metadata["source_name"],
            "author": metadata["author"],
            "organization": metadata["organization"],
            "access_scope": metadata["access_scope"],
            "material_scope": material_scope,
            "semantic_validation": "not_claimed",
            "limitations": limitations,
        }
        gaps: list[DataGap] = []
        quality = "complete"
        if material_scope == "excerpt":
            quality = "limited"
            gaps.append(
                _gap(
                    request_id,
                    "complete original document",
                    metadata["source_name"],
                    retrieved_at,
                    "only an excerpt was supplied",
                    "claims requiring full-document context remain limited",
                    "obtain the complete attributable document",
                )
            )
        quality = _time_and_required_gaps(
            request_id=request_id,
            metadata=metadata,
            normalized=normalized,
            required_fields=required_fields,
            retrieved_at=retrieved_at,
            gaps=gaps,
            quality=quality,
        )
        evidence = Evidence(
            evidence_id=_new_id("evi"),
            source_ref=output_ref,
            locator="/content_utf8",
            published_at=metadata["published_at"],
            retrieved_at=retrieved_at,
            available_at=metadata["available_at"],
            content_kind=metadata["content_kind"],
            claim=metadata["claim"],
            scope=metadata["scope"],
            units=(),
            limitations=tuple(limitations),
            unknown_reasons=_time_unknown_reasons(metadata),
        )
        source_result = SourceResult(
            source="user_provided_material",
            operation="text_ingest",
            security_or_topic=subject,
            observed_at=metadata["published_at"],
            retrieved_at=retrieved_at,
            available_at=metadata["available_at"],
            coverage=(
                "one complete attributable local text document"
                if material_scope == "complete_document"
                else "one attributable local text excerpt"
            ),
            payload_ref=output_ref,
            quality=quality,
            errors=(),
            unknown_reasons=_source_time_unknown_reasons(
                observed_at=metadata["published_at"],
                available_at=metadata["available_at"],
            ),
        )
        return _result(source_result, raw_payload, normalized, [evidence], gaps)

    def _opaque_pdf_result(
        self,
        *,
        request_id: str,
        subject: SecurityIdentity | str,
        metadata: dict[str, Any],
        material_scope: str,
        required_fields: tuple[str, ...],
        input_path: Path,
        output_ref: str,
        retrieved_at: datetime,
        raw_bytes: bytes,
    ) -> dict[str, object]:
        if not raw_bytes.startswith(b"%PDF-") or not raw_bytes.rstrip().endswith(b"%%EOF"):
            raise ValueError
        _reject_material_secrets(raw_bytes.decode("latin-1"), self._settings)
        limitations = list(metadata["limitations"])
        limitations.extend(
            (
                "PDF bytes were archived losslessly without text extraction",
                "ingest did not validate PDF semantics, page count, layout, or the declared claim",
                "document completeness follows the supplied material_scope declaration",
            )
        )
        if material_scope == "excerpt":
            limitations.append("provided PDF was declared as an excerpt")
        raw_payload = {
            "input_ref": input_path.relative_to(self._settings.root).as_posix(),
            "media_type": "application/pdf",
            "encoding": "base64",
            "size": len(raw_bytes),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "content_base64": base64.b64encode(raw_bytes).decode("ascii"),
        }
        normalized: dict[str, object] = {
            "raw_locator": "/content_base64",
            "source_locator": "/content_base64",
            "original_locator": metadata["locator"],
            "origin_url": metadata["origin_url"],
            "source_name": metadata["source_name"],
            "author": metadata["author"],
            "organization": metadata["organization"],
            "access_scope": metadata["access_scope"],
            "material_scope": material_scope,
            "opaque_binary": True,
            "text_extracted": False,
            "semantic_validation": "not_claimed",
            "declared_content_kind": metadata["content_kind"],
            "limitations": limitations,
        }
        gaps = [
            _gap(
                request_id,
                "native review or attributable extracted text for PDF semantics",
                metadata["source_name"],
                retrieved_at,
                "PDF was preserved as opaque bytes; no text was extracted",
                "document content and declared claim are not semantically validated by ingest",
                "reconstruct the PDF attachment and inspect it with the native viewer or provide attributable text",
            )
        ]
        quality = _time_and_required_gaps(
            request_id=request_id,
            metadata=metadata,
            normalized=normalized,
            required_fields=required_fields,
            retrieved_at=retrieved_at,
            gaps=gaps,
            quality="limited",
        )
        evidence = Evidence(
            evidence_id=_new_id("evi"),
            source_ref=output_ref,
            locator="/content_base64",
            published_at=metadata["published_at"],
            retrieved_at=retrieved_at,
            available_at=metadata["available_at"],
            content_kind=metadata["content_kind"],
            claim="An attributable PDF file was archived without semantic extraction.",
            scope=metadata["scope"],
            units=(),
            limitations=tuple(limitations),
            unknown_reasons=_time_unknown_reasons(metadata),
        )
        source_result = SourceResult(
            source="user_provided_material",
            operation="text_ingest",
            security_or_topic=subject,
            observed_at=metadata["published_at"],
            retrieved_at=retrieved_at,
            available_at=metadata["available_at"],
            coverage="one attributable opaque PDF; semantic review not performed by ingest",
            payload_ref=output_ref,
            quality=quality,
            errors=(),
            unknown_reasons=_source_time_unknown_reasons(
                observed_at=metadata["published_at"],
                available_at=metadata["available_at"],
            ),
        )
        return _result(source_result, raw_payload, normalized, [evidence], gaps)

    def _series_result(
        self,
        *,
        request_id: str,
        subject: SecurityIdentity,
        as_of: datetime,
        parameters: dict[str, object],
        required_fields: tuple[str, ...],
        input_path: Path,
        output_ref: str,
        retrieved_at: datetime,
    ) -> dict[str, object]:
        if input_path.suffix.lower() not in _SERIES_EXTENSIONS:
            raise ValueError
        raw_bytes = input_path.read_bytes()
        text = raw_bytes.decode("utf-8")
        rows = _series_rows(input_path, text)
        reject_secrets(rows)
        _reject_material_secrets(text, self._settings)
        metadata = _series_metadata(parameters, subject, as_of)
        normalized_rows, timestamps, displayed_timestamps = _normalize_rows(
            rows, metadata, subject, as_of
        )
        if not normalized_rows:
            raise ValueError

        coverage_start = timestamps[0].date().isoformat()
        coverage_end = timestamps[-1].date().isoformat()
        requested_start = metadata["requested_start"]
        requested_end = metadata["requested_end"]
        covers_request = (
            requested_start is None
            or requested_end is None
            or (timestamps[0].date() <= requested_start and timestamps[-1].date() >= requested_end)
        )
        complete_requested_range = (
            metadata["series_scope"] == "complete_requested_range"
            and covers_request
            and metadata["expected_timestamps"] is not None
            and displayed_timestamps == metadata["expected_timestamps"]
        )
        observed_gaps = _observed_calendar_gaps(timestamps, metadata["bar_interval"])
        limitations = list(metadata["limitations"])
        limitations.append("no market calendar was inferred; date gaps are calendar observations only")
        limitations.append("coverage completeness follows the supplied file and declared range")
        limitations.append("security identity is declared by the request and checked against row fields when present")
        limitations.append("point-in-time availability is not proven by ingest")

        normalized: dict[str, object] = {
            "raw_locator": "/content_utf8",
            "source_locator": "/parsed_rows",
            "original_locator": metadata["locator"],
            "origin_url": metadata["origin_url"],
            "source_name": metadata["source_name"],
            "organization": metadata["organization"],
            "access_scope": metadata["access_scope"],
            "schema": {
                "timestamp_field": metadata["timestamp_field"],
                "value_fields": list(metadata["value_fields"]),
            },
            "bar_interval": metadata["bar_interval"],
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "row_count": len(normalized_rows),
            "unit": metadata["unit"],
            "column_units": metadata["column_units"],
            "currency": metadata["currency"],
            "price_basis": metadata["price_basis"],
            "identity": subject.model_dump(mode="json"),
            "identity_validation": "request identity; matching row identity fields checked when present",
            "adjustment_status": metadata["adjustment_status"],
            "revision_status": metadata["revision_status"],
            "declared_point_in_time_status": metadata["declared_point_in_time_status"],
            "point_in_time_status": "not_proven_by_ingest",
            "series_scope": metadata["series_scope"],
            "complete_requested_range": complete_requested_range,
            "coverage_verification": (
                "declared_expected_timestamps_match"
                if complete_requested_range
                else "unverified_or_incomplete"
            ),
            "coverage_basis": metadata["coverage_basis"],
            "observed_date_gaps": observed_gaps,
            "rows": normalized_rows,
            "limitations": limitations,
        }
        raw_payload = {
            "input_ref": input_path.relative_to(self._settings.root).as_posix(),
            "media_type": _media_type(input_path),
            "encoding": "utf-8",
            "size": len(raw_bytes),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "content_utf8": text,
            "parsed_rows": rows,
        }
        gaps: list[DataGap] = []
        quality = "complete"
        if not complete_requested_range:
            quality = "limited"
            gaps.append(
                _gap(
                    request_id,
                    "declared requested-range coverage",
                    metadata["source_name"],
                    retrieved_at,
                    f"provided {coverage_start} through {coverage_end} as {metadata['series_scope']}",
                    "complete requested history is not verified",
                    "provide attributable expected timestamps or calendar/cadence evidence for the range",
                )
            )
        if metadata["adjustment_status"] == "unknown":
            quality = "limited"
            gaps.append(
                _gap(
                    request_id,
                    "adjustment and corporate-action provenance",
                    metadata["source_name"],
                    retrieved_at,
                    "adjustment status was declared unknown",
                    "adjusted-return use is unsupported",
                    "obtain adjustment and corporate-action metadata",
                )
            )
        quality = _time_and_required_gaps(
            request_id=request_id,
            metadata=metadata,
            normalized=normalized,
            required_fields=required_fields,
            retrieved_at=retrieved_at,
            gaps=gaps,
            quality=quality,
        )
        evidence = Evidence(
            evidence_id=_new_id("evi"),
            source_ref=output_ref,
            locator="/parsed_rows",
            published_at=metadata["published_at"],
            retrieved_at=retrieved_at,
            available_at=metadata["available_at"],
            content_kind="calculation_result",
            claim=(
                f"The imported file contains {len(normalized_rows)} ordered rows from "
                f"{coverage_start} through {coverage_end}."
            ),
            scope=f"{coverage_start} through {coverage_end}; {len(normalized_rows)} rows",
            units=tuple(dict.fromkeys(metadata["column_units"].values())),
            limitations=tuple(limitations),
            unknown_reasons=_time_unknown_reasons(metadata),
        )
        source_result = SourceResult(
            source="user_provided_series",
            operation="series_ingest",
            security_or_topic=subject,
            observed_at=None,
            retrieved_at=retrieved_at,
            available_at=metadata["available_at"],
            coverage=(
                f"{len(normalized_rows)} ordered rows from {coverage_start} through "
                f"{coverage_end}; scope={metadata['series_scope']}"
            ),
            payload_ref=output_ref,
            quality=quality,
            errors=(),
            unknown_reasons=_source_time_unknown_reasons(
                observed_at=None,
                available_at=metadata["available_at"],
                observed_reason="series rows provide dates rather than one observation instant",
            ),
        )
        return _result(source_result, raw_payload, normalized, [evidence], gaps)


def _material_metadata(parameters: Mapping[str, object], as_of: datetime) -> dict[str, Any]:
    content_kind = _required_string(parameters, "content_kind")
    if content_kind not in _CONTENT_KINDS:
        raise ValueError
    metadata: dict[str, Any] = {
        "locator": _required_string(parameters, "locator"),
        "origin_url": _optional_url(parameters.get("origin_url")),
        "source_name": _required_string(parameters, "source_name"),
        "author": _optional_string(parameters.get("author")),
        "organization": _optional_string(parameters.get("organization")),
        "access_scope": _required_string(parameters, "access_scope"),
        "published_at": _optional_aware_time(parameters.get("published_at")),
        "available_at": _optional_aware_time(parameters.get("available_at")),
        "content_kind": content_kind,
        "claim": _required_string(parameters, "claim"),
        "scope": _required_string(parameters, "scope"),
        "limitations": _string_list(parameters.get("limitations"), allow_empty=True),
    }
    _reject_future_times(metadata, as_of)
    if (
        metadata["published_at"] is not None
        and metadata["available_at"] is not None
        and metadata["available_at"] < metadata["published_at"]
    ):
        raise ValueError
    return metadata


def _series_metadata(
    parameters: Mapping[str, object], subject: SecurityIdentity, as_of: datetime
) -> dict[str, Any]:
    metadata = _material_metadata(
        {
            **parameters,
            "content_kind": "calculation_result",
            "claim": "numeric series import",
            "scope": "declared numeric file",
        },
        as_of,
    )
    value_fields = _string_list(parameters.get("value_fields"))
    column_units_raw = parameters.get("column_units")
    uniform_unit = parameters.get("unit")
    if column_units_raw is None:
        if len(value_fields) != 1 or not isinstance(uniform_unit, str) or not uniform_unit:
            raise ValueError
        column_units = {value_fields[0]: uniform_unit}
    else:
        if not isinstance(column_units_raw, dict) or set(column_units_raw) != set(value_fields):
            raise ValueError
        if not all(isinstance(value, str) and value for value in column_units_raw.values()):
            raise ValueError
        column_units = dict(column_units_raw)
    distinct_units = tuple(dict.fromkeys(column_units.values()))
    normalized_unit = distinct_units[0] if len(distinct_units) == 1 else None

    market_timezone = _required_string(parameters, "market_timezone")
    try:
        ZoneInfo(market_timezone)
    except ZoneInfoNotFoundError:
        raise ValueError from None
    expected_raw = parameters.get("expected_timestamps")
    expected_timestamps: list[str] | None
    if expected_raw is None:
        expected_timestamps = None
    else:
        if not isinstance(expected_raw, list) or not expected_raw:
            raise ValueError
        expected_timestamps = []
        expected_order: list[datetime] = []
        for value in expected_raw:
            parsed, displayed, _ = _series_time(value, market_timezone)
            if expected_order and parsed <= expected_order[-1]:
                raise ValueError
            expected_order.append(parsed)
            expected_timestamps.append(displayed)

    metadata.update(
        {
            "timestamp_field": _required_string(parameters, "timestamp_field"),
            "value_fields": value_fields,
            "unit": normalized_unit,
            "column_units": column_units,
            "currency": _required_string(parameters, "currency"),
            "bar_interval": _required_string(parameters, "bar_interval"),
            "price_basis": _required_string(parameters, "price_basis"),
            "adjustment_status": _required_string(parameters, "adjustment_status"),
            "revision_status": _required_string(parameters, "revision_status"),
            "declared_point_in_time_status": _required_string(parameters, "point_in_time_status"),
            "series_scope": _required_string(parameters, "series_scope"),
            "requested_start": _optional_date(parameters.get("requested_start")),
            "requested_end": _optional_date(parameters.get("requested_end")),
            "market_timezone": market_timezone,
            "expected_timestamps": expected_timestamps,
            "coverage_basis": (
                _required_string(parameters, "coverage_basis")
                if expected_timestamps is not None
                else None
            ),
        }
    )
    if metadata["currency"] != subject.currency:
        raise ValueError
    if metadata["series_scope"] not in {"complete_requested_range", "fragment"}:
        raise ValueError
    if not metadata["value_fields"]:
        raise ValueError
    if (
        metadata["requested_start"] is not None
        and metadata["requested_end"] is not None
        and metadata["requested_start"] > metadata["requested_end"]
    ):
        raise ValueError
    return metadata


def _series_rows(path: Path, text: str) -> list[dict[str, object]]:
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError
        return [dict(row) for row in reader]
    value = json.loads(text)
    if isinstance(value, dict):
        value = value.get("rows")
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError
    return [dict(row) for row in value]


def _normalize_rows(
    rows: list[dict[str, object]],
    metadata: Mapping[str, Any],
    subject: SecurityIdentity,
    as_of: datetime,
) -> tuple[list[dict[str, object]], list[datetime], list[str]]:
    normalized: list[dict[str, object]] = []
    timestamps: list[datetime] = []
    displayed_timestamps: list[str] = []
    timestamp_field = metadata["timestamp_field"]
    value_fields = metadata["value_fields"]
    previous: datetime | None = None
    seen: set[datetime] = set()
    for raw in rows:
        if timestamp_field not in raw:
            raise ValueError
        timestamp, displayed, precision = _series_time(
            raw[timestamp_field], metadata["market_timezone"]
        )
        availability = metadata["available_at"]
        if precision == "date":
            market_zone = ZoneInfo(metadata["market_timezone"])
            cutoff_date = as_of.astimezone(market_zone).date()
            if availability is not None:
                cutoff_date = min(cutoff_date, availability.astimezone(market_zone).date())
            if timestamp.date() > cutoff_date:
                raise MaterialValidationError(
                    "series rows available no later than as_of",
                    "a date-only row is after the request or file-availability cutoff in the declared market timezone",
                    "future row would leak into historical analysis",
                    "remove future rows or use a later truthful cutoff",
                )
        elif timestamp > as_of or (availability is not None and timestamp > availability):
            raise MaterialValidationError(
                "series rows available no later than as_of",
                "a timestamped row is after the request or file-availability cutoff",
                "future row would leak into historical analysis",
                "remove future rows or use a later truthful cutoff",
            )
        if timestamp in seen or (previous is not None and timestamp <= previous):
            raise ValueError
        seen.add(timestamp)
        previous = timestamp
        row: dict[str, object] = {timestamp_field: displayed}
        for field in value_fields:
            if field not in raw:
                raise ValueError
            row[field] = _finite_number(raw[field])
        for identity_field, expected in (
            ("market", subject.market),
            ("exchange", subject.exchange),
            ("symbol", subject.symbol),
            ("currency", metadata["currency"]),
        ):
            value = raw.get(identity_field)
            if value not in (None, "") and value != expected:
                raise ValueError
            if identity_field == "currency":
                row[identity_field] = expected
        normalized.append(row)
        timestamps.append(timestamp)
        displayed_timestamps.append(displayed)
    return normalized, timestamps, displayed_timestamps


def _observed_calendar_gaps(
    timestamps: list[datetime], bar_interval: str
) -> list[dict[str, object]]:
    if bar_interval != "1d":
        return []
    gaps: list[dict[str, object]] = []
    for left, right in zip(timestamps, timestamps[1:]):
        days = (right.date() - left.date()).days
        if days > 1:
            gaps.append(
                {
                    "after": left.date().isoformat(),
                    "before": right.date().isoformat(),
                    "calendar_days_without_rows": days - 1,
                    "market_session_status": "not_inferred_without_calendar",
                }
            )
    return gaps


def _time_and_required_gaps(
    *,
    request_id: str,
    metadata: Mapping[str, Any],
    normalized: Mapping[str, object],
    required_fields: tuple[str, ...],
    retrieved_at: datetime,
    gaps: list[DataGap],
    quality: str,
) -> str:
    if metadata["published_at"] is None:
        quality = "limited"
    if metadata["available_at"] is None:
        quality = "limited"
    available: dict[str, object] = {
        **normalized,
        "published_at": metadata["published_at"],
        "available_at": metadata["available_at"],
        "source_locator": metadata["locator"],
        "access_scope": metadata["access_scope"],
        "limitations": metadata["limitations"],
        "coverage": normalized.get("coverage_start"),
        "market_date": normalized.get("coverage_start"),
    }
    for field in required_fields:
        value = available.get(field)
        unusable = value in (None, "", [], {})
        if field == "point_in_time_status" and value != "proven":
            unusable = True
        if field == "adjustment_status" and value == "unknown":
            unusable = True
        if field == "revision_status" and value in {"unknown", "unresolved"}:
            unusable = True
        if unusable:
            quality = "limited"
            gaps.append(
                _gap(
                    request_id,
                    field,
                    metadata["source_name"],
                    retrieved_at,
                    "required field was absent or unknown",
                    f"claims requiring {field} remain limited",
                    f"obtain attributable material with {field}",
                )
            )
    return quality


def _gap(
    request_id: str,
    required_content: str,
    source: str,
    at: datetime,
    result: str,
    impact: str,
    next_action: str,
) -> DataGap:
    return DataGap(
        gap_id=_new_id("gap"),
        request_id=request_id,
        required_content=required_content,
        attempts=({"source": source, "at": at.isoformat(), "result": result},),
        impact=impact,
        next_action=next_action,
    )


def _result(
    source_result: SourceResult,
    raw_payload: object,
    normalized: dict[str, object],
    evidence: list[Evidence],
    gaps: list[DataGap],
) -> dict[str, object]:
    return {
        "source_result": source_result.model_dump(mode="json"),
        "raw_payload": raw_payload,
        "normalized": normalized,
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "gaps": [item.model_dump(mode="json") for item in gaps],
    }


def _failure(
    *,
    request_id: str,
    operation: str,
    subject: SecurityIdentity | str,
    retrieved_at: datetime,
    reason: str,
    coverage: str,
    required_content: str = "valid attributable local material",
    attempt_result: str | None = None,
    impact: str = "no evidence was created from this input",
    next_action: str = "correct the bounded input metadata or file and retry",
) -> dict[str, object]:
    source_result = SourceResult(
        source=(
            "user_provided_series" if operation == "series_ingest" else "user_provided_material"
        ),
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
            "observed_at": "no validated material observation was accepted",
            "available_at": "no validated material availability time was accepted",
        },
    )
    gap = _gap(
        request_id,
        required_content,
        "local ingest",
        retrieved_at,
        attempt_result or reason,
        impact,
        next_action,
    )
    return _result(source_result, None, {"error_reason": reason}, [], [gap])


def _required_string(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _optional_url(value: object) -> str | None:
    value = _optional_string(value)
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError
    return value


def _string_list(value: object, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError
    if not allow_empty and not value:
        raise ValueError
    return tuple(value)


def _aware_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


def _optional_aware_time(value: object) -> datetime | None:
    return None if value is None else _aware_time(value)


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value)


def _reject_future_times(metadata: Mapping[str, Any], as_of: datetime) -> None:
    for field in ("published_at", "available_at"):
        value = metadata[field]
        if value is not None and value > as_of:
            raise ValueError


def _series_time(value: object, market_timezone: str) -> tuple[datetime, str, str]:
    if not isinstance(value, str) or not value:
        raise ValueError
    if "T" not in value:
        parsed_date = date.fromisoformat(value)
        local = datetime.combine(parsed_date, time.min, tzinfo=ZoneInfo(market_timezone))
        return local, parsed_date.isoformat(), "date"
    parsed = _aware_time(value)
    return parsed, parsed.isoformat(), "datetime"


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError from None
    if not math.isfinite(number):
        raise ValueError
    return number


def _time_unknown_reasons(metadata: Mapping[str, Any]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    if metadata["published_at"] is None:
        reasons["published_at"] = "source publication time was not supplied"
    if metadata["available_at"] is None:
        reasons["available_at"] = "source availability time was not supplied"
    return reasons


def _source_time_unknown_reasons(
    *,
    observed_at: datetime | None,
    available_at: datetime | None,
    observed_reason: str = "source publication or observation time was not supplied",
) -> dict[str, str]:
    reasons: dict[str, str] = {}
    if observed_at is None:
        reasons["observed_at"] = observed_reason
    if available_at is None:
        reasons["available_at"] = "source availability time was not supplied"
    return reasons


def _media_type(path: Path) -> str:
    return {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".csv": "text/csv",
        ".pdf": "application/pdf",
    }[path.suffix.lower()]


def _reject_reparse_components(root: Path, ref: str) -> None:
    relative = PurePosixPath(ref.replace("\\", "/"))
    current = root.resolve(strict=True)
    for part in relative.parts:
        current = current / part
        if not current.exists() and not current.is_symlink():
            continue
        is_junction = getattr(current, "is_junction", lambda: False)
        if current.is_symlink() or is_junction():
            raise ValueError


def _reject_material_secrets(text: str, settings: Settings) -> None:
    reject_secrets(text)
    if _CREDENTIAL_ASSIGNMENT.search(text):
        raise ValueError
    for value in settings.credentials.values():
        secret = value.get_secret_value()
        if secret and secret in text:
            raise ValueError


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return timezone-aware datetime")
    return value


def _safe_request_id(request: Mapping[str, object]) -> str:
    value = request.get("request_id")
    return value if isinstance(value, str) and value else "unavailable"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
