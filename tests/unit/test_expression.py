from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from cash_research.calculations.expression import (
    ExpressionLimitError,
    ExpressionLimits,
    ExpressionValidationError,
    ParameterRef,
    Unit,
    validate_expression,
)


ROOT = Path(__file__).parents[2]
FACTOR_FIXTURE = ROOT / "fixtures/factors/expected.json"
LIMITS_EXAMPLE = ROOT / "config/calculation-limits.example.json"


def _field(name: str) -> dict[str, object]:
    return {"op": "field", "args": [], "params": {"name": name}}


def _constant(value: object, unit: str = "dimensionless") -> dict[str, object]:
    return {"op": "constant", "args": [], "params": {"value": value, "unit": unit}}


def _node(op: str, *args: object, **params: object) -> dict[str, object]:
    return {"op": op, "args": list(args), "params": params}


def _dataset(*, rows: int = 8, bar_interval: str = "1d") -> dict[str, object]:
    data_rows = [
        {
            "timestamp": f"2026-01-{index + 1:02d}T16:00:00-05:00",
            "available_at": f"2026-01-{index + 1:02d}T16:05:00-05:00",
            "revision_id": "initial",
            "price": 100.0 + index,
            "other_price": 90.0 + index,
            "volume": 1000 + index,
            "ret": 0.01,
            "signal": 1.0,
            "ratio": 1.1,
            "event": 2.0,
        }
        for index in range(rows)
    ]
    return {
        "schema_version": "1.0",
        "bar_interval": bar_interval,
        "point_in_time_status": "synthetic_explicit_availability_not_live_certification",
        "fields": {
            "price": {"unit": "USD/share", "observed_at": "timestamp", "available_at": "available_at"},
            "other_price": {"unit": "USD/share", "observed_at": "timestamp", "available_at": "available_at"},
            "volume": {"unit": "shares", "observed_at": "timestamp", "available_at": "available_at"},
            "ret": {"unit": "decimal_return", "observed_at": "timestamp", "available_at": "available_at"},
            "signal": {"unit": "direction", "observed_at": "timestamp", "available_at": "available_at"},
            "ratio": {"unit": "dimensionless", "observed_at": "timestamp", "available_at": "available_at"},
            "event": {"unit": "dimensionless", "observed_at": "timestamp", "available_at": "available_at", "revision": "revision_id"},
        },
        "rows": data_rows,
    }


def _validate(
    expression: object,
    *,
    schema: dict[str, object] | None = None,
    sets: list[dict[str, object]] | None = None,
    dataset: dict[str, object] | None = None,
    limits: ExpressionLimits | None = None,
):
    return validate_expression(
        expression,
        dataset=dataset or _dataset(),
        parameter_schema=schema if schema is not None else {},
        parameter_sets=(
            sets if sets is not None else [{"parameter_set_id": "p0", "bindings": {}}]
        ),
        limits=limits or ExpressionLimits(),
    )


def _bound_nodes(root: object) -> list[object]:
    nodes = [root]
    for child in root.args:
        nodes.extend(_bound_nodes(child))
    return nodes


def test_t040_new_combination_and_30m_requests_compile_without_registered_factor_ids() -> None:
    fixture = json.loads(FACTOR_FIXTURE.read_text(encoding="utf-8"))
    new_request = fixture["cases"]["new_combination"]["request"]
    new_dataset = json.loads((ROOT / new_request["dataset_ref"]).read_text(encoding="utf-8"))
    compiled = validate_expression(
        new_request["expression"],
        dataset=new_dataset,
        parameter_schema=new_request["parameter_schema"],
        parameter_sets=new_request["parameter_sets"],
    )
    assert compiled.inferred_unit == "decimal_return"
    assert compiled.referenced_fields == ("close", "volume")
    assert compiled.parameter_names == ("return_periods", "volume_threshold", "volume_window")
    assert [item.parameter_set_id for item in compiled.parameter_sets] == ["p-window2", "p-window3"]
    assert set(compiled.batch_plan.parameter_set_ids) == {"p-window2", "p-window3"}
    nodes = {node.op: node for node in _bound_nodes(compiled.root)}
    assert nodes["where"].parameter("missing_condition") == "propagate"
    assert nodes["rolling_mean"].parameter("missing") == "require_min_periods"
    assert nodes["pct_return"].parameter("missing") == "propagate"

    intraday = fixture["cases"]["different_bar_interval"]["request"]
    intraday_dataset = json.loads((ROOT / intraday["dataset_ref"]).read_text(encoding="utf-8"))
    compiled_30m = validate_expression(
        intraday["expression"],
        dataset=intraday_dataset,
        parameter_schema=intraday["parameter_schema"],
        parameter_sets=intraday["parameter_sets"],
    )
    assert compiled_30m.dataset.bar_interval == "30m"
    assert compiled_30m.inferred_unit == "decimal_return"


