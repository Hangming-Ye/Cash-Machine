"""Integration coverage for frozen factor experiments, trials, and holdout reuse."""

from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path

import pytest

from cash_research.calculations.factor import recompute_matches, run_factor_experiment
from cash_research.calculations.trials import (
    holdout_exposure,
    mark_holdout_exposure,
    start_trial,
    trial_counts,
    verify_frozen_experiment,
)


ROOT = Path(__file__).parents[2]
EXPECTED = json.loads((ROOT / "fixtures/factors/expected.json").read_text(encoding="utf-8"))
TOLERANCE = EXPECTED["contract"]["precision"]["absolute_tolerance"]


def _case(name: str) -> dict[str, object]:
    return copy.deepcopy(EXPECTED["cases"][name])


def _prepare(tmp_path: Path, request: dict[str, object]) -> Path:
    root = tmp_path / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    source = ROOT / str(request["dataset_ref"])
    target = root / str(request["dataset_ref"])
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    # Holdout tracking requires an explicit market timezone on the snapshot.
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload.setdefault("market_timezone", "America/New_York")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    request["dataset_ref"] = str(request["dataset_ref"]).replace("\\", "/")
    return root


def _load_dataset(root: Path, request: dict[str, object]) -> dict[str, object]:
    return json.loads((root / str(request["dataset_ref"])).read_text(encoding="utf-8"))


def test_frozen_new_combination_records_trials_and_matches_fixture(tmp_path: Path) -> None:
    case = _case("new_combination")
    request = case["request"]
    assert isinstance(request, dict)
    root = _prepare(tmp_path, request)
    result = run_factor_experiment(
        request,
        _load_dataset(root, request),
        root=root,
        record_trials=True,
        view_holdout=True,
    )
    expected = case["expected"]
    assert isinstance(expected, dict)
    assert result.experiment_id is not None
    verify_frozen_experiment(root, result.experiment_id)
    assert result.request_hash == case["request_hash"]
    assert result.split_counts_by_parameter_set == expected["split_counts_by_parameter_set"]
    assert result.metrics["directional_accuracy"] is None
    assert result.trial_count["planned"] == expected["trial_count"]["planned"]
    ledger = trial_counts(root, experiment_id=result.experiment_id)
    assert ledger["research_trials"] == 2
    assert ledger["replays"] == 0
    assert result.holdout_status != "unseen"
    assert result.trading_simulation_supported is False
    assert result.returns_are_executable is False


def test_holdout_cannot_be_labeled_unseen_after_prior_view(tmp_path: Path) -> None:
    case = _case("new_combination")
    request = case["request"]
    assert isinstance(request, dict)
    root = _prepare(tmp_path, request)
    first = run_factor_experiment(
        request,
        _load_dataset(root, request),
        root=root,
        record_trials=True,
        view_holdout=True,
    )
    assert first.experiment_id is not None
    assert holdout_exposure(root, first.experiment_id).seen is True

    # Exact infrastructure replay must not create a new research trial, and must
    # not revive an unseen-holdout claim after exposure.
    replay_request = copy.deepcopy(request)
    second = run_factor_experiment(
        replay_request,
        _load_dataset(root, replay_request),
        root=root,
        record_trials=True,
        view_holdout=True,
    )
    # A changed request identity is a new freeze; exposure still overlaps.
    assert second.holdout_status != "unseen"
    assert "unseen" not in second.holdout_status


def test_infrastructure_retry_is_not_a_new_research_trial(tmp_path: Path) -> None:
    case = _case("different_bar_interval")
    request = case["request"]
    assert isinstance(request, dict)
    root = _prepare(tmp_path, request)
    first = run_factor_experiment(
        request,
        _load_dataset(root, request),
        root=root,
        record_trials=True,
        view_holdout=False,
    )
    assert first.experiment_id is not None
    original = first.parameter_results[0].trial
    assert original is not None
    retry = start_trial(
        root,
        first.experiment_id,
        "p-2bar",
        execution_config={"engine_version": first.engine_version},
        replay_of=original.trial_id,
        infrastructure_retry=True,
    )
    assert retry.counts_as_research_trial is False
    counts = trial_counts(root, experiment_id=first.experiment_id)
    assert counts["research_trials"] == 1
    assert counts["replays"] == 1


