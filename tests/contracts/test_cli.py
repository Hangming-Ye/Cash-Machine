from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cash_research.cli import main
from cash_research.artifacts import resolve_reference
from cash_research.models import CallResult


NOW = datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)
COMMANDS = (
    ("data.fetch", ("data", "fetch", "--request")),
    ("data.ingest", ("data", "ingest", "--request")),
    ("compute.factor", ("compute", "factor", "--request")),
    ("compute.valuation", ("compute", "valuation", "--request")),
    ("memory.recall", ("memory", "recall", "--request")),
    ("memory.apply", ("memory", "apply", "--proposal")),
    ("check.artifact", ("check", "artifact", "--request")),
)


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _invoke(
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    *,
    handlers: dict[str, Callable[..., CallResult]] | None = None,
) -> tuple[int, dict[str, object]]:
    exit_code = main(args, handlers=handlers)
    captured = capsys.readouterr()
    assert captured.err == ""
    return exit_code, json.loads(captured.out)


def _decision() -> dict[str, object]:
    return {
        "decision_id": "draft-id",
        "security_or_topic": {
            "market": "US",
            "exchange": "XNAS",
            "symbol": "AAPL",
            "currency": "USD",
        },
        "as_of": NOW.isoformat(),
        "label": "watch",
        "reason_refs": [],
        "price_or_conditions": None,
        "price_or_conditions_reason": "evidence does not support a price",
        "horizon": "12 months",
        "risks": ["demand weakens"],
        "invalidators": ["guidance cut"],
        "memory_packet_refs": [],
    }


@pytest.mark.parametrize(("operation", "command"), COMMANDS)
def test_all_approved_command_groups_reject_incomplete_requests_or_unimplemented_slices(
    operation: str,
    command: tuple[str, ...],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = {"request_id": "req-1"}
    if operation == "check.artifact":
        request.update(
            {"draft_ref": "missing.json", "record_type": "Decision"}
        )
    request_path = _write_json(tmp_path / "request.json", request)

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), *command, str(request_path)],
    )

    if operation in {
        "check.artifact",
        "memory.recall",
        "memory.apply",
        "compute.valuation",
        "compute.factor",
    }:
        assert envelope["error"]["reason"] == "invalid"
    else:
        assert envelope["error"]["reason"] == "unsupported"
    assert exit_code == 2
    assert envelope["operation"] == operation
    assert envelope["status"] == "error"
    assert envelope["artifacts"] == []


@pytest.mark.parametrize(("operation", "command"), COMMANDS)
def test_every_command_rejects_nested_request_secrets_without_echo(
    operation: str,
    command: tuple[str, ...],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "do-not-print-this-value"
    request_path = _write_json(
        tmp_path / "request.json",
        {"request_id": "req-secret", "nested": {"api_token": secret}},
    )

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), *command, str(request_path)],
    )

    assert exit_code == 2
    assert envelope["operation"] == operation
    assert envelope["error"]["reason"] == "invalid"
    assert secret not in json.dumps(envelope)


@pytest.mark.parametrize("contents", ["{", "[]"])
def test_malformed_or_non_object_request_is_a_sanitized_input_error(
    contents: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(contents, encoding="utf-8")

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "data", "fetch", "--request", str(request_path)],
    )

    assert exit_code == 2
    assert envelope["status"] == "error"
    assert envelope["error"] == {
        "reason": "invalid",
        "message": "request file must contain a valid JSON object",
    }
    assert "JSONDecodeError" not in json.dumps(envelope)


@pytest.mark.parametrize(
    "payload",
    [
        {"request_id": "req-1", "source": "unknown", "operation": "positions"},
        {"request_id": "req-1", "source": "ibkr_flex", "operation": "place_order"},
    ],
)
def test_data_fetch_rejects_unknown_sources_and_order_operations(
    payload: dict[str, object],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(tmp_path / "request.json", payload)

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "data", "fetch", "--request", str(request_path)],
    )

    assert exit_code == 2
    assert envelope["status"] == "error"
    assert envelope["artifacts"] == []
    assert envelope["error"]["reason"] == "unsupported"


def test_broker_read_is_never_represented_as_a_fake_empty_portfolio(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(
        tmp_path / "request.json",
        {"request_id": "req-positions", "source": "ibkr_flex", "operation": "positions"},
    )

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "data", "fetch", "--request", str(request_path)],
    )

    assert exit_code == 2
    assert envelope["status"] == "error"
    assert not any(item["type"] == "portfolio_snapshot" for item in envelope["artifacts"])
    assert envelope["error"]["reason"] != "empty"