def test_every_t040_expression_contract_compiles_against_its_current_snapshot() -> None:
    fixture = json.loads(FACTOR_FIXTURE.read_text(encoding="utf-8"))
    for case_id, case in fixture["cases"].items():
        request = case["request"]
        dataset = json.loads((ROOT / request["dataset_ref"]).read_text(encoding="utf-8"))
        compiled = validate_expression(
            request["expression"],
            dataset=dataset,
            parameter_schema=request["parameter_schema"],
            parameter_sets=request["parameter_sets"],
        )
        assert compiled.resource_estimate.parameter_set_count == len(request["parameter_sets"]), case_id


@pytest.mark.parametrize(
    ("expression", "unit", "kind"),
    [
        (_node("add", _field("price"), _field("other_price")), "USD/share", "numeric"),
        (_node("subtract", _field("price"), _field("other_price")), "USD/share", "numeric"),
        (_node("multiply", _field("price"), _field("volume")), "USD", "numeric"),
        (_node("safe_divide", _field("price"), _field("other_price")), "dimensionless", "numeric"),
        (_node("abs", _field("price")), "USD/share", "numeric"),
        (_node("sign", _field("price")), "direction", "numeric"),
        (_node("log", _field("ratio"), nonpositive="missing"), "dimensionless", "numeric"),
        (_node("clip", _field("price"), lower=90.0, upper=120.0, unit="USD/share", missing="propagate"), "USD/share", "numeric"),
        (_node("gt", _field("price"), _field("other_price")), "boolean", "boolean"),
        (_node("and", _node("gt", _field("price"), _field("other_price")), _node("gte", _field("ratio"), _constant(1))), "boolean", "boolean"),
        (_node("where", _node("gt", _field("ratio"), _constant(1)), _field("price"), _field("other_price"), missing_condition="propagate"), "USD/share", "numeric"),
        (_node("weighted_sum", _field("price"), _field("other_price"), weights=[0.4, 0.6], missing="require_all"), "USD/share", "numeric"),
        (_node("lag", _field("price"), periods=1, missing="propagate"), "USD/share", "numeric"),
        (_node("delta", _field("price"), periods=1, missing="propagate"), "USD/share", "numeric"),
        (_node("pct_return", _field("price"), periods=1), "decimal_return", "numeric"),
        (_node("log_return", _field("price"), periods=1), "decimal_return", "numeric"),
        (_node("rolling_mean", _field("price"), window=3, min_periods=2), "USD/share", "numeric"),
        (_node("rolling_std", _field("price"), window=3, min_periods=2, ddof=1, missing="skip"), "USD/share", "numeric"),
        (_node("rolling_quantile", _field("price"), window=3, min_periods=2, q=0.5, interpolation="linear", missing="skip"), "USD/share", "numeric"),
        (_node("rolling_rank", _field("price"), window=3, min_periods=2, method="average", ascending=True, pct=True, na_option="keep", missing="skip"), "dimensionless", "numeric"),
        (_node("rolling_corr", _field("price"), _field("other_price"), window=3, min_periods=2, missing="pairwise"), "dimensionless", "numeric"),
        (_node("rolling_cov", _field("price"), _field("volume"), window=3, min_periods=2, ddof=1, missing="pairwise"), "USD", "numeric"),
        (_node("ewm_mean", _field("price"), span=3.0, adjust=False, ignore_na=True, min_periods=1), "USD/share", "numeric"),
        (_node("ewm_std", _field("price"), alpha=0.5, adjust=False, ignore_na=True, min_periods=1, bias=False), "USD/share", "numeric"),
        (_node("asof_value", _field("event"), observed_at_field="timestamp", available_at_field="available_at", revision_field="revision_id", no_eligible="missing"), "dimensionless", "numeric"),
        (_node("event_age", _field("event"), observed_at_field="timestamp", available_at_field="available_at", revision_field="revision_id", output_unit="bars", no_eligible="missing"), "bars", "numeric"),
    ],
)
def test_each_approved_operation_family_has_precise_arity_params_and_units(
    expression: dict[str, object], unit: str, kind: str
) -> None:
    compiled = _validate(expression)
    assert compiled.inferred_unit == unit
    assert compiled.root.kind == kind


