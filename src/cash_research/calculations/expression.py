"""Validation and binding for the approved structured factor-expression language.

This module compiles JSON-shaped ``{op, args, params}`` nodes.  It never evaluates
strings or numerical data; execution and time alignment belong to later tasks.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Mapping, TypeAlias


Scalar: TypeAlias = int | float | str | bool
ValueKind: TypeAlias = Literal["numeric", "boolean"]

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
_UNIT_TOKEN = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)(?:\^([1-9][0-9]*))?$")
_HARD_MAX_DEPTH = 256
_OPERATIONS = frozenset(
    {
        "field",
        "constant",
        "add",
        "subtract",
        "multiply",
        "safe_divide",
        "abs",
        "sign",
        "log",
        "clip",
        "gt",
        "gte",
        "lt",
        "lte",
        "and",
        "or",
        "where",
        "weighted_sum",
        "lag",
        "delta",
        "pct_return",
        "log_return",
        "rolling_sum",
        "rolling_mean",
        "rolling_median",
        "rolling_min",
        "rolling_max",
        "rolling_std",
        "rolling_quantile",
        "rolling_rank",
        "rolling_corr",
        "rolling_cov",
        "ewm_mean",
        "ewm_std",
        "asof_value",
        "event_age",
    }
)
_ALIASES = {
    "1": "dimensionless",
    "unitless": "dimensionless",
    "ratio": "dimensionless",
    "shares": "share",
}
_ROLLING_SIMPLE = {
    "rolling_sum",
    "rolling_mean",
    "rolling_median",
    "rolling_min",
    "rolling_max",
}
_COMPARISONS = {"gt", "gte", "lt", "lte"}


class ExpressionValidationError(ValueError):
    """A stable, path-specific expression contract error."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


class ExpressionLimitError(ExpressionValidationError):
    """A structural resource limit that cannot be repaired by parameter batching."""


@dataclass(frozen=True)
class Unit:
    """A small deterministic unit product used only for validation and handoff."""

    factors: tuple[tuple[str, int], ...]

    @classmethod
    def parse(cls, value: object, *, path: str) -> "Unit":
        if not isinstance(value, str) or not value:
            _fail("unit", path, "unit must be a non-empty string")
        normalized = value.strip().replace(" ", "_")
        canonical = _ALIASES.get(normalized, normalized)
        if len(canonical) > 1024:
            _fail("unit", path, "unit text exceeds the parser safety limit")
        if canonical == "dimensionless":
            return cls(())
        if canonical.count("/") > 1:
            _fail("unit", path, "unit may contain at most one division separator")
        numerator, *denominator = canonical.split("/")
        factors: dict[str, int] = {}
        for token in numerator.split("*"):
            _add_unit_token(factors, token, 1, path)
        if denominator:
            for token in denominator[0].split("*"):
                _add_unit_token(factors, token, -1, path)
        return cls(tuple(sorted((name, power) for name, power in factors.items() if power)))

    @property
    def display(self) -> str:
        if not self.factors:
            return "dimensionless"
        positive: list[str] = []
        negative: list[str] = []
        for name, power in self.factors:
            target = positive if power > 0 else negative
            amount = abs(power)
            target.append(name if amount == 1 else f"{name}^{amount}")
        numerator = "*".join(positive) or "1"
        return numerator if not negative else f"{numerator}/{'*'.join(negative)}"

    def multiply(self, other: "Unit") -> "Unit":
        return self._combine(other, 1)

    def divide(self, other: "Unit") -> "Unit":
        return self._combine(other, -1)

    def _combine(self, other: "Unit", direction: int) -> "Unit":
        factors = dict(self.factors)
        for name, power in other.factors:
            factors[name] = factors.get(name, 0) + direction * power
        return Unit(tuple(sorted((name, power) for name, power in factors.items() if power)))


@dataclass(frozen=True)
class ParameterRef:
    name: str


BoundValue: TypeAlias = Scalar | ParameterRef | tuple[object, ...]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    unit: Unit
    observed_at_field: str
    available_at_field: str
    revision_field: str | None = None


@dataclass(frozen=True)
class DatasetSpec:
    fields: tuple[FieldSpec, ...]
    metadata_fields: tuple[str, ...]
    bar_interval: str
    row_count: int
    point_in_time_status: str | None

    def field(self, name: str) -> FieldSpec | None:
        return next((item for item in self.fields if item.name == name), None)


@dataclass(frozen=True)
class BoundNode:
    op: str
    args: tuple["BoundNode", ...]
    params: tuple[tuple[str, BoundValue], ...]
    unit: Unit
    kind: ValueKind
    referenced_fields: tuple[str, ...]
    time_fields: tuple[str, ...]

    def parameter(self, name: str) -> BoundValue | None:
        return dict(self.params).get(name)

    def resolved_params(self, parameter_set: "BoundParameterSet") -> dict[str, object]:
        """Resolve this node's already-validated parameter references for one explicit set."""

        return {
            name: _resolve_bound_value(value, parameter_set)
            for name, value in self.params
        }


@dataclass(frozen=True)
class BoundParameterSet:
    parameter_set_id: str
    bindings: tuple[tuple[str, Scalar], ...]

    def value(self, name: str) -> Scalar:
        return dict(self.bindings)[name]