def test_injected_adapter_can_return_partial_without_becoming_an_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(
        tmp_path / "request.json",
        {"request_id": "req-partial", "source": "finnhub", "operation": "quote"},
    )

    observed: dict[str, object] = {}

    def partial_handler(**kwargs: object) -> CallResult:
        observed.update(kwargs)
        return CallResult(
            schema_version="1.0",
            request_id="req-partial",
            operation="data.fetch",
            status="partial",
            artifacts=(),
            warnings=("synthetic adapter returned partial coverage",),
            gaps=("gap-synthetic",),
            error=None,
        )

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "data", "fetch", "--request", str(request_path)],
        handlers={"data.fetch": partial_handler},
    )

    assert exit_code == 0
    assert envelope["status"] == "partial"
    assert envelope["gaps"] == ["gap-synthetic"]
    assert observed["root"] == tmp_path.resolve()
    assert getattr(observed["settings"], "enabled_sources")
    assert set(envelope) == {
        "schema_version",
        "request_id",
        "operation",
        "status",
        "artifacts",
        "warnings",
        "gaps",
        "error",
    }


def test_empty_source_result_remains_an_error_and_not_an_empty_portfolio(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(
        tmp_path / "request.json",
        {"request_id": "req-empty", "source": "ibkr_flex", "operation": "positions"},
    )

    def empty_handler(**_: object) -> CallResult:
        from cash_research.models import CallError

        return CallResult(
            schema_version="1.0",
            request_id="req-empty",
            operation="data.fetch",
            status="error",
            artifacts=(),
            warnings=(),
            gaps=("gap-empty-read",),
            error=CallError(reason="empty", message="source returned no usable rows"),
        )

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "data", "fetch", "--request", str(request_path)],
        handlers={"data.fetch": empty_handler},
    )

    assert exit_code == 2
    assert envelope["status"] == "error"
    assert envelope["error"]["reason"] == "empty"
    assert envelope["artifacts"] == []


def test_disabled_source_is_rejected_before_adapter_dispatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(
        tmp_path / "request.json",
        {"request_id": "req-disabled", "source": "finnhub", "operation": "quote"},
    )
    config_path = _write_json(
        tmp_path / "settings.json",
        {"root": str(tmp_path), "enabled_sources": ["tiingo"]},
    )
    called = False

    def should_not_run(**_: object) -> CallResult:
        nonlocal called
        called = True
        raise AssertionError("disabled source adapter was called")

    exit_code, envelope = _invoke(
        capsys,
        [
            "--config",
            str(config_path),
            "data",
            "fetch",
            "--request",
            str(request_path),
        ],
        handlers={"data.fetch": should_not_run},
    )

    assert exit_code == 2
    assert envelope["error"]["reason"] == "unsupported"
    assert called is False


def test_adapter_runtime_failure_uses_external_exit_code_without_raw_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(
        tmp_path / "request.json",
        {"request_id": "req-fail", "source": "finnhub", "operation": "quote"},
    )

    def failed_handler(**_: object) -> CallResult:
        raise RuntimeError("provider leaked private detail")

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "data", "fetch", "--request", str(request_path)],
        handlers={"data.fetch": failed_handler},
    )

    assert exit_code == 3
    assert envelope["error"] == {
        "reason": "external",
        "message": "operation failed in its external runtime",
    }
    assert "private detail" not in json.dumps(envelope)


def test_adapter_result_cannot_echo_credential_like_content(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(
        tmp_path / "request.json",
        {"request_id": "req-output-secret", "source": "finnhub", "operation": "quote"},
    )

    def unsafe_handler(**_: object) -> CallResult:
        return CallResult(
            schema_version="1.0",
            request_id="req-output-secret",
            operation="data.fetch",
            status="partial",
            artifacts=(),
            warnings=("Authorization: Bearer do-not-print-this-value",),
            gaps=(),
            error=None,
        )

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "data", "fetch", "--request", str(request_path)],
        handlers={"data.fetch": unsafe_handler},
    )

    assert exit_code == 3
    assert envelope["error"]["reason"] == "external"
    assert "do-not-print-this-value" not in json.dumps(envelope)


