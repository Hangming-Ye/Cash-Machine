"""Run the synthetic CLI fixture chain after its task-owned templates exist."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "fixtures" / "scenarios" / "manifest.json"
TOKEN_PATTERN = re.compile(r"^\{\{([a-z][a-z0-9_]*)\}\}$")
INLINE_TOKEN_PATTERN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
TEXT_FIXTURE_SUFFIXES = {".json", ".md", ".txt", ".csv"}
VALUATION_EXPECTED = PROJECT_ROOT / "fixtures" / "valuation" / "expected.json"
FACTOR_EXPECTED = PROJECT_ROOT / "fixtures" / "factors" / "expected.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the validation-only synthetic fixture workflow."
    )
    parser.add_argument("--root", required=True, type=Path, help="Isolated test root")
    parser.add_argument(
        "--case",
        default="all",
        choices=("all",),
        help="Fixture workflow to run (only the approved full chain exists)",
    )
    return parser.parse_args()


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _new_run_directory(root: Path) -> Path:
    root = root.expanduser().resolve()
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
    run_dir = root / "runs" / "fixtures" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _resolve_cash_research() -> str | None:
    win = PROJECT_ROOT / ".venv" / "Scripts" / "cash-research.exe"
    if win.is_file():
        return str(win)
    posix = PROJECT_ROOT / ".venv" / "bin" / "cash-research"
    if posix.is_file():
        return str(posix)
    return shutil.which("cash-research")


def _initial_results(run_dir: Path, workflow: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evidence_level": "synthetic",
        "case": "all",
        "run_directory": str(run_dir),
        "started_at": datetime.now(UTC).isoformat(),
        "status": "not_run",
        "expected_comparison": {
            "status": "not_run",
            "steps": [
                {
                    "id": step["id"],
                    "status": "not_run",
                    "reason": "workflow has not reached expected comparison",
                }
                for step in workflow
            ],
        },
        "steps": [
            {
                "id": step["id"],
                "status": "not_run",
                "template": step["template"],
                "template_owner": step["template_owner"],
            }
            for step in workflow
        ],
        "exports": {},
    }


def _write_results(run_dir: Path, results: dict[str, Any]) -> Path:
    results["finished_at"] = datetime.now(UTC).isoformat()
    output_path = run_dir / "step-results.json"
    output_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return output_path


def _render(value: Any, exports: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _render(item, exports) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, exports) for item in value]
    if isinstance(value, str):
        match = TOKEN_PATTERN.fullmatch(value)
        if match:
            token = match.group(1)
            if token not in exports:
                raise KeyError(token)
            return exports[token]
    return value


def _tokens_in_text(text: str) -> set[str]:
    return set(INLINE_TOKEN_PATTERN.findall(text))


def _render_text(text: str, exports: dict[str, Any]) -> str:
    def replacer(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in exports:
            raise KeyError(token)
        return str(exports[token])

    return INLINE_TOKEN_PATTERN.sub(replacer, text)


def _values_for_keys(value: Any, keys: set[str], found: list[Any] | None = None) -> list[Any]:
    found = found if found is not None else []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys:
                found.append(item)
            _values_for_keys(item, keys, found)
    elif isinstance(value, list):
        for item in value:
            _values_for_keys(item, keys, found)
    return found


def _collect_fixture_refs(value: Any, found: set[str] | None = None) -> set[str]:
    found = found if found is not None else set()
    if isinstance(value, dict):
        for item in value.values():
            _collect_fixture_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_fixture_refs(item, found)
    elif isinstance(value, str):
        normalized = value.replace("\\", "/")
        if normalized.startswith("fixtures/") and "{{" not in normalized:
            found.add(normalized)
    return found


def _discover_fixture_inputs(workflow: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for definition in workflow:
        template_path = PROJECT_ROOT / definition["template"]
        request = json.loads(template_path.read_text(encoding="utf-8"))
        _collect_fixture_refs(request, refs)
    pending = set(refs)
    while pending:
        current = pending.pop()
        source = PROJECT_ROOT / current
        if not source.is_file() or source.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        nested = _collect_fixture_refs(payload)
        for item in nested - refs:
            refs.add(item)
            pending.add(item)
    return refs


def _stage_fixture_inputs(
    run_dir: Path, fixture_refs: set[str], exports: dict[str, Any]
) -> list[str]:
    staged: list[str] = []
    for relative in sorted(fixture_refs):
        source = PROJECT_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"fixture input missing in repository: {relative}")
        destination = run_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in TEXT_FIXTURE_SUFFIXES:
            text = source.read_text(encoding="utf-8")
            tokens = _tokens_in_text(text)
            if tokens and tokens <= set(exports):
                if source.suffix.lower() == ".json":
                    payload = json.loads(text)
                    rendered = _render(deepcopy(payload), exports)
                    destination.write_text(
                        json.dumps(rendered, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                else:
                    destination.write_text(_render_text(text, exports), encoding="utf-8")
            else:
                destination.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(source, destination)
        staged.append(relative)
    return staged


def _safe_json_artifact(run_dir: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    relative_path = artifact.get("path")
    if not isinstance(relative_path, str):
        raise ValueError("captured artifact has no path")
    candidate = (run_dir / relative_path).resolve()
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("captured artifact path escapes the fixture run directory") from exc
    if not candidate.is_file():
        raise ValueError(f"captured artifact does not exist: {relative_path}")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"captured artifact is not readable JSON: {relative_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"captured artifact JSON must be an object: {relative_path}")
    return payload


def _capture_exports(
    envelope: dict[str, Any], definition: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    artifacts = envelope.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("CallResult artifacts must be a list")
    captured: dict[str, Any] = {}
    for export_name, capture in definition.get("captures", {}).items():
        allowed_types = set(capture.get("artifact_types", []))
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict) and artifact.get("type") in allowed_types
        ]
        if len(matches) != 1:
            raise ValueError(
                f"capture {export_name} requires exactly one artifact of type "
                f"{sorted(allowed_types)}; found {len(matches)}"
            )
        artifact = matches[0]
        if capture.get("source") == "artifact_id":
            value = artifact.get("artifact_id")
            if not isinstance(value, str) or not value:
                raise ValueError(f"capture {export_name} has no artifact_id")
        elif capture.get("source") == "json":
            payload = _safe_json_artifact(run_dir, artifact)
            values = _values_for_keys(payload, set(capture.get("keys", [])))
            unique_values = []
            for item in values:
                if item not in unique_values:
                    unique_values.append(item)
            if len(unique_values) != 1:
                raise ValueError(
                    f"capture {export_name} requires one unambiguous version value; "
                    f"found {len(unique_values)}"
                )
            value = unique_values[0]
        else:
            raise ValueError(f"capture {export_name} has an unsupported source")
        captured[export_name] = value
    return captured


def _mark_remaining_not_run(results: dict[str, Any], start: int, reason: str) -> None:
    for step in results["steps"][start:]:
        step["status"] = "not_run"
        step["reason"] = reason
    comparisons = results["expected_comparison"]["steps"]
    for step in comparisons[start:]:
        if step["status"] == "not_run":
            step["reason"] = reason


def _artifact_by_type(envelope: dict[str, Any], artifact_type: str) -> dict[str, Any] | None:
    artifacts = envelope.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("type") == artifact_type
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _numbers_close(actual: Any, expected: Any, abs_tol: Decimal) -> bool:
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False
    try:
        left = Decimal(str(actual))
        right = Decimal(str(expected))
    except (InvalidOperation, ValueError):
        return False
    return abs(left - right) <= abs_tol


def _floats_close(actual: Any, expected: Any, abs_tol: float) -> bool:
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False
    try:
        return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=abs_tol)
    except (TypeError, ValueError):
        return False


def _compare_valuation(run_dir: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    expected_doc = json.loads(VALUATION_EXPECTED.read_text(encoding="utf-8"))
    expected = expected_doc["cases"]["dcf_fcff"]["expected"]
    precision = expected_doc["api_contract"]["precision"]
    abs_tol = Decimal(str(precision["absolute_tolerance"]))
    artifact = _artifact_by_type(envelope, "valuation_result")
    if artifact is None:
        return {
            "status": "mismatched",
            "reason": "valuation step did not publish exactly one valuation_result artifact",
        }
    actual = _safe_json_artifact(run_dir, artifact)
    mismatches: list[str] = []
    for scenario, values in expected["scenario_results"].items():
        actual_scenario = actual.get("scenario_results", {}).get(scenario)
        if not isinstance(actual_scenario, dict):
            mismatches.append(f"missing scenario_results.{scenario}")
            continue
        for field, expected_value in values.items():
            if not _numbers_close(actual_scenario.get(field), expected_value, abs_tol):
                mismatches.append(
                    f"scenario_results.{scenario}.{field}: "
                    f"actual={actual_scenario.get(field)!r} expected={expected_value!r}"
                )
    expected_sensitivity = expected.get("sensitivity_per_share", {})
    actual_sensitivity = actual.get("sensitivity", {}).get("per_share") or actual.get(
        "sensitivity_per_share"
    )
    if isinstance(expected_sensitivity, dict) and isinstance(actual_sensitivity, dict):
        for wacc, row in expected_sensitivity.items():
            actual_row = actual_sensitivity.get(wacc)
            if not isinstance(actual_row, dict):
                mismatches.append(f"missing sensitivity_per_share.{wacc}")
                continue
            for growth, expected_value in row.items():
                if not _numbers_close(actual_row.get(growth), expected_value, abs_tol):
                    mismatches.append(
                        f"sensitivity_per_share.{wacc}.{growth}: "
                        f"actual={actual_row.get(growth)!r} expected={expected_value!r}"
                    )
    if mismatches:
        return {
            "status": "mismatched",
            "expected_source": "fixtures/valuation/expected.json#/cases/dcf_fcff/expected",
            "mismatches": mismatches,
        }
    return {
        "status": "matched",
        "expected_source": "fixtures/valuation/expected.json#/cases/dcf_fcff/expected",
        "compared": ["scenario_results", "sensitivity_per_share"],
    }


def _compare_factor(run_dir: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    expected_doc = json.loads(FACTOR_EXPECTED.read_text(encoding="utf-8"))
    expected = expected_doc["cases"]["new_combination"]["expected"]
    abs_tol = float(expected_doc["contract"]["precision"]["absolute_tolerance"])
    artifact = _artifact_by_type(envelope, "factor_result")
    if artifact is None:
        return {
            "status": "mismatched",
            "reason": "factor step did not publish exactly one factor_result artifact",
        }
    actual = _safe_json_artifact(run_dir, artifact)
    mismatches: list[str] = []
    expected_metrics = expected.get("metrics", {})
    actual_metrics = actual.get("metrics", {})
    if not isinstance(actual_metrics, dict):
        mismatches.append("metrics missing from factor result")
    else:
        for key, expected_value in expected_metrics.items():
            actual_value = actual_metrics.get(key)
            if expected_value is None or actual_value is None:
                if actual_value is not expected_value and not (
                    actual_value is None and expected_value is None
                ):
                    mismatches.append(
                        f"metrics.{key}: actual={actual_value!r} expected={expected_value!r}"
                    )
            elif not _floats_close(actual_value, expected_value, abs_tol):
                mismatches.append(
                    f"metrics.{key}: actual={actual_value!r} expected={expected_value!r}"
                )
    expected_outputs = expected.get("parameter_outputs", {})
    actual_outputs = actual.get("parameter_outputs", {})
    if isinstance(expected_outputs, dict) and isinstance(actual_outputs, dict):
        for parameter_set, expected_series in expected_outputs.items():
            actual_series = actual_outputs.get(parameter_set)
            if not isinstance(actual_series, list) or len(actual_series) != len(expected_series):
                mismatches.append(
                    f"parameter_outputs.{parameter_set}: length mismatch "
                    f"actual={actual_series!r} expected={expected_series!r}"
                )
                continue
            for index, (actual_value, expected_value) in enumerate(
                zip(actual_series, expected_series, strict=True)
            ):
                if not _floats_close(actual_value, expected_value, abs_tol):
                    mismatches.append(
                        f"parameter_outputs.{parameter_set}[{index}]: "
                        f"actual={actual_value!r} expected={expected_value!r}"
                    )
    if mismatches:
        return {
            "status": "mismatched",
            "expected_source": "fixtures/factors/expected.json#/cases/new_combination/expected",
            "mismatches": mismatches,
        }
    return {
        "status": "matched",
        "expected_source": "fixtures/factors/expected.json#/cases/new_combination/expected",
        "compared": ["metrics.directional_accuracy", "parameter_outputs"],
    }


def _not_applicable(step_id: str) -> dict[str, Any]:
    reasons = {
        "evidence_ingest": "no numeric expected artifact for evidence ingest",
        "memory_recall": "no numeric expected artifact for memory recall",
        "artifact_archive": "no numeric expected artifact for artifact archive",
        "memory_apply": "no numeric expected artifact for memory apply",
    }
    return {
        "id": step_id,
        "status": "not_applicable",
        "reason": reasons.get(step_id, "no numeric expected artifact for this step"),
    }


def _build_expected_comparison(
    workflow: list[dict[str, Any]],
    results: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    for index, definition in enumerate(workflow):
        step_id = definition["id"]
        step = results["steps"][index]
        if step["status"] == "not_run":
            comparisons.append(
                {
                    "id": step_id,
                    "status": "not_run",
                    "reason": step.get("reason", "step was not executed"),
                }
            )
            continue
        if step["status"] not in {"ok", "partial"}:
            comparisons.append(
                {
                    "id": step_id,
                    "status": "not_run",
                    "reason": f"step status {step['status']} prevents expected comparison",
                }
            )
            continue
        envelope = step.get("result")
        if not isinstance(envelope, dict):
            comparisons.append(
                {
                    "id": step_id,
                    "status": "mismatched",
                    "reason": "step result envelope is missing",
                }
            )
            continue
        if step_id == "valuation":
            detail = _compare_valuation(run_dir, envelope)
            comparisons.append({"id": step_id, **detail})
        elif step_id == "factor":
            detail = _compare_factor(run_dir, envelope)
            comparisons.append({"id": step_id, **detail})
        else:
            comparisons.append(_not_applicable(step_id))

    if any(item["status"] == "mismatched" for item in comparisons):
        status = "failed"
    elif any(item["status"] == "not_run" for item in comparisons):
        status = "partial" if any(item["status"] == "matched" for item in comparisons) else "not_run"
    else:
        status = "ok"
    return {"status": status, "steps": comparisons}


def main() -> int:
    args = _parse_args()
    manifest = _load_manifest()
    workflow = manifest["fixture_workflow"]
    run_dir = _new_run_directory(args.root)
    results = _initial_results(run_dir, workflow)

    missing_templates = [
        step for step in workflow if not (PROJECT_ROOT / step["template"]).is_file()
    ]
    if missing_templates:
        missing_ids = {step["id"] for step in missing_templates}
        for step in results["steps"]:
            if step["id"] in missing_ids:
                step["status"] = "unimplemented"
                step["reason"] = (
                    f"template is owned by {step['template_owner']} and does not exist yet"
                )
            else:
                step["reason"] = "workflow preflight failed before any CLI invocation"
        results["reason"] = "one or more task-owned request templates are not implemented"
        output_path = _write_results(run_dir, results)
        print(json.dumps({"status": "not_run", "results": str(output_path)}))
        return 2

    executable = _resolve_cash_research()
    if executable is None:
        _mark_remaining_not_run(results, 0, "cash-research CLI is not implemented or not on PATH")
        results["reason"] = "cash-research executable unavailable"
        output_path = _write_results(run_dir, results)
        print(json.dumps({"status": "not_run", "results": str(output_path)}))
        return 2

    try:
        fixture_refs = _discover_fixture_inputs(workflow)
        staged = _stage_fixture_inputs(run_dir, fixture_refs, exports={})
    except (OSError, FileNotFoundError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _mark_remaining_not_run(results, 0, f"fixture input staging failed: {exc}")
        results["reason"] = "required fixture inputs could not be staged into the run root"
        output_path = _write_results(run_dir, results)
        print(json.dumps({"status": "not_run", "results": str(output_path)}))
        return 2
    results["staged_fixture_inputs"] = staged

    rendered_dir = run_dir / "requests"
    rendered_dir.mkdir()
    exports: dict[str, Any] = {}

    for index, definition in enumerate(workflow):
        step_result = results["steps"][index]
        template_path = PROJECT_ROOT / definition["template"]
        try:
            _stage_fixture_inputs(run_dir, fixture_refs, exports)
        except (OSError, FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            step_result["status"] = "failed"
            step_result["reason"] = f"fixture input staging/render failed: {exc}"
            _mark_remaining_not_run(results, index + 1, "not run after fixture staging failure")
            results["status"] = "failed"
            results["expected_comparison"] = _build_expected_comparison(workflow, results, run_dir)
            output_path = _write_results(run_dir, results)
            print(json.dumps({"status": "failed", "results": str(output_path)}))
            return 2
        try:
            request = json.loads(template_path.read_text(encoding="utf-8"))
            if not isinstance(request, dict):
                raise TypeError("request template must contain a JSON object")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            step_result["status"] = "failed"
            step_result["reason"] = f"request template is invalid: {exc}"
            _mark_remaining_not_run(results, index + 1, "not run after an invalid template")
            results["status"] = "failed"
            results["expected_comparison"] = _build_expected_comparison(workflow, results, run_dir)
            output_path = _write_results(run_dir, results)
            print(json.dumps({"status": "failed", "results": str(output_path)}))
            return 2
        try:
            rendered = _render(deepcopy(request), exports)
        except KeyError as exc:
            step_result["status"] = "blocked"
            step_result["reason"] = f"required prior output was not returned: {exc.args[0]}"
            _mark_remaining_not_run(results, index + 1, "blocked by a prior step")
            results["status"] = "blocked"
            results["expected_comparison"] = _build_expected_comparison(workflow, results, run_dir)
            output_path = _write_results(run_dir, results)
            print(json.dumps({"status": "blocked", "results": str(output_path)}))
            return 2

        request_path = rendered_dir / f"{index + 1:02d}-{definition['id']}.json"
        request_path.write_text(
            json.dumps(rendered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        command = [
            executable,
            "--root",
            str(run_dir),
            *definition["command"],
            definition["request_option"],
            str(request_path),
            *definition.get("trailing_args", []),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as exc:
            step_result["command"] = command
            step_result["status"] = "failed"
            step_result["reason"] = f"CLI process could not be started: {exc}"
            _mark_remaining_not_run(results, index + 1, "not run after a CLI launch failure")
            results["status"] = "failed"
            results["expected_comparison"] = _build_expected_comparison(workflow, results, run_dir)
            output_path = _write_results(run_dir, results)
            print(json.dumps({"status": "failed", "results": str(output_path)}))
            return 3
        step_result["command"] = command
        step_result["exit_code"] = completed.returncode
        step_result["stdout"] = completed.stdout
        step_result["stderr"] = completed.stderr

        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError:
            envelope = None
        step_result["result"] = envelope

        status = envelope.get("status") if isinstance(envelope, dict) else None
        if completed.returncode != 0 or status not in {"ok", "partial"}:
            step_result["status"] = "failed"
            step_result["reason"] = "CLI step did not return an ok/partial JSON envelope"
            _mark_remaining_not_run(results, index + 1, "not run after a failed prior step")
            results["status"] = "failed"
            results["expected_comparison"] = _build_expected_comparison(workflow, results, run_dir)
            output_path = _write_results(run_dir, results)
            print(json.dumps({"status": "failed", "results": str(output_path)}))
            return completed.returncode or 3

        try:
            exports.update(_capture_exports(envelope, definition, run_dir))
        except ValueError as exc:
            step_result["status"] = "failed"
            step_result["reason"] = str(exc)
            _mark_remaining_not_run(results, index + 1, "not run after ambiguous prior output")
            results["status"] = "failed"
            results["expected_comparison"] = _build_expected_comparison(workflow, results, run_dir)
            output_path = _write_results(run_dir, results)
            print(json.dumps({"status": "failed", "results": str(output_path)}))
            return 3
        step_result["status"] = status
        step_result["exports_after_step"] = dict(exports)

    results["status"] = (
        "partial" if any(step["status"] == "partial" for step in results["steps"]) else "ok"
    )
    results["exports"] = exports
    results["expected_comparison"] = _build_expected_comparison(workflow, results, run_dir)
    if results["expected_comparison"]["status"] == "failed":
        results["status"] = "failed"
        results["reason"] = "expected numeric comparison mismatched fixture expected artifacts"
        output_path = _write_results(run_dir, results)
        print(json.dumps({"status": "failed", "results": str(output_path)}))
        return 3
    output_path = _write_results(run_dir, results)
    print(json.dumps({"status": results["status"], "results": str(output_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
