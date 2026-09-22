"""Integrated factor experiment computation over validated expression trees.

Program calculates declared signals and research statistics.  It does not emit
buy/sell decisions, execute model-authored code, or invent trading fills.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Literal

from cash_research.calculations.expression import (
    BoundParameterSet,
    ExpressionValidationError,
    ValidatedExpression,
    validate_expression,
)
from cash_research.calculations.operators import (
    EvaluationContext,
    EvaluationResult,
    OperatorWarning,
    SeriesData,
    evaluate_expression,
)
from cash_research.calculations.time_alignment import (
    CompanyAction,
    EventRevisionTable,
    FieldTimeMetadata,
    HistoricalRecord,
    QualificationEvidence,
    historical_handlers,
)
from cash_research.calculations.trials import (
    HoldoutExposure,
    TrialStart,
    freeze_experiment,
    holdout_exposure,
    mark_holdout_exposure,
    record_trial_outcome,
    start_trial,
    trial_counts,
    verify_frozen_experiment,
)
from cash_research.calculations.validation import (
    BaselineComparison,
    CostImpact,
    CrossPeriodStability,
    IntervalEstimate,
    MetricResult,
    PartitionName,
    SampleFlags,
    SplitCounts,
    assign_partition,
    block_resample_mean,
    classify_sample,
    compare_to_baseline,
    compute_primary_metric,
    cost_impact,
    count_split,
    cross_period_stability,
    holdout_status_label,
    partition_end_indices,
    row_timestamp,
    signal_direction,
    target_direction,
    trading_simulation_supported,
)


ENGINE_VERSION = "factor-1.0"
ExecutionStatus = Literal[
    "completed",
    "not_executable_as_full_factor_experiment",
]


class FactorError(ValueError):
    """Raised when a factor experiment cannot be computed safely."""


@dataclass(frozen=True)
class ParameterSetOutput:
    parameter_set_id: str
    values: tuple[float | bool | None, ...]
    warnings: tuple[dict[str, object], ...]
    split_counts: dict[str, SplitCounts]
    sample_flags: tuple[SampleFlags, ...]
    metrics: dict[str, float | None]
    metric_detail: MetricResult
    baseline: BaselineComparison | None
    partition_metrics: dict[str, float | None]
    stability: CrossPeriodStability
    costs: CostImpact
    interval: IntervalEstimate
    trial: TrialStart | None = None


@dataclass(frozen=True)
class FactorExperimentResult:
    request_id: str
    execution_status: ExecutionStatus
    engine_version: str
    parameter_outputs: dict[str, tuple[float | bool | None, ...]]
    target_values: tuple[float | None, ...] | None
    metrics: dict[str, float | None]
    metric_scope: dict[str, object]
    split_counts_by_parameter_set: dict[str, dict[str, dict[str, int]]]
    parameter_results: tuple[ParameterSetOutput, ...]
    trial_count: dict[str, int]
    warnings: tuple[dict[str, object], ...]
    infinite_output_count: int
    trading_simulation_supported: bool
    returns_are_executable: bool
    limitation: str | None
    holdout_status: str
    holdout_exposure: HoldoutExposure | None
    conclusion: str | None
    baseline_comparison: BaselineComparison | None
    descriptive_all_rows: dict[str, object] | None = None
    final_holdout: dict[str, object] | None = None
    asof_values: dict[str, float | None] | None = None
    selected_values: dict[str, float | None] | None = None
    future_truncation: dict[str, object] | None = None
    experiment_id: str | None = None
    request_hash: str | None = None
    extras: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "request_id": self.request_id,
            "execution_status": self.execution_status,
            "engine_version": self.engine_version,
            "parameter_outputs": {
                key: list(values) for key, values in self.parameter_outputs.items()
            },
            "target_values": None if self.target_values is None else list(self.target_values),
            "metrics": dict(self.metrics),
            "metric_scope": dict(self.metric_scope),
            "split_counts_by_parameter_set": self.split_counts_by_parameter_set,
            "trial_count": dict(self.trial_count),
            "warnings": list(self.warnings),
            "infinite_output_count": self.infinite_output_count,
            "trading_simulation_supported": self.trading_simulation_supported,
            "returns_are_executable": self.returns_are_executable,
            "limitation": self.limitation,
            "holdout_status": self.holdout_status,
            "conclusion": self.conclusion,
            "experiment_id": self.experiment_id,
            "request_hash": self.request_hash,
        }
        if self.descriptive_all_rows is not None:
            payload["descriptive_all_rows"] = self.descriptive_all_rows
        if self.final_holdout is not None:
            payload["final_holdout"] = self.final_holdout
        if self.asof_values is not None:
            payload["asof_values"] = self.asof_values
        if self.selected_values is not None:
            payload["selected_values"] = self.selected_values
        if self.future_truncation is not None:
            payload["future_truncation"] = self.future_truncation
        if self.baseline_comparison is not None:
            payload["baseline_comparison"] = {
                "metric": self.baseline_comparison.metric,
                "factor_value": self.baseline_comparison.factor_value,
                "baseline_value": self.baseline_comparison.baseline_value,
                "increment": self.baseline_comparison.increment,
                "conclusion": self.baseline_comparison.conclusion,
            }
        return payload


def load_dataset(path: str | Path) -> dict[str, object]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FactorError("dataset must be a JSON object")
    return data


def compute_forward_returns(
    values: Sequence[float | None],
    horizon: int,
) -> tuple[float | None, ...]:
    if horizon < 1:
        raise FactorError("forward-return horizon must be positive")
    result: list[float | None] = []
    for index, value in enumerate(values):
        end = index + horizon
        if end >= len(values) or value is None or values[end] is None:
            result.append(None)
            continue
        start = float(value)
        finish = float(values[end])  # type: ignore[arg-type]
        if start == 0:
            result.append(None)
            continue
        result.append(finish / start - 1.0)
    return tuple(result)


def compute_targets(
    request: Mapping[str, object],
    dataset: Mapping[str, object],
) -> tuple[float | None, ...] | None:
    target_spec = request.get("target_spec")
    if not isinstance(target_spec, Mapping):
        raise FactorError("target_spec is required")
    rows = dataset.get("rows")
    if not isinstance(rows, list):
        raise FactorError("dataset rows are required")
    operation = target_spec.get("operation")
    field_name = target_spec.get("field")
    horizon = target_spec.get("horizon")
    if not isinstance(field_name, str) or not isinstance(horizon, int) or isinstance(horizon, bool):
        raise FactorError("target_spec field/horizon are invalid")
    if operation == "provided_field":
        if any(field_name not in row for row in rows if isinstance(row, Mapping)):
            return None
        return tuple(
            None if row.get(field_name) is None else float(row[field_name])  # type: ignore[arg-type]
            for row in rows
            if isinstance(row, Mapping)
        )
    if operation == "forward_return":
        if any(field_name not in row for row in rows if isinstance(row, Mapping)):
            return None
        series = [
            None if row.get(field_name) is None else float(row[field_name])  # type: ignore[arg-type]
            for row in rows
            if isinstance(row, Mapping)
        ]
        return compute_forward_returns(series, horizon)
    raise FactorError(f"unsupported target operation: {operation}")


def evaluate_parameter_set(
    compiled: ValidatedExpression,
    *,
    context: EvaluationContext,
    parameter_set: BoundParameterSet,
    historical: Mapping[str, object] | None = None,
) -> EvaluationResult:
    return evaluate_expression(
        compiled.root,
        context=context,
        parameter_set=parameter_set,
        historical_handlers=historical,  # type: ignore[arg-type]
    )


def truncate_dataset(
    dataset: Mapping[str, object],
    *,
    cutoff_index: int | None = None,
    cutoff_time: str | datetime | None = None,
) -> dict[str, object]:
    """Return a copy of ``dataset`` with future rows removed for truncation checks."""

    rows = dataset.get("rows")
    if not isinstance(rows, list):
        raise FactorError("dataset rows are required")
    fields = dataset.get("fields")
    if not isinstance(fields, Mapping):
        raise FactorError("dataset fields are required")
    if cutoff_index is not None:
        kept = rows[: cutoff_index + 1]
    elif cutoff_time is not None:
        instant = (
            cutoff_time
            if isinstance(cutoff_time, datetime)
            else datetime.fromisoformat(str(cutoff_time))
        )
        kept = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            available_field = next(iter(fields.values()))["available_at"]
            assert isinstance(available_field, str)
            available = datetime.fromisoformat(str(row[available_field]))
            if available <= instant:
                kept.append(row)
    else:
        raise FactorError("truncation requires cutoff_index or cutoff_time")
    clone = dict(dataset)
    clone["rows"] = list(kept)
    return clone


def run_factor_experiment(
    request: Mapping[str, object],
    dataset: Mapping[str, object],
    *,
    root: str | Path | None = None,
    decision_times: Sequence[str | datetime] | None = None,
    record_trials: bool = False,
    view_holdout: bool = False,
    execution_config: Mapping[str, object] | None = None,
    company_actions: Sequence[CompanyAction] = (),
) -> FactorExperimentResult:
    """Compute one factor experiment against an explicit dataset snapshot."""

    try:
        compiled = validate_expression(
            request["expression"],
            dataset=dataset,
            parameter_schema=request.get("parameter_schema", {}),
            parameter_sets=request["parameter_sets"],
        )
    except ExpressionValidationError as exc:
        raise FactorError(str(exc)) from exc
    except KeyError as exc:
        raise FactorError(f"request is missing field {exc}") from exc

    targets = compute_targets(request, dataset)
    uses_historical = any(
        node.op in {"asof_value", "event_age"}
        for node in _walk_bound(compiled.root)
    )
    bar_rows = _bar_like_rows(dataset)
    full_experiment = targets is not None and bar_rows and not (
        uses_historical and not _rows_have_field(dataset, _target_field(request))
    )
    # Operator-only / missing-target cases stay research-limited.
    if targets is None or (uses_historical and not bar_rows):
        full_experiment = False

    simulation_ok = trading_simulation_supported(str(request.get("available_time_rule", "")))
    limitation = None
    if not simulation_ok:
        limitation = (
            "trading simulation unsupported; reported forward-return statistics are "
            "research distributions, not executable returns"
        )

    context, historical = _build_context(
        compiled,
        dataset,
        decision_times=decision_times,
        company_actions=company_actions,
        uses_historical=uses_historical,
    )

    experiment_id: str | None = None
    request_hash: str | None = None
    exposure: HoldoutExposure | None = None
    prior_holdout_seen = False
    if root is not None and record_trials:
        frozen = freeze_experiment(root, request)
        experiment_id = frozen.experiment_id
        request_hash = frozen.request_hash
        verify_frozen_experiment(root, experiment_id)
        exposure = holdout_exposure(root, experiment_id)
        prior_holdout_seen = exposure.seen

    viewed_holdout = False
    parameter_results: list[ParameterSetOutput] = []
    all_warnings: list[dict[str, object]] = []
    infinite_count = 0
    config = dict(execution_config or {"engine_version": ENGINE_VERSION})

    zone_name = (
        dataset["market_timezone"]
        if isinstance(dataset.get("market_timezone"), str)
        else "America/New_York"
    )
    rows = [row for row in dataset["rows"] if isinstance(row, Mapping)]  # type: ignore[index]
    fields = dataset["fields"]
    assert isinstance(fields, Mapping)
    timestamps = [row_timestamp(row, fields) for row in rows]  # type: ignore[arg-type]
    split = request["split"]
    assert isinstance(split, Mapping)
    partitions: list[PartitionName | None]
    if full_experiment:
        partitions = [
            assign_partition(instant, split, zone_name=zone_name) for instant in timestamps
        ]
    else:
        partitions = [None for _ in rows]
    ends = partition_end_indices(partitions)
    horizon = int(request["target_spec"]["horizon"])  # type: ignore[index]
    target_operation = str(request.get("target_spec", {}).get("operation", ""))  # type: ignore[union-attr]
    label_available_at_field = _label_available_field(dataset, request)

    for parameter_set in compiled.parameter_sets:
        trial = None
        if root is not None and record_trials and experiment_id is not None:
            trial = start_trial(
                root,
                experiment_id,
                parameter_set.parameter_set_id,
                execution_config=config,
            )
            if view_holdout and not viewed_holdout:
                exposure = mark_holdout_exposure(root, trial.trial_id)
                viewed_holdout = True
                prior_holdout_seen = prior_holdout_seen or exposure.previously_seen

        evaluated = evaluate_parameter_set(
            compiled,
            context=context,
            parameter_set=parameter_set,
            historical=historical,
        )
        values = tuple(
            None if value is None else value
            for value in evaluated.series.values
        )
        warnings = tuple(
            _warning_dict(item, index=context.index) for item in evaluated.warnings
        )
        all_warnings.extend(warnings)
        infinite_count += sum(
            1
            for item in evaluated.warnings
            if item.reason in {"nonfinite_output"}
        )

        if full_experiment and targets is not None:
            flags = tuple(
                _classify_row(
                    row_index=index,
                    row=rows[index],
                    partition=partitions[index],
                    feature_value=values[index] if index < len(values) else None,
                    horizon=horizon,
                    row_count=len(rows),
                    partition_end_index=(
                        ends[partitions[index]] if partitions[index] is not None else None
                    ),
                    target_operation=target_operation,
                    label_available_at_field=label_available_at_field,
                    split=split,
                    zone_name=zone_name,
                    target_value=targets[index],
                )
                for index in range(len(rows))
            )
            split_counts = {
                name: count_split(flags, name)
                for name in ("train", "validation", "final_holdout")
            }
            partition_metrics: dict[str, float | None] = {}
            for name in ("train", "validation", "final_holdout"):
                mask = [flag.partition == name and flag.usable for flag in flags]
                metric = compute_primary_metric(
                    str(request["primary_metric"]),
                    [value for value, keep in zip(values, mask) if keep],
                    [value for value, keep in zip(targets, mask) if keep],
                )
                partition_metrics[name] = metric.value
            primary_name_local = str(request["primary_metric"])
            if primary_name_local == "directional_accuracy":
                primary = _aggregate_primary(primary_name_local, values, targets, flags)
                holdout_mask = [
                    flag.usable and flag.partition == "final_holdout" for flag in flags
                ]
                if not any(holdout_mask) and target_operation == "provided_field":
                    holdout_mask = [
                        flag.partition == "final_holdout" and flag.feature_available
                        for flag in flags
                    ]
                if any(holdout_mask):
                    holdout_metric = compute_primary_metric(
                        "directional_accuracy",
                        [value for value, keep in zip(values, holdout_mask) if keep],
                        [value for value, keep in zip(targets, holdout_mask) if keep],
                    )
                    if holdout_metric.sample_count >= 2:
                        primary = holdout_metric
                baseline = compare_to_baseline(
                    primary=primary,
                    signals=[value for value, keep in zip(values, holdout_mask) if keep]
                    if any(holdout_mask)
                    else values,
                    targets=[value for value, keep in zip(targets, holdout_mask) if keep]
                    if any(holdout_mask)
                    else targets,
                    baseline_spec=request["baseline_spec"],  # type: ignore[arg-type]
                )
            else:
                primary = compute_primary_metric(primary_name_local, values, targets)
                baseline = None
            usable_mask = [flag.usable for flag in flags]
            active_returns = [
                float(target) * (signal_direction(signal) or 0)
                for signal, target, keep in zip(values, targets, usable_mask)
                if keep
                and signal is not None
                and target is not None
                and signal_direction(signal) not in (None, 0)
            ]
            interval = block_resample_mean(
                active_returns,
                block_length=max(1, horizon),
            )
            costs = cost_impact(
                costs=request["costs"],  # type: ignore[arg-type]
                signals=values,
                targets=targets,
                simulation_supported=simulation_ok,
            )
            stability = cross_period_stability(partition_metrics)
        else:
            flags = tuple(
                SampleFlags(None, value is not None, False, False, None) for value in values
            )
            split_counts = {
                name: SplitCounts(0, 0, 0, 0)
                for name in ("train", "validation", "final_holdout")
            }
            newly_available = None
            if uses_historical:
                newly_available = tuple(
                    available is not None
                    and decision is not None
                    and available == decision
                    for available, decision in zip(
                        evaluated.series.available_at, context.index
                    )
                )
            primary = compute_primary_metric(
                str(request["primary_metric"]),
                values,
                targets,
                newly_available=newly_available,
            )
            baseline = None
            partition_metrics = {}
            interval = IntervalEstimate(
                False, "mean", None, None, None, max(1, horizon), 0, "full_experiment_unavailable"
            )
            costs = cost_impact(
                costs=request["costs"],  # type: ignore[arg-type]
                signals=values,
                targets=targets or (),
                simulation_supported=False,
            )
            stability = CrossPeriodStability(False, (), None, "full_experiment_unavailable")

        metrics = {primary.name: primary.value}
        if baseline is not None and baseline.baseline_value is not None:
            metrics["baseline_directional_accuracy"] = baseline.baseline_value
            metrics["increment"] = baseline.increment

        if trial is not None and root is not None:
            record_trial_outcome(
                root,
                trial.trial_id,
                status="completed",
                reason="factor computation completed",
            )

        parameter_results.append(
            ParameterSetOutput(
                parameter_set_id=parameter_set.parameter_set_id,
                values=values,
                warnings=warnings,
                split_counts=split_counts,
                sample_flags=flags,
                metrics=metrics,
                metric_detail=primary,
                baseline=baseline,
                partition_metrics=partition_metrics,
                stability=stability,
                costs=costs,
                interval=interval,
                trial=trial,
            )
        )

    primary_name = str(request["primary_metric"])
    # Aggregate metrics: for multi-parameter insufficient cases keep null; for
    # single-parameter studies use that parameter's metrics.
    if len(parameter_results) == 1:
        top_metrics = dict(parameter_results[0].metrics)
        top_baseline = parameter_results[0].baseline
        top_detail = parameter_results[0].metric_detail
        conclusion = top_baseline.conclusion if top_baseline else None
    else:
        # new_combination: both sets have insufficient per-partition samples.
        top_detail = parameter_results[0].metric_detail
        if all(
            item.metric_detail.minimum_sample_status == "insufficient_for_effect_conclusion"
            for item in parameter_results
        ):
            top_metrics = {primary_name: None}
            top_baseline = None
            conclusion = None
        else:
            top_metrics = dict(parameter_results[0].metrics)
            top_baseline = parameter_results[0].baseline
            conclusion = top_baseline.conclusion if top_baseline else None

    metric_scope = {
        "evaluation": "per_parameter_set_per_partition",
        "zero_signal": "abstain",
        "denominator": top_detail.scope,
        "minimum_sample_status": top_detail.minimum_sample_status,
    }

    split_payload = {
        item.parameter_set_id: {
            name: {
                "candidate": counts.candidate,
                "feature_available": counts.feature_available,
                "label_within_partition": counts.label_within_partition,
                "usable": counts.usable,
            }
            for name, counts in item.split_counts.items()
        }
        for item in parameter_results
    }

    counts = {"planned": len(parameter_results), "failed": 0, "replay": 0}
    if root is not None and record_trials and experiment_id is not None:
        ledger = trial_counts(root, experiment_id=experiment_id)
        counts = {
            "planned": len(parameter_results),
            "failed": ledger["failed_or_abandoned"],
            "replay": ledger["replays"],
        }

    holdout_label = holdout_status_label(
        exposure if exposure is not None else HoldoutExposure(False, False, ()),
        viewed_this_run=viewed_holdout or prior_holdout_seen,
    )
    if prior_holdout_seen or viewed_holdout:
        # Once viewed, later output must not claim unseen.
        if holdout_label == "unseen":
            holdout_label = "previously_viewed_exploratory"

    descriptive = None
    final_holdout_payload = None
    asof_payload = None
    selected_payload = None
    if primary_name == "directional_accuracy" and targets is not None and len(parameter_results) == 1:
        values = parameter_results[0].values
        descriptive = {
            "signal_direction": [signal_direction(value) for value in values],
            "target_direction": [target_direction(value) for value in targets],
        }
        matches = [
            signal_direction(signal) == target_direction(target)
            for signal, target in zip(values, targets)
            if signal is not None and target is not None and signal_direction(signal) != 0
        ]
        if matches:
            descriptive["directional_accuracy"] = sum(matches) / len(matches)
        if request.get("baseline_spec", {}).get("kind") == "constant_direction":  # type: ignore[union-attr]
            baseline_all = compare_to_baseline(
                primary=MetricResult(
                    "directional_accuracy",
                    descriptive.get("directional_accuracy"),  # type: ignore[arg-type]
                    len(matches),
                    "descriptive_sample_available",
                    "all_rows",
                ),
                signals=values,
                targets=targets,
                baseline_spec=request["baseline_spec"],  # type: ignore[arg-type]
            )
            descriptive["baseline_directional_accuracy"] = baseline_all.baseline_value
            if (
                descriptive.get("directional_accuracy") is not None
                and baseline_all.baseline_value is not None
            ):
                descriptive["increment"] = (
                    float(descriptive["directional_accuracy"]) - baseline_all.baseline_value
                )
        flags = parameter_results[0].sample_flags
        holdout_indices = [
            index
            for index, flag in enumerate(flags)
            if flag.partition == "final_holdout" and flag.usable
        ]
        # For provided-field targets, include holdout candidates with features even
        # when label_available_at purge uses a different rule.
        if not holdout_indices and str(request.get("target_spec", {}).get("operation")) == "provided_field":  # type: ignore[union-attr]
            holdout_indices = [
                index
                for index, flag in enumerate(flags)
                if flag.partition == "final_holdout" and flag.feature_available
            ]
            # Fall back to split membership when purge metadata is label_available_at.
            if not holdout_indices:
                holdout_indices = [
                    index
                    for index, part in enumerate(partitions)
                    if part == "final_holdout"
                ]
        if holdout_indices:
            holdout_signals = [signal_direction(values[index]) for index in holdout_indices]
            holdout_targets = [target_direction(targets[index]) for index in holdout_indices]
            holdout_matches = [
                signal == target
                for signal, target in zip(holdout_signals, holdout_targets)
                if signal is not None and target is not None
            ]
            final_holdout_payload = {
                "row_indices": holdout_indices,
                "minimum_samples": 2,
                "sample_count": len(holdout_indices),
                "signal_direction": holdout_signals,
                "target_direction": holdout_targets,
                "matches": holdout_matches,
            }

    if uses_historical and decision_times is not None and len(parameter_results) == 1:
        mapping = {
            (time if isinstance(time, str) else time.isoformat()): (
                None if value is None else float(value)  # type: ignore[arg-type]
            )
            for time, value in zip(decision_times, parameter_results[0].values)
        }
        if primary_name == "selected_value":
            selected_payload = mapping
        else:
            asof_payload = mapping

    status: ExecutionStatus = (
        "completed" if full_experiment else "not_executable_as_full_factor_experiment"
    )
    if not full_experiment and limitation is None:
        limitation = "operator_or_target_series_incomplete_for_full_factor_experiment"

    return FactorExperimentResult(
        request_id=str(request.get("request_id", "anonymous")),
        execution_status=status,
        engine_version=ENGINE_VERSION,
        parameter_outputs={
            item.parameter_set_id: item.values for item in parameter_results
        },
        target_values=targets,
        metrics=top_metrics,
        metric_scope=metric_scope,
        split_counts_by_parameter_set=split_payload,
        parameter_results=tuple(parameter_results),
        trial_count=counts,
        warnings=tuple(all_warnings),
        infinite_output_count=infinite_count,
        trading_simulation_supported=simulation_ok,
        returns_are_executable=False,
        limitation=limitation,
        holdout_status=holdout_label,
        holdout_exposure=exposure,
        conclusion=conclusion,
        baseline_comparison=top_baseline,
        descriptive_all_rows=descriptive,
        final_holdout=final_holdout_payload,
        asof_values=asof_payload,
        selected_values=selected_payload,
        experiment_id=experiment_id,
        request_hash=request_hash,
    )


def recompute_matches(
    left: FactorExperimentResult,
    right: FactorExperimentResult,
    *,
    absolute_tolerance: float = 1e-12,
) -> bool:
    """Exact recomputation check within the fixture absolute tolerance."""

    if left.parameter_outputs.keys() != right.parameter_outputs.keys():
        return False
    for key, values in left.parameter_outputs.items():
        other = right.parameter_outputs[key]
        if len(values) != len(other):
            return False
        for a, b in zip(values, other):
            if a is None or b is None:
                if a is not b:
                    return False
            elif isinstance(a, bool) or isinstance(b, bool):
                if a is not b:
                    return False
            elif not math.isclose(float(a), float(b), abs_tol=absolute_tolerance, rel_tol=0):
                return False
    if left.metrics != right.metrics:
        # Allow float closeness on metric values.
        if left.metrics.keys() != right.metrics.keys():
            return False
        for key, value in left.metrics.items():
            other = right.metrics[key]
            if value is None or other is None:
                if value is not other:
                    return False
            elif not math.isclose(float(value), float(other), abs_tol=absolute_tolerance, rel_tol=0):
                return False
    return left.execution_status == right.execution_status


def _aggregate_primary(
    name: str,
    values: Sequence[float | bool | None],
    targets: Sequence[float | None],
    flags: Sequence[SampleFlags],
) -> MetricResult:
    if name != "directional_accuracy":
        mask = [flag.usable for flag in flags]
        return compute_primary_metric(
            name,
            [value for value, keep in zip(values, mask) if keep],
            [value for value, keep in zip(targets, mask) if keep],
        )
    # Per-partition evaluation: if every partition with usable rows is below the
    # descriptive threshold, the overall effect metric stays null.
    statuses: list[MetricResult] = []
    for partition in ("train", "validation", "final_holdout"):
        mask = [flag.usable and flag.partition == partition for flag in flags]
        if not any(mask):
            continue
        statuses.append(
            compute_primary_metric(
                name,
                [value for value, keep in zip(values, mask) if keep],
                [value for value, keep in zip(targets, mask) if keep],
            )
        )
    if not statuses:
        return MetricResult(
            name,
            None,
            0,
            "insufficient_for_effect_conclusion",
            "non_null_nonzero_signal_with_label",
        )
    if all(item.minimum_sample_status == "insufficient_for_effect_conclusion" for item in statuses):
        return MetricResult(
            name,
            None,
            sum(item.sample_count for item in statuses),
            "insufficient_for_effect_conclusion",
            "non_null_nonzero_signal_with_label",
        )
    # Otherwise combine usable out-of-train rows.
    mask = [flag.usable and flag.partition != "train" for flag in flags]
    return compute_primary_metric(
        name,
        [value for value, keep in zip(values, mask) if keep],
        [value for value, keep in zip(targets, mask) if keep],
    )


def _build_context(
    compiled: ValidatedExpression,
    dataset: Mapping[str, object],
    *,
    decision_times: Sequence[str | datetime] | None,
    company_actions: Sequence[CompanyAction],
    uses_historical: bool,
) -> tuple[EvaluationContext, dict[str, object] | None]:
    rows = [row for row in dataset["rows"] if isinstance(row, Mapping)]  # type: ignore[index]
    fields_meta = dataset["fields"]
    assert isinstance(fields_meta, Mapping)

    if uses_historical:
        decisions = _decision_index(decision_times, rows, fields_meta)
        table = _event_table(dataset, compiled, company_actions=company_actions)
        # Provide placeholder aligned fields for the decision index.
        field_series: dict[str, SeriesData] = {}
        for name in compiled.referenced_fields:
            field_series[name] = SeriesData(
                decisions,
                tuple(None for _ in decisions),
                tuple(None for _ in decisions),
            )
        context = EvaluationContext(index=decisions, fields=field_series)
        return context, historical_handlers(table)

    if decision_times is not None:
        index = tuple(
            item if isinstance(item, datetime) else datetime.fromisoformat(str(item))
            for item in decision_times
        )
    else:
        index = tuple(row_timestamp(row, fields_meta) for row in rows)  # type: ignore[arg-type]
        # Prefer explicit timestamp strings as index labels when present so
        # truncation tests can compare by position stably.
        if rows and "timestamp" in rows[0]:
            index = tuple(str(row["timestamp"]) for row in rows)

    field_series = {}
    for name, meta in fields_meta.items():
        assert isinstance(meta, Mapping)
        available_field = meta["available_at"]
        assert isinstance(available_field, str)
        values = []
        availability = []
        for row in rows:
            raw = row.get(name)
            if raw is None:
                values.append(None)
            elif isinstance(raw, bool):
                values.append(raw)
            else:
                values.append(float(raw))  # type: ignore[arg-type]
            availability.append(datetime.fromisoformat(str(row[available_field])))
        # When index is string timestamps, keep availability aligned by row order.
        if index and not isinstance(index[0], datetime):
            field_series[name] = SeriesData(index, tuple(values), tuple(availability))
        else:
            field_series[name] = SeriesData(index, tuple(values), tuple(availability))
    return EvaluationContext(index=index, fields=field_series), None


def _decision_index(
    decision_times: Sequence[str | datetime] | None,
    rows: Sequence[Mapping[str, object]],
    fields_meta: Mapping[str, object],
) -> tuple[datetime, ...]:
    if decision_times is not None:
        return tuple(
            item if isinstance(item, datetime) else datetime.fromisoformat(str(item))
            for item in decision_times
        )
    # Default: unique available_at / timestamp values from the event table.
    times: list[datetime] = []
    for row in rows:
        for key in ("available_at", "timestamp", "observed_at"):
            if key in row:
                value = row[key]
                if isinstance(value, str) and "T" in value:
                    times.append(datetime.fromisoformat(value))
                break
    if not times:
        raise FactorError("historical evaluation requires decision_times")
    return tuple(sorted({item.astimezone(timezone.utc): item for item in times}.values(), key=lambda item: item.astimezone(timezone.utc)))


def _event_table(
    dataset: Mapping[str, object],
    compiled: ValidatedExpression,
    *,
    company_actions: Sequence[CompanyAction],
) -> EventRevisionTable:
    rows = [row for row in dataset["rows"] if isinstance(row, Mapping)]  # type: ignore[index]
    fields_meta = dataset["fields"]
    assert isinstance(fields_meta, Mapping)
    zone = dataset.get("market_timezone")
    if not isinstance(zone, str):
        zone = "America/New_York"

    records: dict[str, list[HistoricalRecord]] = {}
    metadata: dict[str, FieldTimeMetadata] = {}
    for field_name in compiled.referenced_fields:
        meta = fields_meta[field_name]
        assert isinstance(meta, Mapping)
        observed_key = str(meta["observed_at"])
        available_key = str(meta["available_at"])
        revision_key = meta.get("revision")
        revision_name = str(revision_key) if isinstance(revision_key, str) else None
        field_records: list[HistoricalRecord] = []
        for row in rows:
            observed_raw = row[observed_key]
            if isinstance(observed_raw, str) and "T" not in observed_raw:
                observed: date | datetime = date.fromisoformat(observed_raw)
            else:
                observed = datetime.fromisoformat(str(observed_raw))
            available = datetime.fromisoformat(str(row[available_key]))
            revision_id = None if revision_name is None else str(row[revision_name])
            field_records.append(
                HistoricalRecord(
                    field_name,
                    float(row[field_name]),  # type: ignore[arg-type]
                    observed,
                    available,
                    revision_id,
                )
            )
        records[field_name] = field_records
        basis = "other"
        output_basis = None
        if company_actions:
            basis = "raw_price"
            output_basis = "adjusted_price"
        metadata[field_name] = FieldTimeMetadata(
            observed_key,
            available_key,
            revision_name,
            basis,  # type: ignore[arg-type]
            zone if any(isinstance(item.observed_at, date) and not isinstance(item.observed_at, datetime) for item in field_records) else None,
            output_basis,  # type: ignore[arg-type]
        )

    all_available = [record.available_at for group in records.values() for record in group]
    all_observed = [record.observed_at for group in records.values() for record in group]
    assert all_available and all(item is not None for item in all_available)
    # Knowledge window must cover decision times used by research evaluation, not
    # only the event availability instants themselves.
    knowledge_start = datetime(1970, 1, 1, tzinfo=timezone.utc)
    knowledge_end = datetime(2099, 1, 1, tzinfo=timezone.utc)
    if any(isinstance(item, datetime) for item in all_observed):
        coverage_start: date | datetime = min(
            (
                item
                if isinstance(item, datetime)
                else datetime.combine(item, time.min, tzinfo=timezone.utc)
            )
            for item in all_observed
        )
        coverage_end: date | datetime = max(
            (
                item
                if isinstance(item, datetime)
                else datetime.combine(item, time.min, tzinfo=timezone.utc)
            )
            for item in all_observed
        )
    else:
        coverage_start = min(item for item in all_observed if type(item) is date)
        coverage_end = max(item for item in all_observed if type(item) is date)

    qualification = QualificationEvidence(
        (str(dataset.get("dataset_id", "fixture")),),
        coverage_start,
        coverage_end,
        knowledge_start,
        knowledge_end,
        knowledge_end,
        "complete",
    )
    action_coverage = None
    if company_actions:
        action_coverage = QualificationEvidence(
            ("actions",),
            knowledge_start,
            datetime(2099, 1, 1, tzinfo=timezone.utc),
            knowledge_start,
            datetime(2099, 1, 1, tzinfo=timezone.utc),
            datetime(2099, 1, 1, tzinfo=timezone.utc),
            "complete",
        )
    return EventRevisionTable(
        {name: tuple(items) for name, items in records.items()},
        metadata,
        qualification,
        tuple(company_actions),
        action_coverage,
    )


def _walk_bound(node: object) -> list[object]:
    from cash_research.calculations.expression import BoundNode

    assert isinstance(node, BoundNode)
    nodes: list[object] = [node]
    for child in node.args:
        nodes.extend(_walk_bound(child))
    return nodes


def _bar_like_rows(dataset: Mapping[str, object]) -> bool:
    rows = dataset.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    row = rows[0]
    return isinstance(row, Mapping) and ("timestamp" in row or "close" in row or "signal" in row)


def _rows_have_field(dataset: Mapping[str, object], field_name: str | None) -> bool:
    if field_name is None:
        return False
    rows = dataset.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    row = rows[0]
    return isinstance(row, Mapping) and field_name in row


def _target_field(request: Mapping[str, object]) -> str | None:
    spec = request.get("target_spec")
    if isinstance(spec, Mapping) and isinstance(spec.get("field"), str):
        return spec["field"]
    return None


def _warning_dict(
    warning: OperatorWarning, *, index: tuple[object, ...] | None = None
) -> dict[str, object]:
    row_index: object = warning.row_index
    if index is not None and warning.row_index in index:
        row_index = index.index(warning.row_index)
    return {"row_index": row_index, "reason": warning.reason}


def _label_available_field(
    dataset: Mapping[str, object], request: Mapping[str, object]
) -> str | None:
    fields = dataset.get("fields")
    target_spec = request.get("target_spec")
    if not isinstance(fields, Mapping) or not isinstance(target_spec, Mapping):
        return None
    field_name = target_spec.get("field")
    if not isinstance(field_name, str) or field_name not in fields:
        return None
    meta = fields[field_name]
    if isinstance(meta, Mapping) and isinstance(meta.get("available_at"), str):
        return str(meta["available_at"])
    return None


def _classify_row(
    *,
    row_index: int,
    row: Mapping[str, object],
    partition: PartitionName | None,
    feature_value: float | bool | None,
    horizon: int,
    row_count: int,
    partition_end_index: int | None,
    target_operation: str,
    label_available_at_field: str | None,
    split: Mapping[str, object],
    zone_name: str | None,
    target_value: float | None,
) -> SampleFlags:
    if target_operation == "provided_field" and label_available_at_field and partition is not None:
        feature_available = feature_value is not None and target_value is not None
        available_raw = row.get(label_available_at_field)
        if available_raw is None:
            return SampleFlags(partition, feature_available, False, False, None)
        label_available = (
            available_raw
            if isinstance(available_raw, datetime)
            else datetime.fromisoformat(str(available_raw))
        )
        window = split[partition]
        assert isinstance(window, Mapping)
        from cash_research.calculations.validation import parse_boundary

        partition_end = parse_boundary(window.get("end"), zone_name=zone_name, end=True)
        label_within = label_available <= partition_end
        return SampleFlags(
            partition,
            feature_available,
            label_within,
            feature_available and label_within,
            None,
        )
    return classify_sample(
        row_index=row_index,
        partition=partition,
        feature_value=feature_value,
        horizon=horizon,
        row_count=row_count,
        partition_end_index=partition_end_index,
    )
