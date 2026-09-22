from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cash_research.models import FactorExperiment, SecurityIdentity


ROOT = Path(__file__).parents[2]
EXPECTED_PATH = ROOT / "fixtures/factors/expected.json"
APPROVED_OPERATIONS = {
    "field", "constant", "add", "subtract", "multiply", "safe_divide", "abs", "sign", "log", "clip",
    "gt", "gte", "lt", "lte", "and", "or", "where", "weighted_sum",
    "lag", "delta", "pct_return", "log_return",
    "rolling_sum", "rolling_mean", "rolling_median", "rolling_min", "rolling_max", "rolling_std",
    "rolling_quantile", "rolling_rank", "rolling_corr", "rolling_cov", "ewm_mean", "ewm_std",
    "asof_value", "event_age",
}


@pytest.fixture(scope="module")
def factor_fixture() -> dict[str, Any]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _walk_expression(node: object) -> list[dict[str, object]]:
    assert isinstance(node, dict)
    assert set(node) == {"op", "args", "params"}
    assert isinstance(node["op"], str)
    assert isinstance(node["args"], list)
    assert isinstance(node["params"], dict)
    nodes = [node]
    for child in node["args"]:
        nodes.extend(_walk_expression(child))
    return nodes


def _bindings(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if set(value) == {"bind"}:
            assert isinstance(value["bind"], str) and value["bind"]
            found.add(value["bind"])
        else:
            for item in value.values():
                found.update(_bindings(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_bindings(item))
    return found


def _validate_identifier_consistency(request: dict[str, object]) -> None:
    target_spec = request["target_spec"]
    baseline_spec = request["baseline_spec"]
    assert isinstance(target_spec, dict) and isinstance(baseline_spec, dict)
    if request["target"] != target_spec.get("canonical_id"):
        raise ValueError("target_spec_canonical_mismatch")
    if request["baseline"] != baseline_spec.get("canonical_id"):
        raise ValueError("baseline_spec_canonical_mismatch")
    operation = target_spec.get("operation")
    field = target_spec.get("field")
    horizon = target_spec.get("horizon")
    horizon_unit = target_spec.get("horizon_unit")
    prefix = "provided" if operation == "provided_field" else operation
    derived = f"{prefix}:{field}:{horizon}{horizon_unit}"
    if derived != request["target"] or (
        "horizon" in request and request["horizon"] != f"{horizon}{horizon_unit}"
    ):
        raise ValueError("target_spec_semantic_mismatch")


def _validate_expression_contract(
    expression: object, allowed: set[str], parameter_schema: dict[str, object]
) -> None:
    nodes = _walk_expression(expression)
    for node in nodes:
        if node["op"] not in allowed:
            raise ValueError("unsupported_operation")
        if node["op"] == "constant" and not isinstance(node["params"].get("unit"), str):
            raise ValueError("constant_unit_required")
        if node["op"] == "lag" and node["params"].get("periods", 0) < 0:
            raise ValueError("negative_lookback")
        assert not ({"code", "python", "sql", "shell", "eval"} & set(node["params"]))
    assert _bindings(expression) == set(parameter_schema)


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    return [
        None if index + 1 < window else sum(values[index + 1 - window : index + 1]) / window
        for index in range(len(values))
    ]


def _pct_return(values: list[float], periods: int) -> list[float | None]:
    result: list[float | None] = []
    for index, value in enumerate(values):
        result.append(None if index < periods else value / values[index - periods] - 1.0)
    return result


def _volume_conditioned_signal(
    close: list[float], volume: list[float], *, window: int, threshold: float, periods: int
) -> list[float | None]:
    means = _rolling_mean(volume, window)
    returns = _pct_return(close, periods)
    output: list[float | None] = []
    for raw_volume, mean, item_return in zip(volume, means, returns):
        if mean is None or item_return is None:
            output.append(None)
        else:
            output.append(item_return if raw_volume / mean > threshold else 0.0)
    return output


def _assert_close_sequence(
    actual: list[float | None], expected: list[float | None], tolerance: float
) -> None:
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        if right is None:
            assert left is None
        else:
            assert left is not None and math.isclose(left, right, abs_tol=tolerance, rel_tol=0)


def test_fixture_declares_exact_approved_operations_and_full_request_contract(
    factor_fixture: dict[str, Any],
) -> None:
    contract = factor_fixture["contract"]
    assert set(contract["allowed_operations"]) == APPROVED_OPERATIONS
    required = set(contract["required_request_fields"])
    assert factor_fixture["synthetic"] is True
    assert factor_fixture["engine_status"] == "not_implemented_by_T040"
    assert set(factor_fixture["cases"]) == {
        "new_combination",
        "different_bar_interval",
        "future_leakage",
        "zero_division",
        "revision_asof",
        "no_increment",
    }
    for case in factor_fixture["cases"].values():
        request = case["request"]
        assert required <= set(request)
        SecurityIdentity.model_validate(request["security"])
        assert request["failure_regimes"]
        assert request["horizon"] and request["bar_interval"]
        assert request["split"]["fit_scope"] == "train_only"
        assert request["split"]["final_holdout_reuse"] == "forbidden_after_view"
        assert case["request_ref"].startswith("data/factor-requests/")
        assert case["request_ref"].endswith(".json")
        assert case["fixture_locator"].endswith("/request")
        assert case["request_serialization"] == "canonical_json_utf8_v1"
        _validate_identifier_consistency(request)


def test_valid_ast_nodes_use_only_named_approved_operations_and_bindings(
    factor_fixture: dict[str, Any],
) -> None:
    for case in factor_fixture["cases"].values():
        request = case["request"]
        schema = request["parameter_schema"]
        assert isinstance(schema, dict)
        _validate_expression_contract(request["expression"], APPROVED_OPERATIONS, schema)
        ids: set[str] = set()
        for parameter_set in request["parameter_sets"]:
            assert set(parameter_set) == {"parameter_set_id", "bindings"}
            assert parameter_set["parameter_set_id"] not in ids
            ids.add(parameter_set["parameter_set_id"])
            assert set(parameter_set["bindings"]) == set(schema)


def test_target_and_baseline_strings_are_exact_canonical_views_not_second_meanings(
    factor_fixture: dict[str, Any],
) -> None:
    for case in factor_fixture["cases"].values():
        _validate_identifier_consistency(case["request"])
    for name in ("target_spec_mismatch", "target_semantic_mismatch", "baseline_spec_mismatch"):
        invalid = factor_fixture["invalid_cases"][name]
        with pytest.raises(ValueError, match=invalid["expected_error"]):
            _validate_identifier_consistency(invalid)


def test_unknown_operation_negative_lag_and_code_payload_are_contract_rejections(
    factor_fixture: dict[str, Any],
) -> None:
    invalid = factor_fixture["invalid_cases"]
    with pytest.raises(ValueError, match="unsupported_operation"):
        _validate_expression_contract(
            invalid["unknown_operation"]["expression"], APPROVED_OPERATIONS, {}
        )
    with pytest.raises(ValueError, match="negative_lookback"):
        _validate_expression_contract(
            invalid["negative_lag"]["expression"], APPROVED_OPERATIONS, {}
        )


def test_each_frozen_request_has_canonical_hash_and_shared_model_compatibility(
    factor_fixture: dict[str, Any],
) -> None:
    for name, case in factor_fixture["cases"].items():
        request = case["request"]
        assert case["request_hash"] == _canonical_hash(request), name
        experiment = FactorExperiment(
            experiment_id=f"synthetic-{name}",
            request_ref=case["request_ref"],
            request_hash=case["request_hash"],
            hypothesis=request["hypothesis"],
            failure_regimes=tuple(request["failure_regimes"]),
            expression=request["expression"],
            parameter_sets=tuple(request["parameter_sets"]),
            dataset_ref=request["dataset_ref"],
            available_time_rule=request["available_time_rule"],
            target=request["target"],
            horizon=request["horizon"],
            bar_interval=request["bar_interval"],
            baseline=request["baseline"],
            split=request["split"],
            primary_metric=request["primary_metric"],
            metrics=case["expected"]["metrics"],
            costs=request["costs"],
            trial_group=request["trial_group"],
            result_ref=None,
            result_reason="contract fixture only; factor engine not implemented by T040",
        )
        assert experiment.target == request["target"]
        assert experiment.horizon == request["horizon"]


def test_dataset_fixtures_are_synthetic_time_and_unit_explicit(
    factor_fixture: dict[str, Any],
) -> None:
    intervals: set[str] = set()
    for case in factor_fixture["cases"].values():
        dataset_path = ROOT / case["request"]["dataset_ref"]
        assert dataset_path.is_file()
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        assert dataset["synthetic"] is True
        SecurityIdentity.model_validate(dataset["security"])
        assert dataset["fields"]
        assert dataset["adjustment_status"]
        assert dataset["revision_status"]
        assert "not_live_certification" in dataset["point_in_time_status"]
        for metadata in dataset["fields"].values():
            assert metadata["unit"]
            assert "observed_at" in metadata
            assert "available_at" in metadata
        assert dataset["rows"]
        intervals.add(dataset["bar_interval"])
        serialized = json.dumps(dataset).lower()
        assert "real pit certified" not in serialized
    assert {"1d", "30m", "event"} <= intervals


def test_new_combination_hand_calculation_and_future_truncation(
    factor_fixture: dict[str, Any],
) -> None:
    case = factor_fixture["cases"]["new_combination"]
    dataset = json.loads((ROOT / case["request"]["dataset_ref"]).read_text())
    close = [row["close"] for row in dataset["rows"]]
    volume = [row["volume"] for row in dataset["rows"]]
    tolerance = factor_fixture["contract"]["precision"]["absolute_tolerance"]
    for parameter_set in case["request"]["parameter_sets"]:
        values = parameter_set["bindings"]
        actual = _volume_conditioned_signal(
            close,
            volume,
            window=values["volume_window"],
            threshold=values["volume_threshold"],
            periods=values["return_periods"],
        )
        expected = case["expected"]["parameter_outputs"][parameter_set["parameter_set_id"]]
        _assert_close_sequence(actual, expected, tolerance)

    cutoff = case["expected"]["future_truncation"]["cutoff_index"]
    bindings = case["request"]["parameter_sets"][0]["bindings"]
    full = _volume_conditioned_signal(
        close, volume, window=bindings["volume_window"], threshold=bindings["volume_threshold"], periods=bindings["return_periods"]
    )
    truncated = _volume_conditioned_signal(
        close[: cutoff + 1], volume[: cutoff + 1], window=bindings["volume_window"], threshold=bindings["volume_threshold"], periods=bindings["return_periods"]
    )
    _assert_close_sequence(truncated, full[: cutoff + 1], tolerance)


def test_different_bar_interval_has_independent_hand_calculated_values(
    factor_fixture: dict[str, Any],
) -> None:
    case = factor_fixture["cases"]["different_bar_interval"]
    dataset = json.loads((ROOT / case["request"]["dataset_ref"]).read_text())
    closes = [row["close"] for row in dataset["rows"]]
    actual = _pct_return(closes, 2)
    _assert_close_sequence(
        actual,
        case["expected"]["factor_values"],
        factor_fixture["contract"]["precision"]["absolute_tolerance"],
    )
    assert case["request"]["bar_interval"] == "30m"


def _asof_value(rows: list[dict[str, object]], cutoff: str, value_field: str) -> float | None:
    cutoff_time = datetime.fromisoformat(cutoff)
    eligible = [
        row for row in rows if datetime.fromisoformat(str(row["available_at"])) <= cutoff_time
    ]
    if not eligible:
        return None
    return float(max(eligible, key=lambda row: datetime.fromisoformat(str(row["available_at"])))[value_field])


def test_available_time_and_revision_cases_do_not_backfill_future_values(
    factor_fixture: dict[str, Any],
) -> None:
    for case_name, value_field, expected_key in (
        ("future_leakage", "event_value", "asof_values"),
        ("revision_asof", "reported_value", "selected_values"),
    ):
        case = factor_fixture["cases"][case_name]
        rows = json.loads((ROOT / case["request"]["dataset_ref"]).read_text())["rows"]
        for cutoff, expected in case["expected"][expected_key].items():
            assert _asof_value(rows, cutoff, value_field) == expected
        truncation = case["expected"]["future_truncation"]
        cutoff = truncation["cutoff"]
        expected = next(value for key, value in truncation.items() if key.startswith("expected_value"))
        assert _asof_value(rows, cutoff, value_field) == expected
        truncated_rows = [
            row for row in rows if datetime.fromisoformat(row["available_at"]) <= datetime.fromisoformat(cutoff)
        ]
        assert _asof_value(truncated_rows, cutoff, value_field) == expected


def test_safe_divide_zero_is_missing_with_warning_and_no_infinity(
    factor_fixture: dict[str, Any],
) -> None:
    case = factor_fixture["cases"]["zero_division"]
    rows = json.loads((ROOT / case["request"]["dataset_ref"]).read_text())["rows"]
    actual = [
        None if row["denominator"] == 0 else row["numerator"] / row["denominator"]
        for row in rows
    ]
    assert actual == case["expected"]["factor_values"]
    assert case["expected"]["warnings"] == [{"row_index": 1, "reason": "division_by_zero"}]
    assert not any(value is not None and not math.isfinite(value) for value in actual)


def test_no_increment_is_a_complete_expected_result_not_a_fake_success_claim(
    factor_fixture: dict[str, Any],
) -> None:
    case = factor_fixture["cases"]["no_increment"]
    rows = json.loads((ROOT / case["request"]["dataset_ref"]).read_text())["rows"]
    descriptive = case["expected"]["descriptive_all_rows"]
    signal_direction = [1 if row["signal"] > 0 else -1 for row in rows]
    target_direction = [1 if row["forward_return"] > 0 else -1 for row in rows]
    all_matches = [signal == target for signal, target in zip(signal_direction, target_direction)]
    assert signal_direction == descriptive["signal_direction"]
    assert target_direction == descriptive["target_direction"]
    assert sum(all_matches) / len(all_matches) == descriptive["directional_accuracy"]

    holdout = case["expected"]["final_holdout"]
    indices = holdout["row_indices"]
    holdout_signals = [signal_direction[index] for index in indices]
    holdout_targets = [target_direction[index] for index in indices]
    matches = [signal == target for signal, target in zip(holdout_signals, holdout_targets)]
    accuracy = sum(matches) / len(matches)
    baseline_accuracy = sum(target > 0 for target in holdout_targets) / len(holdout_targets)
    assert holdout_signals == holdout["signal_direction"]
    assert holdout_targets == holdout["target_direction"]
    assert matches == holdout["matches"]
    assert len(matches) >= holdout["minimum_samples"]
    assert accuracy == case["expected"]["metrics"]["directional_accuracy"]
    assert baseline_accuracy == case["expected"]["metrics"]["baseline_directional_accuracy"]
    assert accuracy - baseline_accuracy == case["expected"]["metrics"]["increment"]
    assert case["expected"]["conclusion"] == "no_factor_increment"
    assert factor_fixture["engine_status"] == "not_implemented_by_T040"


def test_split_purge_and_trial_count_expectations_are_fixed_before_execution(
    factor_fixture: dict[str, Any],
) -> None:
    expected = factor_fixture["cases"]["new_combination"]["expected"]
    assert expected["split_counts_by_parameter_set"]["p-window2"] == {
        "train": {"candidate": 2, "feature_available": 1, "label_within_partition": 1, "usable": 0},
        "validation": {"candidate": 2, "feature_available": 2, "label_within_partition": 1, "usable": 1},
        "final_holdout": {"candidate": 2, "feature_available": 2, "label_within_partition": 1, "usable": 1},
    }
    assert expected["split_counts_by_parameter_set"]["p-window3"]["train"]["usable"] == 0
    assert expected["metrics"]["directional_accuracy"] is None
    assert expected["metric_scope"]["minimum_sample_status"] == "insufficient_for_effect_conclusion"
    for case in factor_fixture["cases"].values():
        assert case["expected"]["trial_count"]["planned"] == len(case["request"]["parameter_sets"])
    ledger = factor_fixture["trial_ledger_example"]
    entries = ledger["entries"]
    assert sum(item["counts_as_research_trial"] for item in entries) == ledger["expected_counts"]["research_trials"]
    assert sum(item["status"] in {"failed", "abandoned_after_partial_result"} for item in entries) == ledger["expected_counts"]["failed_or_abandoned"]
    assert sum(item["replay_of"] is not None for item in entries) == ledger["expected_counts"]["replays"]
