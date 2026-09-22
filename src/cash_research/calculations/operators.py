"""Pure deterministic execution for validated T041 expression nodes.

The module evaluates only approved ``BoundNode`` objects.  Historical alignment
operations are explicit extension points owned by T043; no source eligibility is
invented here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias

from cash_research.calculations.expression import BoundNode, BoundParameterSet


IndexValue: TypeAlias = object
SeriesValue: TypeAlias = float | bool | None


class OperatorError(ValueError):
    """Base error for deterministic operator execution."""


class OperatorInputError(OperatorError):
    """Raised when series shape, type, or alignment is unsafe."""


class HistoricalOperatorRequired(OperatorError):
    """Raised when T043 historical alignment has not been supplied."""


@dataclass(frozen=True)
class OperatorWarning:
    operation: str
    row_index: IndexValue
    reason: str


@dataclass(frozen=True)
class SeriesData:
    index: tuple[IndexValue, ...]
    values: tuple[SeriesValue, ...]
    available_at: tuple[datetime | None, ...]
    timeless: bool = False

    def __post_init__(self) -> None:
        if len(self.index) != len(self.values) or len(self.index) != len(self.available_at):
            raise OperatorInputError("series index, values, and availability lengths must match")
        try:
            if len(set(self.index)) != len(self.index):
                raise OperatorInputError("series index values must be unique")
        except TypeError as exc:
            raise OperatorInputError("series index values must be hashable") from exc
        for value in self.values:
            if value is not None and not isinstance(value, (int, float, bool)):
                raise OperatorInputError("series values must be numeric, boolean, or null")
        for value in self.available_at:
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise OperatorInputError("series availability times must be timezone-aware")


@dataclass(frozen=True, init=False)
class EvaluationContext:
    index: tuple[IndexValue, ...]
    fields: tuple[tuple[str, SeriesData], ...]

    def __init__(
        self, *, index: tuple[IndexValue, ...], fields: Mapping[str, SeriesData]
    ) -> None:
        canonical_index = tuple(index)
        try:
            if len(set(canonical_index)) != len(canonical_index):
                raise OperatorInputError("context index values must be unique")
        except TypeError as exc:
            raise OperatorInputError("context index values must be hashable") from exc
        normalized: list[tuple[str, SeriesData]] = []
        for name, item in sorted(fields.items()):
            if not isinstance(name, str) or not name:
                raise OperatorInputError("field names must be non-empty strings")
            if not isinstance(item, SeriesData) or item.index != canonical_index:
                raise OperatorInputError("every field must use the exact context index")
            normalized.append((name, item))
        object.__setattr__(self, "index", canonical_index)
        object.__setattr__(self, "fields", tuple(normalized))

    def field(self, name: str) -> SeriesData:
        for field_name, value in self.fields:
            if field_name == name:
                return value
        raise OperatorInputError("validated field is absent from the evaluation context")


@dataclass(frozen=True)
class EvaluationResult:
    series: SeriesData
    warnings: tuple[OperatorWarning, ...]


HistoricalHandler: TypeAlias = Callable[
    [BoundNode, tuple[SeriesData, ...], Mapping[str, object], EvaluationContext],
    EvaluationResult,
]


def evaluate_expression(
    root: BoundNode,
    *,
    context: EvaluationContext,
    parameter_set: BoundParameterSet,
    historical_handlers: Mapping[str, HistoricalHandler] | None = None,
) -> EvaluationResult:
    """Evaluate one validated AST for one explicit parameter set."""

    if not isinstance(root, BoundNode) or not isinstance(parameter_set, BoundParameterSet):
        raise OperatorInputError("evaluation requires a validated BoundNode and parameter set")
    handlers = historical_handlers or {}

    def visit(node: BoundNode) -> EvaluationResult:
        if node.op == "field":
            name = node.parameter("name")
            if not isinstance(name, str):
                raise OperatorInputError("bound field node has no valid name")
            source = context.field(name)
            if source.timeless:
                raise OperatorInputError("named source fields cannot be timeless")
            values: list[SeriesValue] = []
            warnings: list[OperatorWarning] = []
            for position, value in enumerate(source.values):
                if isinstance(value, bool):
                    values.append(None)
                    warnings.append(_warning(node.op, source.index[position], "boolean_numeric_input"))
                else:
                    try:
                        representable = value is None or math.isfinite(float(value))
                    except (OverflowError, TypeError, ValueError):
                        representable = False
                    if representable:
                        values.append(value)
                    else:
                        values.append(None)
                        warnings.append(_warning(node.op, source.index[position], "nonfinite_input"))
            return EvaluationResult(
                SeriesData(source.index, tuple(values), source.available_at, False),
                tuple(warnings),
            )
        if node.op == "constant":
            params = node.resolved_params(parameter_set)
            value = params["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise OperatorInputError("bound constant is not numeric")
            numeric = float(value)
            return EvaluationResult(
                SeriesData(
                    context.index,
                    tuple(numeric for _ in context.index),
                    tuple(None for _ in context.index),
                    True,
                ),
                (),
            )

        children = tuple(visit(child) for child in node.args)
        child_series = tuple(item.series for item in children)
        child_warnings = tuple(
            warning for child in children for warning in child.warnings
        )
        params = node.resolved_params(parameter_set)
        if node.op in {"asof_value", "event_age"}:
            handler = handlers.get(node.op)
            if handler is None:
                raise HistoricalOperatorRequired(
                    f"{node.op} requires an explicit T043 historical-alignment handler"
                )
            handled = handler(node, child_series, params, context)
            if not isinstance(handled, EvaluationResult):
                raise OperatorInputError("historical handler returned an invalid result")
            if handled.series.index != context.index or handled.series.timeless:
                raise OperatorInputError(
                    "historical handler must return the exact context index and source availability metadata"
                )
            return EvaluationResult(
                handled.series, child_warnings + handled.warnings
            )
        applied = apply_operator(node, child_series, params)
        return EvaluationResult(applied.series, child_warnings + applied.warnings)

    return visit(root)


def apply_operator(
    node: BoundNode,
    args: tuple[SeriesData, ...],
    params: Mapping[str, object],
) -> EvaluationResult:
    """Apply one already-validated non-leaf T042 operation."""

    if node.op in {"field", "constant", "asof_value", "event_age"}:
        raise OperatorInputError("operation is handled by the evaluator boundary")
    _aligned(args)
    if node.op in {"add", "subtract", "multiply", "safe_divide"}:
        return _binary_numeric(node.op, args[0], args[1])
    if node.op in {"abs", "sign", "log", "clip"}:
        return _unary_numeric(node.op, args[0], params)
    if node.op in {"gt", "gte", "lt", "lte"}:
        return _comparison(node.op, args[0], args[1])
    if node.op in {"and", "or"}:
        return _boolean_combine(node.op, args[0], args[1])
    if node.op == "where":
        return _where(args[0], args[1], args[2], str(params["missing_condition"]))
    if node.op == "weighted_sum":
        return _weighted_sum(args, tuple(params["weights"]), str(params["missing"]))  # type: ignore[arg-type]
    if node.op in {"lag", "delta", "pct_return", "log_return"}:
        return _time_operator(node.op, args[0], int(params["periods"]))
    if node.op in {
        "rolling_sum",
        "rolling_mean",
        "rolling_median",
        "rolling_min",
        "rolling_max",
        "rolling_std",
        "rolling_quantile",
        "rolling_rank",
    }:
        return _rolling_unary(node.op, args[0], params)
    if node.op in {"rolling_corr", "rolling_cov"}:
        return _rolling_pair(node.op, args[0], args[1], params)
    if node.op in {"ewm_mean", "ewm_std"}:
        return _ewm(node.op, args[0], params)
    raise OperatorInputError("validated operation is not implemented by T042")


def _binary_numeric(op: str, left: SeriesData, right: SeriesData) -> EvaluationResult:
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    warnings: list[OperatorWarning] = []
    for position, (a, b) in enumerate(zip(left.values, right.values)):
        used = ((left, position), (right, position))
        availability.append(_dependency_time(used))
        if a is None or b is None:
            values.append(None)
            continue
        x = _numeric(a)
        y = _numeric(b)
        try:
            if op == "add":
                result = x + y
            elif op == "subtract":
                result = x - y
            elif op == "multiply":
                result = x * y
            else:
                if y == 0:
                    values.append(None)
                    warnings.append(_warning(op, left.index[position], "division_by_zero"))
                    continue
                result = x / y
        except OverflowError:
            result = math.inf
        values.append(_finite_output(result, op, left.index[position], warnings))
    return _result(left.index, values, availability, _all_timeless(left, right), warnings)


def _unary_numeric(
    op: str, source: SeriesData, params: Mapping[str, object]
) -> EvaluationResult:
    values: list[SeriesValue] = []
    warnings: list[OperatorWarning] = []
    for position, value in enumerate(source.values):
        if value is None:
            values.append(None)
            continue
        number = _numeric(value)
        if op == "abs":
            output = abs(number)
        elif op == "sign":
            output = 1.0 if number > 0 else -1.0 if number < 0 else 0.0
        elif op == "clip":
            output = min(max(number, float(params["lower"])), float(params["upper"]))
        else:
            if number <= 0:
                values.append(None)
                warnings.append(_warning(op, source.index[position], "log_nonpositive"))
                continue
            output = math.log(number)
        values.append(_finite_output(output, op, source.index[position], warnings))
    return _result(source.index, values, list(source.available_at), source.timeless, warnings)


def _comparison(op: str, left: SeriesData, right: SeriesData) -> EvaluationResult:
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    for position, (a, b) in enumerate(zip(left.values, right.values)):
        availability.append(_dependency_time(((left, position), (right, position))))
        if a is None or b is None:
            values.append(None)
            continue
        x, y = _numeric(a), _numeric(b)
        values.append(
            x > y if op == "gt" else x >= y if op == "gte" else x < y if op == "lt" else x <= y
        )
    return _result(left.index, values, availability, _all_timeless(left, right), [])


def _boolean_combine(op: str, left: SeriesData, right: SeriesData) -> EvaluationResult:
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    for position, (a, b) in enumerate(zip(left.values, right.values)):
        _boolean_value(a)
        _boolean_value(b)
        if op == "and":
            if a is False:
                values.append(False)
                used = ((left, position),)
            elif b is False:
                values.append(False)
                used = ((right, position),)
            elif a is True and b is True:
                values.append(True)
                used = ((left, position), (right, position))
            else:
                values.append(None)
                # The missing operand is material to an unknown result, so its
                # unknown availability must remain visible.
                used = ((left, position), (right, position))
        else:
            if a is True:
                values.append(True)
                used = ((left, position),)
            elif b is True:
                values.append(True)
                used = ((right, position),)
            elif a is False and b is False:
                values.append(False)
                used = ((left, position), (right, position))
            else:
                values.append(None)
                used = ((left, position), (right, position))
        availability.append(_dependency_time(used))
    return _result(left.index, values, availability, _all_timeless(left, right), [])


def _where(
    condition: SeriesData,
    when_true: SeriesData,
    when_false: SeriesData,
    missing_policy: str,
) -> EvaluationResult:
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    warnings: list[OperatorWarning] = []
    for position, condition_value in enumerate(condition.values):
        _boolean_value(condition_value)
        if condition_value is None:
            if missing_policy == "propagate":
                values.append(None)
                availability.append(_dependency_time(((condition, position),)))
                continue
            choose_true = missing_policy == "true"
            warnings.append(
                _warning(
                    "where",
                    condition.index[position],
                    f"missing_condition_used_{missing_policy}_policy",
                )
            )
            used_condition = False
        else:
            choose_true = condition_value
            used_condition = True
        chosen = when_true if choose_true else when_false
        values.append(chosen.values[position])
        dependencies = [(chosen, position)]
        if used_condition:
            dependencies.append((condition, position))
        availability.append(_dependency_time(tuple(dependencies)))
    timeless = condition.timeless and when_true.timeless and when_false.timeless
    return _result(condition.index, values, availability, timeless, warnings)


def _weighted_sum(
    args: tuple[SeriesData, ...], weights: tuple[object, ...], missing: str
) -> EvaluationResult:
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    warnings: list[OperatorWarning] = []
    for position in range(len(args[0].index)):
        present = [
            (item, float(weight))
            for item, weight in zip(args, weights)
            if item.values[position] is not None
        ]
        if missing == "require_all" and len(present) != len(args):
            values.append(None)
            availability.append(_dependency_time(tuple((item, position) for item in args)))
            continue
        if not present:
            values.append(None)
            availability.append(None)
            continue
        if len(present) != len(args):
            warnings.append(
                _warning(
                    "weighted_sum",
                    args[0].index[position],
                    "weighted_missing_skipped_without_renormalization",
                )
            )
        output = sum(_numeric(item.values[position]) * weight for item, weight in present)
        values.append(_finite_output(output, "weighted_sum", args[0].index[position], warnings))
        availability.append(
            _dependency_time(tuple((item, position) for item, _ in present))
        )
    return _result(args[0].index, values, availability, all(item.timeless for item in args), warnings)


def _time_operator(op: str, source: SeriesData, periods: int) -> EvaluationResult:
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    warnings: list[OperatorWarning] = []
    for position, value in enumerate(source.values):
        previous = position - periods
        if previous < 0:
            values.append(None)
            availability.append(None)
            continue
        old = source.values[previous]
        used = ((source, position), (source, previous)) if op != "lag" else ((source, previous),)
        availability.append(_dependency_time(used))
        if op == "lag":
            values.append(old)
            continue
        if value is None or old is None:
            values.append(None)
            continue
        current, prior = _numeric(value), _numeric(old)
        if op == "delta":
            output = current - prior
        elif op == "pct_return":
            if prior == 0:
                values.append(None)
                warnings.append(_warning(op, source.index[position], "division_by_zero"))
                continue
            output = current / prior - 1.0
        else:
            if current <= 0 or prior <= 0:
                values.append(None)
                warnings.append(_warning(op, source.index[position], "log_nonpositive"))
                continue
            output = math.log(current) - math.log(prior)
        values.append(_finite_output(output, op, source.index[position], warnings))
    return _result(source.index, values, availability, source.timeless, warnings)


def _rolling_unary(
    op: str, source: SeriesData, params: Mapping[str, object]
) -> EvaluationResult:
    window = int(params["window"])
    minimum = int(params["min_periods"])
    missing = str(params["missing"])
    if op == "rolling_rank":
        return _rolling_rank(source, params)
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    warnings: list[OperatorWarning] = []
    for position in range(len(source.index)):
        positions = list(range(max(0, position - window + 1), position + 1))
        valid = [item for item in positions if source.values[item] is not None]
        ready = _rolling_ready(positions, valid, minimum, missing)
        availability.append(
            _dependency_time(tuple((source, item) for item in (valid if ready else positions)))
        )
        if not ready:
            values.append(None)
            continue
        numbers = sorted(_numeric(source.values[item]) for item in valid)
        if op == "rolling_sum":
            output = sum(numbers)
        elif op == "rolling_mean":
            output = sum(numbers) / len(numbers)
        elif op == "rolling_median":
            output = _quantile(numbers, 0.5, "midpoint")
        elif op == "rolling_min":
            output = numbers[0]
        elif op == "rolling_max":
            output = numbers[-1]
        elif op == "rolling_std":
            ddof = int(params["ddof"])
            if len(numbers) <= ddof:
                values.append(None)
                warnings.append(_warning(op, source.index[position], "insufficient_degrees_of_freedom"))
                continue
            mean = sum(numbers) / len(numbers)
            try:
                variance = sum((item - mean) ** 2 for item in numbers) / (
                    len(numbers) - ddof
                )
                output = math.sqrt(variance)
            except OverflowError:
                output = math.inf
        else:
            output = _quantile(numbers, float(params["q"]), str(params["interpolation"]))
        values.append(_finite_output(output, op, source.index[position], warnings))
    return _result(source.index, values, availability, source.timeless, warnings)


def _rolling_rank(source: SeriesData, params: Mapping[str, object]) -> EvaluationResult:
    window = int(params["window"])
    minimum = int(params["min_periods"])
    missing = str(params["missing"])
    method = str(params["method"])
    ascending = bool(params["ascending"])
    pct = bool(params["pct"])
    na_option = str(params["na_option"])
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    for position in range(len(source.index)):
        positions = list(range(max(0, position - window + 1), position + 1))
        valid = [item for item in positions if source.values[item] is not None]
        if not _rolling_ready(positions, valid, minimum, missing):
            values.append(None)
            availability.append(_dependency_time(tuple((source, item) for item in positions)))
            continue
        if source.values[position] is None and na_option == "keep":
            values.append(None)
            availability.append(_dependency_time(tuple((source, item) for item in valid)))
            continue
        ranked_positions = valid[:]
        if na_option in {"top", "bottom"}:
            ranked_positions.extend(item for item in positions if source.values[item] is None)
        rank = _rank_current(source, ranked_positions, position, method, ascending, na_option)
        if pct:
            denominator = (
                len(_rank_groups(source, ranked_positions, ascending, na_option))
                if method == "dense"
                else len(ranked_positions)
            )
            rank /= denominator
        values.append(rank)
        availability.append(
            _dependency_time(tuple((source, item) for item in ranked_positions))
        )
    return _result(source.index, values, availability, source.timeless, [])


def _rolling_pair(
    op: str, left: SeriesData, right: SeriesData, params: Mapping[str, object]
) -> EvaluationResult:
    window = int(params["window"])
    minimum = int(params["min_periods"])
    ddof = int(params.get("ddof", 1))
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    warnings: list[OperatorWarning] = []
    for position in range(len(left.index)):
        positions = range(max(0, position - window + 1), position + 1)
        pairs = [
            item
            for item in positions
            if left.values[item] is not None and right.values[item] is not None
        ]
        availability.append(
            _dependency_time(
                tuple((series_value, item) for item in pairs for series_value in (left, right))
            )
        )
        if len(pairs) < minimum:
            values.append(None)
            continue
        x = [_numeric(left.values[item]) for item in pairs]
        y = [_numeric(right.values[item]) for item in pairs]
        mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
        try:
            cross = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
        except OverflowError:
            cross = math.inf
        if op == "rolling_cov":
            if len(pairs) <= ddof:
                values.append(None)
                warnings.append(_warning(op, left.index[position], "insufficient_degrees_of_freedom"))
                continue
            output = cross / (len(pairs) - ddof)
        else:
            try:
                ssx = sum((item - mean_x) ** 2 for item in x)
                ssy = sum((item - mean_y) ** 2 for item in y)
            except OverflowError:
                ssx = ssy = math.inf
            if ssx == 0 or ssy == 0:
                values.append(None)
                warnings.append(_warning(op, left.index[position], "zero_variance"))
                continue
            if not all(math.isfinite(item) for item in (cross, ssx, ssy)):
                output = math.nan
            else:
                output = cross / (math.sqrt(ssx) * math.sqrt(ssy))
        values.append(_finite_output(output, op, left.index[position], warnings))
    return _result(left.index, values, availability, _all_timeless(left, right), warnings)


def _ewm(op: str, source: SeriesData, params: Mapping[str, object]) -> EvaluationResult:
    alpha = (
        float(params["alpha"])
        if "alpha" in params
        else 2.0 / (float(params["span"]) + 1.0)
    )
    adjust = bool(params["adjust"])
    ignore_na = bool(params["ignore_na"])
    minimum = int(params["min_periods"])
    bias = bool(params.get("bias", True))
    values: list[SeriesValue] = []
    availability: list[datetime | None] = []
    warnings: list[OperatorWarning] = []
    beta = 1.0 - alpha
    weight = 0.0
    squared_weight = 0.0
    mean = 0.0
    weighted_m2 = 0.0
    observation_count = 0
    dependency_time: datetime | None = None
    dependency_unknown = False
    last_output: float | None = None
    for position in range(len(source.index)):
        raw_value = source.values[position]
        has_observation = raw_value is not None
        previous_weight = weight
        if weight > 0 and (has_observation or not ignore_na):
            weight *= beta
            weighted_m2 *= beta
            squared_weight *= beta * beta

        if has_observation:
            observation = _numeric(raw_value)
            observation_count += 1
            new_weight = 1.0 if adjust else alpha
            if previous_weight == 0 or weight == 0:
                mean = observation
                weighted_m2 = 0.0
                weight = new_weight
                squared_weight = new_weight * new_weight
                dependency_time = source.available_at[position]
                dependency_unknown = source.available_at[position] is None
            else:
                total = weight + new_weight
                try:
                    delta = observation - mean
                    new_mean = mean + delta * new_weight / total
                    weighted_m2 += new_weight * delta * (observation - new_mean)
                except OverflowError:
                    new_mean = math.nan
                    weighted_m2 = math.nan
                mean = new_mean
                weight = total
                squared_weight += new_weight * new_weight
                if source.available_at[position] is None:
                    dependency_unknown = True
                elif dependency_time is None or source.available_at[position] > dependency_time:
                    dependency_time = source.available_at[position]
            if not adjust and weight > 0:
                weighted_m2 /= weight
                squared_weight /= weight * weight
                weight = 1.0

        row_availability = None if dependency_unknown else dependency_time
        availability.append(row_availability)
        if observation_count < minimum or observation_count == 0:
            values.append(None)
            continue
        if not has_observation and weight == 0:
            values.append(last_output)
            continue
        if op == "ewm_mean":
            output = mean
        else:
            variance = weighted_m2 / weight if weight > 0 else math.nan
            if not bias:
                denominator = weight * weight - squared_weight
                if denominator <= 0:
                    values.append(None)
                    last_output = None
                    warnings.append(_warning(op, source.index[position], "insufficient_degrees_of_freedom"))
                    continue
                variance *= weight * weight / denominator
            output = math.sqrt(max(variance, 0.0)) if math.isfinite(variance) else math.nan
        last_output = _finite_output(output, op, source.index[position], warnings)
        values.append(last_output)
    return _result(source.index, values, availability, source.timeless, warnings)


def _rolling_ready(
    positions: list[int], valid: list[int], minimum: int, missing: str
) -> bool:
    if missing == "propagate":
        return len(positions) >= minimum and len(valid) == len(positions)
    if missing == "skip":
        return len(positions) >= minimum and bool(valid)
    return len(valid) >= minimum


def _quantile(values: list[float], q: float, interpolation: str) -> float:
    if len(values) == 1:
        return values[0]
    position = q * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if interpolation == "lower":
        return values[lower]
    if interpolation == "higher":
        return values[upper]
    if interpolation == "nearest":
        return values[round(position)]
    if interpolation == "midpoint":
        return (values[lower] + values[upper]) / 2.0
    fraction = position - lower
    return values[lower] + fraction * (values[upper] - values[lower])


def _rank_current(
    source: SeriesData,
    positions: list[int],
    current: int,
    method: str,
    ascending: bool,
    na_option: str,
) -> float:
    groups = _rank_groups(source, positions, ascending, na_option)
    rank_start = 1
    dense_rank = 1
    for group in groups:
        if current in group:
            offset = group.index(current)
            if method == "min":
                return float(rank_start)
            if method == "max":
                return float(rank_start + len(group) - 1)
            if method == "average":
                return (rank_start + rank_start + len(group) - 1) / 2.0
            if method == "first":
                return float(rank_start + offset)
            return float(dense_rank)
        rank_start += len(group)
        dense_rank += 1
    raise OperatorInputError("current rank value was not present in its rolling window")


def _rank_groups(
    source: SeriesData,
    positions: list[int],
    ascending: bool,
    na_option: str,
) -> list[list[int]]:
    def key(position: int) -> tuple[int, float]:
        value = source.values[position]
        if value is None:
            return (-1 if na_option == "top" else 1, 0.0)
        numeric = _numeric(value)
        return (0, numeric if ascending else -numeric)

    ordered = sorted(positions, key=lambda item: (key(item), item))
    groups: list[list[int]] = []
    for position in ordered:
        value = source.values[position]
        group_key = ("missing",) if value is None else ("value", _numeric(value))
        if not groups:
            groups.append([position])
            continue
        previous = groups[-1][0]
        previous_value = source.values[previous]
        previous_key = (
            ("missing",)
            if previous_value is None
            else ("value", _numeric(previous_value))
        )
        if group_key == previous_key:
            groups[-1].append(position)
        else:
            groups.append([position])
    return groups


def _aligned(args: tuple[SeriesData, ...]) -> None:
    if not args:
        raise OperatorInputError("operator requires input series")
    expected = args[0].index
    if any(item.index != expected for item in args[1:]):
        raise OperatorInputError("operator inputs must have exactly aligned indices")


def _numeric(value: SeriesValue) -> float:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OperatorInputError("numeric operator received a nonnumeric value")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise OperatorInputError("numeric input cannot be represented safely") from exc
    if not math.isfinite(result):
        raise OperatorInputError("numeric input must be finite")
    return result


def _boolean_value(value: SeriesValue) -> None:
    if value is not None and not isinstance(value, bool):
        raise OperatorInputError("boolean operator received a nonboolean value")


def _dependency_time(
    dependencies: tuple[tuple[SeriesData, int], ...]
) -> datetime | None:
    source_dependencies = [item for item in dependencies if not item[0].timeless]
    if not source_dependencies:
        return None
    times = [item.available_at[position] for item, position in source_dependencies]
    if any(value is None for value in times):
        return None
    return max(value for value in times if value is not None)


def _finite_output(
    value: float,
    operation: str,
    row_index: IndexValue,
    warnings: list[OperatorWarning],
) -> float | None:
    if math.isfinite(value):
        return value
    warnings.append(_warning(operation, row_index, "nonfinite_output"))
    return None


def _all_timeless(*series_values: SeriesData) -> bool:
    return all(item.timeless for item in series_values)


def _warning(operation: str, row_index: IndexValue, reason: str) -> OperatorWarning:
    return OperatorWarning(operation, row_index, reason)


def _result(
    index: tuple[IndexValue, ...],
    values: list[SeriesValue],
    availability: list[datetime | None],
    timeless: bool,
    warnings: list[OperatorWarning],
) -> EvaluationResult:
    return EvaluationResult(
        SeriesData(index, tuple(values), tuple(availability), timeless),
        tuple(warnings),
    )
