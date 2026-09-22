"""Time-split validation, metrics, costs, and holdout status for factor studies.

This module does not emit buy/sell decisions.  It scores declared signals against
declared targets under the request's split, baseline, and cost declarations.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cash_research.calculations.trials import HoldoutExposure


PartitionName = Literal["train", "validation", "final_holdout"]
_PARTITIONS: tuple[PartitionName, ...] = ("train", "validation", "final_holdout")


class FactorValidationError(ValueError):
    """Raised when split, target, or metric inputs are inconsistent."""


@dataclass(frozen=True)
class SplitCounts:
    candidate: int
    feature_available: int
    label_within_partition: int
    usable: int


@dataclass(frozen=True)
class SampleFlags:
    partition: PartitionName | None
    feature_available: bool
    label_within_partition: bool
    usable: bool
    label_end_index: int | None


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: float | None
    sample_count: int
    minimum_sample_status: str
    scope: str


@dataclass(frozen=True)
class BaselineComparison:
    metric: str
    factor_value: float | None
    baseline_value: float | None
    increment: float | None
    conclusion: str | None


@dataclass(frozen=True)
class CostImpact:
    applicable: bool
    commission_bps: float
    slippage_bps: float
    total_bps: float
    reason: str | None
    gross_mean: float | None = None
    net_mean: float | None = None


@dataclass(frozen=True)
class IntervalEstimate:
    available: bool
    statistic: str
    point: float | None
    lower: float | None
    upper: float | None
    block_length: int
    resamples: int
    reason: str | None


@dataclass(frozen=True)
class CrossPeriodStability:
    available: bool
    partition_metrics: tuple[tuple[str, float | None], ...]
    sign_agreement: bool | None
    reason: str | None


def parse_boundary(value: object, *, zone_name: str | None, end: bool) -> datetime:
    """Parse a split boundary into a timezone-aware instant."""

    if not isinstance(value, str) or not value:
        raise FactorValidationError("split boundary must be a non-empty string")
    if "T" in value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise FactorValidationError("datetime split boundaries must be timezone-aware")
        return parsed
    if not isinstance(zone_name, str) or not zone_name:
        raise FactorValidationError("date split boundaries require market_timezone")
    try:
        zone = ZoneInfo(zone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise FactorValidationError("market_timezone is invalid") from exc
    day = date.fromisoformat(value)
    return datetime.combine(day, time.max if end else time.min, tzinfo=zone)


def row_timestamp(row: Mapping[str, object], fields: Mapping[str, Mapping[str, object]]) -> datetime:
    """Resolve the observation time used for ordered splits."""

    candidates = ("timestamp", "observed_at", "period_end")
    for name in candidates:
        if name in row:
            return _as_aware(row[name], label=name)
    # Fall back to the first declared observed_at metadata field.
    for meta in fields.values():
        observed = meta.get("observed_at")
        if isinstance(observed, str) and observed in row:
            return _as_aware(row[observed], label=observed)
    raise FactorValidationError("row has no usable observation timestamp")


def assign_partition(
    instant: datetime,
    split: Mapping[str, object],
    *,
    zone_name: str | None,
) -> PartitionName | None:
    """Return the ordered partition containing ``instant``, if any."""

    for name in _PARTITIONS:
        window = split.get(name)
        if not isinstance(window, Mapping):
            raise FactorValidationError(f"split.{name} must be an interval object")
        start = parse_boundary(window.get("start"), zone_name=zone_name, end=False)
        end = parse_boundary(window.get("end"), zone_name=zone_name, end=True)
        if start <= instant <= end:
            return name
    return None


def label_end_index(row_index: int, horizon: int, row_count: int) -> int | None:
    """Index of the bar that completes a forward label, if it exists."""

    if horizon < 1:
        raise FactorValidationError("horizon must be a positive bar count")
    end = row_index + horizon
    if end >= row_count:
        return None
    return end


def classify_sample(
    *,
    row_index: int,
    partition: PartitionName | None,
    feature_value: float | bool | None,
    horizon: int,
    row_count: int,
    partition_end_index: int | None,
) -> SampleFlags:
    """Apply feature availability and label-boundary purge rules."""

    label_end = label_end_index(row_index, horizon, row_count)
    feature_available = feature_value is not None
    if partition is None or partition_end_index is None or label_end is None:
        return SampleFlags(partition, feature_available, False, False, label_end)
    label_within = label_end <= partition_end_index
    usable = feature_available and label_within
    return SampleFlags(partition, feature_available, label_within, usable, label_end)


def partition_end_indices(
    partitions: Sequence[PartitionName | None],
) -> dict[PartitionName, int]:
    """Last row index belonging to each named partition."""

    ends: dict[PartitionName, int] = {}
    for index, name in enumerate(partitions):
        if name is not None:
            ends[name] = index
    return ends


def count_split(
    flags: Sequence[SampleFlags],
    partition: PartitionName,
) -> SplitCounts:
    """Aggregate candidacy / availability / purge / usable counts for one fold."""

    members = [item for item in flags if item.partition == partition]
    return SplitCounts(
        candidate=len(members),
        feature_available=sum(item.feature_available for item in members),
        label_within_partition=sum(item.label_within_partition for item in members),
        usable=sum(item.usable for item in members),
    )


def signal_direction(value: float | bool | None) -> int | None:
    """Map a numeric signal to {-1, 0, +1}; null stays null."""

    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else -1
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def target_direction(value: float | None) -> int | None:
    if value is None:
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def directional_accuracy(
    signals: Sequence[float | bool | None],
    targets: Sequence[float | None],
    *,
    zero_signal: str = "abstain",
) -> MetricResult:
    """Directional hit rate over non-null, non-abstained labeled samples."""

    matches = 0
    count = 0
    for signal, target in zip(signals, targets):
        if signal is None or target is None:
            continue
        direction = signal_direction(signal)
        if direction is None:
            continue
        if direction == 0 and zero_signal == "abstain":
            continue
        if direction == 0:
            continue
        count += 1
        if direction == target_direction(target):
            matches += 1
    if count == 0:
        return MetricResult(
            "directional_accuracy",
            None,
            0,
            "insufficient_for_effect_conclusion",
            "non_null_nonzero_signal_with_label",
        )
    # No invented universal minimum; a single comparable observation is descriptive
    # only and cannot support an effect conclusion for this fixture contract.
    status = (
        "insufficient_for_effect_conclusion"
        if count < 2
        else "descriptive_sample_available"
    )
    value = matches / count if status == "descriptive_sample_available" or count >= 1 else None
    if count < 2:
        value = None
    else:
        value = matches / count
    return MetricResult(
        "directional_accuracy",
        value,
        count,
        status,
        "non_null_nonzero_signal_with_label",
    )


def mean_signal(values: Sequence[float | bool | None]) -> MetricResult:
    numbers = [
        float(value)
        for value in values
        if value is not None and not isinstance(value, bool)
    ]
    if not numbers:
        return MetricResult(
            "mean_signal",
            None,
            0,
            "insufficient_for_effect_conclusion",
            "non_null_signal",
        )
    return MetricResult(
        "mean_signal",
        sum(numbers) / len(numbers),
        len(numbers),
        "descriptive_sample_available",
        "non_null_signal",
    )


def valid_fraction(values: Sequence[float | bool | None]) -> MetricResult:
    if not values:
        return MetricResult(
            "valid_fraction",
            None,
            0,
            "insufficient_for_effect_conclusion",
            "all_rows",
        )
    valid = sum(value is not None for value in values)
    return MetricResult(
        "valid_fraction",
        valid / len(values),
        len(values),
        "descriptive_sample_available",
        "all_rows",
    )


def eligible_observation_count(
    values: Sequence[float | bool | None],
    *,
    newly_available: Sequence[bool] | None = None,
) -> MetricResult:
    if newly_available is not None:
        count = sum(1 for flag in newly_available if flag)
    else:
        count = sum(value is not None for value in values)
    return MetricResult(
        "eligible_observation_count",
        float(count),
        count,
        "descriptive_sample_available",
        "non_null_asof",
    )


def selected_value(values: Sequence[float | bool | None]) -> MetricResult:
    present = [float(value) for value in values if value is not None and not isinstance(value, bool)]
    if not present:
        return MetricResult(
            "selected_value",
            None,
            0,
            "insufficient_for_effect_conclusion",
            "last_non_null",
        )
    return MetricResult(
        "selected_value",
        present[-1],
        len(present),
        "descriptive_sample_available",
        "last_non_null",
    )


def compute_primary_metric(
    name: str,
    signals: Sequence[float | bool | None],
    targets: Sequence[float | None] | None = None,
    *,
    newly_available: Sequence[bool] | None = None,
) -> MetricResult:
    if name == "directional_accuracy":
        if targets is None:
            raise FactorValidationError("directional_accuracy requires targets")
        return directional_accuracy(signals, targets)
    if name == "mean_signal":
        return mean_signal(signals)
    if name == "valid_fraction":
        return valid_fraction(signals)
    if name == "eligible_observation_count":
        return eligible_observation_count(signals, newly_available=newly_available)
    if name == "selected_value":
        return selected_value(signals)
    raise FactorValidationError(f"unsupported primary metric: {name}")


def baseline_directional_accuracy(
    targets: Sequence[float | None],
    baseline_spec: Mapping[str, object],
) -> float | None:
    kind = baseline_spec.get("kind")
    labeled = [value for value in targets if value is not None]
    if not labeled:
        return None
    if kind == "constant_direction":
        direction = signal_direction(baseline_spec.get("value"))  # type: ignore[arg-type]
        if direction is None or direction == 0:
            raise FactorValidationError("constant_direction baseline requires non-zero value")
        matches = sum(1 for value in labeled if target_direction(value) == direction)
        return matches / len(labeled)
    if kind == "unconditional_distribution":
        # Same-security unconditional sign frequency of the target itself.
        positive = sum(1 for value in labeled if value > 0)
        return positive / len(labeled)
    raise FactorValidationError("baseline kind is unsupported")


def compare_to_baseline(
    *,
    primary: MetricResult,
    signals: Sequence[float | bool | None],
    targets: Sequence[float | None],
    baseline_spec: Mapping[str, object],
) -> BaselineComparison:
    if primary.name != "directional_accuracy":
        return BaselineComparison(
            primary.name,
            primary.value,
            None,
            None,
            None,
        )
    baseline = baseline_directional_accuracy(targets, baseline_spec)
    if primary.value is None or baseline is None:
        return BaselineComparison(
            primary.name,
            primary.value,
            baseline,
            None,
            None if primary.value is None else "insufficient_for_effect_conclusion",
        )
    increment = primary.value - baseline
    conclusion = "no_factor_increment" if increment <= 0 else "positive_factor_increment"
    return BaselineComparison(primary.name, primary.value, baseline, increment, conclusion)


def trading_simulation_supported(available_time_rule: str) -> bool:
    """Close-formed signals are research statistics unless a full simulator exists."""

    rule = available_time_rule.lower()
    if "next bar" in rule or "earliest use is next" in rule or "earliest action is the next" in rule:
        return False
    return False


def cost_impact(
    *,
    costs: Mapping[str, object],
    signals: Sequence[float | bool | None],
    targets: Sequence[float | None],
    simulation_supported: bool,
) -> CostImpact:
    commission = float(costs.get("commission_bps") or 0.0)
    slippage = float(costs.get("slippage_bps") or 0.0)
    total = commission + slippage
    if not simulation_supported:
        return CostImpact(
            applicable=False,
            commission_bps=commission,
            slippage_bps=slippage,
            total_bps=total,
            reason="trading_simulation_unsupported; costs are declared but not executable returns",
        )
    paired: list[float] = []
    for signal, target in zip(signals, targets):
        if signal is None or target is None:
            continue
        direction = signal_direction(signal)
        if direction is None or direction == 0:
            continue
        paired.append(float(target) * direction)
    if not paired:
        return CostImpact(
            True,
            commission,
            slippage,
            total,
            "no_active_signals",
            None,
            None,
        )
    gross = sum(paired) / len(paired)
    cost_decimal = total / 10_000.0
    return CostImpact(
        True,
        commission,
        slippage,
        total,
        None,
        gross,
        gross - cost_decimal,
    )


def block_resample_mean(
    values: Sequence[float],
    *,
    block_length: int,
    resamples: int = 64,
    seed: int = 0,
) -> IntervalEstimate:
    """Dependent-series mean interval via circular block resampling."""

    if block_length < 1:
        raise FactorValidationError("block_length must be positive")
    if len(values) < block_length or len(values) < 2:
        return IntervalEstimate(
            False,
            "mean",
            None if not values else sum(values) / len(values),
            None,
            None,
            block_length,
            0,
            "insufficient_dependent_samples_for_interval",
        )
    point = sum(values) / len(values)
    n = len(values)
    means: list[float] = []
    # Deterministic LCG so recomputation is exact without importing random.
    state = seed & 0xFFFFFFFF
    for _ in range(resamples):
        sample: list[float] = []
        while len(sample) < n:
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            start = state % n
            for offset in range(block_length):
                sample.append(values[(start + offset) % n])
                if len(sample) >= n:
                    break
        means.append(sum(sample[:n]) / n)
    ordered = sorted(means)
    lower = ordered[max(0, int(0.025 * (len(ordered) - 1)))]
    upper = ordered[min(len(ordered) - 1, int(0.975 * (len(ordered) - 1)))]
    return IntervalEstimate(True, "mean", point, lower, upper, block_length, resamples, None)


def cross_period_stability(
    partition_metrics: Mapping[str, float | None],
) -> CrossPeriodStability:
    items = tuple((name, partition_metrics.get(name)) for name in _PARTITIONS)
    present = [value for _, value in items if value is not None]
    if len(present) < 2:
        return CrossPeriodStability(
            False,
            items,
            None,
            "insufficient_partitions_with_metric",
        )
    signs = {1 if value > 0 else -1 if value < 0 else 0 for value in present}
    return CrossPeriodStability(True, items, len(signs) == 1, None)


def holdout_status_label(exposure: HoldoutExposure | None, *, viewed_this_run: bool) -> str:
    """Label final-holdout material after exposure rules."""

    if exposure is not None and (exposure.seen or exposure.previously_seen):
        return "previously_viewed_exploratory"
    if viewed_this_run:
        return "viewed_this_run_not_unseen"
    return "unseen"


def fit_train_only_scaler(
    values: Sequence[float | None],
    train_mask: Sequence[bool],
) -> tuple[float, float]:
    """Fit mean/std on the train partition only for optional standardization."""

    train_values = [
        float(value)
        for value, is_train in zip(values, train_mask)
        if is_train and value is not None
    ]
    if not train_values:
        return 0.0, 1.0
    mean = sum(train_values) / len(train_values)
    if len(train_values) == 1:
        return mean, 1.0
    variance = sum((item - mean) ** 2 for item in train_values) / (len(train_values) - 1)
    std = math.sqrt(variance) if variance > 0 else 1.0
    return mean, std


def apply_train_scaler(
    values: Sequence[float | None],
    mean: float,
    std: float,
) -> list[float | None]:
    if std == 0:
        std = 1.0
    return [None if value is None else (float(value) - mean) / std for value in values]


def _as_aware(value: object, *, label: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise FactorValidationError(f"{label} must be timezone-aware")
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str):
        if "T" in value:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise FactorValidationError(f"{label} must be timezone-aware")
            return parsed
        day = date.fromisoformat(value)
        return datetime.combine(day, time.min, tzinfo=timezone.utc)
    raise FactorValidationError(f"{label} has an unsupported timestamp type")


def to_plain_metric(result: MetricResult) -> dict[str, Any]:
    return {
        result.name: result.value,
        "sample_count": result.sample_count,
        "minimum_sample_status": result.minimum_sample_status,
        "metric_scope": result.scope,
    }
