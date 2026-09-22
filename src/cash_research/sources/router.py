"""Route approved source operations and atomically publish immutable source records."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from cash_research.artifacts import (
    SecretContentError,
    json_pointer_exists,
    reject_secrets,
    safe_relative_path,
)
from cash_research.config import (
    credential_secret_values,
    RequestBoundaryError,
    Settings,
    validate_read_request,
)
from cash_research.models import (
    ArtifactSummary,
    CallError,
    CallResult,
    DataGap,
    Evidence,
    PortfolioSnapshot,
    SourceResult,
)
from cash_research.sources.akshare_source import AKShareAdapter
from cash_research.sources.finnhub import FinnhubAdapter
from cash_research.sources.fmp import FmpStableAdapter
from cash_research.sources.ingest import MaterialIngestAdapter
from cash_research.sources.ibkr_flex import IbkrFlexReadOnlyAdapter
from cash_research.sources.longbridge_readonly import LongbridgeOAuthReadOnlyAdapter
from cash_research.sources.tiingo import TiingoAdapter


_SCHEMA_VERSION = "1.0"
_INGEST_OPERATIONS = {
    "user_provided_material": "text_ingest",
    "user_provided_series": "series_ingest",
}
_ERROR_REASONS = {
    "unauthorized",
    "unsupported",
    "rate_limited",
    "empty",
    "stale",
    "conflict",
    "invalid",
    "external",
}


class SourceAdapter(Protocol):
    def fetch(
        self, request: Mapping[str, object], *, output_ref: str
    ) -> Mapping[str, object]: ...


AdapterFactory = Callable[[Settings], SourceAdapter]

_ADAPTER_FACTORIES: dict[str, AdapterFactory] = {
    "finnhub": FinnhubAdapter,
    "tiingo": TiingoAdapter,
    "fmp_stable": FmpStableAdapter,
    "akshare": AKShareAdapter,
    "ibkr_flex": lambda settings: _ibkr_adapter(settings),
    "longbridge_oauth": LongbridgeOAuthReadOnlyAdapter,
}


def _ibkr_adapter(settings: Settings) -> IbkrFlexReadOnlyAdapter:
    client = httpx.Client()
    adapter = IbkrFlexReadOnlyAdapter(settings, client=client)
    adapter.close = client.close  # type: ignore[attr-defined]
    return adapter


class SourceRouterError(RuntimeError):
    """Raised when an adapter result cannot be safely and atomically published."""


class SourceContractError(SourceRouterError):
    """Raised for a malformed or unsafe adapter response."""


def data_fetch_handler(
    *, root: Path, settings: Settings, request: dict[str, Any]
) -> CallResult:
    """Run one approved public-data adapter and publish its complete source record."""

    _require_matching_root(root, settings)
    canonical = _canonical_fetch_request(request)
    request_id = _request_id(canonical)
    try:
        validate_read_request(canonical)
    except RequestBoundaryError:
        return _unsupported(request_id, "data.fetch")
    source = canonical.get("source")
    if source not in settings.enabled_sources:
        return _unsupported(request_id, "data.fetch")
    factory = _ADAPTER_FACTORIES.get(str(source))
    if factory is None:
        return _unsupported(request_id, "data.fetch")

    record_id = _allocate_record_id(settings.root)
    output_ref = _record_ref(record_id, "raw.json")
    adapter = factory(settings)
    try:
        result = adapter.fetch(canonical, output_ref=output_ref)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    return _publish_adapter_result(
        settings=settings,
        request=canonical,
        operation="data.fetch",
        record_id=record_id,
        output_ref=output_ref,
        adapter_result=result,
    )


def data_ingest_handler(
    *, root: Path, settings: Settings, request: dict[str, Any]
) -> CallResult:
    """Validate one already-obtained local material file and publish its record."""

    _require_matching_root(root, settings)
    request_id = _request_id(request)
    try:
        reject_secrets(request)
    except SecretContentError:
        return _invalid(request_id, "data.ingest")
    source = request.get("source")
    operation = request.get("operation")
    if not isinstance(source, str) or _INGEST_OPERATIONS.get(source) != operation:
        return _unsupported(request_id, "data.ingest")

    record_id = _allocate_record_id(settings.root)
    output_ref = _record_ref(record_id, "raw.json")
    adapter = MaterialIngestAdapter(settings)
    result = adapter.fetch(request, output_ref=output_ref)
    return _publish_adapter_result(
        settings=settings,
        request=request,
        operation="data.ingest",
        record_id=record_id,
        output_ref=output_ref,
        adapter_result=result,
    )


def _publish_adapter_result(
    *,
    settings: Settings,
    request: Mapping[str, object],
    operation: str,
    record_id: str,
    output_ref: str,
    adapter_result: Mapping[str, object],
) -> CallResult:
    request_id = _request_id(request)
    parsed = _parse_adapter_result(adapter_result, request=request)

    raw_payload = parsed["raw_payload"]
    normalized = parsed["normalized"]
    source_result = parsed["source_result"]
    evidence = parsed["evidence"]
    gaps = parsed["gaps"]
    portfolio_snapshot = parsed["portfolio_snapshot"]
    assert isinstance(normalized, dict)
    assert isinstance(source_result, SourceResult)
    assert isinstance(evidence, tuple)
    assert isinstance(gaps, tuple)
    assert portfolio_snapshot is None or isinstance(portfolio_snapshot, PortfolioSnapshot)
    if raw_payload is None:
        if source_result.payload_ref is not None or evidence:
            raise SourceContractError("adapter references a raw payload that was not returned")
    else:
        if source_result.payload_ref != output_ref:
            raise SourceContractError("adapter payload reference does not match the assigned output")
        if any(item.source_ref != output_ref for item in evidence):
            raise SourceContractError("adapter evidence source does not match the assigned raw output")
    if source_result.errors and not gaps:
        gaps = (
            DataGap(
                gap_id="router-generated-placeholder",
                request_id=request_id,
                required_content=f"usable {source_result.operation} source result",
                attempts=(
                    {
                        "source": source_result.source,
                        "at": source_result.retrieved_at.isoformat(),
                        "result": "source_result_errors_present",
                    },
                ),
                impact="source errors limit or prevent use of the returned result",
                next_action="inspect the persisted SourceResult coverage and retry or use another approved path",
            ),
        )
    _reject_unsafe_content(
        {
            "source_result": source_result.model_dump(mode="json"),
            "raw_payload": raw_payload,
            "normalized": normalized,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "gaps": [item.model_dump(mode="json") for item in gaps],
            "portfolio_snapshot": (
                portfolio_snapshot.model_dump(mode="json")
                if portfolio_snapshot is not None
                else None
            ),
        },
        credential_secret_values(settings),
    )

    raw_ref = output_ref if raw_payload is not None else None
    source_result = source_result.model_copy(update={"payload_ref": raw_ref})
    evidence_publications: list[tuple[Evidence, str, str]] = []
    for item in evidence:
        evidence_id = _record_scoped_id("evi", record_id)
        path = _record_ref(record_id, f"evidence/{evidence_id}.json")
        evidence_publications.append(
            (item.model_copy(update={"evidence_id": evidence_id, "source_ref": output_ref}), path, item.evidence_id)
        )
    gap_publications: list[tuple[DataGap, str, str]] = []
    for item in gaps:
        gap_id = _record_scoped_id("gap", record_id)
        path = _record_ref(record_id, f"gaps/{gap_id}.json")
        gap_publications.append(
            (item.model_copy(update={"gap_id": gap_id}), path, item.gap_id)
        )
    if portfolio_snapshot is not None:
        snapshot_id = f"snap_{record_id[4:]}"
        portfolio_snapshot = portfolio_snapshot.model_copy(update={"snapshot_id": snapshot_id})

    if raw_payload is not None:
        raw_locator = normalized.get("raw_locator")
        if not isinstance(raw_locator, str) or not json_pointer_exists(raw_payload, raw_locator):
            raise SourceContractError("normalized raw locator does not resolve")
        for item, _, _ in evidence_publications:
            if not json_pointer_exists(raw_payload, item.locator):
                raise SourceContractError("evidence locator does not resolve against persisted raw source")

    publication = _write_source_record(
        root=settings.root,
        record_id=record_id,
        request_id=request_id,
        call_operation=operation,
        source_result=source_result,
        raw_payload=raw_payload,
        normalized=normalized,
        evidence=evidence_publications,
        gaps=gap_publications,
        portfolio_snapshot=portfolio_snapshot,
    )
    status, error = _call_status(source_result, bool(gap_publications))
    warnings: tuple[str, ...] = ()
    if status == "partial":
        warnings = ("source result is evidence-limited; inspect persisted gaps and limitations",)
    return CallResult(
        schema_version=_SCHEMA_VERSION,
        request_id=request_id,
        operation=operation,
        status=status,
        artifacts=publication,
        warnings=warnings,
        gaps=tuple(path for _, path, _ in gap_publications),
        error=error,
    )


def _parse_adapter_result(
    value: Mapping[str, object], *, request: Mapping[str, object]
) -> dict[str, object]:
    required = {"source_result", "raw_payload", "normalized", "evidence", "gaps"}
    if not isinstance(value, Mapping) or not required <= set(value):
        raise SourceContractError("adapter returned an incomplete source mapping")
    normalized = value["normalized"]
    evidence_value = value["evidence"]
    gaps_value = value["gaps"]
    if not isinstance(normalized, dict) or not isinstance(evidence_value, list) or not isinstance(gaps_value, list):
        raise SourceContractError("adapter returned invalid source collection shapes")
    try:
        source_result = SourceResult.model_validate(value["source_result"])
        evidence = tuple(Evidence.model_validate(item) for item in evidence_value)
        gaps = tuple(DataGap.model_validate(item) for item in gaps_value)
        snapshot_value = value.get("portfolio_snapshot")
        portfolio_snapshot = (
            PortfolioSnapshot.model_validate(snapshot_value)
            if snapshot_value is not None
            else None
        )
    except ValidationError as exc:
        raise SourceContractError("adapter returned data outside the shared source models") from exc
    if source_result.source != request.get("source") or source_result.operation != request.get("operation"):
        raise SourceContractError("adapter source identity does not match the request")
    request_id = _request_id(request)
    if any(item.request_id != request_id for item in gaps):
        raise SourceContractError("adapter gap request identity does not match the request")
    raw_payload = value["raw_payload"]
    if raw_payload is None and source_result.quality != "failed":
        raise SourceContractError("a nonfailed source result requires a persistable raw payload")
    if raw_payload is not None and source_result.payload_ref is None:
        raise SourceContractError("a returned raw payload requires a prospective payload reference")
    broker_source = source_result.source in {"ibkr_flex", "longbridge_oauth"}
    if portfolio_snapshot is not None:
        if not broker_source or source_result.operation != "positions":
            raise SourceContractError("portfolio snapshot is only valid for broker positions")
        if portfolio_snapshot.broker != source_result.source:
            raise SourceContractError("portfolio snapshot broker identity does not match source")
        if source_result.quality == "failed":
            raise SourceContractError("failed broker source cannot publish a portfolio snapshot")
        if source_result.quality == "complete" and not portfolio_snapshot.complete_read:
            raise SourceContractError("complete broker source cannot publish a partial snapshot")
    elif broker_source and source_result.operation == "positions" and source_result.quality == "complete":
        raise SourceContractError("complete broker positions require a portfolio snapshot")
    return {
        "source_result": source_result,
        "raw_payload": raw_payload,
        "normalized": normalized,
        "evidence": evidence,
        "gaps": gaps,
        "portfolio_snapshot": portfolio_snapshot,
    }


def _write_source_record(
    *,
    root: Path,
    record_id: str,
    request_id: str,
    call_operation: str,
    source_result: SourceResult,
    raw_payload: object,
    normalized: dict[str, object],
    evidence: list[tuple[Evidence, str, str]],
    gaps: list[tuple[DataGap, str, str]],
    portfolio_snapshot: PortfolioSnapshot | None,
) -> tuple[ArtifactSummary, ...]:
    root_path = Path(root).resolve(strict=True)
    records_candidate = safe_relative_path(root_path, "data/records", must_exist=False)
    records_candidate.mkdir(parents=True, exist_ok=True)
    records_root = records_candidate.resolve(strict=True)
    if not records_root.is_relative_to(root_path):
        raise SourceRouterError("records directory escapes the configured root")
    final_dir = records_root / record_id
    temp_dir = records_root / f".tmp-{record_id}-{uuid.uuid4().hex}"
    if final_dir.exists():
        raise SourceRouterError("immutable source record already exists")

    source_result_id = _record_scoped_id("src", record_id)
    normalized_id = _record_scoped_id("norm", record_id)
    raw_id = _record_scoped_id("raw", record_id) if raw_payload is not None else None
    manifest_id = _record_scoped_id("manifest", record_id)
    source_result_ref = _record_ref(record_id, "source-result.json")
    normalized_ref = _record_ref(record_id, "normalized.json")
    raw_ref = _record_ref(record_id, "raw.json") if raw_payload is not None else None
    record_ref = _record_ref(record_id, "record.json")
    manifest_ref = _record_ref(record_id, "manifest.json")
    portfolio_snapshot_ref = (
        _record_ref(record_id, "portfolio-snapshot.json")
        if portfolio_snapshot is not None
        else None
    )
    created_at = datetime.now(timezone.utc).isoformat()

    canonical = {
        "schema_version": _SCHEMA_VERSION,
        "record_id": record_id,
        "request_id": request_id,
        "operation": call_operation,
        "created_at": created_at,
        "source_result_ref": source_result_ref,
        "raw_ref": raw_ref,
        "normalized_ref": normalized_ref,
        "evidence": [{"evidence_id": item.evidence_id, "path": path} for item, path, _ in evidence],
        "gaps": [{"gap_id": item.gap_id, "path": path} for item, path, _ in gaps],
        "portfolio_snapshot_ref": portfolio_snapshot_ref,
    }
    payloads: dict[str, bytes] = {
        "source-result.json": _json_bytes(source_result.model_dump(mode="json")),
        "normalized.json": _json_bytes(normalized),
        "record.json": _json_bytes(canonical),
    }
    if raw_payload is not None:
        payloads["raw.json"] = _json_bytes(raw_payload)
    if portfolio_snapshot is not None:
        payloads["portfolio-snapshot.json"] = _json_bytes(
            portfolio_snapshot.model_dump(mode="json")
        )
    for item, path, _ in evidence:
        payloads[_inside_record(record_id, path)] = _json_bytes(item.model_dump(mode="json"))
    for item, path, _ in gaps:
        payloads[_inside_record(record_id, path)] = _json_bytes(item.model_dump(mode="json"))
    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "record_id": record_id,
        "created_at": created_at,
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for name, data in sorted(payloads.items())
        },
        "id_paths": {
            source_result_id: source_result_ref,
            normalized_id: normalized_ref,
            **({raw_id: raw_ref} if raw_id is not None and raw_ref is not None else {}),
            **{item.evidence_id: path for item, path, _ in evidence},
            **{item.gap_id: path for item, path, _ in gaps},
            record_id: record_ref,
            manifest_id: manifest_ref,
            **(
                {portfolio_snapshot.snapshot_id: portfolio_snapshot_ref}
                if portfolio_snapshot is not None and portfolio_snapshot_ref is not None
                else {}
            ),
        },
        "adapter_ids": {
            original: item.evidence_id for item, _, original in evidence
        }
        | {original: item.gap_id for item, _, original in gaps},
    }
    payloads["manifest.json"] = _json_bytes(manifest)
    _reject_unsafe_content(
        {
            "source_result": source_result.model_dump(mode="json"),
            "normalized": normalized,
            "canonical": canonical,
            "manifest": manifest,
            "raw_payload": raw_payload,
            "evidence": [item.model_dump(mode="json") for item, _, _ in evidence],
            "gaps": [item.model_dump(mode="json") for item, _, _ in gaps],
        },
        (),
    )

    try:
        temp_dir.mkdir()
        (temp_dir / "evidence").mkdir()
        (temp_dir / "gaps").mkdir()
        for name, data in payloads.items():
            _write_new(temp_dir / Path(name), data)
        os.replace(temp_dir, final_dir)
    except OSError as exc:
        _cleanup_temp(temp_dir, records_root)
        raise SourceRouterError("source record could not be published atomically") from exc
    except Exception:
        _cleanup_temp(temp_dir, records_root)
        raise

    artifacts = [
        ArtifactSummary(path=record_ref, type="source_record", summary="immutable canonical source record", artifact_id=record_id),
        ArtifactSummary(path=source_result_ref, type="source_result", summary="typed source result", artifact_id=source_result_id),
        ArtifactSummary(path=normalized_ref, type="source_normalized", summary="normalized source data and limitations", artifact_id=normalized_id),
    ]
    if raw_ref is not None and raw_id is not None:
        artifacts.append(
            ArtifactSummary(path=raw_ref, type="source_raw", summary="immutable raw provider or imported payload", artifact_id=raw_id)
        )
    if portfolio_snapshot is not None and portfolio_snapshot_ref is not None:
        artifacts.append(
            ArtifactSummary(
                path=portfolio_snapshot_ref,
                type="portfolio_snapshot",
                summary="typed immutable read-only portfolio snapshot",
                artifact_id=portfolio_snapshot.snapshot_id,
            )
        )
    artifacts.extend(
        ArtifactSummary(path=path, type="evidence", summary="immutable evidence locator", artifact_id=item.evidence_id)
        for item, path, _ in evidence
    )
    artifacts.extend(
        ArtifactSummary(path=path, type="data_gap", summary="immutable data gap and attempts", artifact_id=item.gap_id)
        for item, path, _ in gaps
    )
    artifacts.append(
        ArtifactSummary(path=manifest_ref, type="source_manifest", summary="immutable ID, path, hash, and size mapping", artifact_id=manifest_id)
    )
    return tuple(artifacts)


def _call_status(
    source_result: SourceResult, has_gaps: bool
) -> tuple[str, CallError | None]:
    if source_result.quality == "failed":
        raw_reason = source_result.errors[0] if source_result.errors else "external"
        reason = raw_reason if raw_reason in _ERROR_REASONS else "external"
        return "error", CallError(reason=reason, message="source operation failed; inspect persisted gaps")  # type: ignore[arg-type]
    if source_result.quality == "limited" or source_result.errors or has_gaps:
        return "partial", None
    return "ok", None


def _canonical_fetch_request(request: Mapping[str, object]) -> dict[str, object]:
    canonical = dict(request)
    if canonical.get("operation") == "daily_bars":
        canonical["operation"] = "bars"
    return canonical


def _require_matching_root(root: Path, settings: Settings) -> None:
    if Path(root).resolve(strict=True) != settings.root.resolve(strict=True):
        raise SourceRouterError("handler root does not match resolved settings root")


def _allocate_record_id(root: Path) -> str:
    root_path = Path(root).resolve(strict=True)
    records = safe_relative_path(root_path, "data/records", must_exist=False)
    for _ in range(8):
        record_id = _new_id("rec")
        if not (records / record_id).exists():
            return record_id
    raise SourceRouterError("could not allocate a unique source record ID")


def _record_ref(record_id: str, suffix: str) -> str:
    return f"data/records/{record_id}/{suffix}"


def _inside_record(record_id: str, ref: str) -> str:
    prefix = f"data/records/{record_id}/"
    if not ref.startswith(prefix):
        raise SourceRouterError("generated source path escaped its record")
    return ref[len(prefix) :]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _record_scoped_id(prefix: str, record_id: str) -> str:
    if prefix not in {"evi", "gap", "src", "norm", "raw", "manifest"} or not record_id.startswith("rec_"):
        raise SourceRouterError("record-scoped ID inputs are invalid")
    if prefix in {"evi", "gap"}:
        return f"{prefix}_{record_id[4:]}_{uuid.uuid4().hex}"
    return f"{prefix}_{record_id[4:]}"


def _request_id(request: Mapping[str, object]) -> str:
    value = request.get("request_id")
    if not isinstance(value, str) or not value:
        raise SourceContractError("request_id must be a non-empty string")
    return value


def _reject_unsafe_content(value: object, secret_values: Sequence[str]) -> None:
    try:
        reject_secrets(value)
        rendered = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    except (SecretContentError, TypeError, ValueError) as exc:
        raise SourceContractError("source content is unsafe or not JSON serializable") from exc
    for secret in secret_values:
        if secret and secret in rendered:
            raise SourceContractError("source content reflected configured credential material")


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
        raise SourceContractError("source content is not strict JSON") from exc
    return (rendered + "\n").encode("utf-8")


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _cleanup_temp(temp_dir: Path, records_root: Path) -> None:
    if not temp_dir.exists():
        return
    resolved = temp_dir.resolve(strict=True)
    if resolved.parent != records_root or not resolved.name.startswith(".tmp-rec_"):
        raise SourceRouterError("refused to clean an unexpected source temp directory")
    shutil.rmtree(resolved)


def _unsupported(request_id: str, operation: str) -> CallResult:
    return CallResult(
        schema_version=_SCHEMA_VERSION,
        request_id=request_id,
        operation=operation,
        status="error",
        artifacts=(),
        warnings=(),
        gaps=(),
        error=CallError(reason="unsupported", message="source or operation is not implemented in the current slice"),
    )


def _invalid(request_id: str, operation: str) -> CallResult:
    return CallResult(
        schema_version=_SCHEMA_VERSION,
        request_id=request_id,
        operation=operation,
        status="error",
        artifacts=(),
        warnings=(),
        gaps=(),
        error=CallError(reason="invalid", message="request failed the source boundary"),
    )