@dataclass(frozen=True)
class ExpressionLimits:
    max_depth: int = 64
    max_nodes: int = 4096
    max_parameters: int = 256
    max_parameter_sets_per_batch: int = 128
    max_estimated_cells_per_batch: int = 5_000_000
    max_estimated_bytes_per_batch: int = 160_000_000
    estimated_bytes_per_cell: int = 16

    def validate(self) -> None:
        for name, value in self.__dict__.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                _fail("limits", f"limits.{name}", "resource limits must be positive integers")
        if self.max_depth > _HARD_MAX_DEPTH:
            raise ExpressionLimitError(
                "max_depth_config",
                "limits.max_depth",
                f"configured depth exceeds the parser safety ceiling {_HARD_MAX_DEPTH}",
            )


@dataclass(frozen=True)
class ResourceEstimate:
    node_count: int
    depth: int
    row_count: int
    parameter_set_count: int
    estimated_cells: int
    estimated_bytes: int
    estimate_basis: str


@dataclass(frozen=True)
class Batch:
    parameter_set_ids: tuple[str, ...]
    estimated_cells: int
    estimated_bytes: int


@dataclass(frozen=True)
class BatchPlan:
    parameter_set_ids: tuple[str, ...]
    batches: tuple[Batch, ...]
    split_required: bool
    requires_row_partition: bool
    max_rows_per_batch: int | None
    guidance: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedExpression:
    root: BoundNode
    dataset: DatasetSpec
    parameter_sets: tuple[BoundParameterSet, ...]
    parameter_names: tuple[str, ...]
    referenced_fields: tuple[str, ...]
    time_fields: tuple[str, ...]
    point_in_time_proven: bool
    resource_estimate: ResourceEstimate
    batch_plan: BatchPlan

    @property
    def inferred_unit(self) -> str:
        return self.root.unit.display


@dataclass(frozen=True)
class _ParameterSpec:
    name: str
    kind: Literal["integer", "number", "boolean", "string"]
    unit: Unit
    minimum: int | float | None
    maximum: int | float | None
    enum: tuple[Scalar, ...] | None


def validate_expression(
    expression: object,
    *,
    dataset: Mapping[str, object],
    parameter_schema: Mapping[str, object],
    parameter_sets: list[object] | tuple[object, ...],
    limits: ExpressionLimits | None = None,
) -> ValidatedExpression:
    """Validate and bind one expression template without executing numerical data."""

    active_limits = limits or ExpressionLimits()
    active_limits.validate()
    dataset_spec = _dataset_spec(dataset)
    schema = _parameter_specs(parameter_schema, active_limits)
    bound_sets = _parameter_sets(parameter_sets, schema)
    compiler = _Compiler(dataset_spec, schema, bound_sets, active_limits)
    root = compiler.compile(expression)
    used = tuple(sorted(compiler.parameter_refs))
    declared = tuple(sorted(schema))
    if used != declared:
        _fail(
            "parameter_schema_mismatch",
            "parameter_schema",
            "declared parameters must exactly equal expression bindings",
        )
    estimate, plan = _resource_plan(
        node_count=compiler.node_count,
        depth=compiler.max_depth_seen,
        row_count=dataset_spec.row_count,
        parameter_sets=bound_sets,
        limits=active_limits,
    )
    return ValidatedExpression(
        root=root,
        dataset=dataset_spec,
        parameter_sets=bound_sets,
        parameter_names=used,
        referenced_fields=root.referenced_fields,
        time_fields=root.time_fields,
        point_in_time_proven=False,
        resource_estimate=estimate,
        batch_plan=plan,
    )


