"""Immutable factor experiment plans, trial attempts, and holdout exposure receipts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from cash_research.artifacts import (
    ArtifactError,
    reject_secrets,
    resolve_reference,
    safe_relative_path,
)
from cash_research.calculations.expression import (
    ExpressionValidationError,
    validate_expression,
)
from cash_research.models import FactorExperiment, SecurityIdentity


_REQUIRED_REQUEST_FIELDS = frozenset(
    {
        "hypothesis",
        "failure_regimes",
        "dataset_ref",
        "expression",
        "parameter_sets",
        "target",
        "horizon",
        "bar_interval",
        "baseline",
        "available_time_rule",
        "split",
        "primary_metric",
        "costs",
        "trial_group",
    }
)
_EXPERIMENT_ID = re.compile(r"exp_[0-9a-f]{32}")
_TRIAL_ID = re.compile(r"trial_[0-9a-f]{32}")
_OUTCOME_STATUS = frozenset({"completed", "failed", "abandoned_after_partial_result"})
_HASH = re.compile(r"[0-9a-f]{64}")
_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class TrialError(ValueError):
    """Base error for immutable experiment and trial records."""


class ExperimentValidationError(TrialError):
    """Raised when a proposed experiment is incomplete or inconsistent."""


class FrozenExperimentError(TrialError):
    """Raised when immutable experiment material is missing, changed, or unpublished."""


class TrialConflictError(TrialError):
    """Raised when immutable trial state would be overwritten or misclassified."""


class TrialCorruptionError(TrialError):
    """Raised when an existing trial or exposure record cannot be trusted."""


@dataclass(frozen=True)
class FrozenExperiment:
    experiment_id: str
    request_ref: str
    request_hash: str
    dataset_source_ref: str
    dataset_snapshot_ref: str
    dataset_hash: str
    dataset_versions: tuple[tuple[str, str], ...]
    parameter_set_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrialStart:
    trial_id: str
    experiment_id: str
    parameter_set_id: str
    parameter_hash: str
    request_hash: str
    dataset_hash: str
    execution_config_hash: str
    replay_of: str | None
    replay_kind: str | None
    counts_as_research_trial: bool


@dataclass(frozen=True)
class TrialRecord:
    start: TrialStart
    status: str | None
    result_ref: str | None
    reason: str | None
    partial_result_seen: bool
    terminal_ref: str | None

    @property
    def trial_id(self) -> str:
        return self.start.trial_id


@dataclass(frozen=True)
class HoldoutExposure:
    seen: bool
    previously_seen: bool
    trial_ids: tuple[str, ...]
    receipt_ref: str | None = None


@dataclass(frozen=True)
class OutcomeReceipt:
    trial_id: str
    status: str
    outcome_ref: str


def freeze_experiment(
    root: str | Path, request: Mapping[str, object]
) -> FrozenExperiment:
    """Validate and atomically publish a complete plan plus exact dataset bytes."""

    root_path = _root(root)
    request_value, request_bytes, dataset_path, dataset_bytes, dataset = _validate_request(
        root_path, request
    )
    request_hash = _sha256(request_bytes)
    dataset_hash = _sha256(dataset_bytes)
    experiment_id = f"exp_{uuid.uuid4().hex}"
    relative_dir = f"data/factor-experiments/{experiment_id}"
    request_ref = f"{relative_dir}/request.json"
    snapshot_ref = f"{relative_dir}/dataset.json"
    dataset_source_ref = str(request_value["dataset_ref"]).replace("\\", "/")
    parameter_sets = request_value["parameter_sets"]
    parameter_ids = tuple(item["parameter_set_id"] for item in parameter_sets)
    versions = _dataset_versions(dataset)
    exposure = _exposure_descriptor(request_value, dataset)

    try:
        experiment = _factor_experiment(
            experiment_id, request_ref, request_hash, dataset_source_ref, request_value
        )
    except ValidationError:
        raise ExperimentValidationError("experiment request does not match the factor contract") from None
    experiment_bytes = _pretty_json_bytes(experiment.model_dump(mode="json"))
    manifest = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "request": {"ref": request_ref, "sha256": request_hash, "size": len(request_bytes)},
        "dataset": {
            "source_ref": dataset_source_ref,
            "snapshot_ref": snapshot_ref,
            "sha256": dataset_hash,
            "size": len(dataset_bytes),
            "versions": dict(versions),
        },
        "experiment": {
            "ref": f"{relative_dir}/experiment.json",
            "sha256": _sha256(experiment_bytes),
            "size": len(experiment_bytes),
        },
        "parameter_set_ids": list(parameter_ids),
        "holdout": exposure,
        "serialization": "canonical_json_utf8_v1",
    }
    manifest_bytes = _pretty_json_bytes(manifest)

    base = safe_relative_path(root_path, "data/factor-experiments", must_exist=False)
    base.mkdir(parents=True, exist_ok=True)
    temp_dir = safe_relative_path(
        root_path, f"data/factor-experiments/.tmp_{uuid.uuid4().hex}", must_exist=False
    )
    final_dir = safe_relative_path(root_path, relative_dir, must_exist=False)
    try:
        temp_dir.mkdir()
        _write_new(temp_dir / "request.json", request_bytes)
        _write_new(temp_dir / "dataset.json", dataset_bytes)
        _write_new(temp_dir / "experiment.json", experiment_bytes)
        _write_new(temp_dir / "manifest.json", manifest_bytes)
        if final_dir.exists():
            raise FrozenExperimentError("immutable experiment already exists")
        os.replace(temp_dir, final_dir)
    except FrozenExperimentError:
        _remove_owned_temp(temp_dir, base)
        raise
    except OSError as exc:
        _remove_owned_temp(temp_dir, base)
        raise FrozenExperimentError("experiment could not be published atomically") from exc

    return FrozenExperiment(
        experiment_id=experiment_id,
        request_ref=request_ref,
        request_hash=request_hash,
        dataset_source_ref=dataset_source_ref,
        dataset_snapshot_ref=snapshot_ref,
        dataset_hash=dataset_hash,
        dataset_versions=versions,
        parameter_set_ids=parameter_ids,
    )


def verify_frozen_experiment(
    root: str | Path, experiment_id: str
) -> FrozenExperiment:
    """Re-read and verify every immutable input needed for recomputation."""

    if not isinstance(experiment_id, str) or _EXPERIMENT_ID.fullmatch(experiment_id) is None:
        raise FrozenExperimentError("experiment ID is invalid")
    root_path = _root(root)
    relative_dir = f"data/factor-experiments/{experiment_id}"
    try:
        manifest_path = safe_relative_path(root_path, f"{relative_dir}/manifest.json")
        manifest = _load_json_object(manifest_path, FrozenExperimentError, "manifest")
        if manifest.get("experiment_id") != experiment_id:
            raise ValueError
        request_meta = manifest["request"]
        dataset_meta = manifest["dataset"]
        request_path = safe_relative_path(root_path, request_meta["ref"])
        dataset_path = safe_relative_path(root_path, dataset_meta["snapshot_ref"])
        expected_request_ref = f"{relative_dir}/request.json"
        expected_dataset_ref = f"{relative_dir}/dataset.json"
        expected_experiment_ref = f"{relative_dir}/experiment.json"
        experiment_meta = manifest["experiment"]
        if (
            request_meta["ref"] != expected_request_ref
            or dataset_meta["snapshot_ref"] != expected_dataset_ref
            or experiment_meta["ref"] != expected_experiment_ref
        ):
            raise FrozenExperimentError("frozen experiment paths are not canonical")
        experiment_path = safe_relative_path(root_path, experiment_meta["ref"])
        request_bytes = request_path.read_bytes()
        dataset_bytes = dataset_path.read_bytes()
        experiment_bytes = experiment_path.read_bytes()
        if (
            _sha256(request_bytes) != request_meta["sha256"]
            or len(request_bytes) != request_meta["size"]
        ):
            raise FrozenExperimentError("frozen request hash or size changed")
        if (
            _sha256(dataset_bytes) != dataset_meta["sha256"]
            or len(dataset_bytes) != dataset_meta["size"]
        ):
            raise FrozenExperimentError("frozen dataset hash or size changed")
        if (
            _sha256(experiment_bytes) != experiment_meta["sha256"]
            or len(experiment_bytes) != experiment_meta["size"]
        ):
            raise FrozenExperimentError("frozen experiment summary hash or size changed")
        request = json.loads(request_bytes.decode("utf-8"))
        dataset = json.loads(dataset_bytes.decode("utf-8"))
        if request_bytes != _canonical_json_bytes(request, "frozen request"):
            raise FrozenExperimentError("frozen request is not canonical")
        experiment = FactorExperiment.model_validate_json(experiment_bytes)
        expected_experiment = _factor_experiment(
            experiment_id, expected_request_ref, request_meta["sha256"], dataset_meta["source_ref"], request
        )
        if (
            experiment != expected_experiment
            or dict(dataset_meta["versions"]) != dict(_dataset_versions(dataset))
            or manifest["holdout"] != _exposure_descriptor(request, dataset)
        ):
            raise FrozenExperimentError("frozen experiment summary does not match its request")
        parameter_ids = tuple(item["parameter_set_id"] for item in request["parameter_sets"])
        if list(parameter_ids) != manifest["parameter_set_ids"]:
            raise FrozenExperimentError("frozen parameter sets do not match the manifest")
    except FrozenExperimentError:
        raise
    except (ArtifactError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, KeyError, TypeError, ValueError):
        raise FrozenExperimentError("frozen experiment is missing, corrupt, or inconsistent") from None
    return FrozenExperiment(
        experiment_id=experiment_id,
        request_ref=request_meta["ref"],
        request_hash=request_meta["sha256"],
        dataset_source_ref=dataset_meta["source_ref"],
        dataset_snapshot_ref=dataset_meta["snapshot_ref"],
        dataset_hash=dataset_meta["sha256"],
        dataset_versions=tuple(sorted(dataset_meta["versions"].items())),
        parameter_set_ids=parameter_ids,
    )


def start_trial(
    root: str | Path,
    experiment_id: str,
    parameter_set_id: str,
    *,
    execution_config: Mapping[str, object],
    replay_of: str | None = None,
    infrastructure_retry: bool = False,
) -> TrialStart:
    """Create an immutable pre-compute attempt for one explicit parameter set."""

    root_path = _root(root)
    if not isinstance(parameter_set_id, str) or not parameter_set_id:
        raise ExperimentValidationError("parameter_set_id must be a non-empty string")
    if not isinstance(execution_config, Mapping):
        raise ExperimentValidationError("execution config must be an object")
    if not isinstance(infrastructure_retry, bool):
        raise ExperimentValidationError("infrastructure_retry must be boolean")
    frozen = verify_frozen_experiment(root_path, experiment_id)
    request = _load_json_object(
        safe_relative_path(root_path, frozen.request_ref), ExperimentValidationError, "request"
    )
    parameter = next(
        (item for item in request["parameter_sets"] if item["parameter_set_id"] == parameter_set_id),
        None,
    )
    if parameter is None:
        raise ExperimentValidationError("parameter_set_id is absent from the frozen request")
    config_bytes = _canonical_json_bytes(execution_config, "execution config")
    try:
        reject_secrets(execution_config)
    except ArtifactError as exc:
        raise ExperimentValidationError("execution config contains credential material") from exc
    parameter_hash = _sha256(_canonical_json_bytes(parameter, "parameter set"))
    config_hash = _sha256(config_bytes)
    replay_kind: str | None = None
    counts_as_research_trial = True
    if replay_of is not None:
        original = read_trial(root_path, replay_of)
        if original.status is None:
            raise TrialConflictError("replay_of must identify a terminal trial")
        if original.start.request_hash != frozen.request_hash:
            raise TrialConflictError("replay request or inputs changed")
        if original.start.dataset_hash != frozen.dataset_hash:
            raise TrialConflictError("replay request or inputs changed")
        if original.start.parameter_hash != parameter_hash:
            raise TrialConflictError("replay parameter set changed")
        if original.start.execution_config_hash != config_hash:
            raise TrialConflictError("replay execution config changed")
        counts_as_research_trial = False
        replay_kind = "infrastructure_retry" if infrastructure_retry else "exact_recompute"
    elif infrastructure_retry:
        raise TrialConflictError("infrastructure retry requires replay_of")

    trial_id = f"trial_{uuid.uuid4().hex}"
    start = TrialStart(
        trial_id=trial_id,
        experiment_id=experiment_id,
        parameter_set_id=parameter_set_id,
        parameter_hash=parameter_hash,
        request_hash=frozen.request_hash,
        dataset_hash=frozen.dataset_hash,
        execution_config_hash=config_hash,
        replay_of=replay_of,
        replay_kind=replay_kind,
        counts_as_research_trial=counts_as_research_trial,
    )
    payload = {
        **start.__dict__,
        "parameter_set": parameter,
        "execution_config": json.loads(config_bytes),
        "trial_group": request["trial_group"],
        "holdout": _experiment_manifest(root_path, experiment_id)["holdout"],
    }
    _publish_directory(
        root_path,
        f"data/factor-trials/{trial_id}",
        {"start.json": _pretty_json_bytes(payload)},
        error="trial start could not be published atomically",
    )
    return start


def record_trial_outcome(
    root: str | Path,
    trial_id: str,
    *,
    status: Literal["completed", "failed", "abandoned_after_partial_result"],
    result_ref: str | None = None,
    reason: str | None = None,
    partial_result_seen: bool = False,
) -> OutcomeReceipt:
    """Add the single immutable terminal outcome; never rewrite the trial start."""

    if status not in _OUTCOME_STATUS:
        raise ExperimentValidationError("trial outcome status is invalid")
    if not isinstance(partial_result_seen, bool):
        raise ExperimentValidationError("partial_result_seen must be boolean")
    if result_ref is not None and not isinstance(result_ref, str):
        raise ExperimentValidationError("result_ref must be a string")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise ExperimentValidationError("outcome reason must be a non-empty string")
    if partial_result_seen and status != "abandoned_after_partial_result":
        raise ExperimentValidationError("partial result flag requires abandoned status")
    if status != "completed" and not reason:
        raise ExperimentValidationError("failed or abandoned trial requires a reason")
    root_path = _root(root)
    record = read_trial(root_path, trial_id)
    if record.status is not None:
        raise TrialConflictError("terminal trial outcome already exists")
    if result_ref is not None:
        try:
            reject_secrets({"result_ref": result_ref, "reason": reason})
            result_path = resolve_reference(root_path, result_ref)
            result_bytes = result_path.read_bytes()
        except (ArtifactError, OSError) as exc:
            raise ExperimentValidationError("result_ref must identify an immutable workspace file") from exc
    elif status == "completed" and not reason:
        raise ExperimentValidationError("completed trial requires result_ref or an explicit reason")
    else:
        try:
            reject_secrets({"reason": reason})
        except ArtifactError as exc:
            raise ExperimentValidationError("trial outcome contains credential material") from exc
        result_bytes = None
    payload = {
        "trial_id": trial_id,
        "status": status,
        "result_ref": result_ref,
        "reason": reason,
        "partial_result_seen": partial_result_seen,
        "result_sha256": _sha256(result_bytes) if result_bytes is not None else None,
        "result_size": len(result_bytes) if result_bytes is not None else None,
    }
    relative = f"data/factor-trials/{trial_id}/outcome.json"
    outcome_path = safe_relative_path(root_path, relative, must_exist=False)
    lock_path = safe_relative_path(
        root_path, f"data/factor-trials/{trial_id}/.outcome.lock", must_exist=False
    )
    with _file_lock(lock_path):
        if outcome_path.exists():
            raise TrialConflictError("terminal trial outcome already exists")
        _atomic_write_new(outcome_path, _pretty_json_bytes(payload), "trial outcome")
    return OutcomeReceipt(trial_id=trial_id, status=status, outcome_ref=relative)


def read_trial(root: str | Path, trial_id: str) -> TrialRecord:
    """Read one trial and reject any malformed immutable record."""

    return _read_trial(_root(root), trial_id, frozenset())


def _read_trial(root_path: Path, trial_id: str, lineage: frozenset[str]) -> TrialRecord:

    if not isinstance(trial_id, str) or _TRIAL_ID.fullmatch(trial_id) is None:
        raise TrialCorruptionError("trial ID is invalid")
    if trial_id in lineage:
        raise TrialCorruptionError("trial replay lineage contains a cycle")
    try:
        start_path = safe_relative_path(root_path, f"data/factor-trials/{trial_id}/start.json")
        payload = _load_json_object(start_path, TrialCorruptionError, "trial start")
        start = _parse_trial_start(payload, trial_id)
        frozen = verify_frozen_experiment(root_path, start.experiment_id)
        if start.request_hash != frozen.request_hash or start.dataset_hash != frozen.dataset_hash:
            raise ValueError
        request = _load_json_object(
            safe_relative_path(root_path, frozen.request_ref), TrialCorruptionError, "request"
        )
        expected_parameter = next(
            (
                item
                for item in request["parameter_sets"]
                if item["parameter_set_id"] == start.parameter_set_id
            ),
            None,
        )
        parameter = payload["parameter_set"]
        if (
            not isinstance(parameter, dict)
            or parameter != expected_parameter
            or parameter.get("parameter_set_id") != start.parameter_set_id
            or _sha256(_canonical_json_bytes(parameter, "parameter set")) != start.parameter_hash
            or _sha256(_canonical_json_bytes(payload["execution_config"], "execution config"))
            != start.execution_config_hash
            or payload["trial_group"] != request["trial_group"]
            or payload["holdout"] != _experiment_manifest(root_path, start.experiment_id)["holdout"]
        ):
            raise ValueError
        if start.replay_of is not None:
            original = _read_trial(root_path, start.replay_of, lineage | {trial_id})
            if (
                original.status is None
                or original.start.request_hash != start.request_hash
                or original.start.dataset_hash != start.dataset_hash
                or original.start.parameter_hash != start.parameter_hash
                or original.start.execution_config_hash != start.execution_config_hash
            ):
                raise ValueError
        outcome_ref = f"data/factor-trials/{trial_id}/outcome.json"
        outcome_path = safe_relative_path(root_path, outcome_ref, must_exist=False)
        if not outcome_path.exists():
            return TrialRecord(start, None, None, None, False, None)
        outcome = _load_json_object(outcome_path, TrialCorruptionError, "trial outcome")
        if (
            outcome.get("trial_id") != trial_id
            or outcome.get("status") not in _OUTCOME_STATUS
            or not isinstance(outcome.get("partial_result_seen"), bool)
            or (outcome["status"] != "completed" and not isinstance(outcome.get("reason"), str))
            or (
                outcome["partial_result_seen"]
                and outcome["status"] != "abandoned_after_partial_result"
            )
            or set(outcome)
            != {
                "trial_id", "status", "result_ref", "reason", "partial_result_seen",
                "result_sha256", "result_size",
            }
        ):
            raise ValueError
        result_ref = outcome.get("result_ref")
        if result_ref is not None:
            result_path = resolve_reference(root_path, result_ref)
            result_bytes = result_path.read_bytes()
            if (
                outcome["result_sha256"] != _sha256(result_bytes)
                or outcome["result_size"] != len(result_bytes)
            ):
                raise ValueError
        elif outcome["status"] == "completed" and not isinstance(outcome.get("reason"), str):
            raise ValueError
        elif outcome["result_sha256"] is not None or outcome["result_size"] is not None:
            raise ValueError
        return TrialRecord(
            start=start,
            status=outcome["status"],
            result_ref=result_ref,
            reason=outcome.get("reason"),
            partial_result_seen=outcome["partial_result_seen"],
            terminal_ref=outcome_ref,
        )
    except TrialCorruptionError:
        raise
    except (ArtifactError, ExperimentValidationError, FrozenExperimentError, OSError, KeyError, TypeError, ValueError):
        raise TrialCorruptionError("trial record is missing, corrupt, or inconsistent") from None


def trial_counts(root: str | Path, *, experiment_id: str | None = None) -> dict[str, int]:
    """Count immutable attempts, including failed, abandoned, and exact replays."""

    records = _all_trials(_root(root))
    if experiment_id is not None:
        records = [item for item in records if item.start.experiment_id == experiment_id]
    return {
        "research_trials": sum(item.start.counts_as_research_trial for item in records),
        "failed_or_abandoned": sum(
            item.status in {"failed", "abandoned_after_partial_result"} for item in records
        ),
        "replays": sum(not item.start.counts_as_research_trial for item in records),
        "completed": sum(item.status == "completed" for item in records),
    }


def mark_holdout_exposure(root: str | Path, trial_id: str) -> HoldoutExposure:
    """Persist exposure before any holdout value is evaluated or returned."""

    root_path = _root(root)
    trial = read_trial(root_path, trial_id)
    descriptor = _trial_start_payload(root_path, trial_id)["holdout"]
    security_key = descriptor["instrument_key"]
    with _PROCESS_LOCKS_GUARD:
        lock_dir = safe_relative_path(
            root_path, "data/factor-holdout-exposures/.locks", must_exist=False
        )
        lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = safe_relative_path(
        root_path, f"data/factor-holdout-exposures/.locks/{security_key}.lock", must_exist=False
    )
    with _file_lock(lock_path):
        matching = _matching_exposures(root_path, descriptor)
        existing = next((item for item in matching if item["trial_id"] == trial_id), None)
        if existing is not None:
            return HoldoutExposure(
                seen=True,
                previously_seen=any(item["trial_id"] != trial_id for item in matching),
                trial_ids=tuple(sorted({item["trial_id"] for item in matching})),
                receipt_ref=existing["receipt_ref"],
            )
        receipt_id = f"exposure_{uuid.uuid4().hex}"
        relative = f"data/factor-holdout-exposures/{receipt_id}.json"
        payload = {
            "receipt_id": receipt_id,
            "trial_id": trial_id,
            "experiment_id": trial.start.experiment_id,
            "marked_at": datetime.now(timezone.utc).isoformat(),
            **descriptor,
        }
        path = safe_relative_path(root_path, relative, must_exist=False)
        _atomic_write_new(path, _pretty_json_bytes(payload), "holdout exposure")
        previous_ids = tuple(sorted({item["trial_id"] for item in matching}))
        return HoldoutExposure(
            seen=True,
            previously_seen=bool(previous_ids),
            trial_ids=previous_ids + (trial_id,),
            receipt_ref=relative,
        )


def holdout_exposure(root: str | Path, experiment_id: str) -> HoldoutExposure:
    """Return exposure for overlapping intervals with the same security and target family."""

    root_path = _root(root)
    verify_frozen_experiment(root_path, experiment_id)
    descriptor = _experiment_manifest(root_path, experiment_id)["holdout"]
    matching = _matching_exposures(root_path, descriptor)
    return HoldoutExposure(
        seen=bool(matching),
        previously_seen=bool(matching),
        trial_ids=tuple(sorted({item["trial_id"] for item in matching})),
    )


def _validate_request(
    root: Path, request: Mapping[str, object]
) -> tuple[dict[str, object], bytes, Path, bytes, dict[str, object]]:
    if not isinstance(request, Mapping):
        raise ExperimentValidationError("experiment request must be an object")
    missing = sorted(_REQUIRED_REQUEST_FIELDS - set(request))
    if missing:
        raise ExperimentValidationError("experiment request is missing required fields")
    try:
        reject_secrets(request)
    except ArtifactError as exc:
        raise ExperimentValidationError("experiment request contains credential material") from exc
    request_bytes = _canonical_json_bytes(request, "experiment request")
    value = json.loads(request_bytes)
    for field in ("hypothesis", "target", "horizon", "bar_interval", "baseline", "available_time_rule", "primary_metric", "trial_group"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ExperimentValidationError(f"{field} must be a non-empty string")
    if not isinstance(value.get("failure_regimes"), list):
        raise ExperimentValidationError("failure_regimes must be a list")
    if not isinstance(value.get("costs"), dict):
        raise ExperimentValidationError("costs must be an object with finite values")
    _reject_nonfinite(value, "experiment request")
    try:
        dataset_path = safe_relative_path(root, value["dataset_ref"])
        dataset_bytes = dataset_path.read_bytes()
        dataset = json.loads(dataset_bytes.decode("utf-8"))
    except (ArtifactError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise ExperimentValidationError("dataset_ref must identify a safe readable JSON dataset") from None
    if not isinstance(dataset, dict):
        raise ExperimentValidationError("dataset must be a JSON object")
    try:
        reject_secrets(dataset)
    except ArtifactError as exc:
        raise ExperimentValidationError("dataset contains credential material") from exc
    _reject_nonfinite(dataset, "dataset")
    _validate_request_semantics(value)
    _validate_security_identity(value, dataset)
    try:
        validate_expression(
            value["expression"],
            dataset=dataset,
            parameter_schema=value.get("parameter_schema", {}),
            parameter_sets=value["parameter_sets"],
        )
    except ExpressionValidationError as exc:
        raise ExperimentValidationError("expression or parameter sets are invalid") from exc
    _exposure_descriptor(value, dataset)
    return value, request_bytes, dataset_path, dataset_bytes, dataset


def _validate_request_semantics(request: dict[str, object]) -> None:
    target_spec = request.get("target_spec")
    if not isinstance(target_spec, dict) or target_spec.get("canonical_id") != request["target"]:
        raise ExperimentValidationError("target and target_spec are inconsistent")
    target_horizon = target_spec.get("horizon")
    horizon_unit = target_spec.get("horizon_unit")
    if (
        isinstance(target_horizon, bool)
        or not isinstance(target_horizon, int)
        or target_horizon < 1
        or not isinstance(horizon_unit, str)
        or f"{target_horizon}{horizon_unit}" != request["horizon"]
    ):
        raise ExperimentValidationError("horizon and target_spec are inconsistent")
    operation = target_spec.get("operation")
    field = target_spec.get("field")
    if not isinstance(operation, str) or not operation or not isinstance(field, str) or not field:
        raise ExperimentValidationError("target semantics are incomplete")
    expected_target = (
        f"provided:{field}:{request['horizon']}"
        if operation == "provided_field"
        else f"{operation}:{field}:{request['horizon']}"
    )
    if request["target"] != expected_target:
        raise ExperimentValidationError("target semantic fields do not match its canonical ID")
    baseline_spec = request.get("baseline_spec")
    if not isinstance(baseline_spec, dict) or baseline_spec.get("canonical_id") != request["baseline"]:
        raise ExperimentValidationError("baseline and baseline_spec are inconsistent")
    baseline_kind = baseline_spec.get("kind")
    if not isinstance(baseline_kind, str) or not baseline_kind:
        raise ExperimentValidationError("baseline structured meaning is incomplete")
    baseline_target = baseline_spec.get("target")
    if baseline_target is not None and baseline_target != request["target"]:
        raise ExperimentValidationError("baseline target does not match the experiment target")
    if baseline_kind == "constant_direction":
        value = baseline_spec.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or baseline_spec.get("unit") != "direction"
        ):
            raise ExperimentValidationError("constant direction baseline is incomplete")
    if not isinstance(request.get("split"), dict) or not isinstance(request.get("parameter_sets"), list):
        raise ExperimentValidationError("split and parameter_sets must be explicit")


def _validate_security_identity(
    request: Mapping[str, object], dataset: Mapping[str, object]
) -> None:
    try:
        request_security = SecurityIdentity.model_validate(request.get("security"))
        dataset_security = SecurityIdentity.model_validate(dataset.get("security"))
    except ValidationError:
        raise ExperimentValidationError("request and dataset require valid security identities") from None
    if request_security != dataset_security:
        raise ExperimentValidationError("request security does not match the frozen dataset")


def _exposure_descriptor(request: Mapping[str, object], dataset: Mapping[str, object]) -> dict[str, object]:
    try:
        security_model = SecurityIdentity.model_validate(request.get("security"))
    except ValidationError:
        raise ExperimentValidationError("security identity is required for holdout tracking") from None
    security = security_model.model_dump(mode="json")
    target_spec = request.get("target_spec")
    split = request.get("split")
    final_holdout = split.get("final_holdout") if isinstance(split, Mapping) else None
    if not isinstance(target_spec, Mapping) or not all(
        isinstance(target_spec.get(name), str) and target_spec.get(name)
        for name in ("operation", "field")
    ):
        raise ExperimentValidationError("target semantics are required for holdout tracking")
    if not isinstance(final_holdout, Mapping):
        raise ExperimentValidationError("final holdout interval is required")
    timezone_name = dataset.get("market_timezone")
    if not isinstance(timezone_name, str):
        raise ExperimentValidationError("dataset market_timezone is required for holdout tracking")
    try:
        zone = ZoneInfo(timezone_name)
        start = _aware_boundary(final_holdout.get("start"), zone, end=False)
        end = _aware_boundary(final_holdout.get("end"), zone, end=True)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ExperimentValidationError("final holdout must have valid aware time boundaries") from None
    if start > end:
        raise ExperimentValidationError("final holdout interval is inverted")
    security_value = {
        name: security[name] for name in ("market", "exchange", "symbol", "currency")
    }
    instrument_value = {
        name: security[name] for name in ("market", "symbol", "currency")
    }
    target_value = {name: target_spec[name] for name in ("operation", "field")}
    return {
        "security_key": _sha256(_canonical_json_bytes(security_value, "security")),
        "instrument_key": _sha256(
            _canonical_json_bytes(instrument_value, "security instrument")
        ),
        "exchange": security["exchange"],
        "target_key": _sha256(_canonical_json_bytes(target_value, "target semantics")),
        "start": start.astimezone(timezone.utc).isoformat(),
        "end": end.astimezone(timezone.utc).isoformat(),
    }


def _aware_boundary(value: object, zone: ZoneInfo, *, end: bool) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    if "T" in value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed
    parsed_date = date.fromisoformat(value)
    return datetime.combine(parsed_date, time.max if end else time.min, tzinfo=zone)


def _matching_exposures(root: Path, descriptor: Mapping[str, object]) -> list[dict[str, object]]:
    base = safe_relative_path(root, "data/factor-holdout-exposures", must_exist=False)
    if not base.exists():
        return []
    matches: list[dict[str, object]] = []
    try:
        paths = sorted(path for path in base.glob("exposure_*.json") if path.is_file())
        for path in paths:
            payload = _load_json_object(path, TrialCorruptionError, "holdout exposure")
            required = {
                "receipt_id", "trial_id", "experiment_id", "marked_at", "security_key",
                "instrument_key", "exchange", "target_key", "start", "end",
            }
            string_fields = required - {"exchange"}
            if (
                set(payload) != required
                or not all(isinstance(payload[name], str) for name in string_fields)
                or (payload["exchange"] is not None and not isinstance(payload["exchange"], str))
            ):
                raise TrialCorruptionError("holdout exposure record is corrupt")
            marked_at = datetime.fromisoformat(payload["marked_at"])
            start = datetime.fromisoformat(payload["start"])
            end = datetime.fromisoformat(payload["end"])
            if (
                marked_at.tzinfo is None
                or start.tzinfo is None
                or end.tzinfo is None
                or start > end
            ):
                raise TrialCorruptionError("holdout exposure record is corrupt")
            receipt_trial = read_trial(root, payload["trial_id"])
            if receipt_trial.start.experiment_id != payload["experiment_id"]:
                raise TrialCorruptionError("holdout exposure record is corrupt")
            original_descriptor = _trial_start_payload(root, payload["trial_id"])["holdout"]
            if any(
                payload[name] != original_descriptor[name]
                for name in (
                    "security_key", "instrument_key", "exchange", "target_key", "start", "end"
                )
            ):
                raise TrialCorruptionError("holdout exposure record is corrupt")
            if (
                payload["instrument_key"] == descriptor["instrument_key"]
                and (
                    payload["exchange"] is None
                    or descriptor["exchange"] is None
                    or payload["exchange"] == descriptor["exchange"]
                )
                and payload["target_key"] == descriptor["target_key"]
                and _intervals_overlap(payload, descriptor)
            ):
                payload["receipt_ref"] = path.relative_to(root).as_posix()
                matches.append(payload)
    except (OSError, ValueError):
        raise TrialCorruptionError("holdout exposure record is corrupt") from None
    return matches


def _intervals_overlap(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return datetime.fromisoformat(str(left["start"])) <= datetime.fromisoformat(str(right["end"])) and datetime.fromisoformat(str(right["start"])) <= datetime.fromisoformat(str(left["end"]))


def _all_trials(root: Path) -> list[TrialRecord]:
    base = safe_relative_path(root, "data/factor-trials", must_exist=False)
    if not base.exists():
        return []
    try:
        paths = sorted(path for path in base.iterdir() if path.is_dir() and path.name.startswith("trial_"))
    except OSError:
        raise TrialCorruptionError("trial records could not be enumerated") from None
    return [read_trial(root, path.name) for path in paths]


def _parse_trial_start(payload: Mapping[str, object], trial_id: str) -> TrialStart:
    required = {
        "trial_id", "experiment_id", "parameter_set_id", "parameter_hash", "request_hash",
        "dataset_hash", "execution_config_hash", "replay_of", "replay_kind",
        "counts_as_research_trial", "parameter_set", "execution_config", "trial_group", "holdout",
    }
    if set(payload) != required or payload.get("trial_id") != trial_id:
        raise TrialCorruptionError("trial start record is corrupt")
    for name in ("experiment_id", "parameter_set_id", "parameter_hash", "request_hash", "dataset_hash", "execution_config_hash"):
        if not isinstance(payload.get(name), str) or not payload[name]:
            raise TrialCorruptionError("trial start record is corrupt")
    if any(_HASH.fullmatch(payload[name]) is None for name in ("parameter_hash", "request_hash", "dataset_hash", "execution_config_hash")):
        raise TrialCorruptionError("trial start record is corrupt")
    if not isinstance(payload.get("counts_as_research_trial"), bool):
        raise TrialCorruptionError("trial start record is corrupt")
    replay_of = payload.get("replay_of")
    replay_kind = payload.get("replay_kind")
    if replay_of is None:
        if replay_kind is not None or payload["counts_as_research_trial"] is not True:
            raise TrialCorruptionError("trial replay classification is corrupt")
    elif (
        not isinstance(replay_of, str)
        or _TRIAL_ID.fullmatch(replay_of) is None
        or replay_kind not in {"infrastructure_retry", "exact_recompute"}
        or payload["counts_as_research_trial"] is not False
    ):
        raise TrialCorruptionError("trial replay classification is corrupt")
    return TrialStart(
        trial_id=trial_id,
        experiment_id=payload["experiment_id"],
        parameter_set_id=payload["parameter_set_id"],
        parameter_hash=payload["parameter_hash"],
        request_hash=payload["request_hash"],
        dataset_hash=payload["dataset_hash"],
        execution_config_hash=payload["execution_config_hash"],
        replay_of=replay_of,
        replay_kind=replay_kind,
        counts_as_research_trial=payload["counts_as_research_trial"],
    )


def _experiment_manifest(root: Path, experiment_id: str) -> dict[str, object]:
    return _load_json_object(
        safe_relative_path(root, f"data/factor-experiments/{experiment_id}/manifest.json"),
        FrozenExperimentError,
        "experiment manifest",
    )


def _trial_start_payload(root: Path, trial_id: str) -> dict[str, object]:
    return _load_json_object(
        safe_relative_path(root, f"data/factor-trials/{trial_id}/start.json"),
        TrialCorruptionError,
        "trial start",
    )


def _dataset_versions(dataset: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    names = ("schema_version", "dataset_id", "revision_status", "point_in_time_status")
    return tuple(sorted((name, value) for name in names if isinstance((value := dataset.get(name)), str)))


def _factor_experiment(
    experiment_id: str,
    request_ref: str,
    request_hash: str,
    dataset_source_ref: str,
    request: Mapping[str, object],
) -> FactorExperiment:
    return FactorExperiment(
        experiment_id=experiment_id,
        request_ref=request_ref,
        request_hash=request_hash,
        hypothesis=request["hypothesis"],
        failure_regimes=tuple(request["failure_regimes"]),
        expression=request["expression"],
        parameter_sets=tuple(request["parameter_sets"]),
        dataset_ref=dataset_source_ref,
        available_time_rule=request["available_time_rule"],
        target=request["target"],
        horizon=request["horizon"],
        bar_interval=request["bar_interval"],
        baseline=request["baseline"],
        split=request["split"],
        primary_metric=request["primary_metric"],
        metrics={request["primary_metric"]: None},
        costs=request["costs"],
        trial_group=request["trial_group"],
        result_ref=None,
        result_reason="experiment frozen; computation not started",
    )


def _canonical_json_bytes(value: object, label: str) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise ExperimentValidationError(f"{label} must be finite JSON data") from None


def _reject_nonfinite(value: object, label: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ExperimentValidationError(f"{label} must contain finite numbers")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_nonfinite(item, label)
    elif isinstance(value, list):
        for item in value:
            _reject_nonfinite(item, label)


def _load_json_object(path: Path, error_type: type[TrialError], label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise error_type(f"{label} is missing or corrupt") from None
    if not isinstance(value, dict):
        raise error_type(f"{label} must be a JSON object")
    return value


def _publish_directory(root: Path, relative: str, files: Mapping[str, bytes], *, error: str) -> None:
    parent_relative = str(Path(relative).parent).replace("\\", "/")
    parent = safe_relative_path(root, parent_relative, must_exist=False)
    parent.mkdir(parents=True, exist_ok=True)
    temp = safe_relative_path(root, f"{parent_relative}/.tmp_{uuid.uuid4().hex}", must_exist=False)
    final = safe_relative_path(root, relative, must_exist=False)
    try:
        temp.mkdir()
        for name, data in files.items():
            _write_new(temp / name, data)
        if final.exists():
            raise TrialConflictError("immutable record already exists")
        os.replace(temp, final)
    except TrialConflictError:
        _remove_owned_temp(temp, parent)
        raise
    except OSError as exc:
        _remove_owned_temp(temp, parent)
        raise FrozenExperimentError(error) from exc


def _atomic_write_new(path: Path, data: bytes, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".tmp_{uuid.uuid4().hex}")
    try:
        _write_new(temp, data)
        if path.exists():
            raise TrialConflictError(f"immutable {label} already exists")
        os.replace(temp, path)
    except TrialConflictError:
        temp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise FrozenExperimentError(f"{label} could not be published atomically") from exc


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _remove_owned_temp(path: Path, parent: Path) -> None:
    try:
        resolved = path.resolve(strict=False)
        if resolved.parent == parent.resolve(strict=True) and resolved.name.startswith(".tmp_"):
            shutil.rmtree(resolved, ignore_errors=True)
    except OSError:
        pass


def _pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root(root: str | Path) -> Path:
    try:
        return Path(root).resolve(strict=True)
    except OSError as exc:
        raise ExperimentValidationError("workspace root must exist") from exc


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    lock_key = str(path.resolve(strict=False))
    with _PROCESS_LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.setdefault(lock_key, threading.Lock())
    with process_lock:
        path.touch(exist_ok=True)
        with path.open("r+b", buffering=0) as stream:
            if os.name == "nt":
                import msvcrt

                if path.stat().st_size == 0:
                    stream.write(b"0")
                    stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
