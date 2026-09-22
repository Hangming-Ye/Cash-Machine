from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cash_research.calculations.expression import validate_expression
from cash_research.calculations.operators import (
    EvaluationContext,
    EvaluationResult,
    HistoricalOperatorRequired,
    OperatorInputError,
    SeriesData,
    evaluate_expression,
)


ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def field(name: str) -> dict[str, object]:
    return {"op": "field", "args": [], "params": {"name": name}}


def constant(value: float, unit: str = "dimensionless") -> dict[str, object]:
    return {"op": "constant", "args": [], "params": {"value": value, "unit": unit}}


def node(op: str, *args: object, **params: object) -> dict[str, object]:
    return {"op": op, "args": list(args), "params": params}


def schema(names: tuple[str, ...], count: int, *, units: dict[str, str] | None = None) -> dict[str, object]:
    units = units or {}
    rows = []
    for index in range(count):
        row: dict[str, object] = {
            "timestamp": f"t{index}",
            "available_at": (NOW + timedelta(minutes=index)).isoformat(),
            "revision_id": "initial",
        }
        row.update({name: 0.0 for name in names})
        rows.append(row)
    return {
        "bar_interval": "1d",
        "point_in_time_status": "not_proven",
        "fields": {
            name: {
                "unit": units.get(name, "dimensionless"),
                "observed_at": "timestamp",
                "available_at": "available_at",
            }
            for name in names
        },
        "rows": rows,
    }


def series(
    values: list[object],
    *,
    index: tuple[object, ...] | None = None,
    availability: list[datetime | None] | None = None,
    timeless: bool = False,
) -> SeriesData:
    idx = index or tuple(range(len(values)))
    available = availability or [NOW + timedelta(minutes=i) for i in range(len(values))]
    return SeriesData(index=idx, values=tuple(values), available_at=tuple(available), timeless=timeless)


def compile_and_run(
    expression: dict[str, object],
    values: dict[str, list[object]],
    *,
    availability: dict[str, list[datetime | None]] | None = None,
    units: dict[str, str] | None = None,
    parameter_schema: dict[str, object] | None = None,
    parameter_sets: list[dict[str, object]] | None = None,
    set_index: int = 0,
    historical_handlers: object | None = None,
) -> EvaluationResult:
    count = len(next(iter(values.values()))) if values else 3
    dataset = schema(tuple(values), count, units=units)
    compiled = validate_expression(
        expression,
        dataset=dataset,
        parameter_schema=parameter_schema or {},
        parameter_sets=parameter_sets or [{"parameter_set_id": "p0", "bindings": {}}],
    )
    index = tuple(range(count))
    context = EvaluationContext(
        index=index,
        fields={
            name: series(
                rows,
                index=index,
                availability=(availability or {}).get(name),
            )
            for name, rows in values.items()
        },
    )
    return evaluate_expression(
        compiled.root,
        context=context,
        parameter_set=compiled.parameter_sets[set_index],
        historical_handlers=historical_handlers,
    )


def assert_optional_floats(
    actual: tuple[object, ...], expected: list[object]
) -> None:
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if expected_value is None:
            assert actual_value is None
        else:
            assert actual_value == pytest.approx(expected_value)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (node("add", field("x"), field("y")), [3.0, None, 7.0]),
        (node("subtract", field("x"), field("y")), [-1.0, None, -1.0]),
        (node("multiply", field("x"), field("y")), [2.0, None, 12.0]),
        (node("abs", field("x")), [1.0, None, 3.0]),
        (node("sign", field("x")), [1.0, None, 1.0]),
        (node("clip", field("x"), lower=1.5, upper=2.5, unit="dimensionless", missing="propagate"), [1.5, None, 2.5]),
    ],
)
def test_basic_math_is_hand_checkable_and_never_fills_missing(
    expression: dict[str, object], expected: list[float | None]
) -> None:
    result = compile_and_run(expression, {"x": [1.0, None, 3.0], "y": [2.0, 3.0, 4.0]})
    assert list(result.series.values) == expected