@pytest.mark.parametrize(
    "op",
    ["rolling_sum", "rolling_mean", "rolling_median", "rolling_min", "rolling_max"],
)
def test_all_simple_rolling_names_preserve_input_unit(op: str) -> None:
    compiled = _validate(_node(op, _field("price"), window=3, min_periods=1, missing="skip"))
    assert compiled.inferred_unit == "USD/share"


@pytest.mark.parametrize("op", ["gt", "gte", "lt", "lte"])
def test_all_comparison_names_return_boolean(op: str) -> None:
    assert _validate(_node(op, _field("price"), _field("other_price"))).root.kind == "boolean"


@pytest.mark.parametrize("op", ["and", "or"])
def test_boolean_combiners_reject_numeric_and_accept_boolean(op: str) -> None:
    condition = _node("gt", _field("price"), _field("other_price"))
    assert _validate(_node(op, condition, condition)).inferred_unit == "boolean"
    with pytest.raises(ExpressionValidationError, match="boolean"):
        _validate(_node(op, condition, _field("price")))


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        (_field("unknown"), "unknown_field"),
        (_node("add", _field("price"), _field("volume")), "incompatible_units"),
        (_node("where", _node("gt", _field("ratio"), _constant(1)), _field("price"), _field("volume"), missing_condition="propagate"), "incompatible_units"),
        (_node("log", _field("price"), nonpositive="missing"), "dimensionless_required"),
        (_node("add", _field("price")), "arity"),
        ({"op": "field", "args": [], "params": {"name": "price"}, "code": "x"}, "node_keys"),
        ({"op": "python_eval", "args": [], "params": {"code": "future()"}}, "unsupported_operation"),
        ("price / future()", "node_type"),
        (_node("lag", _field("price"), periods=-1, missing="propagate"), "negative_lookback"),
        (_node("delta", _field("price"), periods=0, missing="propagate"), "positive_lookback"),
        (_node("rolling_mean", _field("price"), window=3, min_periods=4, missing="skip"), "min_periods"),
        (_node("rolling_mean", _field("price"), window=3, min_periods=1, center=True, missing="skip"), "unknown_params"),
        (_node("rolling_std", _field("price"), window=3, min_periods=1, ddof=True, missing="skip"), "parameter_type"),
        (_node("rolling_quantile", _field("price"), window=3, min_periods=1, q=1.5, interpolation="linear", missing="skip"), "parameter_range"),
        (_node("ewm_mean", _field("price"), span=3, alpha=0.5, adjust=False, ignore_na=True, min_periods=1), "ewm_decay"),
        (_node("ewm_std", _field("price"), span=3, adjust=False, ignore_na=True, min_periods=1), "missing_params"),
        (_node("weighted_sum", _field("price"), _field("other_price"), weights=[1.0], missing="require_all"), "weights"),
        (_node("weighted_sum", _field("price"), _field("other_price"), weights=[1.0, math.inf], missing="require_all"), "finite"),
        (_node("asof_value", _field("event"), observed_at_field="missing", available_at_field="available_at", no_eligible="missing"), "unknown_metadata_field"),
        (_constant(True), "parameter_type"),
        (_constant(math.nan), "finite"),
        (_node("rolling_mean", _field("price"), window=-2, min_periods=1, missing="skip"), "positive_window"),
        (_node("lag", _field("price"), periods=1, missing="propagate", code="future()"), "unknown_params"),
    ],
)
def test_invalid_structure_units_future_windows_and_params_are_rejected(
    expression: object, code: str
) -> None:
    with pytest.raises(ExpressionValidationError) as caught:
        _validate(expression)
    assert caught.value.code == code


def test_cyclic_python_mapping_is_rejected_without_recursing_forever() -> None:
    cyclic: dict[str, object] = {"op": "abs", "args": [], "params": {}}
    cyclic["args"] = [cyclic]
    with pytest.raises(ExpressionValidationError) as caught:
        _validate(cyclic)
    assert caught.value.code == "cyclic_expression"

    weights: list[object] = [1.0]
    weights.append(weights)
    with pytest.raises(ExpressionValidationError) as nested:
        _validate(
            _node(
                "weighted_sum",
                _field("price"),
                _field("other_price"),
                weights=weights,
                missing="require_all",
            )
        )
    assert nested.value.code == "parameter_type"