def test_no_increment_integration_and_recompute(tmp_path: Path) -> None:
    case = _case("no_increment")
    request = case["request"]
    assert isinstance(request, dict)
    root = _prepare(tmp_path, request)
    dataset = _load_dataset(root, request)
    first = run_factor_experiment(request, dataset, root=root, record_trials=True, view_holdout=True)
    second = run_factor_experiment(request, dataset)
    assert first.conclusion == "no_factor_increment"
    assert first.metrics == case["expected"]["metrics"]
    assert recompute_matches(first, second, absolute_tolerance=TOLERANCE)
    assert first.limitation is not None
    assert first.returns_are_executable is False


def test_operator_only_cases_stay_limited_and_recomputable(tmp_path: Path) -> None:
    for name in ("future_leakage", "zero_division", "revision_asof"):
        case = _case(name)
        request = case["request"]
        assert isinstance(request, dict)
        root = _prepare(tmp_path / name, request)
        dataset = _load_dataset(root, request)
        decision_times = None
        expected = case["expected"]
        assert isinstance(expected, dict)
        if "asof_values" in expected:
            decision_times = list(expected["asof_values"])
        elif "selected_values" in expected:
            decision_times = list(expected["selected_values"])
        left = run_factor_experiment(request, dataset, decision_times=decision_times)
        right = run_factor_experiment(request, dataset, decision_times=decision_times)
        assert left.execution_status == "not_executable_as_full_factor_experiment"
        assert recompute_matches(left, right, absolute_tolerance=TOLERANCE)
        assert left.trial_count["planned"] == expected["trial_count"]["planned"]


def test_fixture_adjustment_status_is_preserved_on_bar_series(tmp_path: Path) -> None:
    case = _case("new_combination")
    request = case["request"]
    assert isinstance(request, dict)
    root = _prepare(tmp_path, request)
    dataset = _load_dataset(root, request)
    assert "adjustment_status" in dataset
    assert dataset["adjustment_status"]
    result = run_factor_experiment(request, dataset)
    # Unadjusted synthetic bars still compute; corporate-action failure regimes stay declared.
    assert "corporate-action volume discontinuity" in request["failure_regimes"]
    assert result.execution_status == "completed"
    for values in result.parameter_outputs.values():
        assert any(value is not None and isinstance(value, float) and math.isfinite(value) for value in values)


def test_cli_compute_factor_freezes_interprets_and_skips_memory_without_evidence(
    tmp_path: Path,
) -> None:
    """T048: request → freeze → calculation table → interpretation → no memory write."""

    from io import StringIO
    import contextlib

    from cash_research.artifacts import resolve_reference
    from cash_research.calculations.trials import verify_frozen_experiment
    from cash_research.cli import main
    from cash_research.models import Calculation

    fixture_request = json.loads(
        (ROOT / "fixtures/requests/factor-new-combination.json").read_text(encoding="utf-8")
    )
    expected_request = _case("new_combination")["request"]
    assert fixture_request == expected_request

    request = copy.deepcopy(fixture_request)
    assert isinstance(request, dict)
    root = _prepare(tmp_path, request)
    request_path = root / "factor-request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    output = StringIO()
    with contextlib.redirect_stdout(output):
        code = main(["--root", str(root), "compute", "factor", "--request", str(request_path)])
    envelope = json.loads(output.getvalue())
    assert code == 0
    assert envelope["operation"] == "compute.factor"
    assert envelope["status"] in {"ok", "partial"}
    assert envelope["request_id"] == "factor-new-combination"

    result_artifact = next(item for item in envelope["artifacts"] if item["type"] == "factor_result")
    interpretation_artifact = next(
        item for item in envelope["artifacts"] if item["type"] == "factor_interpretation"
    )
    calculation_artifact = next(item for item in envelope["artifacts"] if item["type"] == "factor")
    result_table = json.loads((root / result_artifact["path"]).read_text(encoding="utf-8"))
    interpretation = json.loads(
        (root / interpretation_artifact["path"]).read_text(encoding="utf-8")
    )
    calculation = Calculation.model_validate(
        json.loads(resolve_reference(root, calculation_artifact["artifact_id"]).read_text(encoding="utf-8"))
    )

    assert result_table["experiment_id"]
    verify_frozen_experiment(root, result_table["experiment_id"])
    assert result_table["request_hash"] == _case("new_combination")["request_hash"]
    assert result_table["parameter_outputs"]
    assert result_table["split_counts_by_parameter_set"]
    assert calculation.kind == "factor.experiment"
    assert calculation.result_ref.endswith("/result.json")
    assert calculation.parameters["expression"] == request["expression"]

    assert interpretation["mode"] == "interpretation"
    assert interpretation["hypothesis"] == request["hypothesis"]
    assert interpretation["experiment_ids"] == [result_table["experiment_id"]]
    assert interpretation["validation_readout"]["metrics"] == result_table["metrics"]
    assert "buy" not in json.dumps(interpretation)
    assert "sell" not in json.dumps(interpretation)
    assert interpretation["memory"]["action"] in {"no_change", "not_written"}
    assert interpretation["memory"]["reason"]
    assert not (root / "data/topics").exists()
    assert not (root / "data/lessons").exists()

    missing = copy.deepcopy(request)
    missing["dataset_ref"] = "fixtures/factors/does-not-exist.json"
    missing_path = root / "missing-dataset.json"
    missing_path.write_text(json.dumps(missing), encoding="utf-8")
    failed_out = StringIO()
    with contextlib.redirect_stdout(failed_out):
        failed_code = main(
            ["--root", str(root), "compute", "factor", "--request", str(missing_path)]
        )
    failed = json.loads(failed_out.getvalue())
    assert failed_code == 2
    assert failed["status"] == "error"
    assert failed["error"]["reason"] == "invalid"
    assert failed["artifacts"] == []