def test_check_artifact_defaults_to_validation_without_archive_id_or_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    request_path = _write_json(
        tmp_path / "request.json",
        {
            "request_id": "req-check",
            "draft_ref": "decision.json",
            "record_type": "Decision",
            "reference_refs": [],
        },
    )

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "check", "artifact", "--request", str(request_path)],
    )

    assert exit_code == 0
    assert envelope["status"] == "ok"
    assert envelope["artifacts"][0]["type"] == "artifact_validation"
    assert envelope["artifacts"][0]["artifact_id"].startswith("sha256:")
    assert not envelope["artifacts"][0]["artifact_id"].startswith("rec_")
    assert not (tmp_path / "data").exists()


def test_check_artifact_archive_returns_canonical_record_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    request_path = _write_json(
        tmp_path / "request.json",
        {
            "request_id": "req-archive",
            "draft_ref": "decision.json",
            "record_type": "Decision",
        },
    )

    exit_code, envelope = _invoke(
        capsys,
        [
            "--root",
            str(tmp_path),
            "check",
            "artifact",
            "--request",
            str(request_path),
            "--archive",
        ],
    )

    artifact = envelope["artifacts"][0]
    assert exit_code == 0
    assert artifact["artifact_id"].startswith("rec_")
    assert artifact["type"] == "decision"
    assert artifact["path"].endswith("/record.json")
    assert (tmp_path / artifact["path"]).is_file()


def test_check_artifact_report_fields_are_validation_only_until_explicit_archive(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    report = tmp_path / "report.md"
    report.write_text("# Synthetic report\n", encoding="utf-8")
    _write_json(tmp_path / "support.json", {"kind": "synthetic"})
    request_path = _write_json(
        tmp_path / "report-check.json",
        {
            "request_id": "req-report-check",
            "draft_ref": "decision.json",
            "record_type": "Decision",
            "reference_refs": [],
            "report_ref": "report.md",
            "attachment_refs": ["support.json"],
        },
    )

    check_code, check_envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "check", "artifact", "--request", str(request_path)],
    )
    assert check_code == 0
    assert [item["type"] for item in check_envelope["artifacts"]] == ["artifact_validation"]
    assert not (tmp_path / "data").exists()

    archive_code, archive_envelope = _invoke(
        capsys,
        [
            "--root",
            str(tmp_path),
            "check",
            "artifact",
            "--request",
            str(request_path),
            "--archive",
        ],
    )
    assert archive_code == 0
    assert [item["type"] for item in archive_envelope["artifacts"]] == [
        "decision",
        "report_body",
        "report_attachment",
        "archive_manifest",
    ]
    assert all((tmp_path / item["path"]).is_file() for item in archive_envelope["artifacts"])
    for item in archive_envelope["artifacts"][1:]:
        assert item["artifact_id"] == item["path"]
        assert resolve_reference(tmp_path, item["artifact_id"]) == (tmp_path / item["path"]).resolve()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("report_ref", []),
        ("attachment_refs", "support.json"),
        ("change_explanation", []),
    ],
)
def test_check_artifact_rejects_malformed_optional_archive_fields(
    field: str,
    value: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(
        tmp_path / "request.json",
        {
            "request_id": "req-malformed-archive",
            "draft_ref": "decision.json",
            "record_type": "Decision",
            field: value,
        },
    )
    code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "check", "artifact", "--request", str(request_path)],
    )
    assert code == 2
    assert envelope["error"]["reason"] == "invalid"


def test_check_artifact_rejects_configured_secret_inside_report_without_echo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "s3"
    _write_json(tmp_path / "decision.json", _decision())
    (tmp_path / "report.md").write_text(f"ordinary text {secret}", encoding="utf-8")
    request_path = _write_json(
        tmp_path / "request.json",
        {
            "request_id": "req-report-secret",
            "draft_ref": "decision.json",
            "record_type": "Decision",
            "report_ref": "report.md",
        },
    )
    env_path = tmp_path / "credentials.env"
    env_path.write_text(f"FINNHUB_API_KEY={secret}\n", encoding="utf-8")

    code, envelope = _invoke(
        capsys,
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_path),
            "check",
            "artifact",
            "--request",
            str(request_path),
        ],
    )
    assert code == 2
    assert envelope["error"]["reason"] == "invalid"
    assert secret not in json.dumps(envelope)