def test_safe_divide_log_and_nonfinite_output_become_null_with_warnings() -> None:
    divide = compile_and_run(
        node("safe_divide", field("x"), field("y")),
        {"x": [2.0, 3.0, 1e308], "y": [1.0, 0.0, 1e-308]},
    )
    assert divide.series.values == (2.0, None, None)
    assert [warning.reason for warning in divide.warnings] == ["division_by_zero", "nonfinite_output"]

    logged = compile_and_run(
        node("log", field("x"), nonpositive="missing"),
        {"x": [1.0, 0.0, -1.0]},
    )
    assert logged.series.values == (0.0, None, None)
    assert [warning.reason for warning in logged.warnings] == ["log_nonpositive", "log_nonpositive"]

    unrepresentable = compile_and_run(
        node("add", field("x"), constant(1)),
        {"x": [math.inf, 10**10000]},
    )
    assert unrepresentable.series.values == (None, None)
    assert [warning.reason for warning in unrepresentable.warnings] == [
        "nonfinite_input",
        "nonfinite_input",
    ]


def test_comparisons_and_three_valued_boolean_short_circuit_availability() -> None:
    early = NOW
    late = NOW + timedelta(days=3)
    expression = node(
        "and",
        node("gt", field("x"), constant(0)),
        node("gt", field("y"), constant(0)),
    )
    result = compile_and_run(
        expression,
        {"x": [-1.0, 1.0, None], "y": [None, None, -1.0]},
        availability={"x": [early, early, None], "y": [late, None, late]},
    )
    assert result.series.values == (False, None, False)
    assert result.series.available_at == (early, None, late)

    either = compile_and_run(
        node("or", node("gt", field("x"), constant(0)), node("gt", field("y"), constant(0))),
        {"x": [1.0, -1.0], "y": [None, None]},
    )
    assert either.series.values == (True, None)


def test_where_uses_only_selected_branch_and_explicit_missing_condition_policy() -> None:
    late = NOW + timedelta(days=10)
    expression = node(
        "where",
        node("gt", field("condition"), constant(0)),
        field("left"),
        field("right"),
        missing_condition="false",
    )
    result = compile_and_run(
        expression,
        {
            "condition": [1.0, -1.0, None],
            "left": [10.0, 20.0, 30.0],
            "right": [1.0, 2.0, 3.0],
        },
        availability={
            "condition": [NOW, NOW, None],
            "left": [NOW, late, late],
            "right": [late, NOW, NOW],
        },
    )
    assert result.series.values == (10.0, 2.0, 3.0)
    assert result.series.available_at == (NOW, NOW, NOW)
    assert [item.reason for item in result.warnings] == ["missing_condition_used_false_policy"]


def test_weighted_sum_require_all_and_skip_are_distinct_without_zero_fill() -> None:
    require = compile_and_run(
        node("weighted_sum", field("x"), field("y"), weights=[0.25, 0.75], missing="require_all"),
        {"x": [4.0, None], "y": [8.0, 8.0]},
    )
    skip = compile_and_run(
        node("weighted_sum", field("x"), field("y"), weights=[0.25, 0.75], missing="skip"),
        {"x": [4.0, None], "y": [8.0, 8.0]},
    )
    assert require.series.values == (7.0, None)
    assert skip.series.values == (7.0, 6.0)
    assert skip.warnings[0].reason == "weighted_missing_skipped_without_renormalization"