def test_exact_integer_relations_do_not_round_through_float() -> None:
    with pytest.raises(ExpressionValidationError) as literal:
        _validate(
            _node(
                "rolling_mean",
                _field("price"),
                window=2**53,
                min_periods=2**53 + 1,
            )
        )
    assert literal.value.code == "min_periods"

    expression = _node(
        "rolling_mean",
        _field("price"),
        window={"bind": "window"},
        min_periods={"bind": "minimum"},
    )
    schema = {
        "window": {"type": "integer", "unit": "bars"},
        "minimum": {"type": "integer", "unit": "bars"},
    }
    sets = [
        {
            "parameter_set_id": "p-exact",
            "bindings": {"window": 2**53, "minimum": 2**53 + 1},
        }
    ]
    with pytest.raises(ExpressionValidationError) as bound:
        _validate(expression, schema=schema, sets=sets)
    assert bound.value.code == "min_periods"


def test_unrepresentable_integer_magnitude_is_a_typed_error_not_overflow() -> None:
    huge = 10**10000
    with pytest.raises(ExpressionValidationError) as literal:
        _validate(_constant(huge))
    assert literal.value.code == "finite"

    expression = _constant({"bind": "value"})
    schema = {"value": {"type": "number", "unit": "dimensionless"}}
    sets = [{"parameter_set_id": "p-huge", "bindings": {"value": huge}}]
    with pytest.raises(ExpressionValidationError) as bound:
        _validate(expression, schema=schema, sets=sets)
    assert bound.value.code == "binding_finite"


def test_inferred_unit_products_round_trip_through_small_unit_grammar() -> None:
    covariance = _validate(
        _node(
            "rolling_cov",
            _field("price"),
            _field("other_price"),
            window=3,
            min_periods=2,
            ddof=1,
            missing="pairwise",
        )
    ).root.unit
    inverse = _validate(
        _node("safe_divide", _constant(1), _field("price"))
    ).root.unit
    compound = _validate(
        _node("multiply", _node("multiply", _field("price"), _field("price")), _field("volume"))
    ).root.unit
    assert covariance.display == "USD^2/share^2"
    assert inverse.display == "share/USD"
    assert compound.display == "USD^2/share"
    for unit in (covariance, inverse, compound):
        assert Unit.parse(unit.display, path="test.unit") == unit


@pytest.mark.parametrize(
    "unit",
    ["USD^0/share", "USD^-2", "USD^x", "USD^^2", "USD^" + "9" * 2000],
)
def test_invalid_unit_exponents_are_typed_rejections(unit: str) -> None:
    with pytest.raises(ExpressionValidationError) as caught:
        Unit.parse(unit, path="test.unit")
    assert caught.value.code == "unit"


def test_raised_depth_limit_and_deep_parameter_shapes_never_leak_recursion_error() -> None:
    expression: object = _field("price")
    for _ in range(1200):
        expression = _node("abs", expression)
    with pytest.raises(ExpressionLimitError) as configured:
        _validate(expression, limits=ExpressionLimits(max_depth=5000, max_nodes=5000))
    assert configured.value.code == "max_depth_config"

    moderately_deep: object = _field("price")
    for _ in range(80):
        moderately_deep = _node("abs", moderately_deep)
    with pytest.raises(ExpressionLimitError) as structural:
        _validate(moderately_deep)
    assert structural.value.code == "max_depth"

    nested: object = 1.0
    for _ in range(2000):
        nested = [nested]
    with pytest.raises(ExpressionValidationError) as params:
        _validate(
            _node(
                "weighted_sum",
                _field("price"),
                _field("other_price"),
                weights=[1.0, nested],
                missing="require_all",
            )
        )
    assert params.value.code == "parameter_type"


def test_asof_parser_preserves_explicit_time_and_revision_fields_without_pit_claim() -> None:
    compiled = _validate(
        _node(
            "asof_value",
            _field("event"),
            observed_at_field="timestamp",
            available_at_field="available_at",
            revision_field="revision_id",
            no_eligible="missing",
        )
    )
    assert compiled.root.time_fields == ("available_at", "revision_id", "timestamp")
    assert compiled.point_in_time_proven is False


