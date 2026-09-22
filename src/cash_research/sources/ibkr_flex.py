"""Read-only Interactive Brokers Activity Flex Web Service adapter."""

from __future__ import annotations

import csv
import io
import os
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from datetime import date as Date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import SecretStr, ValidationError

from cash_research.artifacts import ArtifactError, reject_secrets, safe_relative_path
from cash_research.config import RequestBoundaryError, Settings, validate_read_request
from cash_research.models import (
    AccountState,
    DataGap,
    PortfolioSnapshot,
    Position,
    Quantity,
    SecurityIdentity,
    SourceResult,
)


_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
_PENDING_CODES = frozenset({"1001", "1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"})
_INVALID_QUERY_CODES = frozenset({"1014", "1015", "1016", "1017"})
_UNAUTHORIZED_CODES = frozenset({"1002", "1003", "1012", "1013"})
_DATE = re.compile(r"^\d{8}$")
_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "accounts": frozenset({"account_ref", "currency", "balances", "retrieved_at", "reported_at"}),
    "positions": frozenset({"account_ref", "symbol", "market", "exchange", "currency", "quantity", "market_value", "cost_basis", "retrieved_at", "reported_at"}),
    "executions": frozenset({"account_ref", "trade_id", "order_id", "symbol", "side", "currency", "quantity", "price", "trade_done_at", "retrieved_at", "reported_at"}),
}
_EXCHANGE_MARKETS = {
    "XNAS": "US", "NASDAQ": "US", "XNYS": "US", "NYSE": "US", "XASE": "US", "AMEX": "US",
    "SEHK": "HK", "HKEX": "HK", "XHKG": "HK", "XETR": "EU",
}


