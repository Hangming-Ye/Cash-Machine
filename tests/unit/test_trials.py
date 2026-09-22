from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cash_research.calculations.trials import (
    ExperimentValidationError,
    FrozenExperimentError,
    TrialConflictError,
    TrialCorruptionError,
    freeze_experiment,
    holdout_exposure,
    mark_holdout_exposure,
    read_trial,
    record_trial_outcome,
    start_trial,
    trial_counts,
    verify_frozen_experiment,
)


ROOT = Path(__file__).parents[2]


def fixture_request(case: str = "new_combination") -> dict[str, object]:
    contract = json.loads((ROOT / "fixtures/factors/expected.json").read_text("utf-8"))
    return copy.deepcopy(contract["cases"][case]["request"])


def prepare_root(tmp_path: Path, request: dict[str, object]) -> Path:
    root = tmp_path / "workspace"
    root.mkdir(parents=True)
    source = ROOT / str(request["dataset_ref"])
    target = root / str(request["dataset_ref"])
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    return root


def canonical_hash(value: object) -> str:
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def freeze(tmp_path: Path, request: dict[str, object] | None = None):
    selected = request or fixture_request()
    root = prepare_root(tmp_path, selected)
    return root, freeze_experiment(root, selected)


def test_freeze_writes_complete_request_and_exact_dataset_before_compute(
    tmp_path: Path,
) -> None:
    request = fixture_request()
    root, frozen = freeze(tmp_path, request)
    expected = json.loads((ROOT / "fixtures/factors/expected.json").read_text("utf-8"))[
        "cases"
    ]["new_combination"]

    assert frozen.request_hash == expected["request_hash"] == canonical_hash(request)
    assert frozen.request_ref == f"data/factor-experiments/{frozen.experiment_id}/request.json"
    assert frozen.parameter_set_ids == ("p-window2", "p-window3")
    assert (root / frozen.request_ref).read_bytes() == json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert (root / frozen.dataset_snapshot_ref).read_bytes() == (
        root / str(request["dataset_ref"])
    ).read_bytes()
    assert verify_frozen_experiment(root, frozen.experiment_id) == frozen


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.pop("primary_metric"), "required"),
        (lambda value: value["target_spec"].update({"canonical_id": "wrong"}), "target"),
        (lambda value: value.update({"horizon": "2bar"}), "horizon"),
        (lambda value: value["baseline_spec"].update({"canonical_id": "wrong"}), "baseline"),
        (lambda value: value.update({"costs": {"commission_bps": float("nan")}}), "finite"),
    ],
)
def test_freeze_rejects_incomplete_inconsistent_or_nonfinite_request(
    tmp_path: Path, mutation: object, message: str
) -> None:
    request = fixture_request()
    mutation(request)  # type: ignore[operator]
    root = prepare_root(tmp_path, request)
    with pytest.raises(ExperimentValidationError, match=message):
        freeze_experiment(root, request)


def test_freeze_rejects_dataset_escape_and_secret_fields(tmp_path: Path) -> None:
    request = fixture_request()
    root = prepare_root(tmp_path, request)
    escaped = copy.deepcopy(request)
    escaped["dataset_ref"] = "../secret.json"
    with pytest.raises(ExperimentValidationError, match="dataset"):
        freeze_experiment(root, escaped)

    secret = copy.deepcopy(request)
    secret["apiKey"] = "should-not-persist"
    with pytest.raises(ExperimentValidationError, match="credential"):
        freeze_experiment(root, secret)
    assert not (root / "data/factor-experiments").exists()


def test_freeze_atomic_publish_failure_leaves_no_canonical_or_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.calculations.trials as trials

    request = fixture_request()
    root = prepare_root(tmp_path, request)

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("synthetic publish failure")

    monkeypatch.setattr(trials.os, "replace", fail_replace)
    with pytest.raises(FrozenExperimentError, match="publish"):
        freeze_experiment(root, request)
    base = root / "data/factor-experiments"
    assert not base.exists() or list(base.iterdir()) == []