class _Compiler:
    def __init__(
        self,
        dataset: DatasetSpec,
        schema: dict[str, _ParameterSpec],
        parameter_sets: tuple[BoundParameterSet, ...],
        limits: ExpressionLimits,
    ) -> None:
        self.dataset = dataset
        self.schema = schema
        self.parameter_sets = parameter_sets
        self.limits = limits
        self.node_count = 0
        self.max_depth_seen = 0
        self.parameter_refs: set[str] = set()
        self._active: set[int] = set()

    def compile(self, expression: object) -> BoundNode:
        return self._compile(expression, path="expression", depth=1)

    def _compile(self, value: object, *, path: str, depth: int) -> BoundNode:
        if not isinstance(value, dict):
            _fail("node_type", path, "expression nodes must be objects, never code strings")
        identity = id(value)
        if identity in self._active:
            _fail("cyclic_expression", path, "expression mappings cannot contain cycles")
        self.node_count += 1
        self.max_depth_seen = max(self.max_depth_seen, depth)
        if self.node_count > self.limits.max_nodes:
            raise ExpressionLimitError("max_nodes", path, "expression exceeds the configured structural node limit")
        if depth > self.limits.max_depth:
            raise ExpressionLimitError("max_depth", path, "expression exceeds the configured structural depth limit")
        if set(value) != {"op", "args", "params"}:
            _fail("node_keys", path, "each node must contain exactly op, args, and params")
        op = value["op"]
        args = value["args"]
        params = value["params"]
        if not isinstance(op, str) or op not in _OPERATIONS:
            _fail("unsupported_operation", f"{path}.op", "operation is outside the approved expression language")
        if not isinstance(args, list) or not isinstance(params, dict):
            _fail("node_shape", path, "args must be a list and params must be an object")
        self._active.add(identity)
        try:
            children = tuple(
                self._compile(child, path=f"{path}.args[{index}]", depth=depth + 1)
                for index, child in enumerate(args)
            )
        finally:
            self._active.remove(identity)
        return self._bind_node(op, children, params, path)

    def _bind_node(
        self,
        op: str,
        args: tuple[BoundNode, ...],
        raw_params: dict[str, object],
        path: str,
    ) -> BoundNode:
        fields = _merge_names(*(child.referenced_fields for child in args))
        times = _merge_names(*(child.time_fields for child in args))
        if op == "field":
            _arity(args, 0, path)
            params = self._params(raw_params, {"name"}, path)
            name = params["name"]
            if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
                _fail("field_name", f"{path}.params.name", "field name must be a safe identifier")
            field = self.dataset.field(name)
            if field is None:
                _fail("unknown_field", f"{path}.params.name", "field is absent from the current dataset snapshot")
            return BoundNode(op, args, _freeze_params(params), field.unit, "numeric", (name,), tuple(sorted({field.observed_at_field, field.available_at_field})))
        if op == "constant":
            _arity(args, 0, path)
            params = self._params(raw_params, {"value", "unit"}, path)
            unit = Unit.parse(params["unit"], path=f"{path}.params.unit")
            params["value"] = self._bound_value(params["value"], f"{path}.params.value")
            self._expect_number(params["value"], f"{path}.params.value", unit=unit)
            return BoundNode(op, args, _freeze_params(params), unit, "numeric", (), ())

        if op in {"add", "subtract", "multiply", "safe_divide"}:
            _arity(args, 2, path)
            self._params(raw_params, set(), path)
            _numeric(args, path)
            if op in {"add", "subtract"}:
                _compatible(args[0].unit, args[1].unit, path)
                unit = args[0].unit
            elif op == "multiply":
                unit = args[0].unit.multiply(args[1].unit)
            else:
                unit = args[0].unit.divide(args[1].unit)
            return _bound(op, args, {}, unit, "numeric", fields, times)

        if op in {"abs", "sign", "log"}:
            _arity(args, 1, path)
            _numeric(args, path)
            if op == "log":
                params = self._params(raw_params, {"nonpositive"}, path)
                params["nonpositive"] = self._bound_value(
                    params["nonpositive"], f"{path}.params.nonpositive"
                )
                self._expect_mode(
                    params["nonpositive"], {"missing"}, f"{path}.params.nonpositive"
                )
                if args[0].unit != Unit(()):
                    _fail("dimensionless_required", path, "log accepts only dimensionless values")
                unit = Unit(())
            else:
                params = self._params(raw_params, set(), path)
                unit = Unit.parse("direction", path=path) if op == "sign" else args[0].unit
            return _bound(op, args, params, unit, "numeric", fields, times)

        if op == "clip":
            _arity(args, 1, path)
            _numeric(args, path)
            params = self._params(raw_params, {"lower", "upper", "unit", "missing"}, path)
            unit = Unit.parse(params["unit"], path=f"{path}.params.unit")
            _compatible(args[0].unit, unit, path)
            for name in ("lower", "upper"):
                params[name] = self._bound_value(params[name], f"{path}.params.{name}")
                self._expect_number(params[name], f"{path}.params.{name}", unit=unit)
            self._validate_relation(params["lower"], params["upper"], lambda left, right: left <= right, "parameter_range", path)
            params["missing"] = self._bound_value(params["missing"], f"{path}.params.missing")
            self._expect_mode(params["missing"], {"propagate"}, f"{path}.params.missing")
            return _bound(op, args, params, unit, "numeric", fields, times)

        if op in _COMPARISONS:
            _arity(args, 2, path)
            self._params(raw_params, set(), path)
            _numeric(args, path)
            _compatible(args[0].unit, args[1].unit, path)
            return _bound(op, args, {}, Unit.parse("boolean", path=path), "boolean", fields, times)

        if op in {"and", "or"}:
            _arity(args, 2, path)
            self._params(raw_params, set(), path)
            _boolean(args, path)
            return _bound(op, args, {}, Unit.parse("boolean", path=path), "boolean", fields, times)

        if op == "where":
            _arity(args, 3, path)
            params = self._params(raw_params, {"missing_condition"}, path, defaults={"missing_condition": "propagate"})
            if args[0].kind != "boolean":
                _fail("boolean_required", f"{path}.args[0]", "where condition must be boolean")
            _numeric(args[1:], path)
            _compatible(args[1].unit, args[2].unit, path)
            params["missing_condition"] = self._bound_value(
                params["missing_condition"], f"{path}.params.missing_condition"
            )
            self._expect_mode(
                params["missing_condition"],
                {"propagate", "false", "true"},
                f"{path}.params.missing_condition",
            )
            return _bound(op, args, params, args[1].unit, "numeric", fields, times)

        if op == "weighted_sum":
            if not args:
                _fail("arity", path, "weighted_sum requires at least one argument")
            _numeric(args, path)
            params = self._params(raw_params, {"weights", "missing"}, path)
            weights = params["weights"]
            if not isinstance(weights, list) or len(weights) != len(args):
                _fail("weights", f"{path}.params.weights", "weights must match argument count")
            normalized_weights: list[BoundValue] = []
            for index, value in enumerate(weights):
                item = self._bound_value(value, f"{path}.params.weights[{index}]")
                self._expect_number(item, f"{path}.params.weights[{index}]", unit=Unit(()))
                normalized_weights.append(item)
            params["weights"] = tuple(normalized_weights)
            params["missing"] = self._bound_value(params["missing"], f"{path}.params.missing")
            self._expect_mode(params["missing"], {"require_all", "skip"}, f"{path}.params.missing")
            for child in args[1:]:
                _compatible(args[0].unit, child.unit, path)
            return _bound(op, args, params, args[0].unit, "numeric", fields, times)

        if op in {"lag", "delta", "pct_return", "log_return"}:
            _arity(args, 1, path)
            _numeric(args, path)
            params = self._params(raw_params, {"periods", "missing"}, path, defaults={"missing": "propagate"})
            params["periods"] = self._bound_value(params["periods"], f"{path}.params.periods")
            self._expect_integer(params["periods"], f"{path}.params.periods", unit="bars")
            minimum = 0 if op == "lag" else 1
            self._validate_minimum(params["periods"], minimum, "negative_lookback" if op == "lag" else "positive_lookback", path)
            params["missing"] = self._bound_value(params["missing"], f"{path}.params.missing")
            self._expect_mode(params["missing"], {"propagate"}, f"{path}.params.missing")
            unit = Unit.parse("decimal_return", path=path) if op in {"pct_return", "log_return"} else args[0].unit
            return _bound(op, args, params, unit, "numeric", fields, times)

        if op in _ROLLING_SIMPLE | {"rolling_std", "rolling_quantile", "rolling_rank"}:
            _arity(args, 1, path)
            _numeric(args, path)
            required = {"window", "min_periods", "missing"}
            defaults: dict[str, object] = (
                {"missing": "require_min_periods"}
                if op == "rolling_mean"
                else {}
            )
            if op == "rolling_std":
                required.add("ddof")
            elif op == "rolling_quantile":
                required.update({"q", "interpolation"})
            elif op == "rolling_rank":
                required.update({"method", "ascending", "pct", "na_option"})
            params = self._params(raw_params, required, path, defaults=defaults)
            self._rolling_common(params, path)
            if op == "rolling_std":
                params["ddof"] = self._bound_value(params["ddof"], f"{path}.params.ddof")
                self._expect_integer(params["ddof"], f"{path}.params.ddof", unit="dimensionless")
                self._validate_minimum(params["ddof"], 0, "parameter_range", path)
            if op == "rolling_quantile":
                params["q"] = self._bound_value(params["q"], f"{path}.params.q")
                self._expect_number(params["q"], f"{path}.params.q", unit=Unit(()))
                self._validate_range(params["q"], 0, 1, path)
                params["interpolation"] = self._bound_value(
                    params["interpolation"], f"{path}.params.interpolation"
                )
                self._expect_mode(
                    params["interpolation"],
                    {"linear", "lower", "higher", "midpoint", "nearest"},
                    f"{path}.params.interpolation",
                )
            if op == "rolling_rank":
                for name, allowed_values in (
                    ("method", {"average", "min", "max", "first", "dense"}),
                    ("na_option", {"keep", "top", "bottom"}),
                ):
                    params[name] = self._bound_value(params[name], f"{path}.params.{name}")
                    self._expect_mode(params[name], allowed_values, f"{path}.params.{name}")
                for name in ("ascending", "pct"):
                    params[name] = self._bound_value(params[name], f"{path}.params.{name}")
                    self._expect_boolean(params[name], f"{path}.params.{name}")
            unit = Unit(()) if op == "rolling_rank" else args[0].unit
            return _bound(op, args, params, unit, "numeric", fields, times)

        if op in {"rolling_corr", "rolling_cov"}:
            _arity(args, 2, path)
            _numeric(args, path)
            required = {"window", "min_periods", "missing"}
            if op == "rolling_cov":
                required.add("ddof")
            params = self._params(raw_params, required, path)
            self._rolling_common(params, path, allowed_missing={"pairwise"})
            if op == "rolling_cov":
                params["ddof"] = self._bound_value(params["ddof"], f"{path}.params.ddof")
                self._expect_integer(params["ddof"], f"{path}.params.ddof", unit="dimensionless")
                self._validate_minimum(params["ddof"], 0, "parameter_range", path)
            unit = Unit(()) if op == "rolling_corr" else args[0].unit.multiply(args[1].unit)
            return _bound(op, args, params, unit, "numeric", fields, times)

        if op in {"ewm_mean", "ewm_std"}:
            _arity(args, 1, path)
            _numeric(args, path)
            allowed = {"span", "alpha", "adjust", "ignore_na", "min_periods"}
            if op == "ewm_std":
                allowed.add("bias")
            params = self._params(raw_params, allowed, path, optional={"span", "alpha"})
            has_span = "span" in raw_params
            has_alpha = "alpha" in raw_params
            if has_span == has_alpha:
                _fail("ewm_decay", path, "EWM requires exactly one of span or alpha")
            decay = "span" if has_span else "alpha"
            params[decay] = self._bound_value(params[decay], f"{path}.params.{decay}")
            self._expect_number(params[decay], f"{path}.params.{decay}", unit=Unit(()))
            if decay == "span":
                self._validate_minimum(params[decay], 1, "parameter_range", path)
            else:
                self._validate_range(params[decay], 0, 1, path, lower_open=True)
            for name in ("adjust", "ignore_na"):
                params[name] = self._bound_value(params[name], f"{path}.params.{name}")
                self._expect_boolean(params[name], f"{path}.params.{name}")
            params["min_periods"] = self._bound_value(
                params["min_periods"], f"{path}.params.min_periods"
            )
            self._expect_integer(
                params["min_periods"], f"{path}.params.min_periods", unit="bars"
            )
            self._validate_minimum(params["min_periods"], 0, "parameter_range", path)
            if op == "ewm_std":
                params["bias"] = self._bound_value(params["bias"], f"{path}.params.bias")
                self._expect_boolean(params["bias"], f"{path}.params.bias")
            return _bound(op, args, params, args[0].unit, "numeric", fields, times)

        if op in {"asof_value", "event_age"}:
            _arity(args, 1, path)
            _numeric(args, path)
            if args[0].op != "field":
                _fail(
                    "asof_direct_field",
                    f"{path}.args[0]",
                    "historical alignment requires a direct field; apply arithmetic outside alignment",
                )
            allowed = {"observed_at_field", "available_at_field", "revision_field", "no_eligible"}
            defaults = {"no_eligible": "missing"}
            if op == "event_age":
                allowed.add("output_unit")
            params = self._params(
                raw_params,
                allowed,
                path,
                defaults=defaults,
                optional={"revision_field"},
            )
            if len(args[0].referenced_fields) != 1:
                _fail(
                    "asof_field",
                    f"{path}.args[0]",
                    "historical alignment requires one declared source field",
                )
            source_field = self.dataset.field(args[0].referenced_fields[0])
            assert source_field is not None
            explicit_times: list[str] = []
            for name in ("observed_at_field", "available_at_field"):
                field_name = params[name]
                self._metadata_field(field_name, f"{path}.params.{name}")
                explicit_times.append(str(field_name))
            if (
                params["observed_at_field"] != source_field.observed_at_field
                or params["available_at_field"] != source_field.available_at_field
            ):
                _fail(
                    "time_metadata_mismatch",
                    path,
                    "historical alignment fields must match the source field metadata",
                )
            if "revision_field" in params:
                self._metadata_field(params["revision_field"], f"{path}.params.revision_field")
                explicit_times.append(str(params["revision_field"]))
            if params.get("revision_field") != source_field.revision_field:
                _fail(
                    "time_metadata_mismatch",
                    path,
                    "revision-aware source field requires its declared revision metadata",
                )
            params["no_eligible"] = self._bound_value(
                params["no_eligible"], f"{path}.params.no_eligible"
            )
            self._expect_mode(
                params["no_eligible"], {"missing", "reject"}, f"{path}.params.no_eligible"
            )
            if op == "event_age":
                _mode(params["output_unit"], {"bars", "seconds", "days"}, f"{path}.params.output_unit")
                unit = Unit.parse(str(params["output_unit"]), path=f"{path}.params.output_unit")
            else:
                unit = args[0].unit
            return _bound(op, args, params, unit, "numeric", fields, _merge_names(times, tuple(explicit_times)))

        _fail("unsupported_operation", path, "operation is outside the approved expression language")

    def _params(
        self,
        raw: dict[str, object],
        allowed: set[str],
        path: str,
        *,
        defaults: Mapping[str, object] | None = None,
        optional: set[str] | None = None,
    ) -> dict[str, object]:
        unknown = set(raw) - allowed
        if unknown:
            _fail("unknown_params", f"{path}.params", f"unknown parameters: {', '.join(sorted(unknown))}")
        result = dict(defaults or {})
        result.update(raw)
        missing = allowed - set(optional or ()) - set(result)
        if missing:
            _fail("missing_params", f"{path}.params", f"missing parameters: {', '.join(sorted(missing))}")
        return result

    def _bound_value(self, value: object, path: str) -> BoundValue:
        if isinstance(value, dict):
            if set(value) != {"bind"} or not isinstance(value["bind"], str):
                _fail("binding_form", path, "binding must be exactly {'bind': <parameter_name>}")
            name = value["bind"]
            if name not in self.schema:
                _fail("unknown_binding", path, "binding is absent from parameter_schema")
            self.parameter_refs.add(name)
            return ParameterRef(name)
        if isinstance(value, list):
            _fail(
                "parameter_type",
                path,
                "nested parameter lists are not valid scalar parameter values",
            )
        if not isinstance(value, (int, float, str, bool)) or value is None:
            _fail("parameter_type", path, "parameter value has an unsupported type")
        if isinstance(value, float) and not math.isfinite(value):
            _fail("finite", path, "numeric parameters must be finite")
        return value

    def _resolved(self, value: BoundValue) -> tuple[Scalar, ...]:
        if isinstance(value, ParameterRef):
            return tuple(item.value(value.name) for item in self.parameter_sets)
        if isinstance(value, tuple):
            _fail("parameter_type", "expression.params", "a scalar parameter was required")
        return (value,)

    def _expect_number(self, value: BoundValue, path: str, *, unit: Unit) -> None:
        if isinstance(value, ParameterRef):
            spec = self.schema[value.name]
            if spec.kind not in {"integer", "number"}:
                _fail("parameter_type", path, "binding must be numeric")
            if spec.unit != unit:
                _fail("binding_unit", path, "binding unit does not match the parameter position")
        for item in self._resolved(value):
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                _fail("parameter_type", path, "parameter must be numeric")
            _representable_number(item, path, code="finite")

    def _expect_integer(self, value: BoundValue, path: str, *, unit: str) -> None:
        if isinstance(value, ParameterRef):
            spec = self.schema[value.name]
            if spec.kind != "integer":
                _fail("parameter_type", path, "binding must be an integer")
            if spec.unit != Unit.parse(unit, path=path):
                _fail("binding_unit", path, "binding unit does not match the parameter position")
        for item in self._resolved(value):
            if isinstance(item, bool) or not isinstance(item, int):
                _fail("parameter_type", path, "parameter must be an integer")
            _representable_number(item, path, code="parameter_range")

    def _validate_minimum(self, value: BoundValue, minimum: float, code: str, path: str) -> None:
        if any(item < minimum for item in self._resolved(value)):
            _fail(code, path, f"parameter must be at least {minimum:g}")

    def _expect_mode(self, value: BoundValue, allowed: set[str], path: str) -> None:
        if isinstance(value, ParameterRef):
            spec = self.schema[value.name]
            if spec.kind != "string" or spec.unit != Unit(()):
                _fail("parameter_type", path, "mode binding must be a dimensionless string")
        for item in self._resolved(value):
            _mode(item, allowed, path)

    def _expect_boolean(self, value: BoundValue, path: str) -> None:
        if isinstance(value, ParameterRef):
            spec = self.schema[value.name]
            if spec.kind != "boolean" or spec.unit != Unit(()):
                _fail("parameter_type", path, "boolean binding must be dimensionless")
        for item in self._resolved(value):
            if not isinstance(item, bool):
                _fail("parameter_type", path, "parameter must be boolean")

    def _validate_range(
        self,
        value: BoundValue,
        lower: float,
        upper: float,
        path: str,
        *,
        lower_open: bool = False,
    ) -> None:
        invalid = any(
            (item <= lower if lower_open else item < lower) or item > upper
            for item in self._resolved(value)
        )
        if invalid:
            _fail("parameter_range", path, "parameter is outside the allowed range")

    def _validate_relation(
        self,
        left: BoundValue,
        right: BoundValue,
        predicate: object,
        code: str,
        path: str,
    ) -> None:
        left_values = self._resolved(left)
        right_values = self._resolved(right)
        if len(left_values) == 1 and len(right_values) > 1:
            left_values *= len(right_values)
        if len(right_values) == 1 and len(left_values) > 1:
            right_values *= len(left_values)
        if any(not predicate(a, b) for a, b in zip(left_values, right_values)):  # type: ignore[operator]
            _fail(code, path, "related parameters violate their required ordering")

    def _rolling_common(
        self,
        params: dict[str, object],
        path: str,
        *,
        allowed_missing: set[str] | None = None,
    ) -> None:
        for name in ("window", "min_periods"):
            params[name] = self._bound_value(params[name], f"{path}.params.{name}")
            self._expect_integer(params[name], f"{path}.params.{name}", unit="bars")
        self._validate_minimum(params["window"], 1, "positive_window", path)  # type: ignore[arg-type]
        self._validate_minimum(params["min_periods"], 1, "min_periods", path)  # type: ignore[arg-type]
        self._validate_relation(params["min_periods"], params["window"], lambda left, right: left <= right, "min_periods", path)  # type: ignore[arg-type]
        params["missing"] = self._bound_value(params["missing"], f"{path}.params.missing")
        self._expect_mode(
            params["missing"],
            allowed_missing or {"skip", "require_min_periods", "propagate"},
            f"{path}.params.missing",
        )

    def _metadata_field(self, value: object, path: str) -> None:
        if not isinstance(value, str) or value not in self.dataset.metadata_fields:
            _fail("unknown_metadata_field", path, "time/revision field is absent from the current dataset snapshot")