@pytest.mark.parametrize(
    ("op", "expected"),
    [
        ("lag", [None, 1.0, 2.0, 4.0]),
        ("delta", [None, 1.0, 2.0, 4.0]),
        ("pct_return", [None, 1.0, 1.0, 1.0]),
        ("log_return", [None, math.log(2), math.log(2), math.log(2)]),
    ],
)
def test_backward_time_operators_match_hand_values_and_keep_prefix(
    op: str, expected: list[float | None]
) -> None:
    expression = node(op, field("x"), periods=1, missing="propagate")
    full = compile_and_run(expression, {"x": [1.0, 2.0, 4.0, 8.0]})
    short = compile_and_run(expression, {"x": [1.0, 2.0, 4.0]})
    for actual, wanted in zip(full.series.values, expected):
        assert actual == pytest.approx(wanted) if wanted is not None else actual is None
    assert short.series.values == full.series.values[:3]


def test_log_return_uses_stable_logs_for_positive_extreme_values() -> None:
    result = compile_and_run(
        node("log_return", field("x"), periods=1, missing="propagate"),
        {"x": [1e308, 1e-308]},
    )
    assert result.series.values[-1] == pytest.approx(math.log(1e-308) - math.log(1e308))


@pytest.mark.parametrize(
    ("op", "expected_second", "expected_last"),
    [
        ("rolling_sum", 3.0, 6.0),
        ("rolling_mean", 1.5, 2.0),
        ("rolling_median", 1.5, 2.0),
        ("rolling_min", 1.0, 1.0),
        ("rolling_max", 2.0, 3.0),
    ],
)
def test_simple_rolling_partial_history_respects_min_periods(
    op: str, expected_second: float, expected_last: float
) -> None:
    result = compile_and_run(
        node(op, field("x"), window=3, min_periods=2, missing="skip"),
        {"x": [1.0, 2.0, 3.0]},
    )
    assert result.series.values == (None, expected_second, expected_last)


def test_rolling_missing_modes_are_distinct() -> None:
    outputs = {}
    for mode in ("skip", "require_min_periods", "propagate"):
        outputs[mode] = compile_and_run(
            node("rolling_mean", field("x"), window=2, min_periods=2, missing=mode),
            {"x": [None, 2.0]},
        ).series.values[-1]
    assert outputs == {"skip": 2.0, "require_min_periods": None, "propagate": None}


def test_rolling_appending_future_rows_cannot_change_past_values() -> None:
    expression = node(
        "rolling_mean", field("x"), window=3, min_periods=2, missing="skip"
    )
    prefix = compile_and_run(expression, {"x": [1.0, 2.0, 4.0]})
    full = compile_and_run(expression, {"x": [1.0, 2.0, 4.0, 1000.0]})
    assert prefix.series.values == full.series.values[:3]
    assert prefix.series.available_at == full.series.available_at[:3]


def test_rolling_std_quantile_and_interpolation_are_hand_calculated() -> None:
    std = compile_and_run(
        node("rolling_std", field("x"), window=3, min_periods=3, ddof=1, missing="skip"),
        {"x": [1.0, 2.0, 4.0]},
    )
    assert std.series.values[-1] == pytest.approx(math.sqrt(7 / 3))

    expected = {"lower": 1.0, "higher": 2.0, "midpoint": 1.5, "linear": 1.5, "nearest": 1.0}
    for interpolation, value in expected.items():
        result = compile_and_run(
            node("rolling_quantile", field("x"), window=3, min_periods=3, q=0.25, interpolation=interpolation, missing="skip"),
            {"x": [1.0, 2.0, 4.0]},
        )
        assert result.series.values[-1] == value

    overflow = compile_and_run(
        node("rolling_std", field("x"), window=2, min_periods=2, ddof=1, missing="skip"),
        {"x": [-1e308, 1e308]},
    )
    assert overflow.series.values[-1] is None
    assert overflow.warnings[-1].reason == "nonfinite_output"


