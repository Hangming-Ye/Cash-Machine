"""Unit checks for factor split purge, metrics, costs, and recomputation helpers."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import pytest

from cash_research.calculations.factor import (
    compute_forward_returns,
    compute_targets,
    recompute_matches,
    run_factor_experiment,
    truncate_dataset,
)
from cash_research.calculations.time_alignment import CompanyAction
from cash_research.calculations.validation import (
    assign_partition,
    block_resample_mean,
    classify_sample,
    compare_to_baseline,
    compute_primary_metric,
    cost_impact,
    count_split,
    directional_accuracy,
    fit_train_only_scaler,
    apply_train_scaler,
    holdout_status_label,
    partition_end_indices,
    trading_simulation_supported,
)
from cash_research.calculations.trials import HoldoutExposure


ROOT = Path(__file__).parents[2]
EXPECTED = json.loads((ROOT / "fixtures/factors/expected.json").read_text(encoding="utf-8"))
TOLERANCE = EXPECTED["contract"]["precision"]["absolute_tolerance"]


def _case(name: str) -> dict[str, object]:
    return EXPECTED["cases"][name]


def _dataset(case: dict[str, object]) -> dict[str, object]:
    request = case["request"]
    assert isinstance(request, dict)
    return json.loads((ROOT / str(request["dataset_ref"])).read_text(encoding="utf-8"))


def _assert_close_seq(actual: list[object], expected: list[object]) -> None:
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        if right is None:
            assert left is None
        else:
            assert left is not None and math.isclose(
                float(left), float(right), abs_tol=TOLERANCE, rel_tol=0
            )


def test_hand_calculation_matches_new_combination_and_30m_fixtures() -> None:
    case = _case("new_combination")
    result = run_factor_experiment(case["request"], _dataset(case))  # type: ignore[arg-type]
    expected = case["expected"]
    assert isinstance(expected, dict)
    for parameter_set_id, values in expected["parameter_outputs"].items():  # type: ignore[index]
        _assert_close_seq(list(result.parameter_outputs[parameter_set_id]), values)
    _assert_close_seq(list(result.target_values or ()), expected["target_values"])  # type: ignore[arg-type]
    assert result.metrics["directional_accuracy"] is None
    assert result.metric_scope["minimum_sample_status"] == "insufficient_for_effect_conclusion"
    assert result.split_counts_by_parameter_set == expected["split_counts_by_parameter_set"]

    intraday = _case("different_bar_interval")
    timed = run_factor_experiment(intraday["request"], _dataset(intraday))  # type: ignore[arg-type]
    _assert_close_seq(
        list(timed.parameter_outputs["p-2bar"]),
        intraday["expected"]["factor_values"],  # type: ignore[index]
    )
    assert timed.metrics["mean_signal"] == pytest.approx(
        intraday["expected"]["metrics"]["mean_signal"]  # type: ignore[index]
    )


def test_label_leakage_across_folds_is_purged() -> None:
    case = _case("new_combination")
    dataset = _dataset(case)
    request = case["request"]
    assert isinstance(request, dict)
    result = run_factor_experiment(request, dataset)
    counts = result.split_counts_by_parameter_set["p-window2"]
    # Train has a feature on the last train bar whose one-bar label lands in validation.
    assert counts["train"]["feature_available"] == 1
    assert counts["train"]["label_within_partition"] == 1
    assert counts["train"]["usable"] == 0
    assert counts["validation"]["usable"] == 1
    assert counts["final_holdout"]["usable"] == 1

    partitions = ["train", "train", "validation", "validation", "final_holdout", "final_holdout"]
    ends = partition_end_indices(partitions)  # type: ignore[arg-type]
    leaked = classify_sample(
        row_index=1,
        partition="train",
        feature_value=0.0,
        horizon=1,
        row_count=6,
        partition_end_index=ends["train"],
    )
    assert leaked.feature_available is True
    assert leaked.label_within_partition is False
    assert leaked.usable is False


def test_future_truncation_leaves_historical_prefix_unchanged() -> None:
    case = _case("new_combination")
    request = case["request"]
    dataset = _dataset(case)
    assert isinstance(request, dict)
    full = run_factor_experiment(request, dataset)
    cutoff = case["expected"]["future_truncation"]["cutoff_index"]  # type: ignore[index]
    truncated = truncate_dataset(dataset, cutoff_index=int(cutoff))
    partial = run_factor_experiment(request, truncated)
    prefix = list(full.parameter_outputs["p-window2"][: int(cutoff) + 1])
    _assert_close_seq(list(partial.parameter_outputs["p-window2"]), prefix)


def test_zero_division_and_asof_operator_limits() -> None:
    zero = _case("zero_division")
    zero_result = run_factor_experiment(zero["request"], _dataset(zero))  # type: ignore[arg-type]
    assert zero_result.execution_status == "not_executable_as_full_factor_experiment"
    _assert_close_seq(
        list(zero_result.parameter_outputs["p-ratio"]),
        zero["expected"]["factor_values"],  # type: ignore[index]
    )
    assert zero_result.warnings == tuple(zero["expected"]["warnings"])  # type: ignore[arg-type]
    assert zero_result.infinite_output_count == 0
    assert zero_result.metrics["valid_fraction"] == pytest.approx(
        zero["expected"]["metrics"]["valid_fraction"]  # type: ignore[index]
    )

    leakage = _case("future_leakage")
    decisions = list(leakage["expected"]["asof_values"])  # type: ignore[arg-type]
    leak_result = run_factor_experiment(
        leakage["request"],  # type: ignore[arg-type]
        _dataset(leakage),
        decision_times=decisions,
    )
    assert leak_result.execution_status == "not_executable_as_full_factor_experiment"
    assert leak_result.asof_values == leakage["expected"]["asof_values"]
    assert leak_result.metrics["eligible_observation_count"] == pytest.approx(2.0)
    truncation = leakage["expected"]["future_truncation"]
    assert isinstance(truncation, dict)
    cutoff = str(truncation["cutoff"])
    before = run_factor_experiment(
        leakage["request"],  # type: ignore[arg-type]
        truncate_dataset(_dataset(leakage), cutoff_time=cutoff),
        decision_times=[cutoff],
    )
    after = run_factor_experiment(
        leakage["request"],  # type: ignore[arg-type]
        _dataset(leakage),
        decision_times=[cutoff],
    )
    expected_value = next(
        value for key, value in truncation.items() if key.startswith("expected_value")
    )
    assert before.asof_values == {cutoff: expected_value}
    assert after.asof_values == {cutoff: expected_value}


def test_revision_asof_and_corporate_action_adjustment() -> None:
    revision = _case("revision_asof")
    decisions = list(revision["expected"]["selected_values"])  # type: ignore[arg-type]
    result = run_factor_experiment(
        revision["request"],  # type: ignore[arg-type]
        _dataset(revision),
        decision_times=decisions,
    )
    assert result.selected_values == revision["expected"]["selected_values"]
    assert result.metrics["selected_value"] == pytest.approx(90.0)
    truncation = revision["expected"]["future_truncation"]
    assert isinstance(truncation, dict)
    cutoff = str(truncation["cutoff"])
    expected_value = next(
        value for key, value in truncation.items() if key.startswith("expected_value")
    )
    truncated = truncate_dataset(_dataset(revision), cutoff_time=cutoff)
    assert (
        run_factor_experiment(
            revision["request"],  # type: ignore[arg-type]
            truncated,
            decision_times=[cutoff],
        ).selected_values
        == {cutoff: expected_value}
    )

    # Corporate-action / adjustment path uses the datetime event fixture already
    # present under fixtures/factors (failure regimes name the discontinuity).
    leakage = _case("future_leakage")
    action_time = datetime.fromisoformat("2026-01-09T16:05:00-05:00")
    action = CompanyAction(
        effective_at=action_time,
        available_at=action_time,
        factor=2.0,
        applies_to="price",
        evidence_ref="fixtures/factors/event-availability.json#synthetic-split",
    )
    decision = "2026-01-09T16:10:00-05:00"
    adjusted = run_factor_experiment(
        leakage["request"],  # type: ignore[arg-type]
        _dataset(leakage),
        decision_times=[decision],
        company_actions=(action,),
    )
    # Event value 20 observed at 16:00; split effective/available at 16:05 → 10 adjusted.
    assert adjusted.asof_values == {decision: 10.0}


def test_no_increment_and_trading_simulation_limit() -> None:
    case = _case("no_increment")
    result = run_factor_experiment(case["request"], _dataset(case))  # type: ignore[arg-type]
    expected = case["expected"]
    assert isinstance(expected, dict)
    assert result.metrics == expected["metrics"]
    assert result.conclusion == "no_factor_increment"
    assert result.final_holdout is not None
    assert result.final_holdout["row_indices"] == expected["final_holdout"]["row_indices"]  # type: ignore[index]
    assert result.descriptive_all_rows is not None
    assert result.descriptive_all_rows["increment"] == expected["descriptive_all_rows"]["increment"]  # type: ignore[index]
    assert result.trading_simulation_supported is False
    assert result.returns_are_executable is False
    assert result.limitation is not None
    assert "not executable" in result.limitation.lower() or "research" in result.limitation.lower()
    assert trading_simulation_supported(str(case["request"]["available_time_rule"])) is False  # type: ignore[index]
    costs = result.parameter_results[0].costs
    assert costs.applicable is False
    assert costs.total_bps == pytest.approx(5.0)


def test_train_only_scaler_ignores_validation_rows() -> None:
    values = [1.0, 3.0, 100.0, None]
    mask = [True, True, False, False]
    mean, std = fit_train_only_scaler(values, mask)
    scaled = apply_train_scaler(values, mean, std)
    assert mean == pytest.approx(2.0)
    assert scaled[2] is not None
    # Validation extreme must not enter the fit moments.
    assert abs(float(scaled[2])) > 10


def test_block_resample_is_deterministic_and_same_inputs_recompute() -> None:
    values = [0.01, -0.02, 0.015, 0.0, 0.02]
    first = block_resample_mean(values, block_length=2, resamples=32, seed=7)
    second = block_resample_mean(values, block_length=2, resamples=32, seed=7)
    assert first == second
    assert first.available is True

    case = _case("new_combination")
    left = run_factor_experiment(case["request"], _dataset(case))  # type: ignore[arg-type]
    right = run_factor_experiment(case["request"], _dataset(case))  # type: ignore[arg-type]
    assert recompute_matches(left, right, absolute_tolerance=TOLERANCE)


def test_holdout_status_cannot_stay_unseen_after_view() -> None:
    unseen = holdout_status_label(HoldoutExposure(False, False, ()), viewed_this_run=False)
    assert unseen == "unseen"
    viewed = holdout_status_label(HoldoutExposure(True, True, ("trial_a",)), viewed_this_run=False)
    assert viewed != "unseen"
    assert "exploratory" in viewed or "viewed" in viewed


def test_forward_targets_and_split_helpers() -> None:
    case = _case("new_combination")
    dataset = _dataset(case)
    targets = compute_targets(case["request"], dataset)  # type: ignore[arg-type]
    _assert_close_seq(list(targets or ()), case["expected"]["target_values"])  # type: ignore[arg-type]
    closes = [row["close"] for row in dataset["rows"]]
    _assert_close_seq(list(compute_forward_returns(closes, 1)), case["expected"]["target_values"])  # type: ignore[arg-type]

    split = case["request"]["split"]
    assert isinstance(split, dict)
    assert assign_partition(
        datetime.fromisoformat("2026-01-07T16:00:00-05:00"),
        split,
        zone_name="America/New_York",
    ) == "validation"

    metric = directional_accuracy([1.0, -1.0], [0.01, 0.02])
    assert metric.value == pytest.approx(0.5)
    baseline = compare_to_baseline(
        primary=metric,
        signals=[1.0, -1.0],
        targets=[0.01, 0.02],
        baseline_spec={"kind": "constant_direction", "value": 1.0, "unit": "direction"},
    )
    assert baseline.conclusion == "no_factor_increment"
    impact = cost_impact(
        costs={"commission_bps": 2.0, "slippage_bps": 3.0},
        signals=[1.0],
        targets=[0.01],
        simulation_supported=False,
    )
    assert impact.applicable is False
    assert count_split([], "train").candidate == 0
    assert compute_primary_metric("mean_signal", [1.0, 3.0]).value == pytest.approx(2.0)
