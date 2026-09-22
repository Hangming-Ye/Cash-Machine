"""On-demand command-line boundary for deterministic research utilities."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeAlias

from cash_research.artifacts import (
    ArchivedArtifact,
    ArtifactConflictError,
    ArtifactError,
    ArtifactValidation,
    SecretContentError,
    check_artifact,
    reject_secrets,
)
from cash_research.config import (
    ConfigurationError,
    RequestBoundaryError,
    Settings,
    credential_secret_values,
    load_settings,
    validate_read_request,
)
from cash_research.models import ArtifactSummary, CallError, CallResult
from cash_research.calculations.publication import publish_valuation
from cash_research.calculations.valuation import ValuationError, calculate_valuation
from cash_research.memory import (
    MemoryConflictError,
    MemoryRequestError,
    MemoryWriteError,
    apply_lesson,
    apply_topic,
    recall_memory,
)
from cash_research.sources.router import data_fetch_handler, data_ingest_handler


OperationHandler: TypeAlias = Callable[..., CallResult]

_SCHEMA_VERSION = "1.0"
_RECORD_ARTIFACT_TYPES = {
    "Decision": "decision",
    "WorkRecord": "work_record",
    "Review": "review",
}
_BUILTIN_HANDLERS: dict[str, OperationHandler] = {}


class CliInputError(ValueError):
    """Raised for a request that cannot safely enter an operation."""


class CliUnsupportedError(CliInputError):
    """Raised when a source or operation is outside the implemented read-only slice."""


class CliParseError(ValueError):
    """Raised instead of allowing argparse to echo untrusted command values."""


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliParseError("invalid command arguments")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="cash-research",
        description="Run one deterministic Cash Machine research utility and exit.",
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--env-file", type=Path)
    groups = parser.add_subparsers(dest="group", required=True)

    data = groups.add_parser("data")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    _request_command(data_commands, "fetch", option="--request", operation="data.fetch")
    _request_command(data_commands, "ingest", option="--request", operation="data.ingest")

    compute = groups.add_parser("compute")
    compute_commands = compute.add_subparsers(dest="compute_command", required=True)
    _request_command(
        compute_commands, "factor", option="--request", operation="compute.factor"
    )
    _request_command(
        compute_commands,
        "valuation",
        option="--request",
        operation="compute.valuation",
    )

    memory = groups.add_parser("memory")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    _request_command(
        memory_commands, "recall", option="--request", operation="memory.recall"
    )
    _request_command(
        memory_commands, "apply", option="--proposal", operation="memory.apply"
    )

    check = groups.add_parser("check")
    check_commands = check.add_subparsers(dest="check_command", required=True)
    artifact = check_commands.add_parser("artifact")
    artifact.add_argument("--request", dest="request_file", type=Path, required=True)
    artifact.add_argument("--archive", action="store_true")
    artifact.set_defaults(operation="check.artifact")
    return parser


def _request_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    *,
    option: str,
    operation: str,
) -> None:
    command = subparsers.add_parser(name)
    command.add_argument(option, dest="request_file", type=Path, required=True)
    command.set_defaults(operation=operation, archive=False)


def main(
    argv: Sequence[str] | None = None,
    *,
    handlers: Mapping[str, OperationHandler] | None = None,
) -> int:
    """Parse one command, emit one JSON envelope, and return its process exit code."""

    try:
        args = build_parser().parse_args(argv)
    except CliParseError:
        result = _error_result(
            request_id="unavailable",
            operation="unknown",
            reason="invalid",
            message="invalid command arguments",
        )
        _emit(result)
        return 2
    operation: str = args.operation
    request_id = "unavailable"
    try:
        request = load_request(args.request_file)
        request_id = _request_id(request)
        settings = load_settings(
            root=args.root,
            config_path=args.config,
            env_file=args.env_file,
        )
        if operation == "data.fetch":
            if request.get("operation") == "daily_bars":
                request = {**request, "operation": "bars"}
            try:
                validate_read_request(request)
            except RequestBoundaryError as exc:
                raise CliUnsupportedError(
                    "source or operation is outside the approved read-only boundary"
                ) from exc
            if request["source"] not in settings.enabled_sources:
                raise CliUnsupportedError("source is disabled by the active configuration")
        result = execute_operation(
            operation,
            settings=settings,
            request=request,
            archive=bool(getattr(args, "archive", False)),
            handlers=handlers,
        )
        _validate_handler_result(result, operation=operation, request_id=request_id)
    except (
        CliInputError,
        ConfigurationError,
        ArtifactError,
        MemoryConflictError,
        MemoryRequestError,
        MemoryWriteError,
    ) as exc:
        if isinstance(exc, (ArtifactConflictError, MemoryConflictError)):
            reason = "conflict"
        elif isinstance(exc, CliUnsupportedError):
            reason = "unsupported"
        else:
            reason = "invalid"
        result = _error_result(
            request_id=request_id,
            operation=operation,
            reason=reason,
            message=_safe_input_message(exc),
        )
        _emit(result)
        return 2
    except Exception:
        result = _error_result(
            request_id=request_id,
            operation=operation,
            reason="external",
            message="operation failed in its external runtime",
        )
        _emit(result)
        return 3

    _emit(result)
    return _result_exit_code(result)


def load_request(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object and reject embedded credential material."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliInputError("request file must contain a valid JSON object") from exc
    if not isinstance(payload, dict):
        raise CliInputError("request file must contain a valid JSON object")
    try:
        reject_secrets(payload)
    except SecretContentError as exc:
        raise CliInputError("request contains credential material") from exc
    return payload


def execute_operation(
    operation: str,
    *,
    settings: Settings,
    request: dict[str, Any],
    archive: bool = False,
    handlers: Mapping[str, OperationHandler] | None = None,
) -> CallResult:
    """Dispatch one operation; future integrations can supply the same handler interface."""

    if operation == "check.artifact":
        return _check_artifact_result(
            root=settings.root,
            request=request,
            archive=archive,
            secret_values=credential_secret_values(settings),
        )
    handler = (handlers or {}).get(operation) or _BUILTIN_HANDLERS.get(operation)
    if handler is None:
        return _error_result(
            request_id=_request_id(request),
            operation=operation,
            reason="unsupported",
            message="operation is not implemented in the current slice",
        )
    return handler(root=settings.root, settings=settings, request=request)


def _check_artifact_result(
    *,
    root: Path,
    request: dict[str, Any],
    archive: bool,
    secret_values: tuple[str, ...] = (),
) -> CallResult:
    request_id = _request_id(request)
    draft_ref = request.get("draft_ref")
    record_type = request.get("record_type")
    reference_refs = request.get("reference_refs", [])
    report_ref = request.get("report_ref")
    attachment_refs = request.get("attachment_refs", [])
    change_explanation = request.get("change_explanation")
    allowed_fields = {
        "request_id",
        "draft_ref",
        "record_type",
        "reference_refs",
        "report_ref",
        "attachment_refs",
        "change_explanation",
    }
    if set(request) - allowed_fields:
        raise CliInputError("check artifact request contains unsupported fields")
    if not isinstance(draft_ref, str) or not draft_ref:
        raise CliInputError("check artifact requires draft_ref")
    if not isinstance(record_type, str) or record_type not in _RECORD_ARTIFACT_TYPES:
        raise CliInputError("check artifact requires a supported record_type")
    if not isinstance(reference_refs, list) or not all(
        isinstance(item, str) and item for item in reference_refs
    ):
        raise CliInputError("reference_refs must be a list of non-empty strings")
    if report_ref is not None and (not isinstance(report_ref, str) or not report_ref):
        raise CliInputError("report_ref must be a non-empty string when provided")
    if not isinstance(attachment_refs, list) or not all(
        isinstance(item, str) and item for item in attachment_refs
    ):
        raise CliInputError("attachment_refs must be a list of non-empty strings")
    if change_explanation is not None and (
        not isinstance(change_explanation, str) or not change_explanation.strip()
    ):
        raise CliInputError("change_explanation must be a non-empty string when provided")

    checked = check_artifact(
        root=root,
        draft_ref=draft_ref,
        record_type=record_type,
        reference_refs=tuple(reference_refs),
        report_ref=report_ref,
        attachment_refs=tuple(attachment_refs),
        change_explanation=change_explanation,
        secret_values=secret_values,
        archive=archive,
    )
    artifacts = _artifact_summaries(checked)
    return CallResult(
        schema_version=_SCHEMA_VERSION,
        request_id=request_id,
        operation="check.artifact",
        status="ok",
        artifacts=artifacts,
        warnings=(),
        gaps=(),
        error=None,
    )


def _memory_apply_result(
    *, root: Path, settings: Settings, request: dict[str, Any]
) -> CallResult:
    del settings
    request_id = _request_id(request)
    memory_type = request.get("memory_type")
    expected_version = request.get("expected_version")
    if memory_type not in {"topic", "lesson"}:
        raise MemoryRequestError("memory_type must be topic or lesson")
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version < 0
    ):
        raise MemoryRequestError("expected_version must be a non-negative integer")
    if any(field in request for field in ("version", "known_at", "updated_at")):
        raise MemoryRequestError("version and memory timestamps are program-owned")
    proposal = {
        key: value
        for key, value in request.items()
        if key not in {"request_id", "memory_type", "expected_version"}
    }
    if memory_type == "topic":
        saved = apply_topic(
            root=root, proposal=proposal, expected_version=expected_version
        )
        memory_id = saved.topic_id
        kind = "topics"
        artifact_type = "topic_summary"
    else:
        saved = apply_lesson(
            root=root, proposal=proposal, expected_version=expected_version
        )
        memory_id = saved.lesson_id
        kind = "lessons"
        artifact_type = "lesson"
    artifact = ArtifactSummary(
        path=f"data/{kind}/{memory_id}/versions/{saved.version}.json",
        type=artifact_type,
        summary=f"immutable {memory_type} memory version {saved.version}",
        artifact_id=memory_id,
    )
    return CallResult(
        schema_version=_SCHEMA_VERSION,
        request_id=request_id,
        operation="memory.apply",
        status="ok",
        artifacts=(artifact,),
        warnings=(),
        gaps=(),
        error=None,
    )


def _memory_recall_result(
    *, root: Path, settings: Settings, request: dict[str, Any]
) -> CallResult:
    del settings
    publication = recall_memory(root=root, request=request)
    packet = publication.packet
    artifacts = (
        ArtifactSummary(
            path=publication.packet_ref,
            type="memory_packet",
            summary="immutable record of memory delivered to the caller",
            artifact_id=packet.packet_id,
        ),
        ArtifactSummary(
            path=packet.content_ref,
            type="memory_content",
            summary="time-filtered memory content or compact follow-up index",
            artifact_id=packet.packet_id,
        ),
        ArtifactSummary(
            path=publication.state_ref,
            type="memory_state",
            summary="current versions for optimistic memory updates",
            artifact_id=packet.packet_id,
        ),
    )
    return CallResult(
        schema_version=_SCHEMA_VERSION,
        request_id=packet.request_id,
        operation="memory.recall",
        status="partial" if publication.gaps else "ok",
        artifacts=artifacts,
        warnings=publication.warnings,
        gaps=publication.gaps,
        error=None,
    )


def _valuation_result(
    *, root: Path, settings: Settings, request: dict[str, Any]
) -> CallResult:
    if Path(root).resolve(strict=True) != settings.root.resolve(strict=True):
        raise CliInputError("valuation handler root does not match settings root")
    try:
        result = calculate_valuation(request)
    except ValuationError as exc:
        raise CliInputError("valuation request failed deterministic validation") from exc
    artifacts = publish_valuation(
        root=settings.root,
        request=request,
        result=result,
        secret_values=credential_secret_values(settings),
    )
    limited = result.get("status") == "limited"
    result_warnings = result.get("warnings", [])
    assert isinstance(result_warnings, list)
    warnings = tuple(str(item) for item in result_warnings)
    if limited and "valuation result is limited; inspect scenario and sensitivity output" not in warnings:
        warnings = (*warnings, "valuation result is limited; inspect scenario and sensitivity output")
    return CallResult(
        schema_version=_SCHEMA_VERSION,
        request_id=str(result["request_id"]),
        operation="compute.valuation",
        status="partial" if limited else "ok",
        artifacts=artifacts,
        warnings=warnings,
        gaps=(),
        error=None,
    )
def _artifact_summary(
    checked: ArtifactValidation | ArchivedArtifact,
) -> ArtifactSummary:
    if isinstance(checked, ArchivedArtifact):
        return ArtifactSummary(
            path=f"{checked.relative_path}/record.json",
            type=_RECORD_ARTIFACT_TYPES[checked.record_type],
            summary="immutable canonical research record",
            artifact_id=checked.record_id,
        )
    return ArtifactSummary(
        path=checked.draft_ref,
        type="artifact_validation",
        summary="validation only; no immutable record was created",
        artifact_id=f"sha256:{checked.draft_sha256}",
    )


def _artifact_summaries(
    checked: ArtifactValidation | ArchivedArtifact,
) -> tuple[ArtifactSummary, ...]:
    primary = _artifact_summary(checked)
    if not isinstance(checked, ArchivedArtifact):
        return (primary,)
    extras: list[ArtifactSummary] = []
    if checked.report_ref is not None:
        extras.append(
            ArtifactSummary(
                path=checked.report_ref,
                type="report_body",
                summary="immutable report body frozen with the canonical record",
                artifact_id=checked.report_ref,
            )
        )
    extras.extend(
        ArtifactSummary(
            path=ref,
            type="report_attachment",
            summary="immutable report attachment frozen with the canonical record",
            artifact_id=ref,
        )
        for ref in checked.attachment_refs
    )
    extras.append(
        ArtifactSummary(
            path=checked.manifest_ref,
            type="archive_manifest",
            summary="hash manifest for the immutable record, report, and attachments",
            artifact_id=checked.manifest_ref,
        )
    )
    return (primary, *extras)


_BUILTIN_HANDLERS.update(
    {
        "data.fetch": data_fetch_handler,
        "data.ingest": data_ingest_handler,
        "memory.recall": _memory_recall_result,
        "memory.apply": _memory_apply_result,
        "compute.valuation": _valuation_result,
    }
)


def _request_id(request: Mapping[str, Any]) -> str:
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise CliInputError("request_id must be a non-empty string")
    return request_id


def _validate_handler_result(
    result: CallResult, *, operation: str, request_id: str
) -> None:
    if not isinstance(result, CallResult):
        raise TypeError("operation handler returned an invalid result")
    if result.operation != operation or result.request_id != request_id:
        raise TypeError("operation handler returned a mismatched result")
    try:
        reject_secrets(result.model_dump(mode="json"))
    except SecretContentError as exc:
        raise TypeError("operation handler returned unsafe output") from exc


def _safe_input_message(error: Exception) -> str:
    if isinstance(error, CliInputError):
        return str(error)
    if isinstance(error, ArtifactConflictError):
        return "artifact version or immutable record conflict"
    if isinstance(error, ArtifactError):
        return "artifact request failed validation"
    if isinstance(error, ConfigurationError):
        return "configuration could not be loaded safely"
    return "request is invalid"


def _error_result(
    *,
    request_id: str,
    operation: str,
    reason: str,
    message: str,
) -> CallResult:
    return CallResult(
        schema_version=_SCHEMA_VERSION,
        request_id=request_id,
        operation=operation,
        status="error",
        artifacts=(),
        warnings=(),
        gaps=(),
        error=CallError(reason=reason, message=message),  # type: ignore[arg-type]
    )


def _emit(result: CallResult) -> None:
    print(result.model_dump_json())


def _result_exit_code(result: CallResult) -> int:
    if result.status in {"ok", "partial"}:
        return 0
    if result.error is not None and result.error.reason in {
        "unauthorized",
        "rate_limited",
        "external",
    }:
        return 3
    return 2


def console_main() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    console_main()