def _dataset_spec(dataset: Mapping[str, object]) -> DatasetSpec:
    if not isinstance(dataset, Mapping):
        _fail("dataset", "dataset", "dataset must be a current snapshot mapping")
    fields_value = dataset.get("fields")
    rows = dataset.get("rows")
    interval = dataset.get("bar_interval")
    if not isinstance(fields_value, Mapping) or not fields_value:
        _fail("dataset_fields", "dataset.fields", "dataset must declare named fields")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        _fail("dataset_rows", "dataset.rows", "dataset rows must be a list of mappings")
    if not isinstance(interval, str) or not interval:
        _fail("dataset_interval", "dataset.bar_interval", "bar_interval must be explicit")
    metadata_fields = set.intersection(*(set(row) for row in rows)) if rows else set()
    declared_metadata: set[str] = set()
    fields: list[FieldSpec] = []
    for name, raw in fields_value.items():
        path = f"dataset.fields.{name}"
        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name) or not isinstance(raw, Mapping):
            _fail("dataset_field", path, "field metadata is invalid")
        if not {"unit", "observed_at", "available_at"} <= set(raw) or set(raw) - {
            "unit",
            "observed_at",
            "available_at",
            "revision",
        }:
            _fail(
                "dataset_field",
                path,
                "field metadata must declare unit, observed_at, available_at, and optional revision",
            )
        observed = raw["observed_at"]
        available = raw["available_at"]
        if not isinstance(observed, str) or not isinstance(available, str):
            _fail("dataset_field", path, "time metadata fields must be names")
        if rows and (observed not in metadata_fields or available not in metadata_fields or name not in metadata_fields):
            _fail("dataset_field", path, "declared fields and time metadata must exist in every row")
        revision = raw.get("revision")
        if revision is not None and not isinstance(revision, str):
            _fail("dataset_field", path, "revision metadata field must be a name")
        if rows and revision is not None and revision not in metadata_fields:
            _fail("dataset_field", path, "declared revision metadata must exist in every row")
        declared_metadata.update({observed, available})
        if revision is not None:
            declared_metadata.add(revision)
        fields.append(
            FieldSpec(
                name,
                Unit.parse(raw["unit"], path=f"{path}.unit"),
                observed,
                available,
                revision,
            )
        )
    return DatasetSpec(
        fields=tuple(sorted(fields, key=lambda item: item.name)),
        metadata_fields=tuple(sorted(metadata_fields | declared_metadata)),
        bar_interval=interval,
        row_count=len(rows),
        point_in_time_status=(
            str(dataset["point_in_time_status"])
            if dataset.get("point_in_time_status") is not None
            else None
        ),
    )