@pytest.mark.parametrize(
    ("method", "expected"),
    [("average", 2.5), ("min", 2.0), ("max", 3.0), ("first", 3.0), ("dense", 2.0)],
)
def test_all_admitted_rolling_rank_tie_methods_are_implemented(
    method: str, expected: float
) -> None:
    result = compile_and_run(
        node(
            "rolling_rank",
            field("x"),
            window=3,
            min_periods=3,
            method=method,
            ascending=True,
            pct=False,
            na_option="keep",
            missing="skip",
        ),
        {"x": [2.0, 1.0, 2.0]},
    )
    assert result.series.values[-1] == expected


def test_rank_descending_pct_and_na_options_are_explicit() -> None:
    descending = compile_and_run(
        node("rolling_rank", field("x"), window=3, min_periods=3, method="average", ascending=False, pct=True, na_option="keep", missing="skip"),
        {"x": [2.0, 1.0, 2.0]},
    )
    assert descending.series.values[-1] == pytest.approx(1.5 / 3)
    outputs = {}
    for option in ("keep", "top", "bottom"):
        outputs[option] = compile_and_run(
            node("rolling_rank", field("x"), window=3, min_periods=2, method="average", ascending=True, pct=False, na_option=option, missing="skip"),
            {"x": [2.0, 1.0, None]},
        ).series.values[-1]
    assert outputs == {"keep": None, "top": 1.0, "bottom": 3.0}


def test_rolling_corr_cov_pairwise_and_zero_variance() -> None:
    corr = compile_and_run(
        node("rolling_corr", field("x"), field("y"), window=3, min_periods=2, missing="pairwise"),
        {"x": [1.0, 2.0, 3.0], "y": [2.0, 4.0, 6.0]},
    )
    cov = compile_and_run(
        node("rolling_cov", field("x"), field("y"), window=3, min_periods=2, ddof=1, missing="pairwise"),
        {"x": [1.0, 2.0, 3.0], "y": [2.0, 4.0, 6.0]},
    )
    assert corr.series.values[-1] == pytest.approx(1.0)
    assert cov.series.values[-1] == pytest.approx(2.0)

    zero = compile_and_run(
        node("rolling_corr", field("x"), field("y"), window=3, min_periods=2, missing="pairwise"),
        {"x": [1.0, 1.0, 1.0], "y": [2.0, 3.0, 4.0]},
    )
    assert zero.series.values[-1] is None
    assert zero.warnings[-1].reason == "zero_variance"


def test_ewm_mean_adjust_and_ignore_na_match_independent_weight_examples() -> None:
    adjusted = compile_and_run(
        node("ewm_mean", field("x"), alpha=0.5, adjust=True, ignore_na=False, min_periods=1),
        {"x": [1.0, 2.0, 3.0]},
    )
    recursive = compile_and_run(
        node("ewm_mean", field("x"), alpha=0.5, adjust=False, ignore_na=True, min_periods=1),
        {"x": [1.0, 2.0, 3.0]},
    )
    assert adjusted.series.values == pytest.approx((1.0, 5 / 3, 17 / 7))
    assert recursive.series.values == pytest.approx((1.0, 1.5, 2.25))

    absolute = compile_and_run(
        node("ewm_mean", field("x"), alpha=0.5, adjust=True, ignore_na=False, min_periods=1),
        {"x": [1.0, None, 3.0]},
    )
    relative = compile_and_run(
        node("ewm_mean", field("x"), alpha=0.5, adjust=True, ignore_na=True, min_periods=1),
        {"x": [1.0, None, 3.0]},
    )
    assert absolute.series.values[-1] == pytest.approx(2.6)
    assert relative.series.values[-1] == pytest.approx(7 / 3)

    recursive_gap = compile_and_run(
        node("ewm_mean", field("x"), alpha=0.5, adjust=False, ignore_na=False, min_periods=1),
        {"x": [1.0, None, 3.0, 4.0]},
    )
    assert recursive_gap.series.values == pytest.approx((1.0, 1.0, 7 / 3, 19 / 6))

    alpha_one = compile_and_run(
        node("ewm_mean", field("x"), alpha=1.0, adjust=False, ignore_na=False, min_periods=1),
        {"x": [1.0, None, 3.0]},
    )
    assert alpha_one.series.values == pytest.approx((1.0, 1.0, 3.0))


