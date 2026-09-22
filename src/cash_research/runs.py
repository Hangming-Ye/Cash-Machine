"""Long-running research run manifests for multi-stage studies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cash_research.artifacts import ArtifactError, UnsafePathError, safe_relative_path
from cash_research.models import Decision, WorkRecord


StudyKind = Literal["supply_chain", "single_name"]
StageStatus = Literal["missing", "accepted", "blocked"]

SUPPLY_CHAIN_STAGES: tuple[str, ...] = (
    "process_map",
    "demand",
    "bottleneck_test",
    "shortage_queue",
    "price_in",
    "valuation",
    "review",
)
SINGLE_NAME_STAGES: tuple[str, ...] = (
    "driver_bridge",
    "valuation",
    "quote_comparison",
    "review",
)
_REQUIRED_BY_KIND: dict[str, tuple[str, ...]] = {
    "supply_chain": SUPPLY_CHAIN_STAGES,
    "single_name": SINGLE_NAME_STAGES,
}
_NEVER_BLOCKED = frozenset(
    {
        "process_map",
        "demand",
        "bottleneck_test",
        "shortage_queue",
        "driver_bridge",
        "review",
    }
)
_MAY_BLOCK = frozenset({"valuation", "price_in", "quote_comparison"})
_RECURSE_PREFIX = "recurse:"


@dataclass(frozen=True)
class RunStage:
    id: str
    status: StageStatus
    path: str | None
    blocked_reason: str | None


@dataclass(frozen=True)
class RunManifest:
    request_id: str
    study_kind: StudyKind
    stages: tuple[RunStage, ...]
    relative_path: str

    @property
    def required_ids(self) -> tuple[str, ...]:
        return _REQUIRED_BY_KIND[self.study_kind]

    @property
    def stage_by_id(self) -> dict[str, RunStage]:
        return {stage.id: stage for stage in self.stages}

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(
            stage_id
            for stage_id in self.required_ids
            if self.stage_by_id[stage_id].status == "missing"
        )


@dataclass(frozen=True)
class RunCheckResult:
    status: str
    next_stage_id: str | None
    missing: tuple[str, ...]


def load_run_manifest(root: str | Path, ref: str) -> RunManifest:
    """Load and structurally validate a workspace-relative run manifest."""

    if not isinstance(ref, str) or not ref.strip():
        raise ArtifactError("run_manifest_ref must be a non-empty workspace-relative path")
    try:
        path = safe_relative_path(root, ref)
    except UnsafePathError as exc:
        raise ArtifactError("run manifest path is unsafe") from exc
    except ArtifactError:
        raise
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ArtifactError("run manifest could not be read") from exc
    if not raw.strip():
        raise ArtifactError("run manifest is empty")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("run manifest must be readable UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ArtifactError("run manifest must contain a JSON object")

    relative = path.relative_to(Path(root).resolve(strict=True)).as_posix()
    return _parse_manifest(root, payload, relative_path=relative)


def check_run_manifest(root: str | Path, ref: str) -> RunCheckResult:
    """Validate a manifest file and report the next incomplete stage."""

    manifest = load_run_manifest(root, ref)
    next_stage = _next_stage_id(root, manifest)
    missing = manifest.missing
    status = "ok" if next_stage is None else "incomplete"
    return RunCheckResult(status=status, next_stage_id=next_stage, missing=missing)


def validate_record_run_manifest(
    root: str | Path,
    model: Decision | WorkRecord,
) -> None:
    """Reject Decision/WorkRecord drafts whose run manifest is incomplete or invalid."""

    ref = model.run_manifest_ref
    if ref is None:
        return
    manifest = load_run_manifest(root, ref)
    _assert_stage_order_and_rules(root, manifest)
    if any(manifest.stage_by_id[stage_id].status == "missing" for stage_id in manifest.required_ids):
        raise ArtifactError("run manifest still has required stages missing")
    review = manifest.stage_by_id["review"]
    if review.status != "accepted":
        raise ArtifactError("run manifest review stage must be accepted")

    blocked = tuple(
        stage_id
        for stage_id in manifest.required_ids
        if manifest.stage_by_id[stage_id].status == "blocked"
    )
    if not blocked:
        return
    unexpected = [stage_id for stage_id in blocked if stage_id not in _MAY_BLOCK]
    if unexpected:
        raise ArtifactError(f"run manifest stage cannot be blocked: {unexpected[0]}")
    if isinstance(model, Decision):
        if not model.evidence_limited or not model.limitations:
            raise ArtifactError(
                "blocked valuation stages require an evidence_limited Decision with limitations"
            )
        return
    if model.outcome != "limited":
        raise ArtifactError("blocked valuation stages require a WorkRecord outcome of limited")


def parse_run_manifest_payload(
    root: str | Path,
    payload: dict[str, Any],
    *,
    relative_path: str = "manifest.json",
) -> RunManifest:
    """Parse an already-loaded manifest object (used by CLI when FILE is the manifest)."""

    return _parse_manifest(root, payload, relative_path=relative_path)


def _parse_manifest(
    root: str | Path,
    payload: dict[str, Any],
    *,
    relative_path: str,
) -> RunManifest:
    request_id = payload.get("request_id")
    study_kind = payload.get("study_kind")
    stages_raw = payload.get("stages")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ArtifactError("run manifest request_id must be a non-empty string")
    if study_kind not in _REQUIRED_BY_KIND:
        raise ArtifactError("run manifest study_kind must be supply_chain or single_name")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise ArtifactError("run manifest stages must be a non-empty list")
    if set(payload) - {"request_id", "study_kind", "stages"}:
        raise ArtifactError("run manifest contains unsupported fields")

    required = _REQUIRED_BY_KIND[study_kind]
    stages: list[RunStage] = []
    seen: set[str] = set()
    for item in stages_raw:
        stage = _parse_stage(item)
        if stage.id in seen:
            raise ArtifactError(f"run manifest duplicates stage id: {stage.id}")
        seen.add(stage.id)
        stages.append(stage)

    for stage_id in required:
        if stage_id not in seen:
            raise ArtifactError(f"run manifest missing required stage: {stage_id}")

    extras = [stage for stage in stages if stage.id not in required]
    for stage in extras:
        if not stage.id.startswith(_RECURSE_PREFIX) or stage.id == _RECURSE_PREFIX:
            raise ArtifactError(f"run manifest has unsupported stage id: {stage.id}")

    manifest = RunManifest(
        request_id=request_id,
        study_kind=study_kind,  # type: ignore[arg-type]
        stages=tuple(stages),
        relative_path=relative_path,
    )
    _assert_stage_order_and_rules(root, manifest)
    return manifest


def _parse_stage(item: object) -> RunStage:
    if not isinstance(item, dict):
        raise ArtifactError("run manifest stage must be an object")
    if set(item) - {"id", "status", "path", "blocked_reason"}:
        raise ArtifactError("run manifest stage contains unsupported fields")
    stage_id = item.get("id")
    status = item.get("status")
    path = item.get("path")
    blocked_reason = item.get("blocked_reason")
    if not isinstance(stage_id, str) or not stage_id.strip():
        raise ArtifactError("run manifest stage id must be a non-empty string")
    if status not in {"missing", "accepted", "blocked"}:
        raise ArtifactError(f"run manifest stage status is invalid: {stage_id}")
    if status == "accepted":
        if not isinstance(path, str) or not path.strip():
            raise ArtifactError(f"accepted stage requires a non-empty path: {stage_id}")
        if blocked_reason is not None:
            raise ArtifactError(f"accepted stage blocked_reason must be null: {stage_id}")
    elif status == "blocked":
        if not isinstance(blocked_reason, str) or not blocked_reason.strip():
            raise ArtifactError(f"blocked stage requires a non-empty blocked_reason: {stage_id}")
        if path is not None:
            raise ArtifactError(f"blocked stage path must be null: {stage_id}")
    else:
        if path is not None:
            raise ArtifactError(f"missing stage path must be null: {stage_id}")
        if blocked_reason is not None:
            raise ArtifactError(f"missing stage blocked_reason must be null: {stage_id}")
    return RunStage(
        id=stage_id,
        status=status,  # type: ignore[arg-type]
        path=path if isinstance(path, str) else None,
        blocked_reason=blocked_reason if isinstance(blocked_reason, str) else None,
    )


def _assert_stage_order_and_rules(root: str | Path, manifest: RunManifest) -> None:
    required = manifest.required_ids
    by_id = manifest.stage_by_id

    for stage_id in required:
        stage = by_id[stage_id]
        if stage.status == "blocked" and stage_id in _NEVER_BLOCKED:
            raise ArtifactError(f"run manifest stage cannot be blocked: {stage_id}")
        if stage.status == "blocked" and stage_id not in _MAY_BLOCK:
            raise ArtifactError(f"run manifest stage cannot be blocked: {stage_id}")

    for index, stage_id in enumerate(required):
        stage = by_id[stage_id]
        if stage.status != "accepted":
            continue
        for prior_id in required[:index]:
            prior = by_id[prior_id]
            if prior.status == "accepted":
                continue
            if prior.status == "blocked" and prior_id in _MAY_BLOCK:
                continue
            raise ArtifactError(f"run manifest stage accepted out of order: {stage_id}")
        assert stage.path is not None
        _require_existing_file(root, stage.path)

    queue_nodes = _queue_nodes_for(root, manifest)
    queue_ids = {node_id for node_id, _status in queue_nodes}
    shortage = by_id.get("shortage_queue") if manifest.study_kind == "supply_chain" else None

    for stage in manifest.stages:
        if not stage.id.startswith(_RECURSE_PREFIX):
            continue
        node_id = stage.id[len(_RECURSE_PREFIX) :]
        if shortage is None or shortage.status != "accepted":
            raise ArtifactError("recurse stages require an accepted shortage_queue")
        if node_id not in queue_ids:
            raise ArtifactError(f"recurse stage does not match a queue node: {stage.id}")
        if stage.status == "accepted":
            assert stage.path is not None
            _require_existing_file(root, stage.path)

    if shortage is not None and shortage.status == "accepted":
        _validate_shortage_queue_file(root, shortage.path)
        price_in = by_id["price_in"]
        if price_in.status == "accepted":
            pending = [node_id for node_id, status in queue_nodes if status == "pending"]
            if pending:
                raise ArtifactError("price_in cannot be accepted while queue nodes are pending")
            for node_id, _status in queue_nodes:
                recurse_id = f"{_RECURSE_PREFIX}{node_id}"
                recurse = by_id.get(recurse_id)
                if recurse is None or recurse.status != "accepted":
                    raise ArtifactError(
                        f"price_in requires an accepted recurse stage for queue node: {node_id}"
                    )


def _queue_nodes_for(
    root: str | Path, manifest: RunManifest
) -> tuple[tuple[str, str], ...]:
    if manifest.study_kind != "supply_chain":
        return ()
    shortage = manifest.stage_by_id["shortage_queue"]
    if shortage.status != "accepted" or not shortage.path:
        return ()
    return _load_shortage_queue_nodes(root=root, relative_path=shortage.path)


def _validate_shortage_queue_file(root: str | Path, relative_path: str | None) -> None:
    if not relative_path:
        raise ArtifactError("accepted shortage_queue requires a path")
    _load_shortage_queue_nodes(root=root, relative_path=relative_path)


def _load_shortage_queue_nodes(
    *,
    root: str | Path,
    relative_path: str,
) -> tuple[tuple[str, str], ...]:
    path = _require_existing_file(root, relative_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("shortage_queue file must be readable UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"nodes"}:
        raise ArtifactError("shortage_queue file must contain only a nodes list")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        raise ArtifactError("shortage_queue nodes must be a list")
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in nodes:
        if not isinstance(item, dict) or set(item) != {"id", "reason", "status"}:
            raise ArtifactError("shortage_queue node must have id, reason, and status")
        node_id = item.get("id")
        reason = item.get("reason")
        status = item.get("status")
        if not isinstance(node_id, str) or not node_id.strip():
            raise ArtifactError("shortage_queue node id must be non-empty")
        if not isinstance(reason, str) or not reason.strip():
            raise ArtifactError("shortage_queue node reason must be non-empty")
        if status not in {"pending", "accepted"}:
            raise ArtifactError("shortage_queue node status must be pending or accepted")
        if node_id in seen:
            raise ArtifactError(f"shortage_queue duplicates node id: {node_id}")
        seen.add(node_id)
        parsed.append((node_id, status))
    return tuple(parsed)


def _require_existing_file(root: str | Path, relative_path: str) -> Path:
    try:
        return safe_relative_path(root, relative_path)
    except UnsafePathError as exc:
        raise ArtifactError("run stage path is unsafe") from exc
    except ArtifactError:
        raise


def _next_stage_id(root: str | Path, manifest: RunManifest) -> str | None:
    for stage_id in manifest.required_ids:
        if manifest.stage_by_id[stage_id].status != "accepted":
            return stage_id
    pending = [node_id for node_id, status in _queue_nodes_for(root, manifest) if status == "pending"]
    if pending:
        return f"{_RECURSE_PREFIX}{pending[0]}"
    return None