def _parameter_specs(
    value: Mapping[str, object], limits: ExpressionLimits
) -> dict[str, _ParameterSpec]:
    if not isinstance(value, Mapping):
        _fail("parameter_schema", "parameter_schema", "parameter_schema must be an object")
    if len(value) > limits.max_parameters:
        raise ExpressionLimitError("max_parameters", "parameter_schema", "parameter schema exceeds the configured limit")
    result: dict[str, _ParameterSpec] = {}
    for name, raw in value.items():
        path = f"parameter_schema.{name}"
        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name) or not isinstance(raw, Mapping):
            _fail("parameter_schema", path, "parameter declaration is invalid")
        allowed = {"type", "unit", "minimum", "maximum", "enum"}
        if set(raw) - allowed or not {"type", "unit"} <= set(raw):
            _fail("parameter_schema_keys", path, "parameter schema keys are invalid")
        kind = raw["type"]
        if kind not in {"integer", "number", "boolean", "string"}:
            _fail("parameter_schema_type", path, "parameter type is unsupported")
        minimum = _optional_finite(raw.get("minimum"), f"{path}.minimum")
        maximum = _optional_finite(raw.get("maximum"), f"{path}.maximum")
        if minimum is not None and maximum is not None and minimum > maximum:
            _fail("parameter_schema_range", path, "minimum exceeds maximum")
        if kind in {"boolean", "string"} and (minimum is not None or maximum is not None):
            _fail(
                "parameter_schema_range",
                path,
                "minimum and maximum apply only to numeric parameters",
            )
        enum_value = raw.get("enum")
        enum: tuple[Scalar, ...] | None = None
        if enum_value is not None:
            if not isinstance(enum_value, list) or not enum_value:
                _fail("parameter_schema_enum", path, "enum must be a non-empty explicit list")
            checked: list[Scalar] = []
            for index, item in enumerate(enum_value):
                if not isinstance(item, (int, float, str, bool)) or (
                    isinstance(item, float) and not math.isfinite(item)
                ):
                    _fail(
                        "parameter_schema_enum",
                        f"{path}.enum[{index}]",
                        "enum values must be finite scalar values",
                    )
                probe = _ParameterSpec(
                    name=name,
                    kind=kind,  # type: ignore[arg-type]
                    unit=Unit.parse(raw["unit"], path=f"{path}.unit"),
                    minimum=minimum,
                    maximum=maximum,
                    enum=None,
                )
                _validate_binding(item, probe, f"{path}.enum[{index}]")
                checked.append(item)
            if len({(type(item), item) for item in checked}) != len(checked):
                _fail("parameter_schema_enum", path, "enum values must be unique")
            enum = tuple(checked)
        result[name] = _ParameterSpec(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            unit=Unit.parse(raw["unit"], path=f"{path}.unit"),
            minimum=minimum,
            maximum=maximum,
            enum=enum,
        )
    return result