def test_ewm_std_bias_and_prefix_invariance_use_independent_weight_formula() -> None:
    expression = node("ewm_std", field("x"), alpha=0.5, adjust=True, ignore_na=True, min_periods=2, bias=True)
    biased = compile_and_run(expression, {"x": [1.0, 2.0, 3.0]})
    weights = [0.25, 0.5, 1.0]
    mean = sum(w * x for w, x in zip(weights, [1.0, 2.0, 3.0])) / sum(weights)
    variance = sum(w * (x - mean) ** 2 for w, x in zip(weights, [1.0, 2.0, 3.0])) / sum(weights)
    assert biased.series.values[-1] == pytest.approx(math.sqrt(variance))

    unbiased = compile_and_run(
        node("ewm_std", field("x"), alpha=0.5, adjust=True, ignore_na=True, min_periods=2, bias=False),
        {"x": [1.0, 2.0, 3.0]},
    )
    correction = sum(weights) ** 2 / (sum(weights) ** 2 - sum(w * w for w in weights))
    assert unbiased.series.values[-1] == pytest.approx(math.sqrt(variance * correction))

    full = compile_and_run(expression, {"x": [1.0, 2.0, 3.0, 4.0]})
    assert biased.series.values == full.series.values[:3]


def test_ewm_thousand_rows_is_deterministic_without_resetting_history() -> None:
    expression = node(
        "ewm_mean", field("x"), alpha=0.2, adjust=False, ignore_na=False, min_periods=1
    )
    values = [float(index % 17) for index in range(1000)]
    first = compile_and_run(expression, {"x": values})
    second = compile_and_run(expression, {"x": values})
    assert first == second
    expected = values[0]
    for value in values[1:]:
        expected = 0.8 * expected + 0.2 * value
    assert first.series.values[-1] == pytest.approx(expected)


def test_ewm_overflow_is_missing_with_warning_instead_of_nan_or_crash() -> None:
    result = compile_and_run(
        node(
            "ewm_std",
            field("x"),
            alpha=0.5,
            adjust=False,
            ignore_na=False,
            min_periods=2,
            bias=True,
        ),
        {"x": [-1e308, 1e308]},
    )
    assert result.series.values[-1] is None
    assert result.warnings[-1].reason == "nonfinite_output"


def test_parameter_sets_resolve_independently_without_mutating_inputs() -> None:
    expression = node("lag", field("x"), periods={"bind": "periods"}, missing="propagate")
    parameter_schema = {"periods": {"type": "integer", "unit": "bars", "minimum": 0}}
    parameter_sets = [
        {"parameter_set_id": "p1", "bindings": {"periods": 1}},
        {"parameter_set_id": "p2", "bindings": {"periods": 2}},
    ]
    values = {"x": [1.0, 2.0, 3.0]}
    first = compile_and_run(expression, values, parameter_schema=parameter_schema, parameter_sets=parameter_sets, set_index=0)
    second = compile_and_run(expression, values, parameter_schema=parameter_schema, parameter_sets=parameter_sets, set_index=1)
    assert first.series.values == (None, 1.0, 2.0)
    assert second.series.values == (None, None, 1.0)
    assert values == {"x": [1.0, 2.0, 3.0]}


