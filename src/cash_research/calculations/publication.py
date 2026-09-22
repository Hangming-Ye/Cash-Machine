"""Atomic publication for deterministic valuation requests and results."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cash_research.artifacts import ArtifactError, reject_secrets, resolve_reference, safe_relative_path
from cash_research.models import ArtifactSummary, Calculation


class ValuationPublicationError(RuntimeError):
    """Raised when a valuation result cannot be safely published."""


class ValuationPublicationInputError(ArtifactError):
    """Raised for invalid, unsafe, missing, or unstable valuation inputs."""


@dataclass(frozen=True)
class _InputSnapshot:
    ref: str
    relative_path: str
    data: bytes
    sha256: str
    source_manifest_ref: str | None
    source_manifest_sha256: str | None


def publish_valuation(
    *,
    root: Path,
    request: Mapping[str, object],
    result: Mapping[str, object],
    secret_values: Sequence[str] = (),
) -> tuple[ArtifactSummary, ...]:
    """Freeze one validated request, result, Calculation, and hash manifest."""

    root = Path(root).resolve(strict=True)
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValuationPublicationInputError("valuation request_id must be a non-empty string")
    if result.get("request_id") != request_id or result.get("method") != request.get("method"):
        raise ValuationPublicationError("valuation result identity does not match its request")
    parameters = result.get("parameters")
    if not isinstance(parameters, dict) or parameters != dict(request):
        raise ValuationPublicationError("valuation result did not preserve the complete request")
    input_refs = result.get("input_refs")
    warnings = result.get("warnings")
    assumptions = result.get("assumptions")
    if (
        not isinstance(input_refs, list)
        or not all(isinstance(ref, str) and ref for ref in input_refs)
        or not isinstance(warnings, list)
        or not all(isinstance(item, str) and item for item in warnings)
        or not isinstance(assumptions, list)
    ):
        raise ValuationPublicationInputError("valuation result collections are invalid")
    if len(input_refs) != len(set(input_refs)):
        raise ValuationPublicationInputError("valuation input_refs contain duplicates")

    request_bytes = _json_bytes(request)
    result_bytes = _json_bytes(result)
    _reject_unsafe((request, result), secret_values)
    input_snapshots = tuple(
        _snapshot_input(root, ref, secret_values=secret_values) for ref in input_refs
    )

    records = safe_relative_path(root, "data/records", must_exist=False)
    records.mkdir(parents=True, exist_ok=True)
    records = records.resolve(strict=True)
    if not records.is_relative_to(root):
        raise ValuationPublicationError("valuation records directory escapes root")
    record_id = _allocate_record_id(records)
    suffix = record_id[4:]
    calculation_id = f"calc_{suffix}"
    relative_dir = f"data/records/{record_id}"
    request_ref = f"{relative_dir}/request.json"
    result_ref = f"{relative_dir}/result.json"
    calculation_ref = f"{relative_dir}/calculation.json"
    record_ref = f"{relative_dir}/record.json"
    manifest_ref = f"{relative_dir}/manifest.json"
    input_payloads: dict[str, bytes] = {}
    input_provenance: list[dict[str, object]] = []
    frozen_input_refs: list[str] = []
    for index, snapshot in enumerate(input_snapshots, start=1):
        if snapshot.source_manifest_ref is not None:
            frozen_ref = snapshot.ref
        else:
            frozen_name = f"inputs/{index:03d}{_safe_suffix(snapshot.relative_path)}"
            frozen_ref = f"{relative_dir}/{frozen_name}"
            input_payloads[frozen_name] = snapshot.data
        frozen_input_refs.append(frozen_ref)
        input_provenance.append(
            {
                "ref": snapshot.ref,
                "relative_path": snapshot.relative_path,
                "sha256": snapshot.sha256,
                "size": len(snapshot.data),
                "frozen_ref": frozen_ref,
                "source_manifest_ref": snapshot.source_manifest_ref,
                "source_manifest_sha256": snapshot.source_manifest_sha256,
            }
        )
    assumption_text = tuple(
        json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False)
        for item in assumptions
    )
    calculation = Calculation(
        calculation_id=calculation_id,
        kind=f"valuation.{request.get('method')}",
        input_refs=tuple(frozen_input_refs),
        parameters=dict(request),
        assumptions=assumption_text,
        engine_version="valuation-1.0",
        result_ref=result_ref,
        result_reason=None,
        warnings=tuple(warnings),
    )
    calculation_bytes = _json_bytes(calculation.model_dump(mode="json"))
    created_at = datetime.now(timezone.utc).isoformat()
    canonical = {
        "schema_version": "1.0",
        "record_id": record_id,
        "request_id": request_id,
        "operation": "compute.valuation",
        "created_at": created_at,
        "request_ref": request_ref,
        "calculation_id": calculation_id,
        "calculation_ref": calculation_ref,
        "result_ref": result_ref,
        "input_provenance": input_provenance,
    }
    canonical_bytes = _json_bytes(canonical)
    payloads = {
        "request.json": request_bytes,
        "result.json": result_bytes,
        "calculation.json": calculation_bytes,
        "record.json": canonical_bytes,
        **input_payloads,
    }
    manifest = {
        "schema_version": "1.0",
        "record_id": record_id,
        "record_type": "Calculation",
        "created_at": created_at,
        "canonical_ref": record_ref,
        "calculation_id": calculation_id,
        "id_paths": {
            record_id: record_ref,
            calculation_id: calculation_ref,
        },
        "input_provenance": input_provenance,
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for name, data in sorted(payloads.items())
        },
    }
    payloads["manifest.json"] = _json_bytes(manifest)
    _reject_unsafe((canonical, calculation.model_dump(mode="json"), manifest), secret_values)
    _verify_input_snapshots(root, input_snapshots)

    final_dir = records / record_id
    temporary = records / f".tmp-{record_id}-{uuid.uuid4().hex}"
    if final_dir.exists():
        raise ValuationPublicationError("immutable valuation record already exists")
    try:
        temporary.mkdir()
        for name, data in payloads.items():
            if "/" in name:
                (temporary / Path(name).parent).mkdir(parents=True, exist_ok=True)
            _write_new(temporary / name, data)
        os.replace(temporary, final_dir)
    except OSError as exc:
        _cleanup_temp(temporary, records)
        raise ValuationPublicationError("valuation record could not be published atomically") from exc
    except Exception:
        _cleanup_temp(temporary, records)
        raise

    return (
        ArtifactSummary(
            path=record_ref,
            type="calculation_record",
            summary="immutable canonical valuation calculation record",
            artifact_id=record_id,
        ),
        ArtifactSummary(
            path=request_ref,
            type="valuation_request",
            summary="frozen valuation request and assumptions",
            artifact_id=request_ref,
        ),
        ArtifactSummary(
            path=result_ref,
            type="valuation_result",
            summary="deterministic valuation scenarios, sensitivity, and warnings",
            artifact_id=result_ref,
        ),
        ArtifactSummary(
            path=calculation_ref,
            type="valuation",
            summary="typed Calculation linking request inputs to the result",
            artifact_id=calculation_id,
        ),
        ArtifactSummary(
            path=manifest_ref,
            type="calculation_manifest",
            summary="immutable valuation file and input provenance hashes",
            artifact_id=manifest_ref,
        ),
    )


def _reject_unsafe(value: object, secret_values: Sequence[str]) -> None:
    try:
        reject_secrets(value)
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValuationPublicationInputError("valuation content is not safe strict JSON") from exc
    if any(secret and secret in rendered for secret in secret_values):
        raise ValuationPublicationInputError("valuation content reflected configured credential material")


def _snapshot_input(
    root: Path, ref: str, *, secret_values: Sequence[str]
) -> _InputSnapshot:
    try:
        path = resolve_reference(root, ref)
        data = path.read_bytes()
    except OSError as exc:
        raise ValuationPublicationInputError("valuation input reference could not be read") from exc
    _reject_input_bytes(data, secret_values)
    relative = path.relative_to(root).as_posix()
    manifest_ref, manifest_sha = _verified_source_manifest(root, path, data)
    return _InputSnapshot(
        ref=ref,
        relative_path=relative,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        source_manifest_ref=manifest_ref,
        source_manifest_sha256=manifest_sha,
    )


def _verified_source_manifest(
    root: Path, path: Path, data: bytes
) -> tuple[str | None, str | None]:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None, None
    parts = relative.parts
    if len(parts) < 4 or parts[0:2] != ("data", "records") or not parts[2].startswith("rec_"):
        return None, None
    record_dir = root / Path(*parts[:3])
    try:
        manifest_path = safe_relative_path(
            root, f"data/records/{parts[2]}/manifest.json"
        )
    except ArtifactError as exc:
        raise ValuationPublicationInputError(
            "canonical valuation input is missing its immutable manifest"
        ) from exc
    try:
        manifest_data = manifest_path.read_bytes()
        manifest = json.loads(manifest_data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValuationPublicationInputError(
            "canonical valuation input has an unreadable manifest"
        ) from exc
    inside = path.relative_to(record_dir).as_posix()
    files = manifest.get("files") if isinstance(manifest, dict) else None
    entry = files.get(inside) if isinstance(files, dict) else None
    if (
        not isinstance(entry, dict)
        or entry.get("sha256") != hashlib.sha256(data).hexdigest()
        or entry.get("size") != len(data)
    ):
        raise ValuationPublicationInputError(
            "canonical valuation input does not match its immutable manifest"
        )
    return (
        manifest_path.relative_to(root).as_posix(),
        hashlib.sha256(manifest_data).hexdigest(),
    )


def _verify_input_snapshots(root: Path, snapshots: Sequence[_InputSnapshot]) -> None:
    for snapshot in snapshots:
        path = resolve_reference(root, snapshot.ref)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != snapshot.sha256 or len(data) != len(snapshot.data):
            raise ValuationPublicationInputError("valuation input changed during publication")
        if snapshot.source_manifest_ref is not None:
            manifest_path = safe_relative_path(root, snapshot.source_manifest_ref)
            if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != snapshot.source_manifest_sha256:
                raise ValuationPublicationInputError("valuation input manifest changed during publication")


def _reject_input_bytes(data: bytes, secret_values: Sequence[str]) -> None:
    if any(secret and secret.encode("utf-8") in data for secret in secret_values):
        raise ValuationPublicationInputError("valuation input reflected configured credential material")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValuationPublicationInputError("valuation inputs must be UTF-8 JSON") from exc
    _reject_unsafe(payload, secret_values)


def _safe_suffix(relative_path: str) -> str:
    suffix = Path(relative_path).suffix.lower()
    return suffix if suffix and len(suffix) <= 11 and suffix[1:].isalnum() else ".json"


def _allocate_record_id(records: Path) -> str:
    for _ in range(8):
        record_id = f"rec_{uuid.uuid4().hex}"
        if not (records / record_id).exists():
            return record_id
    raise ValuationPublicationError("could not allocate a valuation record ID")


def _json_bytes(value: object) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValuationPublicationError("valuation content is not strict JSON") from exc
    return (rendered + "\n").encode("utf-8")


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _cleanup_temp(path: Path, records: Path) -> None:
    if not path.exists():
        return
    resolved = path.resolve(strict=True)
    if resolved.parent != records or not resolved.name.startswith(".tmp-rec_"):
        raise ValuationPublicationError("refused to clean an unexpected valuation directory")
    shutil.rmtree(resolved)