def _parameter_sets(
    values: list[object] | tuple[object, ...],
    schema: Mapping[str, _ParameterSpec],
) -> tuple[BoundParameterSet, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        _fail("parameter_sets", "parameter_sets", "at least one explicit parameter set is required")
    ids: set[str] = set()
    result: list[BoundParameterSet] = []
    expected = set(schema)
    for index, raw in enumerate(values):
        path = f"parameter_sets[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != {"parameter_set_id", "bindings"}:
            _fail("parameter_set_shape", path, "parameter set must contain exactly parameter_set_id and bindings")
        identifier = raw["parameter_set_id"]
        bindings = raw["bindings"]
        if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
            _fail("parameter_set_id", f"{path}.parameter_set_id", "parameter set ID is invalid")
        if identifier in ids:
            _fail("duplicate_parameter_set_id", f"{path}.parameter_set_id", "parameter set IDs must be unique")
        ids.add(identifier)
        if not isinstance(bindings, Mapping):
            _fail("bindings", f"{path}.bindings", "bindings must be an object")
        missing = expected - set(bindings)
        extra = set(bindings) - expected
        if missing:
            _fail("missing_bindings", f"{path}.bindings", "parameter set omits declared bindings")
        if extra:
            _fail("extra_bindings", f"{path}.bindings", "parameter set contains undeclared bindings")
        frozen: list[tuple[str, Scalar]] = []
        for name in sorted(schema):
            item = bindings[name]
            _validate_binding(item, schema[name], f"{path}.bindings.{name}")
            frozen.append((name, item))  # type: ignore[arg-type]
        result.append(BoundParameterSet(identifier, tuple(frozen)))
    return tuple(result)


def _validate_binding(value: object, spec: _ParameterSpec, path: str) -> None:
    if spec.kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _fail("binding_type", path, "integer binding must not be boolean")
    elif spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail("binding_type", path, "numeric binding must not be boolean")
    elif spec.kind == "boolean":
        if not isinstance(value, bool):
            _fail("binding_type", path, "boolean binding is required")
    elif not isinstance(value, str):
        _fail("binding_type", path, "string binding is required")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        _representable_number(value, path, code="binding_finite")
        if spec.minimum is not None and value < spec.minimum:
            _fail("binding_range", path, "binding is below its declared minimum")
        if spec.maximum is not None and value > spec.maximum:
            _fail("binding_range", path, "binding exceeds its declared maximum")
    if spec.enum is not None and value not in spec.enum:
        _fail("binding_enum", path, "binding is absent from its declared enum")


def _resource_plan(
    *,
    node_count: int,
    depth: int,
    row_count: int,
    parameter_sets: tuple[BoundParameterSet, ...],
    limits: ExpressionLimits,
) -> tuple[ResourceEstimate, BatchPlan]:
    set_count = len(parameter_sets)
    cells_per_set = node_count * max(row_count, 1)
    bytes_per_set = cells_per_set * limits.estimated_bytes_per_cell
    estimate = ResourceEstimate(
        node_count=node_count,
        depth=depth,
        row_count=row_count,
        parameter_set_count=set_count,
        estimated_cells=cells_per_set * set_count,
        estimated_bytes=bytes_per_set * set_count,
        estimate_basis="nodes * max(rows,1) * explicit_parameter_sets; bytes use configured bytes-per-cell and are not a memory guarantee",
    )
    by_cells = limits.max_estimated_cells_per_batch // max(cells_per_set, 1)
    by_bytes = limits.max_estimated_bytes_per_batch // max(bytes_per_set, 1)
    batch_size = max(1, min(limits.max_parameter_sets_per_batch, by_cells or 1, by_bytes or 1))
    batches: list[Batch] = []
    for start in range(0, set_count, batch_size):
        chunk = parameter_sets[start : start + batch_size]
        batches.append(
            Batch(
                parameter_set_ids=tuple(item.parameter_set_id for item in chunk),
                estimated_cells=cells_per_set * len(chunk),
                estimated_bytes=bytes_per_set * len(chunk),
            )
        )
    requires_rows = cells_per_set > limits.max_estimated_cells_per_batch or bytes_per_set > limits.max_estimated_bytes_per_batch
    max_rows: int | None = None
    guidance: list[str] = []
    if len(batches) > 1:
        guidance.append("execute the explicit parameter-set batches under one trial group; do not drop or auto-expand sets")
    if requires_rows:
        rows_by_cells = limits.max_estimated_cells_per_batch // max(node_count, 1)
        rows_by_bytes = limits.max_estimated_bytes_per_batch // max(node_count * limits.estimated_bytes_per_cell, 1)
        max_rows = max(1, min(rows_by_cells or 1, rows_by_bytes or 1))
        guidance.append(
            "row partitioning is execution guidance only: T045 must preserve prior history/state, rolling overlap, as-of eligibility, and label/split boundaries; never reset history per chunk"
        )
    return estimate, BatchPlan(
        parameter_set_ids=tuple(item.parameter_set_id for item in parameter_sets),
        batches=tuple(batches),
        split_required=len(batches) > 1 or requires_rows,
        requires_row_partition=requires_rows,
        max_rows_per_batch=max_rows,
        guidance=tuple(guidance),
    )


def _bound(
    op: str,
    args: tuple[BoundNode, ...],
    params: Mapping[str, object],
    unit: Unit,
    kind: ValueKind,
    fields: tuple[str, ...],
    times: tuple[str, ...],
) -> BoundNode:
    return BoundNode(op, args, _freeze_params(params), unit, kind, fields, times)


def _freeze_params(params: Mapping[str, object]) -> tuple[tuple[str, BoundValue], ...]:
    return tuple(sorted((name, _freeze_value(value)) for name, value in params.items()))


def _freeze_value(value: object) -> BoundValue:
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    return value  # type: ignore[return-value]


def _resolve_bound_value(value: object, parameter_set: BoundParameterSet) -> object:
    if isinstance(value, ParameterRef):
        return parameter_set.value(value.name)
    if isinstance(value, tuple):
        return tuple(_resolve_bound_value(item, parameter_set) for item in value)
    return value


def _merge_names(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({item for group in groups for item in group}))


def _arity(args: tuple[BoundNode, ...], expected: int, path: str) -> None:
    if len(args) != expected:
        _fail("arity", path, f"operation requires exactly {expected} arguments")


def _numeric(args: tuple[BoundNode, ...], path: str) -> None:
    if any(item.kind != "numeric" for item in args):
        _fail("numeric_required", path, "operation requires numeric arguments")


def _boolean(args: tuple[BoundNode, ...], path: str) -> None:
    if any(item.kind != "boolean" for item in args):
        _fail("boolean_required", path, "operation requires boolean arguments")


def _compatible(left: Unit, right: Unit, path: str) -> None:
    if left != right:
        _fail("incompatible_units", path, f"units are incompatible: {left.display} and {right.display}")


def _mode(value: object, allowed: set[str], path: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        _fail("parameter_value", path, f"value must be one of: {', '.join(sorted(allowed))}")


def _optional_finite(value: object, path: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("parameter_schema_range", path, "range boundary must be a finite number")
    _representable_number(value, path, code="parameter_schema_range")
    return value


def _add_unit_token(factors: dict[str, int], raw: str, power: int, path: str) -> None:
    direct = _ALIASES.get(raw, raw)
    if direct == "dimensionless":
        return
    match = _UNIT_TOKEN.fullmatch(direct)
    if match is None:
        _fail("unit", path, "unit contains an invalid token or exponent")
    token = _ALIASES.get(match.group(1), match.group(1))
    try:
        exponent = int(match.group(2) or "1")
    except ValueError:
        _fail("unit", path, "unit exponent is invalid")
    if token == "dimensionless":
        return
    factors[token] = factors.get(token, 0) + power * exponent


def _representable_number(value: int | float, path: str, *, code: str) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(code, path, "numeric value must be finite")
        return
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        _fail(code, path, "integer magnitude is not representable by the numerical handoff")
    if not math.isfinite(converted):
        _fail(code, path, "integer magnitude is not representable by the numerical handoff")


def _fail(code: str, path: str, message: str) -> None:
    raise ExpressionValidationError(code, path, message)