class IbkrFlexReadOnlyAdapter:
    """Fetch saved Activity Flex reports without exposing any trading surface."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        poll_attempts: int = 3,
        poll_interval: float = 1.0,
        min_send_interval: float = 1.0,
    ) -> None:
        if poll_attempts < 1 or poll_attempts > 20:
            raise ValueError("poll_attempts must be between 1 and 20")
        if poll_interval < 0 or min_send_interval < 0:
            raise ValueError("poll intervals cannot be negative")
        self._settings = settings
        self._client = client
        self._sleep = sleeper
        self._clock = clock
        self._monotonic = monotonic
        self._poll_attempts = poll_attempts
        self._poll_interval = poll_interval
        self._min_send_interval = min_send_interval
        self._last_send_at: float | None = None
        self._send_times: deque[float] = deque()
        self._send_lock = threading.Lock()
        self._token = _setting(settings, "IBKR_FLEX_TOKEN")
        self._query_ids = {
            "default": _setting(settings, "IBKR_FLEX_QUERY_ID"),
            "accounts": _setting(settings, "IBKR_FLEX_QUERY_ID_ACCOUNTS"),
            "positions": _setting(settings, "IBKR_FLEX_QUERY_ID_POSITIONS"),
            "executions": _setting(settings, "IBKR_FLEX_QUERY_ID_EXECUTIONS"),
        }
        expected = _setting(settings, "IBKR_FLEX_EXPECTED_ACCOUNT_REFS")
        self._expected_accounts = frozenset(
            part.strip() for part in expected.split(",") if part.strip()
        )
        self._query_timezone = _setting(settings, "IBKR_FLEX_QUERY_TIMEZONE")

    def fetch(
        self, request: Mapping[str, object], *, output_ref: str
    ) -> dict[str, object]:
        retrieved_at = self._now()
        request_id = str(request.get("request_id") or "unknown-request")
        operation = str(request.get("operation") or "unknown")
        subject = request.get("subject")
        safe_subject = subject if isinstance(subject, str) and subject else "authorized-portfolio"
        try:
            validated = self._validate_request(request, output_ref)
        except (ArtifactError, RequestBoundaryError, TypeError, ValueError, ValidationError):
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=safe_subject,
                retrieved_at=retrieved_at,
                reason="invalid",
                coverage="IBKR Flex request was rejected before network access",
            )

        request_id = validated["request_id"]
        operation = validated["operation"]
        subject = validated["subject"]
        query_id = validated["query_id"]
        send_params: dict[str, str] = {"t": self._token, "q": query_id, "v": "3"}
        send_params.update(validated["date_params"])

        send = self._send_request(send_params)
        if not send["ok"]:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=send["at"],
                reason=send["reason"],
                coverage="IBKR Flex report request failed",
                metadata=send.get("metadata"),
            )

        reference = send["reference"]
        report: dict[str, object] | None = None
        for attempt in range(1, self._poll_attempts + 1):
            if attempt > 1:
                self._sleep(self._poll_interval)
            report = self._get_statement(reference)
            if report["ok"] or report["reason"] != "pending":
                break
        assert report is not None
        if not report["ok"]:
            metadata = dict(report.get("metadata") or {})
            metadata["poll_attempts"] = attempt
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=report["at"],
                reason=report["reason"],
                coverage="IBKR Flex report retrieval failed",
                metadata=metadata,
            )

        raw = report["body"]
        if self._token and self._token in raw:
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=report["at"],
                reason="secret_reflection",
                coverage="IBKR response reflected configured credential content",
            )
        try:
            if report["format"] == "xml":
                parsed = self._parse_xml(raw, operation)
            else:
                parsed = self._parse_csv(raw, operation)
        except (ET.ParseError, UnicodeError, ValueError):
            return _failure(
                request_id=request_id,
                operation=operation,
                subject=subject,
                retrieved_at=report["at"],
                reason="invalid_response",
                coverage="IBKR Flex returned an unusable report",
            )
        return self._build_result(
            request_id=request_id,
            operation=operation,
            subject=subject,
            required_fields=validated["required_fields"],
            as_of=validated["as_of"],
            output_ref=output_ref.replace("\\", "/"),
            retrieved_at=report["at"],
            raw=raw,
            parsed=parsed,
        )

    def _validate_request(
        self, request: Mapping[str, object], output_ref: str
    ) -> dict[str, Any]:
        reject_secrets(dict(request))
        validate_read_request(request)
        if request.get("source") != "ibkr_flex" or "ibkr_flex" not in self._settings.enabled_sources:
            raise RequestBoundaryError("IBKR Flex source is not enabled")
        required_keys = {
            "request_id", "source", "operation", "subject", "as_of", "parameters", "required_fields"
        }
        if not required_keys <= set(request):
            raise ValueError("request keys are incomplete")
        request_id = request["request_id"]
        operation = request["operation"]
        subject = request["subject"]
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be non-empty")
        if operation not in {"accounts", "positions", "executions"}:
            raise ValueError("operation is unsupported")
        if subject != "authorized-portfolio":
            raise ValueError("subject must identify the authorized portfolio")
        as_of = request["as_of"]
        if not isinstance(as_of, str):
            raise ValueError("as_of must be a timestamp")
        parsed_time = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            raise ValueError("as_of requires timezone")
        parameters = request["parameters"]
        required_fields = request["required_fields"]
        if not isinstance(parameters, Mapping) or not isinstance(required_fields, list):
            raise ValueError("parameters and required_fields have invalid shape")
        if not all(isinstance(field, str) and field for field in required_fields):
            raise ValueError("required_fields must contain names")
        if set(required_fields) - _REQUIRED_FIELDS[str(operation)]:
            raise ValueError("unsupported required field")
        allowed_parameters = {"query_ref", "from_date", "to_date", "period"}
        if set(parameters) - allowed_parameters:
            raise ValueError("unsupported IBKR Flex parameter")
        query_ref = parameters.get("query_ref", operation)
        if query_ref not in {"default", "accounts", "positions", "executions"}:
            raise ValueError("unknown query reference")
        if not self._token:
            raise ValueError("IBKR Flex token is unavailable")
        query_id = self._query_ids.get(str(query_ref)) or self._query_ids["default"]
        if not query_id:
            raise ValueError("IBKR Flex query is unavailable")
        date_params = _date_parameters(parameters)
        safe_relative_path(self._settings.root, output_ref, must_exist=False)
        suffix = Path(output_ref).suffix.lower()
        if suffix not in {".xml", ".csv", ".json"}:
            raise ValueError("output_ref must be a supported raw container")
        return {
            "request_id": request_id,
            "operation": operation,
            "subject": subject,
            "query_id": query_id,
            "date_params": date_params,
            "required_fields": tuple(required_fields),
            "as_of": parsed_time.astimezone(timezone.utc),
        }

    def _send_request(self, params: Mapping[str, str]) -> dict[str, Any]:
        with self._send_lock:
            now_mono = self._monotonic()
            while self._send_times and now_mono - self._send_times[0] >= 60.0:
                self._send_times.popleft()
            minute_wait = (
                max(0.0, 60.0 - (now_mono - self._send_times[0]))
                if len(self._send_times) >= 10
                else 0.0
            )
            if self._last_send_at is not None:
                second_wait = max(
                    0.0, self._min_send_interval - (now_mono - self._last_send_at)
                )
            else:
                second_wait = 0.0
            wait_for = max(minute_wait, second_wait)
            if wait_for > 0:
                self._sleep(wait_for)
            response = self._http_get("SendRequest", params)
            sent_at = self._monotonic()
            self._last_send_at = sent_at
            self._send_times.append(sent_at)
        if not response["ok"]:
            return response
        body = response["body"]
        if self._token and self._token in body:
            return {"ok": False, "reason": "secret_reflection", "at": response["at"]}
        try:
            root = _safe_xml(body)
        except (ET.ParseError, ValueError):
            return {"ok": False, "reason": "invalid_response", "at": response["at"]}
        status = _text(root, "Status")
        if status != "Success":
            reason, code = _flex_error(root)
            return {"ok": False, "reason": reason, "at": response["at"], "metadata": {"provider_code": code}}
        reference = _text(root, "ReferenceCode")
        if not reference:
            return {"ok": False, "reason": "invalid_response", "at": response["at"]}
        return {"ok": True, "reference": reference, "at": response["at"]}

    def _get_statement(self, reference: str) -> dict[str, Any]:
        response = self._http_get(
            "GetStatement", {"t": self._token, "q": reference, "v": "3"}
        )
        if not response["ok"]:
            return response
        body = response["body"]
        if self._token and self._token in body:
            return {"ok": False, "reason": "secret_reflection", "at": response["at"]}
        stripped = body.lstrip("\ufeff\r\n\t ")
        if stripped.startswith("<"):
            try:
                root = _safe_xml(body)
            except (ET.ParseError, ValueError):
                return {"ok": False, "reason": "invalid_response", "at": response["at"]}
            if root.tag.endswith("FlexStatementResponse") or _text(root, "Status") == "Fail":
                reason, code = _flex_error(root)
                return {"ok": False, "reason": reason, "at": response["at"], "metadata": {"provider_code": code}}
            if not root.tag.endswith("FlexQueryResponse"):
                return {"ok": False, "reason": "invalid_response", "at": response["at"]}
            return {"ok": True, "body": body, "format": "xml", "at": response["at"]}
        try:
            rows = list(csv.DictReader(io.StringIO(body)))
        except (csv.Error, UnicodeError):
            rows = []
        if not rows or not any(rows[0].keys()):
            return {"ok": False, "reason": "invalid_response", "at": response["at"]}
        return {"ok": True, "body": body, "format": "csv", "at": response["at"]}

    def _http_get(self, endpoint: str, params: Mapping[str, str]) -> dict[str, Any]:
        try:
            response = self._client.get(f"{_BASE_URL}/{endpoint}", params=dict(params))
        except httpx.HTTPError:
            return {"ok": False, "reason": "external", "at": self._now()}
        at = self._now()
        if response.status_code in {401, 403}:
            return {"ok": False, "reason": "unauthorized", "at": at}
        if response.status_code == 429:
            return {"ok": False, "reason": "rate_limited", "at": at}
        if response.status_code >= 400:
            return {"ok": False, "reason": "external", "at": at}
        return {"ok": True, "body": response.text, "at": at}

    def _parse_xml(self, raw: str, operation: str) -> dict[str, Any]:
        root = _safe_xml(raw)
        statements = list(root.findall(".//FlexStatement"))
        if not statements:
            raise ValueError("report has no statements")
        rows: dict[str, list[dict[str, str]]] = {
            "account_information": [], "cash": [], "positions": [], "executions": []
        }
        report_dates: set[str] = set()
        generated: set[str] = set()
        position_sections = 0
        account_sections = 0
        cash_sections = 0
        execution_sections = 0
        statement_account_refs: set[str] = set()
        raw_statements: list[dict[str, object]] = []
        for statement in statements:
            attrs = dict(statement.attrib)
            if attrs.get("toDate"):
                report_dates.add(attrs["toDate"])
            if attrs.get("whenGenerated"):
                generated.add(attrs["whenGenerated"])
            if attrs.get("accountId"):
                statement_account_refs.add(attrs["accountId"])
            direct_positions = statement.findall(".//OpenPosition")
            if statement.find(".//OpenPositions") is not None or direct_positions:
                position_sections += 1
            account_rows = [dict(node.attrib) for node in statement.findall(".//AccountInformation")]
            cash_rows = [dict(node.attrib) for node in statement.findall(".//CashReportCurrency")]
            position_rows = [dict(node.attrib) for node in direct_positions]
            execution_rows = [dict(node.attrib) for node in statement.findall(".//Trade")]
            if account_rows:
                account_sections += 1
            if statement.find(".//CashReport") is not None or cash_rows:
                cash_sections += 1
            if statement.find(".//Trades") is not None or execution_rows:
                execution_sections += 1
            statement_account = attrs.get("accountId")
            for collection in (account_rows, cash_rows, position_rows, execution_rows):
                for row in collection:
                    if statement_account and not row.get("accountId"):
                        row["accountId"] = statement_account
            rows["account_information"].extend(account_rows)
            rows["cash"].extend(cash_rows)
            rows["positions"].extend(position_rows)
            rows["executions"].extend(execution_rows)
            raw_statements.append({"attributes": attrs, "position_section_present": statement.find(".//OpenPositions") is not None or bool(direct_positions)})
        return {
            "format": "xml",
            "rows": rows,
            "statement_count": len(statements),
            "position_sections": position_sections,
            "account_sections": account_sections,
            "cash_sections": cash_sections,
            "execution_sections": execution_sections,
            "statement_account_refs": sorted(statement_account_refs),
            "report_dates": sorted(report_dates),
            "when_generated": sorted(generated),
            "statement_metadata": raw_statements,
            "query_name": root.attrib.get("queryName"),
            "query_type": root.attrib.get("type"),
        }

    def _parse_csv(self, raw: str, operation: str) -> dict[str, Any]:
        rows = [dict(row) for row in csv.DictReader(io.StringIO(raw))]
        if not rows:
            raise ValueError("CSV report is empty")
        return {
            "format": "csv",
            "rows": {"account_information": [], "cash": rows, "positions": [], "executions": []},
            "statement_count": 0,
            "position_sections": 0,
            "account_sections": 0,
            "cash_sections": 0,
            "execution_sections": 0,
            "statement_account_refs": sorted({row.get("accountId", "") for row in rows if row.get("accountId")}),
            "report_dates": sorted({row.get("toDate", "") for row in rows if row.get("toDate")}),
            "when_generated": sorted({row.get("whenGenerated", "") for row in rows if row.get("whenGenerated")}),
            "statement_metadata": [],
            "query_name": None,
            "query_type": None,
        }

    def _build_result(
        self,
        *,
        request_id: str,
        operation: str,
        subject: str,
        required_fields: tuple[str, ...],
        as_of: datetime,
        output_ref: str,
        retrieved_at: datetime,
        raw: str,
        parsed: dict[str, Any],
    ) -> dict[str, object]:
        rows = parsed["rows"]
        query_type = parsed["query_type"]
        activity_flex = query_type == "AF"
        reported_at = _generated_instant(parsed["when_generated"], self._query_timezone)
        provider_cutoff_date, cutoff_timezone_valid = _provider_cutoff_date(
            as_of, self._query_timezone
        )
        report_after_cutoff, invalid_report_dates = _dates_after_cutoff(
            parsed["report_dates"], provider_cutoff_date
        )
        historical_request = as_of < retrieved_at
        historical_unproven = historical_request and (
            reported_at is None or reported_at > as_of
        )
        normalization_allowed = activity_flex and not report_after_cutoff
        if normalization_allowed:
            accounts, account_exclusions = _accounts(rows["account_information"], rows["cash"])
            positions, position_exclusions = _positions(rows["positions"])
            executions, execution_exclusions = _executions(
                rows["executions"], provider_cutoff_date=provider_cutoff_date
            )
        else:
            accounts, positions, executions = [], [], []
            account_exclusions, position_exclusions, execution_exclusions = [], [], []
        returned_accounts = {account.account_ref for account in accounts}
        returned_report_accounts = set(parsed["statement_account_refs"])
        linked_positions: list[Position] = []
        for position in positions:
            if position.account_ref in returned_accounts:
                linked_positions.append(position)
            else:
                position_exclusions.append(
                    {
                        "section": "OpenPosition",
                        "reason": "account_ref_not_present_in_account_sections",
                        "account_ref": position.account_ref,
                        "symbol": position.security.symbol,
                    }
                )
        positions = linked_positions
        expected_complete = bool(self._expected_accounts) and returned_report_accounts == self._expected_accounts
        operation_sections_complete = _operation_sections_complete(operation, parsed)
        exclusions = account_exclusions + position_exclusions + execution_exclusions
        explicit_empty = operation_sections_complete and (
            (operation == "positions" and not rows["positions"])
            or (operation == "executions" and not rows["executions"])
        )
        missing_required = _missing_required(
            operation,
            required_fields,
            accounts,
            positions,
            executions,
            reported_at=reported_at,
            explicit_empty=explicit_empty,
        )
        gaps: list[dict[str, object]] = []
        errors: list[str] = []

        if not activity_flex:
            gaps.append(_gap(request_id, retrieved_at, "saved Activity Flex report type AF", f"returned query type is {query_type or 'unknown'}", "report cannot be treated as T+1 Activity Flex data", "select a saved Activity Flex query and retry"))
            errors.append("unsupported_query_type")
        if parsed["report_dates"] and not cutoff_timezone_valid:
            gaps.append(_gap(request_id, retrieved_at, "report and execution date cutoff in the saved query timezone", "query timezone is absent or invalid", "provider-local dates cannot be proven before or after as_of", "configure the verified saved-query timezone before historical cutoff use"))
            errors.append("cutoff_timezone_unknown")
        if invalid_report_dates:
            gaps.append(_gap(request_id, retrieved_at, "valid Flex report calendar dates", f"invalid report dates retained raw: {', '.join(invalid_report_dates)}", "report cutoff comparison is incomplete", "fix the saved query date fields and retry"))
            errors.append("invalid_report_date")
        if report_after_cutoff:
            gaps.append(_gap(request_id, retrieved_at, "broker report within the requested knowledge cutoff", "report toDate is after as_of", "later portfolio facts were excluded from normalization", "request a saved report bounded to the historical cutoff"))
            errors.append("after_as_of_cutoff")
        elif historical_unproven:
            gaps.append(_gap(request_id, retrieved_at, "broker report proven available by the historical cutoff", "report availability is unknown or later than as_of", "historical eligibility is not proven; normalized rows are usable only with this limitation", "provide a verified query timezone/version available by the cutoff"))
            errors.append("historical_availability_unproven")
        if not self._expected_accounts:
            gaps.append(_gap(request_id, retrieved_at, "configured account coverage", "expected account set is not configured", "report account coverage cannot be confirmed", "configure the protected expected account references for this saved query"))
        elif not expected_complete:
            gaps.append(_gap(request_id, retrieved_at, "all configured accounts", "returned account set differs from protected expected set", "account coverage is partial or mismatched", "verify the saved query and protected expected account mapping"))
        if not operation_sections_complete:
            section_name = {"accounts": "AccountInformation and CashReport", "positions": "AccountInformation, CashReport, and OpenPositions", "executions": "Trades"}[operation]
            gaps.append(_gap(request_id, retrieved_at, f"complete {section_name} sections for every report account", "one or more required sections are absent", "operation coverage cannot be complete", "include the required sections for every account in the saved Flex query"))
            errors.append("missing_section")
        if exclusions:
            gaps.append(_gap(request_id, retrieved_at, "unambiguous broker rows", f"{len(exclusions)} rows excluded with preserved reasons", "some rows could not be normalized", "fix the saved query fields and retry"))
            errors.append("excluded_rows")
        if missing_required:
            gaps.append(_gap(request_id, retrieved_at, ", ".join(missing_required), "required fields absent after normalization", "requested broker content is incomplete", "add the required fields to the saved query and retry"))
            errors.append("required_fields_missing")

        portfolio_snapshot: dict[str, object] | None = None
        if operation == "positions" and accounts and normalization_allowed:
            if positions:
                complete_read = expected_complete and operation_sections_complete and not account_exclusions and not position_exclusions
                snapshot = PortfolioSnapshot(
                    snapshot_id=f"snap_{uuid.uuid4().hex}",
                    broker="ibkr_flex",
                    reported_at=reported_at,
                    retrieved_at=retrieved_at,
                    accounts=tuple(accounts),
                    positions=tuple(positions),
                    coverage=_coverage(returned_report_accounts, self._expected_accounts),
                    complete_read=complete_read,
                    confirmed_empty=False,
                    unknown_reasons={} if reported_at else {"reported_at": "Flex toDate is date-only and whenGenerated has no verified timezone"},
                )
                portfolio_snapshot = snapshot.model_dump(mode="json")
            elif expected_complete and operation_sections_complete and not account_exclusions and not position_exclusions:
                snapshot = PortfolioSnapshot(
                    snapshot_id=f"snap_{uuid.uuid4().hex}", broker="ibkr_flex",
                    reported_at=reported_at, retrieved_at=retrieved_at,
                    accounts=tuple(accounts), positions=(),
                    coverage=_coverage(returned_report_accounts, self._expected_accounts),
                    complete_read=True, confirmed_empty=True,
                    unknown_reasons={} if reported_at else {"reported_at": "Flex toDate is date-only and whenGenerated has no verified timezone"},
                )
                portfolio_snapshot = snapshot.model_dump(mode="json")

        normalized: dict[str, object] = {
            "raw_locator": "",
            "raw_format": parsed["format"],
            "query_kind": "activity_flex" if activity_flex else "unknown_or_unsupported",
            "query_name": parsed["query_name"],
            "query_type": parsed["query_type"],
            "freshness": "T+1" if activity_flex else "unknown",
            "t_plus_one": True if activity_flex else None,
            "date_coverage_only": True,
            "historical_eligibility": "current_retrieval_only" if not historical_request else ("eligible_by_verified_generation_time" if reported_at is not None and reported_at <= as_of and not report_after_cutoff else "not_proven"),
            "as_of": as_of.isoformat(),
            "cutoff_timezone": self._query_timezone or None,
            "cutoff_comparison": "provider_timezone" if cutoff_timezone_valid else "unknown_without_verified_query_timezone",
            "invalid_report_dates": invalid_report_dates,
            "report_to_dates": parsed["report_dates"],
            "when_generated_raw": parsed["when_generated"],
            "when_generated_timezone": self._query_timezone or None,
            "statement_metadata": parsed["statement_metadata"],
            "account_refs": sorted(returned_report_accounts),
            "expected_account_coverage_configured": bool(self._expected_accounts),
            "accounts": [item.model_dump(mode="json") for item in accounts],
            "positions": [item.model_dump(mode="json") for item in positions],
            "executions": executions,
            "excluded_rows": exclusions,
        }
        if parsed["format"] == "csv":
            gaps.append(_gap(request_id, retrieved_at, "saved-query CSV section identity and full coverage", "CSV rows were preserved but section completeness is not independently verified", "CSV normalization is limited", "verify the saved CSV query columns or use an XML Activity Flex query"))
        quality = "complete" if not gaps and not errors else "limited"
        unknown = {
            "observed_at": "Flex report toDate values are date-only and do not define an observation instant",
        }
        if reported_at is None:
            unknown["available_at"] = "Flex whenGenerated is absent or has no verified query timezone"
        source_result = SourceResult(
            source="ibkr_flex", operation=operation, security_or_topic=subject,
            observed_at=None, retrieved_at=retrieved_at, available_at=reported_at,
            coverage=f"{_coverage(returned_report_accounts, self._expected_accounts)}; " + ("Activity Flex through previous business day; T+1" if activity_flex else "saved query type is not verified Activity Flex"),
            payload_ref=output_ref, quality=quality, errors=tuple(errors), unknown_reasons=unknown,
        )
        return {
            "source_result": source_result.model_dump(mode="json"),
            "raw_payload": raw,
            "normalized": normalized,
            "evidence": [],
            "gaps": gaps,
            "portfolio_snapshot": portfolio_snapshot,
        }

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return timezone-aware datetime")
        return value


def _setting(settings: Settings, name: str) -> str:
    value: SecretStr | None = settings.credentials.get(name)
    if value is not None:
        return value.get_secret_value().strip()
    return (os.environ.get(name) or "").strip()


def _date_parameters(parameters: Mapping[str, object]) -> dict[str, str]:
    start, end, period = parameters.get("from_date"), parameters.get("to_date"), parameters.get("period")
    if period is not None:
        if start is not None or end is not None or not isinstance(period, str) or not period:
            raise ValueError("period cannot be combined with date range")
        return {"p": period}
    if (start is None) != (end is None):
        raise ValueError("from_date and to_date must be supplied together")
    if start is None:
        return {}
    if not isinstance(start, str) or not isinstance(end, str) or not _DATE.fullmatch(start) or not _DATE.fullmatch(end):
        raise ValueError("Flex date range must use YYYYMMDD")
    start_date = datetime.strptime(start, "%Y%m%d").date()
    end_date = datetime.strptime(end, "%Y%m%d").date()
    if end_date < start_date or (end_date - start_date).days > 365:
        raise ValueError("Flex date range is invalid")
    return {"fd": start, "td": end}


def _safe_xml(body: str) -> ET.Element:
    upper = body.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ValueError("XML declarations with entities are rejected")
    return ET.fromstring(body)


def _text(root: ET.Element, name: str) -> str:
    node = root.find(f".//{name}")
    return (node.text or "").strip() if node is not None else ""


def _flex_error(root: ET.Element) -> tuple[str, str | None]:
    code = _text(root, "ErrorCode") or None
    if code == "1018":
        return "rate_limited", code
    if code in _PENDING_CODES:
        return "pending", code
    if code in _INVALID_QUERY_CODES:
        return "invalid_query", code
    if code in _UNAUTHORIZED_CODES:
        return "unauthorized", code
    return "external", code


def _decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _accounts(
    information: list[dict[str, str]], cash: list[dict[str, str]]
) -> tuple[list[AccountState], list[dict[str, object]]]:
    base = {row.get("accountId", ""): row.get("currency") for row in information if row.get("accountId")}
    by_account: dict[str, list[Quantity]] = {account: [] for account in base}
    excluded: list[dict[str, object]] = []
    for row in cash:
        account, currency = row.get("accountId"), row.get("currency")
        value = _decimal(row.get("endingCash"))
        if not account or not currency or not re.fullmatch(r"[A-Z]{3}", currency) or value is None:
            excluded.append({"section": "CashReportCurrency", "reason": "missing_or_invalid_account_currency_or_endingCash", "raw_attributes": row})
            continue
        by_account.setdefault(account, []).append(Quantity(value=value, unit="money", currency=currency))
    accounts: list[AccountState] = []
    for account in sorted(by_account):
        base_currency = base.get(account)
        if base_currency is not None and not re.fullmatch(r"[A-Z]{3}", base_currency):
            base_currency = None
        accounts.append(AccountState(account_ref=account, base_currency=base_currency, balances=tuple(by_account[account])))
    return accounts, excluded


def _positions(rows: list[dict[str, str]]) -> tuple[list[Position], list[dict[str, object]]]:
    positions: list[Position] = []
    excluded: list[dict[str, object]] = []
    for row in rows:
        account, symbol, currency = row.get("accountId"), row.get("symbol"), row.get("currency")
        exchange = row.get("listingExchange") or row.get("exchange")
        market = row.get("market") or row.get("countryCode") or _EXCHANGE_MARKETS.get(exchange or "")
        quantity = _decimal(row.get("position"))
        asset_category = row.get("assetCategory")
        if asset_category != "STK":
            excluded.append({"section": "OpenPosition", "reason": "unsupported_or_missing_asset_category", "raw_attributes": row})
            continue
        if not account or not symbol or not currency or not market or quantity is None or not re.fullmatch(r"[A-Z]{3}", currency):
            excluded.append({"section": "OpenPosition", "reason": "missing_or_ambiguous_identity_or_quantity", "raw_attributes": row})
            continue
        market_value = _money(row.get("positionValue"), currency)
        cost_basis = _money(row.get("costBasisMoney"), currency)
        positions.append(Position(
            account_ref=account,
            security=SecurityIdentity(market=market, exchange=exchange, symbol=symbol, currency=currency),
            quantity=Quantity(value=quantity, unit="shares"),
            market_value=market_value,
            cost_basis=cost_basis,
        ))
    return positions, excluded


def _money(value: str | None, currency: str) -> Quantity | None:
    parsed = _decimal(value)
    return Quantity(value=parsed, unit="money", currency=currency) if parsed is not None else None


def _executions(
    rows: list[dict[str, str]], *, provider_cutoff_date: Date | None
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    results: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for row in rows:
        raw_time = row.get("dateTime", "")
        if len(raw_time) >= 8 and _DATE.fullmatch(raw_time[:8]):
            try:
                trade_date = datetime.strptime(raw_time[:8], "%Y%m%d").date()
            except ValueError:
                excluded.append({"section": "Trade", "reason": "invalid_trade_date", "raw_attributes": row})
                continue
            if provider_cutoff_date is not None and trade_date > provider_cutoff_date:
                excluded.append({"section": "Trade", "reason": "after_as_of_cutoff", "raw_attributes": row})
                continue
        required = ("accountId", "tradeID", "symbol", "buySell", "quantity", "tradePrice")
        if any(not row.get(key) for key in required) or _decimal(row.get("quantity")) is None or _decimal(row.get("tradePrice")) is None:
            excluded.append({"section": "Trade", "reason": "missing_execution_identity_or_value", "raw_attributes": row})
            continue
        results.append(dict(row))
    return results, excluded


def _provider_cutoff_date(as_of: datetime, timezone_name: str) -> tuple[Date | None, bool]:
    if not timezone_name:
        return None, False
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return None, False
    return as_of.astimezone(zone).date(), True


def _dates_after_cutoff(
    values: list[str], provider_cutoff_date: Date | None
) -> tuple[bool, list[str]]:
    after = False
    invalid: list[str] = []
    for value in values:
        if not _DATE.fullmatch(value):
            invalid.append(value)
            continue
        try:
            parsed = datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            invalid.append(value)
            continue
        if provider_cutoff_date is not None and parsed > provider_cutoff_date:
            after = True
    return after, invalid


def _operation_sections_complete(operation: str, parsed: Mapping[str, object]) -> bool:
    statement_count = int(parsed["statement_count"])
    if parsed["format"] != "xml" or statement_count < 1:
        return False
    if operation == "accounts":
        return parsed["account_sections"] == statement_count and parsed["cash_sections"] == statement_count
    if operation == "positions":
        return (
            parsed["account_sections"] == statement_count
            and parsed["cash_sections"] == statement_count
            and parsed["position_sections"] == statement_count
        )
    return parsed["execution_sections"] == statement_count


def _missing_required(
    operation: str,
    required: tuple[str, ...],
    accounts: list[AccountState],
    positions: list[Position],
    executions: list[dict[str, object]],
    *,
    reported_at: datetime | None,
    explicit_empty: bool,
) -> list[str]:
    if operation == "accounts":
        checks = {
            "account_ref": bool(accounts),
            "currency": bool(accounts) and all(account.base_currency or account.balances for account in accounts),
            "balances": bool(accounts) and all(account.balances for account in accounts),
        }
    elif operation == "positions":
        row_ok = explicit_empty or bool(positions)
        checks = {
            "account_ref": row_ok and all(position.account_ref for position in positions),
            "symbol": row_ok and all(position.security.symbol for position in positions),
            "market": row_ok and all(position.security.market for position in positions),
            "exchange": row_ok and all(position.security.exchange for position in positions),
            "currency": row_ok and all(position.security.currency for position in positions),
            "quantity": row_ok and all(position.quantity.value is not None for position in positions),
            "market_value": row_ok and all(position.market_value is not None for position in positions),
            "cost_basis": row_ok and all(position.cost_basis is not None for position in positions),
        }
    else:
        row_ok = explicit_empty or bool(executions)
        raw_names = {
            "account_ref": "accountId", "trade_id": "tradeID", "order_id": "orderID",
            "symbol": "symbol", "side": "buySell", "currency": "currency",
            "quantity": "quantity", "price": "tradePrice", "trade_done_at": "dateTime",
        }
        checks = {
            field: row_ok and all(row.get(raw_name) not in (None, "") for row in executions)
            for field, raw_name in raw_names.items()
        }
    checks["retrieved_at"] = True
    checks["reported_at"] = reported_at is not None
    return sorted(field for field in required if not checks[field])


def _generated_instant(values: list[str], timezone_name: str) -> datetime | None:
    if not timezone_name or len(values) != 1:
        return None
    try:
        zone = ZoneInfo(timezone_name)
        parsed = datetime.strptime(values[0], "%Y%m%d;%H%M%S").replace(tzinfo=zone)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return parsed.astimezone(timezone.utc)


def _coverage(returned: set[str], expected: frozenset[str]) -> str:
    if expected:
        return f"{len(returned & expected)}/{len(expected)} configured accounts"
    return f"{len(returned)} report accounts; configured account set unverified"


def _gap(
    request_id: str, at: datetime, required: str, result: str, impact: str, next_action: str
) -> dict[str, object]:
    return DataGap(
        gap_id=f"gap_{uuid.uuid4().hex}", request_id=request_id,
        required_content=required,
        attempts=({"source": "ibkr_flex", "at": at.isoformat(), "result": result},),
        impact=impact, next_action=next_action,
    ).model_dump(mode="json")


def _failure(
    *, request_id: str, operation: str, subject: str, retrieved_at: datetime,
    reason: str, coverage: str, metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    source = SourceResult(
        source="ibkr_flex", operation=operation, security_or_topic=subject,
        observed_at=None, retrieved_at=retrieved_at, available_at=None,
        coverage=coverage, payload_ref=None, quality="failed", errors=(reason,),
        unknown_reasons={"observed_at": "no usable Flex report", "available_at": "no usable Flex report"},
    )
    return {
        "source_result": source.model_dump(mode="json"), "raw_payload": None,
        "normalized": {"raw_locator": None, "error_reason": reason, **dict(metadata or {})},
        "evidence": [],
        "gaps": [_gap(request_id, retrieved_at, f"IBKR Flex {operation} report", reason, coverage, "verify the existing saved query or retry the same read-only channel when appropriate")],
        "portfolio_snapshot": None,
    }