def test_historical_alignment_requires_direct_field_but_allows_outer_arithmetic() -> None:
    invalid = _node(
        "asof_value",
        _node("abs", _field("event")),
        observed_at_field="timestamp",
        available_at_field="available_at",
        revision_field="revision_id",
        no_eligible="missing",
    )
    with pytest.raises(ExpressionValidationError, match="apply arithmetic outside alignment"):
        validate_expression(invalid, dataset=_dataset(), parameter_schema={}, parameter_sets=({"parameter_set_id": "p0", "bindings": {}},))

    valid = _node(
        "abs",
        _node("asof_value", _field("event"), observed_at_field="timestamp", available_at_field="available_at", revision_field="revision_id", no_eligible="missing"),
    )
    assert validate_expression(valid, dataset=_dataset(), parameter_schema={}, parameter_sets=({"parameter_set_id": "p0", "bindings": {}},)).root.op == "abs"


def test_parameter_bindings_are_typed_finite_exact_and_not_cartesian_expanded() -> None:
    expression = _node(
        "rolling_mean",
        _field("price"),
        window={"bind": "window"},
        min_periods={"bind": "window"},
    )
    schema = {"window": {"type": "integer", "unit": "bars", "minimum": 1}}
    sets = [
        {"parameter_set_id": "p2", "bindings": {"window": 2}},
        {"parameter_set_id": "p4", "bindings": {"window": 4}},
    ]
    compiled = _validate(expression, schema=schema, sets=sets)
    assert isinstance(dict(compiled.root.params)["window"], ParameterRef)
    assert [item.bindings for item in compiled.parameter_sets] == [(('window', 2),), (('window', 4),)]
    assert compiled.root.resolved_params(compiled.parameter_sets[0])["window"] == 2
    assert compiled.root.resolved_params(compiled.parameter_sets[1])["min_periods"] == 4
    assert len(compiled.parameter_sets) == 2


def test_boolean_string_and_ewm_parameters_are_validated_in_every_explicit_set() -> None:
    expression = _node(
        "ewm_std",
        _field("price"),
        alpha={"bind": "alpha"},
        adjust={"bind": "adjust"},
        ignore_na={"bind": "ignore_na"},
        min_periods={"bind": "min_periods"},
        bias={"bind": "bias"},
    )
    schema = {
        "alpha": {"type": "number", "unit": "dimensionless", "minimum": 0.01, "maximum": 1.0},
        "adjust": {"type": "boolean", "unit": "dimensionless"},
        "ignore_na": {"type": "boolean", "unit": "dimensionless"},
        "min_periods": {"type": "integer", "unit": "bars", "minimum": 0},
        "bias": {"type": "boolean", "unit": "dimensionless"},
    }
    sets = [
        {
            "parameter_set_id": "p-ewm",
            "bindings": {
                "alpha": 0.5,
                "adjust": False,
                "ignore_na": True,
                "min_periods": 1,
                "bias": False,
            },
        }
    ]
    compiled = _validate(expression, schema=schema, sets=sets)
    assert compiled.inferred_unit == "USD/share"
    assert set(compiled.parameter_names) == set(schema)


@pytest.mark.parametrize(
    ("schema", "sets", "code"),
    [
        ({"window": {"type": "integer", "unit": "bars", "minimum": 1}}, [{"parameter_set_id": "p", "bindings": {}}], "missing_bindings"),
        ({"window": {"type": "integer", "unit": "bars", "minimum": 1}}, [{"parameter_set_id": "p", "bindings": {"window": 2, "extra": 1}}], "extra_bindings"),
        ({"window": {"type": "integer", "unit": "bars", "minimum": 1}}, [{"parameter_set_id": "p", "bindings": {"window": True}}], "binding_type"),
        ({"window": {"type": "integer", "unit": "bars", "minimum": 1}}, [{"parameter_set_id": "p", "bindings": {"window": 0}}], "binding_range"),
        ({"window": {"type": "number", "unit": "bars"}}, [{"parameter_set_id": "p", "bindings": {"window": math.nan}}], "binding_finite"),
        ({"window": {"type": "integer", "unit": "bars", "minimum": 1}}, [{"parameter_set_id": "p", "bindings": {"window": 2}}, {"parameter_set_id": "p", "bindings": {"window": 3}}], "duplicate_parameter_set_id"),
        ({"window": {"type": "integer", "unit": "bars", "minimum": 1}, "unused": {"type": "number", "unit": "dimensionless"}}, [{"parameter_set_id": "p", "bindings": {"window": 2, "unused": 1.0}}], "parameter_schema_mismatch"),
        ({"window": {"type": "integer", "unit": "bars", "minimum": 1}}, [], "parameter_sets"),
    ],
)
def test_invalid_parameter_schemas_and_sets_are_rejected(
    schema: dict[str, object], sets: list[dict[str, object]], code: str
) -> None:
    expression = _node("rolling_mean", _field("price"), window={"bind": "window"}, min_periods=1)
    with pytest.raises(ExpressionValidationError) as caught:
        _validate(expression, schema=schema, sets=sets)
    assert caught.value.code == code


