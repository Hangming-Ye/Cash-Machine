"""Run the synthetic CLI fixture chain after its task-owned templates exist."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "fixtures" / "scenarios" / "manifest.json"
TOKEN_PATTERN = re.compile(r"^\{\{([a-z][a-z0-9_]*)\}\}$")


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


def _initial_results(run_dir: Path, workflow: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evidence_level": "synthetic",
        "case": "all",
        "run_directory": str(run_dir),
        "started_at": datetime.now(UTC).isoformat(),
        "status": "not_run",
        "expected_comparison": "not_implemented_until_T060",
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

    executable = shutil.which("cash-research")
    if executable is None:
        _mark_remaining_not_run(results, 0, "cash-research CLI is not implemented or not on PATH")
        results["reason"] = "cash-research executable unavailable"
        output_path = _write_results(run_dir, results)
        print(json.dumps({"status": "not_run", "results": str(output_path)}))
        return 2

    rendered_dir = run_dir / "requests"
    rendered_dir.mkdir()
    exports: dict[str, Any] = {}

    for index, definition in enumerate(workflow):
        step_result = results["steps"][index]
        template_path = PROJECT_ROOT / definition["template"]
        try:
            request = json.loads(template_path.read_text(encoding="utf-8"))
            if not isinstance(request, dict):
                raise TypeError("request template must contain a JSON object")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            step_result["status"] = "failed"
            step_result["reason"] = f"request template is invalid: {exc}"
            _mark_remaining_not_run(results, index + 1, "not run after an invalid template")
            results["status"] = "failed"
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
            output_path = _write_results(run_dir, results)
            print(json.dumps({"status": "failed", "results": str(output_path)}))
            return 3
        step_result["status"] = status
        step_result["exports_after_step"] = dict(exports)

    results["status"] = (
        "partial" if any(step["status"] == "partial" for step in results["steps"]) else "ok"
    )
    results["exports"] = exports
    output_path = _write_results(run_dir, results)
    print(json.dumps({"status": results["status"], "results": str(output_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