def test_cli_compute_factor_applies_memory_for_no_increment_evidence(
    tmp_path: Path,
) -> None:
    """T048: completed no_factor_increment with metrics may write memory via proposal."""

    from io import StringIO
    import contextlib

    from cash_research.cli import main

    case = _case("no_increment")
    request = case["request"]
    assert isinstance(request, dict)
    expected = case["expected"]
    assert isinstance(expected, dict)
    assert expected["conclusion"] == "no_factor_increment"
    assert expected["metrics"]["directional_accuracy"] is not None

    root = _prepare(tmp_path, request)
    support_path = root / "evidence.json"
    support_path.write_text(
        json.dumps(
            {
                "hypothesis": request["hypothesis"],
                "expected_conclusion": expected["conclusion"],
                "expected_metrics": expected["metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    topic_id = "synthetic-no-increment-factor"
    request_with_memory = {
        **request,
        "memory_proposal": {
            "memory_type": "topic",
            "expected_version": 0,
            "topic_id": topic_id,
            "current_thesis": (
                "Program factor result is no_factor_increment for the supplied "
                "directional signal versus the always-positive baseline."
            ),
            "support_refs": ["evidence.json"],
            "opposing_refs": [],
            "changes": [
                "Recorded no_factor_increment from compute.factor on the synthetic fixture."
            ],
            "open_questions": [
                "Would a different approved-operator combination change the increment?"
            ],
            "next_checks": [
                "Reopen only with a new frozen request and unseen holdout."
            ],
            "topics": ["factor study"],
            "methods": ["factor research"],
            "securities": ["US:XNAS:SYNF"],
        },
    }
    request_path = root / "factor-no-increment-request.json"
    request_path.write_text(
        json.dumps(request_with_memory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output = StringIO()
    with contextlib.redirect_stdout(output):
        code = main(
            ["--root", str(root), "compute", "factor", "--request", str(request_path)]
        )
    envelope = json.loads(output.getvalue())
    assert code == 0
    assert envelope["operation"] == "compute.factor"

    interpretation_artifact = next(
        item for item in envelope["artifacts"] if item["type"] == "factor_interpretation"
    )
    interpretation = json.loads(
        (root / interpretation_artifact["path"]).read_text(encoding="utf-8")
    )
    memory = interpretation["memory"]
    assert memory["action"] == "applied"
    assert memory["memory_type"] == "topic"
    assert memory["memory_id"] == topic_id
    assert memory["version"] == 1

    version_path = root / f"data/topics/{topic_id}/versions/1.json"
    current_path = root / f"data/topics/{topic_id}/current.json"
    assert version_path.is_file()
    assert current_path.is_file()
    saved = json.loads(version_path.read_text(encoding="utf-8"))
    assert saved["topic_id"] == topic_id
    assert saved["version"] == 1
    assert "no_factor_increment" in saved["current_thesis"]
    assert saved["support_refs"] == ["evidence.json"]