def test_constant_binding_unit_must_match_parameter_schema_unit() -> None:
    expression = _constant({"bind": "threshold"}, "decimal_return")
    schema = {"threshold": {"type": "number", "unit": "dimensionless"}}
    sets = [{"parameter_set_id": "p", "bindings": {"threshold": 0.1}}]
    with pytest.raises(ExpressionValidationError) as caught:
        _validate(expression, schema=schema, sets=sets)
    assert caught.value.code == "binding_unit"


def test_structural_limits_reject_but_batch_limits_split_without_dropping_sets() -> None:
    expression = _node("abs", _node("abs", _node("abs", _field("price"))))
    with pytest.raises(ExpressionLimitError) as depth:
        _validate(expression, limits=ExpressionLimits(max_depth=2))
    assert depth.value.code == "max_depth"
    with pytest.raises(ExpressionLimitError) as nodes:
        _validate(expression, limits=ExpressionLimits(max_nodes=3))
    assert nodes.value.code == "max_nodes"

    bound = _node("lag", _field("price"), periods={"bind": "periods"}, missing="propagate")
    schema = {"periods": {"type": "integer", "unit": "bars", "minimum": 0}}
    sets = [
        {"parameter_set_id": f"p{index}", "bindings": {"periods": index}}
        for index in range(7)
    ]
    compiled = _validate(
        bound,
        schema=schema,
        sets=sets,
        dataset=_dataset(rows=100),
        limits=ExpressionLimits(
            max_parameter_sets_per_batch=2,
            max_estimated_cells_per_batch=500,
            max_estimated_bytes_per_batch=8000,
        ),
    )
    flattened = [item for batch in compiled.batch_plan.batches for item in batch.parameter_set_ids]
    assert flattened == [f"p{index}" for index in range(7)]
    assert compiled.batch_plan.split_required is True
    assert compiled.batch_plan.guidance


def test_one_large_parameter_set_returns_row_split_guidance_instead_of_scope_cap() -> None:
    compiled = _validate(
        _node("rolling_mean", _field("price"), window=2, min_periods=1),
        dataset=_dataset(rows=1000),
        limits=ExpressionLimits(
            max_estimated_cells_per_batch=100,
            max_estimated_bytes_per_batch=1600,
        ),
    )
    assert compiled.batch_plan.requires_row_partition is True
    assert 0 < compiled.batch_plan.max_rows_per_batch < 1000
    assert compiled.batch_plan.parameter_set_ids == ("p0",)
    assert any("rolling overlap" in item and "never reset history" in item for item in compiled.batch_plan.guidance)


def test_parameter_schema_limit_is_configurable_and_not_a_trial_count_limit() -> None:
    expression = _constant({"bind": "x"})
    schema = {"x": {"type": "number", "unit": "dimensionless"}}
    sets = [{"parameter_set_id": f"p{index}", "bindings": {"x": float(index)}} for index in range(20)]
    compiled = _validate(
        expression,
        schema=schema,
        sets=sets,
        limits=ExpressionLimits(max_parameters=1, max_parameter_sets_per_batch=3),
    )
    assert len(compiled.parameter_sets) == 20
    with pytest.raises(ExpressionLimitError) as caught:
        _validate(expression, schema=schema | {"y": {"type": "number", "unit": "dimensionless"}}, sets=[], limits=ExpressionLimits(max_parameters=1))
    assert caught.value.code == "max_parameters"


def test_example_limits_match_public_defaults_and_record_fixture_measurement() -> None:
    example = json.loads(LIMITS_EXAMPLE.read_text(encoding="utf-8"))
    limits = ExpressionLimits(**example["expression_limits"])
    assert limits == ExpressionLimits()
    measurement = example["measurement"]
    assert measurement["maximum_nodes"] == 10
    assert measurement["maximum_depth"] == 5
    assert measurement["maximum_estimated_cells"] == 120
    assert "not memory or runtime guarantees" in measurement["note"]
    assert "no overall trial-count cap" in measurement["note"].lower()
    assert "must not reset history" in example["split_boundary"]