@pytest.mark.parametrize("case_name", ["new_combination", "different_bar_interval"])
def test_frozen_t040_hand_outputs_execute_through_real_validator(
    case_name: str,
) -> None:
    contract = json.loads((ROOT / "fixtures/factors/expected.json").read_text("utf-8"))
    case = contract["cases"][case_name]
    request = case["request"]
    dataset = json.loads((ROOT / request["dataset_ref"]).read_text("utf-8"))
    compiled = validate_expression(
        request["expression"],
        dataset=dataset,
        parameter_schema=request["parameter_schema"],
        parameter_sets=request["parameter_sets"],
    )
    rows = dataset["rows"]
    index = tuple(row["timestamp"] for row in rows)
    context = EvaluationContext(
        index=index,
        fields={
            name: SeriesData(
                index=index,
                values=tuple(row.get(name) for row in rows),
                available_at=tuple(
                    datetime.fromisoformat(row[metadata["available_at"]]) for row in rows
                ),
            )
            for name, metadata in dataset["fields"].items()
        },
    )

    if case_name == "new_combination":
        for parameter_set in compiled.parameter_sets:
            result = evaluate_expression(
                compiled.root, context=context, parameter_set=parameter_set
            )
            assert_optional_floats(
                result.series.values,
                case["expected"]["parameter_outputs"][parameter_set.parameter_set_id],
            )
    else:
        result = evaluate_expression(
            compiled.root,
            context=context,
            parameter_set=compiled.parameter_sets[0],
        )
        assert_optional_floats(result.series.values, case["expected"]["factor_values"])


def test_series_context_rejects_alignment_naive_time_and_named_timeless_source() -> None:
    with pytest.raises(OperatorInputError):
        SeriesData(index=(0,), values=(1.0,), available_at=(datetime(2026, 1, 1),))
    with pytest.raises(OperatorInputError):
        EvaluationContext(index=(0, 1), fields={"x": series([1.0], index=(0,))})

    compiled = validate_expression(
        field("x"),
        dataset=schema(("x",), 1),
        parameter_schema={},
        parameter_sets=[{"parameter_set_id": "p", "bindings": {}}],
    )
    context = EvaluationContext(index=(0,), fields={"x": series([1.0], index=(0,), timeless=True)})
    with pytest.raises(OperatorInputError, match="timeless"):
        evaluate_expression(compiled.root, context=context, parameter_set=compiled.parameter_sets[0])


def test_constants_are_timeless_but_unknown_source_availability_stays_unknown() -> None:
    result = compile_and_run(
        node("add", field("x"), constant(2)),
        {"x": [1.0, 2.0]},
        availability={"x": [None, NOW]},
    )
    assert result.series.values == (3.0, 4.0)
    assert result.series.available_at == (None, NOW)
    assert result.series.timeless is False


def test_historical_ops_require_explicit_handler_and_validate_handler_output() -> None:
    expression = node(
        "asof_value",
        field("event"),
        observed_at_field="timestamp",
        available_at_field="available_at",
        no_eligible="missing",
    )
    dataset = schema(("event",), 2)
    compiled = validate_expression(
        expression,
        dataset=dataset,
        parameter_schema={},
        parameter_sets=[{"parameter_set_id": "p", "bindings": {}}],
    )
    context = EvaluationContext(index=(0, 1), fields={"event": series([10.0, 20.0], index=(0, 1))})
    with pytest.raises(HistoricalOperatorRequired):
        evaluate_expression(compiled.root, context=context, parameter_set=compiled.parameter_sets[0])

    def handler(node_value: object, args: object, params: object, context_value: EvaluationContext) -> EvaluationResult:
        return EvaluationResult(series([None, 10.0], index=context_value.index), ())

    handled = evaluate_expression(
        compiled.root,
        context=context,
        parameter_set=compiled.parameter_sets[0],
        historical_handlers={"asof_value": handler},
    )
    assert handled.series.values == (None, 10.0)

    def wrong_index(node_value: object, args: object, params: object, context_value: EvaluationContext) -> EvaluationResult:
        return EvaluationResult(series([10.0], index=("wrong",)), ())

    with pytest.raises(OperatorInputError, match="index"):
        evaluate_expression(
            compiled.root,
            context=context,
            parameter_set=compiled.parameter_sets[0],
            historical_handlers={"asof_value": wrong_index},
        )