def test_nonsecret_account_context_is_not_treated_as_a_credential_value(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account_ref = "account-context-001"
    _write_json(tmp_path / "decision.json", _decision())
    (tmp_path / "report.md").write_text(
        f"Private archive context for {account_ref}", encoding="utf-8"
    )
    request_path = _write_json(
        tmp_path / "request.json",
        {
            "request_id": "req-account-context",
            "draft_ref": "decision.json",
            "record_type": "Decision",
            "report_ref": "report.md",
        },
    )
    env_path = tmp_path / "runtime.env"
    env_path.write_text(f"IBKR_ACCOUNT_REF={account_ref}\n", encoding="utf-8")
    code, envelope = _invoke(
        capsys,
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_path),
            "check",
            "artifact",
            "--request",
            str(request_path),
        ],
    )
    assert code == 0
    assert envelope["status"] == "ok"


@pytest.mark.parametrize("record_type", [[], {}])
def test_non_string_record_type_is_an_input_error(
    record_type: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = _write_json(
        tmp_path / "request.json",
        {
            "request_id": "req-bad-record-type",
            "draft_ref": "decision.json",
            "record_type": record_type,
        },
    )

    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "check", "artifact", "--request", str(request_path)],
    )

    assert exit_code == 2
    assert envelope["error"]["reason"] == "invalid"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["unknown-command", "do-not-print-this-value"],
        ["data", "fetch", "--request"],
    ],
)
def test_parser_errors_are_sanitized_json_without_argument_echo(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, envelope = _invoke(capsys, args)

    assert exit_code == 2
    assert envelope["operation"] == "unknown"
    assert envelope["error"] == {
        "reason": "invalid",
        "message": "invalid command arguments",
    }
    assert "do-not-print-this-value" not in json.dumps(envelope)


def test_package_entrypoint_help_runs_in_a_subprocess() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "cash_research.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "cash-research" in completed.stdout
    assert "data" in completed.stdout
    assert "check" in completed.stdout


def test_installed_console_entrypoint_help_runs_in_a_subprocess() -> None:
    executable_name = "cash-research.exe" if os.name == "nt" else "cash-research"
    executable = Path(sys.executable).with_name(executable_name)

    completed = subprocess.run(
        [str(executable), "--help"], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0
    assert "cash-research" in completed.stdout


def _memory_recall_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "request_id": "req-memory",
        "query": "unseen topic",
        "context_mode": "current",
        "as_of": "runtime",
        "topic_ids": ["unseen"],
        "lesson_ids": [],
        "budget": {"max_items": 3, "max_chars": 4000},
    }
    request.update(overrides)
    return request


def test_memory_recall_no_history_is_ok_and_not_a_read_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _write_json(tmp_path / "recall.json", _memory_recall_request())
    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "memory", "recall", "--request", str(request_path)],
    )
    assert exit_code == 0
    assert envelope["status"] == "ok"
    assert {item["type"] for item in envelope["artifacts"]} == {
        "memory_packet",
        "memory_content",
        "memory_state",
    }


def test_memory_recall_malformed_mode_is_a_sanitized_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _write_json(
        tmp_path / "recall.json", _memory_recall_request(context_mode=[])
    )
    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "memory", "recall", "--request", str(request_path)],
    )
    assert exit_code == 2
    assert envelope["error"]["reason"] == "invalid"


def test_memory_apply_conflict_is_exit_two_and_does_not_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence = _write_json(
        tmp_path / "evidence.json",
        {"evidence_id": "synthetic", "available_at": NOW.isoformat()},
    )
    proposal = {
        "request_id": "req-apply",
        "memory_type": "topic",
        "expected_version": 0,
        "topic_id": "topic-one",
        "current_thesis": "Initial.",
        "support_refs": [evidence.relative_to(tmp_path).as_posix()],
        "opposing_refs": [],
        "changes": ["Created."],
        "open_questions": [],
        "next_checks": ["Check again."],
    }
    proposal_path = _write_json(tmp_path / "proposal.json", proposal)
    first_code, _ = _invoke(
        capsys,
        ["--root", str(tmp_path), "memory", "apply", "--proposal", str(proposal_path)],
    )
    second_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "memory", "apply", "--proposal", str(proposal_path)],
    )
    assert first_code == 0
    assert second_code == 2
    assert envelope["error"]["reason"] == "conflict"


def test_memory_corruption_is_an_external_read_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    current = tmp_path / "data/topics/unseen/current.json"
    current.parent.mkdir(parents=True)
    current.write_text("not-json", encoding="utf-8")
    request_path = _write_json(tmp_path / "recall.json", _memory_recall_request())
    exit_code, envelope = _invoke(
        capsys,
        ["--root", str(tmp_path), "memory", "recall", "--request", str(request_path)],
    )
    assert exit_code == 3
    assert envelope["error"] == {
        "reason": "external",
        "message": "operation failed in its external runtime",
    }
