"""Unit tests for long-running research run manifests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cash_research.artifacts import ArtifactError, archive_artifact
from cash_research.cli import main


NOW = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)

SUPPLY_CHAIN_IDS = (
    "process_map",
    "demand",
    "bottleneck_test",
    "shortage_queue",
    "price_in",
    "valuation",
    "review",
)


def _decision(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "decision_id": "draft-id",
        "security_or_topic": {
            "market": "US",
            "exchange": "XNAS",
            "symbol": "AAPL",
            "currency": "USD",
        },
        "as_of": NOW.isoformat(),
        "label": "watch",
        "reason_refs": [],
        "price_or_conditions": None,
        "price_or_conditions_reason": "evidence does not support a price",
        "horizon": "12 months",
        "risks": ["demand weakens"],
        "invalidators": ["guidance cut"],
        "memory_packet_refs": [],
    }
    payload.update(overrides)
    return payload


def _work_record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "record_id": "draft-id",
        "request_id": "request-1",
        "created_at": NOW.isoformat(),
        "owner": "research-bot",
        "input_refs": [],
        "output_refs": [],
        "outcome": "complete",
        "limitations": [],
    }
    payload.update(overrides)
    return payload


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _stage(
    stage_id: str,
    status: str = "missing",
    *,
    path: str | None = None,
    blocked_reason: str | None = None,
) -> dict[str, object]:
    return {
        "id": stage_id,
        "status": status,
        "path": path,
        "blocked_reason": blocked_reason,
    }


def _accepted(stage_id: str, path: str) -> dict[str, object]:
    return _stage(stage_id, "accepted", path=path)


def _missing(stage_id: str) -> dict[str, object]:
    return _stage(stage_id, "missing")


def _blocked(stage_id: str, reason: str) -> dict[str, object]:
    return _stage(stage_id, "blocked", blocked_reason=reason)


def _supply_chain_stages(
    *,
    accepted_through: str | None = None,
    overrides: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    stop_at = None if accepted_through is None else SUPPLY_CHAIN_IDS.index(accepted_through)
    stages: list[dict[str, object]] = []
    for index, stage_id in enumerate(SUPPLY_CHAIN_IDS):
        if overrides and stage_id in overrides:
            stages.append(overrides[stage_id])
            continue
        if stop_at is not None and index <= stop_at:
            stages.append(_accepted(stage_id, f"data/runs/req-1/{stage_id}.json"))
        else:
            stages.append(_missing(stage_id))
    return stages


def _write_stage_files(root: Path, stages: list[dict[str, object]]) -> None:
    for stage in stages:
        if stage["status"] != "accepted":
            continue
        path = stage["path"]
        assert isinstance(path, str)
        if stage["id"] == "shortage_queue":
            _write_json(root / path, {"nodes": []})
        else:
            _write_json(root / path, {"stage": stage["id"], "ok": True})


def _write_manifest(
    root: Path,
    *,
    stages: list[dict[str, object]],
    request_id: str = "req-1",
    study_kind: str = "supply_chain",
    relative: str = "data/runs/req-1/manifest.json",
) -> str:
    _write_stage_files(root, stages)
    payload = {
        "request_id": request_id,
        "study_kind": study_kind,
        "stages": stages,
    }
    _write_json(root / relative, payload)
    return relative


def test_missing_process_map_blocks_decision_archive(tmp_path: Path) -> None:
    stages = _supply_chain_stages()
    manifest_ref = _write_manifest(tmp_path, stages=stages)
    _write_json(
        tmp_path / "decision.json",
        _decision(run_manifest_ref=manifest_ref),
    )

    with pytest.raises(ArtifactError):
        archive_artifact(
            root=tmp_path, draft_ref="decision.json", record_type="Decision"
        )


def test_accepting_demand_before_process_map_fails(tmp_path: Path) -> None:
    stages = _supply_chain_stages(
        overrides={
            "process_map": _missing("process_map"),
            "demand": _accepted("demand", "data/runs/req-1/demand.json"),
        }
    )
    manifest_ref = _write_manifest(tmp_path, stages=stages)
    _write_json(
        tmp_path / "decision.json",
        _decision(run_manifest_ref=manifest_ref),
    )

    with pytest.raises(ArtifactError):
        archive_artifact(
            root=tmp_path, draft_ref="decision.json", record_type="Decision"
        )


def test_shortage_queue_before_bottleneck_test_fails(tmp_path: Path) -> None:
    stages = _supply_chain_stages(
        overrides={
            "process_map": _accepted(
                "process_map", "data/runs/req-1/process_map.json"
            ),
            "demand": _accepted("demand", "data/runs/req-1/demand.json"),
            "bottleneck_test": _missing("bottleneck_test"),
            "shortage_queue": _accepted(
                "shortage_queue", "data/runs/req-1/shortage_queue.json"
            ),
        }
    )
    manifest_ref = _write_manifest(tmp_path, stages=stages)
    _write_json(
        tmp_path / "decision.json",
        _decision(run_manifest_ref=manifest_ref),
    )

    with pytest.raises(ArtifactError):
        archive_artifact(
            root=tmp_path, draft_ref="decision.json", record_type="Decision"
        )


def test_pending_queue_node_blocks_price_in(tmp_path: Path) -> None:
    queue_path = "data/runs/req-1/shortage_queue.json"
    stages = _supply_chain_stages(
        accepted_through="shortage_queue",
        overrides={
            "shortage_queue": _accepted("shortage_queue", queue_path),
            "price_in": _accepted("price_in", "data/runs/req-1/price_in.json"),
        },
    )
    _write_manifest(tmp_path, stages=stages)
    _write_json(
        tmp_path / queue_path,
        {"nodes": [{"id": "node-a", "reason": "tight capacity", "status": "pending"}]},
    )
    _write_json(
        tmp_path / "decision.json",
        _decision(run_manifest_ref="data/runs/req-1/manifest.json"),
    )

    with pytest.raises(ArtifactError):
        archive_artifact(
            root=tmp_path, draft_ref="decision.json", record_type="Decision"
        )


def test_complete_supply_chain_with_empty_queue_archives(tmp_path: Path) -> None:
    stages = _supply_chain_stages(accepted_through="review")
    manifest_ref = _write_manifest(tmp_path, stages=stages)
    _write_json(
        tmp_path / "decision.json",
        _decision(run_manifest_ref=manifest_ref),
    )

    archived = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )

    assert archived.record_type == "Decision"
    assert archived.model.run_manifest_ref == manifest_ref


def test_decision_without_run_manifest_ref_still_archives(tmp_path: Path) -> None:
    _write_json(tmp_path / "decision.json", _decision())

    archived = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )

    assert archived.record_type == "Decision"
    assert archived.model.run_manifest_ref is None


def test_blocked_process_map_fails_and_blocked_valuation_needs_limited(
    tmp_path: Path,
) -> None:
    blocked_map = _supply_chain_stages(
        overrides={"process_map": _blocked("process_map", "cannot map")}
    )
    map_ref = _write_manifest(
        tmp_path,
        stages=blocked_map,
        relative="data/runs/req-blocked-map/manifest.json",
        request_id="req-blocked-map",
    )
    _write_json(
        tmp_path / "blocked-map.json",
        _decision(run_manifest_ref=map_ref),
    )
    with pytest.raises(ArtifactError):
        archive_artifact(
            root=tmp_path, draft_ref="blocked-map.json", record_type="Decision"
        )

    limited_stages = _supply_chain_stages(
        accepted_through="price_in",
        overrides={
            "valuation": _blocked("valuation", "inputs unavailable after follow-up"),
            "review": _accepted("review", "data/runs/req-1/review.json"),
        },
    )
    limited_ref = _write_manifest(tmp_path, stages=limited_stages)
    _write_json(
        tmp_path / "limited-decision.json",
        _decision(
            run_manifest_ref=limited_ref,
            evidence_limited=True,
            limitations=["valuation inputs remain unavailable"],
        ),
    )
    decision = archive_artifact(
        root=tmp_path, draft_ref="limited-decision.json", record_type="Decision"
    )
    assert decision.model.evidence_limited is True

    _write_json(
        tmp_path / "unlimited-decision.json",
        _decision(run_manifest_ref=limited_ref),
    )
    with pytest.raises(ArtifactError):
        archive_artifact(
            root=tmp_path,
            draft_ref="unlimited-decision.json",
            record_type="Decision",
        )

    _write_json(
        tmp_path / "limited-work.json",
        _work_record(run_manifest_ref=limited_ref, outcome="limited"),
    )
    work = archive_artifact(
        root=tmp_path, draft_ref="limited-work.json", record_type="WorkRecord"
    )
    assert work.model.outcome == "limited"

    _write_json(
        tmp_path / "complete-work.json",
        _work_record(run_manifest_ref=limited_ref, outcome="complete"),
    )
    with pytest.raises(ArtifactError):
        archive_artifact(
            root=tmp_path, draft_ref="complete-work.json", record_type="WorkRecord"
        )


def test_check_run_returns_next_stage_demand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stages = _supply_chain_stages(accepted_through="process_map")
    relative = _write_manifest(tmp_path, stages=stages)
    # check run --request points at the manifest file itself
    manifest_path = tmp_path / relative

    exit_code = main(
        ["--root", str(tmp_path), "check", "run", "--request", str(manifest_path)]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["next_stage_id"] == "demand"
    assert "demand" in payload["missing"]
    assert payload["status"] in {"ok", "partial", "incomplete"}