def test_verify_rejects_request_or_dataset_tampering(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    request_path = root / frozen.request_ref
    request_path.write_bytes(request_path.read_bytes() + b" ")
    with pytest.raises(FrozenExperimentError, match="request"):
        verify_frozen_experiment(root, frozen.experiment_id)

    root2, frozen2 = freeze(tmp_path / "second")
    dataset_path = root2 / frozen2.dataset_snapshot_ref
    dataset_path.write_bytes(dataset_path.read_bytes() + b" ")
    with pytest.raises(FrozenExperimentError, match="dataset"):
        verify_frozen_experiment(root2, frozen2.experiment_id)


def test_verify_rejects_valid_shaped_summary_and_trial_tampering(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    experiment_path = root / f"data/factor-experiments/{frozen.experiment_id}/experiment.json"
    manifest_path = root / f"data/factor-experiments/{frozen.experiment_id}/manifest.json"
    experiment = json.loads(experiment_path.read_text("utf-8"))
    experiment["hypothesis"] = "mutated but valid-shaped hypothesis"
    experiment_bytes = (json.dumps(experiment, indent=2, sort_keys=True) + "\n").encode()
    experiment_path.write_bytes(experiment_bytes)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["experiment"]["sha256"] = hashlib.sha256(experiment_bytes).hexdigest()
    manifest["experiment"]["size"] = len(experiment_bytes)
    manifest_path.write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(FrozenExperimentError, match="summary"):
        verify_frozen_experiment(root, frozen.experiment_id)

    root2, frozen2 = freeze(tmp_path / "trial")
    trial = start_trial(root2, frozen2.experiment_id, "p-window2", execution_config={})
    start_path = root2 / f"data/factor-trials/{trial.trial_id}/start.json"
    start = json.loads(start_path.read_text("utf-8"))
    start["parameter_set"]["bindings"]["volume_threshold"] = 9.0
    start["parameter_hash"] = canonical_hash(start["parameter_set"])
    start_path.write_text(json.dumps(start), "utf-8")
    with pytest.raises(TrialCorruptionError):
        read_trial(root2, trial.trial_id)


def test_trials_count_each_parameter_failure_and_abandonment(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    first = start_trial(
        root, frozen.experiment_id, "p-window2", execution_config={"engine": "v1"}
    )
    second = start_trial(
        root, frozen.experiment_id, "p-window3", execution_config={"engine": "v1"}
    )
    record_trial_outcome(root, first.trial_id, status="failed", reason="numeric failure")
    record_trial_outcome(
        root,
        second.trial_id,
        status="abandoned_after_partial_result",
        reason="unstable intermediate result",
        partial_result_seen=True,
    )

    assert trial_counts(root) == {
        "research_trials": 2,
        "failed_or_abandoned": 2,
        "replays": 0,
        "completed": 0,
    }
    assert read_trial(root, second.trial_id).partial_result_seen is True


def test_exact_failed_infrastructure_retry_is_replay_not_new_candidate(
    tmp_path: Path,
) -> None:
    root, frozen = freeze(tmp_path)
    original = start_trial(
        root,
        frozen.experiment_id,
        "p-window2",
        execution_config={"engine": "v1", "precision": 1e-12},
    )
    record_trial_outcome(root, original.trial_id, status="failed", reason="worker lost")
    replay = start_trial(
        root,
        frozen.experiment_id,
        "p-window2",
        execution_config={"engine": "v1", "precision": 1e-12},
        replay_of=original.trial_id,
        infrastructure_retry=True,
    )
    assert replay.replay_of == original.trial_id
    assert replay.counts_as_research_trial is False
    assert trial_counts(root)["research_trials"] == 1
    assert trial_counts(root)["replays"] == 1


def test_exact_completed_recompute_is_replay_not_new_candidate(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    original = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    record_trial_outcome(root, original.trial_id, status="completed", reason="checked")
    replay = start_trial(
        root, frozen.experiment_id, "p-window2", execution_config={}, replay_of=original.trial_id
    )
    assert replay.replay_kind == "exact_recompute"
    assert trial_counts(root) == {
        "research_trials": 1,
        "failed_or_abandoned": 0,
        "replays": 1,
        "completed": 1,
    }


def test_exact_replay_preserves_partial_result_and_changed_config_is_new_attempt(
    tmp_path: Path,
) -> None:
    root, frozen = freeze(tmp_path)
    original = start_trial(
        root, frozen.experiment_id, "p-window2", execution_config={"engine": "v1"}
    )
    record_trial_outcome(
        root,
        original.trial_id,
        status="abandoned_after_partial_result",
        reason="changed after seeing partial result",
        partial_result_seen=True,
    )
    replay = start_trial(
        root,
        frozen.experiment_id,
        "p-window2",
        execution_config={"engine": "v1"},
        replay_of=original.trial_id,
    )
    assert replay.counts_as_research_trial is False
    with pytest.raises(TrialConflictError, match="config"):
        start_trial(
            root,
            frozen.experiment_id,
            "p-window2",
            execution_config={"engine": "v2"},
            replay_of=original.trial_id,
            infrastructure_retry=True,
        )

    new_attempt = start_trial(
        root, frozen.experiment_id, "p-window2", execution_config={"engine": "v2"}
    )
    assert new_attempt.counts_as_research_trial is True
    assert new_attempt.trial_id != original.trial_id


def test_changed_dataset_bytes_require_new_frozen_experiment_and_trial(
    tmp_path: Path,
) -> None:
    request = fixture_request()
    root, frozen = freeze(tmp_path, request)
    first = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    source = root / str(request["dataset_ref"])
    payload = json.loads(source.read_text("utf-8"))
    payload["dataset_id"] = "synthetic-factor-1d-v2"
    source.write_text(json.dumps(payload), encoding="utf-8")
    changed = freeze_experiment(root, request)
    assert changed.dataset_hash != frozen.dataset_hash
    second = start_trial(root, changed.experiment_id, "p-window2", execution_config={})
    assert second.trial_id != first.trial_id
    assert trial_counts(root)["research_trials"] == 2


def test_changed_parameter_set_is_new_research_trial_not_replay(tmp_path: Path) -> None:
    request = fixture_request()
    root, frozen = freeze(tmp_path, request)
    original = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    record_trial_outcome(
        root,
        original.trial_id,
        status="abandoned_after_partial_result",
        reason="partial result changed hypothesis",
        partial_result_seen=True,
    )
    changed_request = copy.deepcopy(request)
    changed_request["parameter_sets"][0]["bindings"]["volume_threshold"] = 1.5
    changed = freeze_experiment(root, changed_request)
    with pytest.raises(TrialConflictError, match="changed"):
        start_trial(
            root,
            changed.experiment_id,
            "p-window2",
            execution_config={},
            replay_of=original.trial_id,
        )
    new_trial = start_trial(root, changed.experiment_id, "p-window2", execution_config={})
    assert new_trial.counts_as_research_trial is True
    assert trial_counts(root)["research_trials"] == 2


def test_holdout_exposure_survives_request_and_trial_group_renaming(
    tmp_path: Path,
) -> None:
    request = fixture_request()
    root, frozen = freeze(tmp_path, request)
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    exposure = mark_holdout_exposure(root, trial.trial_id)
    assert exposure.previously_seen is False
    record_trial_outcome(
        root, trial.trial_id, status="completed", reason="synthetic result retained externally"
    )
    assert holdout_exposure(root, frozen.experiment_id).seen is True

    renamed = copy.deepcopy(request)
    renamed["request_id"] = "renamed-request"
    renamed["trial_group"] = "renamed-trial-group"
    renamed_frozen = freeze_experiment(root, renamed)
    observed = holdout_exposure(root, renamed_frozen.experiment_id)
    assert observed.seen is True
    assert trial.trial_id in observed.trial_ids


def test_holdout_mark_precedes_outcome_and_exact_replay_preserves_exposure(
    tmp_path: Path,
) -> None:
    root, frozen = freeze(tmp_path)
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    mark_holdout_exposure(root, trial.trial_id)
    record_trial_outcome(root, trial.trial_id, status="failed", reason="failed after holdout")
    with pytest.raises(TrialConflictError, match="terminal"):
        record_trial_outcome(root, trial.trial_id, status="completed", reason="overwrite")
    replay = start_trial(
        root,
        frozen.experiment_id,
        "p-window2",
        execution_config={},
        replay_of=trial.trial_id,
    )
    replay_exposure = mark_holdout_exposure(root, replay.trial_id)
    assert replay_exposure.previously_seen is True
    assert holdout_exposure(root, frozen.experiment_id).seen is True


def test_appended_dataset_and_changed_horizon_do_not_reset_overlapping_holdout(
    tmp_path: Path,
) -> None:
    request = fixture_request()
    root, frozen = freeze(tmp_path, request)
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    mark_holdout_exposure(root, trial.trial_id)

    dataset_path = root / str(request["dataset_ref"])
    dataset = json.loads(dataset_path.read_text("utf-8"))
    dataset["rows"].append(
        {
            "timestamp": "2026-01-13T16:00:00-05:00",
            "available_at": "2026-01-13T16:05:00-05:00",
            "close": 105.0,
            "volume": 100.0,
        }
    )
    dataset_path.write_text(json.dumps(dataset), "utf-8")
    changed = copy.deepcopy(request)
    changed["horizon"] = "2bar"
    changed["target"] = "forward_return:close:2bar"
    changed["target_spec"].update(
        {"canonical_id": changed["target"], "horizon": 2}
    )
    changed["baseline_spec"]["target"] = changed["target"]
    changed_frozen = freeze_experiment(root, changed)
    observed = holdout_exposure(root, changed_frozen.experiment_id)
    assert observed.seen is True
    assert trial.trial_id in observed.trial_ids


def test_optional_exchange_is_valid_and_later_known_exchange_keeps_exposure(
    tmp_path: Path,
) -> None:
    request = fixture_request()
    request["security"]["exchange"] = None
    root = prepare_root(tmp_path, request)
    dataset_path = root / str(request["dataset_ref"])
    dataset = json.loads(dataset_path.read_text("utf-8"))
    dataset["security"]["exchange"] = None
    dataset_path.write_text(json.dumps(dataset), "utf-8")
    unknown_exchange = freeze_experiment(root, request)
    trial = start_trial(
        root, unknown_exchange.experiment_id, "p-window2", execution_config={}
    )
    mark_holdout_exposure(root, trial.trial_id)

    known_request = copy.deepcopy(request)
    known_request["security"]["exchange"] = "XNAS"
    dataset["security"]["exchange"] = "XNAS"
    dataset_path.write_text(json.dumps(dataset), "utf-8")
    known_exchange = freeze_experiment(root, known_request)
    assert holdout_exposure(root, known_exchange.experiment_id).seen is True


def test_concurrent_holdout_marks_allow_only_one_first_view(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    trials = [
        start_trial(root, frozen.experiment_id, name, execution_config={})
        for name in ("p-window2", "p-window3")
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: mark_holdout_exposure(root, item.trial_id), trials))
    assert sorted(item.previously_seen for item in results) == [False, True]
    assert set(holdout_exposure(root, frozen.experiment_id).trial_ids) == {
        item.trial_id for item in trials
    }


def test_missing_or_corrupt_trial_records_never_reset_counts(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    (root / f"data/factor-trials/{trial.trial_id}/start.json").write_text("{}", "utf-8")
    with pytest.raises(TrialCorruptionError):
        trial_counts(root)
    with pytest.raises(TrialCorruptionError):
        read_trial(root, trial.trial_id)


def test_corrupt_exposure_is_not_treated_as_unseen(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    marked = mark_holdout_exposure(root, trial.trial_id)
    (root / str(marked.receipt_ref)).write_text("{}", "utf-8")
    with pytest.raises(TrialCorruptionError):
        holdout_exposure(root, frozen.experiment_id)


def test_valid_shaped_exposure_mutation_is_corruption_not_unseen(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    marked = mark_holdout_exposure(root, trial.trial_id)
    receipt_path = root / str(marked.receipt_ref)
    receipt = json.loads(receipt_path.read_text("utf-8"))
    receipt["start"] = "2030-01-01T00:00:00+00:00"
    receipt["end"] = "2030-01-02T00:00:00+00:00"
    receipt_path.write_text(json.dumps(receipt), "utf-8")
    with pytest.raises(TrialCorruptionError):
        holdout_exposure(root, frozen.experiment_id)


def test_outcome_publish_failure_leaves_trial_nonterminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.calculations.trials as trials

    root, frozen = freeze(tmp_path)
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("synthetic outcome failure")

    monkeypatch.setattr(trials.os, "replace", fail_replace)
    with pytest.raises(FrozenExperimentError, match="outcome"):
        record_trial_outcome(root, trial.trial_id, status="failed", reason="worker lost")
    assert read_trial(root, trial.trial_id).status is None
    assert not list((root / f"data/factor-trials/{trial.trial_id}").glob(".tmp_*"))


def test_result_reference_must_exist_inside_workspace(tmp_path: Path) -> None:
    root, frozen = freeze(tmp_path)
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    with pytest.raises(ExperimentValidationError, match="result"):
        record_trial_outcome(
            root, trial.trial_id, status="completed", result_ref="../outside.json"
        )


def test_outcome_rejects_mutable_or_secret_content_and_detects_result_change(
    tmp_path: Path,
) -> None:
    root, frozen = freeze(tmp_path)
    mutable = root / "drafts/current.json"
    mutable.parent.mkdir()
    mutable.write_text("{}", "utf-8")
    trial = start_trial(root, frozen.experiment_id, "p-window2", execution_config={})
    with pytest.raises(ExperimentValidationError, match="immutable"):
        record_trial_outcome(
            root, trial.trial_id, status="completed", result_ref="drafts/current.json"
        )
    with pytest.raises(ExperimentValidationError, match="credential"):
        record_trial_outcome(
            root, trial.trial_id, status="failed", reason="Bearer synthetic-secret-value"
        )

    result = root / "data/results/result.json"
    result.parent.mkdir(parents=True)
    result.write_text('{"metric": 1}', "utf-8")
    record_trial_outcome(
        root, trial.trial_id, status="completed", result_ref="data/results/result.json"
    )
    result.write_text('{"metric": 2}', "utf-8")
    with pytest.raises(TrialCorruptionError):
        read_trial(root, trial.trial_id)


def test_structured_target_security_and_dataset_content_are_validated(tmp_path: Path) -> None:
    request = fixture_request()
    root = prepare_root(tmp_path, request)
    bad_target = copy.deepcopy(request)
    bad_target["target"] = "forward_return:open:1bar"
    bad_target["target_spec"]["canonical_id"] = bad_target["target"]
    bad_target["baseline_spec"]["target"] = bad_target["target"]
    with pytest.raises(ExperimentValidationError, match="semantic"):
        freeze_experiment(root, bad_target)

    dataset_path = root / str(request["dataset_ref"])
    dataset = json.loads(dataset_path.read_text("utf-8"))
    dataset["security"]["symbol"] = "OTHER"
    dataset_path.write_text(json.dumps(dataset), "utf-8")
    with pytest.raises(ExperimentValidationError, match="security"):
        freeze_experiment(root, request)

    dataset["security"] = request["security"]
    dataset["apiKey"] = "must-not-persist"
    dataset_path.write_text(json.dumps(dataset), "utf-8")
    with pytest.raises(ExperimentValidationError, match="credential"):
        freeze_experiment(root, request)

    dataset.pop("apiKey")
    dataset["rows"][0]["close"] = float("nan")
    dataset_path.write_text(json.dumps(dataset), "utf-8")
    with pytest.raises(ExperimentValidationError, match="finite"):
        freeze_experiment(root, request)
