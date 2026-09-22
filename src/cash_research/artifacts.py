"""Validation and immutable publication of core research records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, TypeAlias

from pydantic import BaseModel, ValidationError

from cash_research.models import Decision, MemoryPacket, Review, WorkRecord


RecordType: TypeAlias = Literal["Decision", "WorkRecord", "Review"]
RecordModel: TypeAlias = Decision | WorkRecord | Review

_MODEL_BY_TYPE: dict[str, type[RecordModel]] = {
    "Decision": Decision,
    "WorkRecord": WorkRecord,
    "Review": Review,
}
_ID_FIELD_BY_TYPE = {
    "Decision": "decision_id",
    "WorkRecord": "record_id",
    "Review": "review_id",
}
_ARCHIVE_ID = re.compile(r"^rec_[0-9a-f]{32}$")
_MEMORY_PACKET_ID = re.compile(r"^mem_[0-9a-f]{32}$")
_CALCULATION_ID = re.compile(r"^calc_[0-9a-f]{32}$")
_PORTFOLIO_SNAPSHOT_ID = re.compile(r"^snap_[0-9a-f]{32}$")
_RECORD_ITEM_ID = re.compile(r"^(evi|gap)_([0-9a-f]{32})_([0-9a-f]{32})$")
_RECORD_FIXED_ID = re.compile(r"^(src|norm|raw|manifest)_([0-9a-f]{32})$")
_SECRET_KEY_TOKENS = frozenset(
    {"secret", "password", "token", "apikey", "privatekey", "credential", "authorization"}
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----", re.IGNORECASE),
    re.compile(
        r"(?im)^\s*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret[_-]?key|password|secret|credential)\s*[:=]\s*[^\s]+"
    ),
)
_MUTABLE_REFERENCE_PARTS = frozenset({"draft", "drafts", "tmp", "temp"})


class ArtifactError(ValueError):
    """Raised when an artifact cannot be safely validated or archived."""


class UnsafePathError(ArtifactError):
    """Raised for an absolute, escaping, special, or symlink-escaping path."""


class ArtifactConflictError(ArtifactError):
    """Raised rather than overwrite an existing immutable record."""


class SecretContentError(ArtifactError):
    """Raised when shareable artifact content appears to contain a secret."""


@dataclass(frozen=True)
class ProvenanceLocator:
    ref: str
    relative_path: str
    sha256: str


@dataclass(frozen=True)
class FrozenFile:
    source_ref: str
    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class MemoryPacketAssociation:
    ref: str
    relative_path: str
    sha256: str
    manifest_sha256: str
    content_ref: str
    content_sha256: str
    index_ref: str | None
    index_sha256: str | None
    context_mode: str
    as_of: str


@dataclass(frozen=True)
class DecisionDifference:
    previous_id: str
    explanation: str | None
    changed_fields: tuple[str, ...]
    changes: dict[str, dict[str, object]]


@dataclass(frozen=True)
class ArtifactValidation:
    record_type: RecordType
    draft_ref: str
    draft_sha256: str
    model: RecordModel
    provenance: tuple[ProvenanceLocator, ...]
    report: FrozenFile | None = None
    attachments: tuple[FrozenFile, ...] = ()
    memory_packets: tuple[MemoryPacketAssociation, ...] = ()
    decision_difference: DecisionDifference | None = None


@dataclass(frozen=True)
class ArchivedArtifact:
    record_id: str
    record_type: RecordType
    relative_path: str
    model: RecordModel
    provenance: tuple[ProvenanceLocator, ...]
    manifest_ref: str = ""
    report_ref: str | None = None
    attachment_refs: tuple[str, ...] = ()
    memory_packets: tuple[MemoryPacketAssociation, ...] = ()
    decision_difference: DecisionDifference | None = None


def safe_relative_path(
    root: str | Path,
    ref: str | Path,
    *,
    must_exist: bool = True,
) -> Path:
    """Resolve an ordinary workspace-relative path without drive, UNC, ADS, or escape."""

    root_path = Path(root).resolve(strict=True)
    raw = str(ref)
    windows = PureWindowsPath(raw)
    posix = PurePosixPath(raw.replace("\\", "/"))
    if (
        not raw
        or windows.is_absolute()
        or bool(windows.drive)
        or posix.is_absolute()
        or ".." in posix.parts
        or any(":" in part for part in posix.parts)
    ):
        raise UnsafePathError("path must be a safe workspace-relative path")

    candidate = root_path.joinpath(*posix.parts)
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise UnsafePathError("workspace-relative path could not be resolved") from exc
    if not resolved.is_relative_to(root_path):
        raise UnsafePathError("path escapes the configured workspace root")
    if must_exist and not resolved.is_file():
        raise ArtifactError("referenced path must be an existing file")
    return resolved


def resolve_reference(root: str | Path, ref: str | Path) -> Path:
    """Resolve a frozen file reference or generated archive ID."""

    raw = str(ref)
    if _ARCHIVE_ID.fullmatch(raw):
        return safe_relative_path(root, f"data/records/{raw}/record.json")
    if _MEMORY_PACKET_ID.fullmatch(raw):
        return safe_relative_path(root, f"data/memory-packets/{raw}/packet.json")
    calculation_id = _CALCULATION_ID.fullmatch(raw)
    if calculation_id is not None:
        return safe_relative_path(root, f"data/records/rec_{raw[5:]}/calculation.json")
    snapshot_id = _PORTFOLIO_SNAPSHOT_ID.fullmatch(raw)
    if snapshot_id is not None:
        return safe_relative_path(root, f"data/records/rec_{raw[5:]}/portfolio-snapshot.json")
    item_id = _RECORD_ITEM_ID.fullmatch(raw)
    if item_id is not None:
        prefix = item_id.group(1)
        record_id = f"rec_{item_id.group(2)}"
        kind = "evidence" if prefix == "evi" else "gaps"
        ref_path = f"data/records/{record_id}/{kind}/{raw}.json"
        return safe_relative_path(root, ref_path)
    fixed_id = _RECORD_FIXED_ID.fullmatch(raw)
    if fixed_id is not None:
        prefix = fixed_id.group(1)
        record_id = f"rec_{fixed_id.group(2)}"
        filename = {
            "src": "source-result.json",
            "norm": "normalized.json",
            "raw": "raw.json",
            "manifest": "manifest.json",
        }[prefix]
        ref_path = f"data/records/{record_id}/{filename}"
        return safe_relative_path(root, ref_path)
    if raw.startswith(
        ("evi_", "gap_", "src_", "norm_", "raw_", "manifest_", "mem_", "calc_", "snap_")
    ):
        raise ArtifactError("generated source reference ID is invalid")
    normalized = PurePosixPath(raw.replace("\\", "/"))
    lowered = tuple(part.lower() for part in normalized.parts)
    if any(part in _MUTABLE_REFERENCE_PARTS for part in lowered) or (
        lowered and lowered[-1] == "current.json"
    ):
        raise ArtifactError("mutable draft/current files cannot be historical provenance")
    return safe_relative_path(root, raw)


def validate_artifact(
    *,
    root: str | Path,
    draft_ref: str | Path,
    record_type: RecordType,
    reference_refs: Sequence[str] = (),
    report_ref: str | Path | None = None,
    attachment_refs: Sequence[str] = (),
    change_explanation: str | None = None,
    secret_values: Sequence[str] = (),
) -> ArtifactValidation:
    """Validate a core record and its frozen provenance without writing anything."""

    draft_path = safe_relative_path(root, draft_ref)
    draft_bytes, payload = _read_draft(draft_path)
    _validate_shareable_bytes(
        draft_bytes,
        path=draft_path,
        secret_values=secret_values,
        require_text=True,
    )
    model = _validate_payload(payload, record_type, generated_id=None)
    if isinstance(model, (Decision, WorkRecord)):
        from cash_research.runs import validate_record_run_manifest

        validate_record_run_manifest(root, model)
    all_refs = tuple(dict.fromkeys((*_model_references(model), *reference_refs)))
    provenance = tuple(_provenance_locator(root, ref) for ref in all_refs)
    report, attachments = _freeze_inputs(
        root=root,
        report_ref=report_ref,
        attachment_refs=attachment_refs,
        secret_values=secret_values,
    )
    memory_packets = _validate_record_relationships(root, model)
    difference = _decision_difference(
        root=root,
        model=model,
        report_backed=report is not None,
        change_explanation=change_explanation,
        secret_values=secret_values,
    )
    return ArtifactValidation(
        record_type=record_type,
        draft_ref=_relative_ref(root, draft_path),
        draft_sha256=_sha256(draft_bytes),
        model=model,
        provenance=provenance,
        report=report,
        attachments=attachments,
        memory_packets=memory_packets,
        decision_difference=difference,
    )


def archive_artifact(
    *,
    root: str | Path,
    draft_ref: str | Path,
    record_type: RecordType,
    reference_refs: Sequence[str] = (),
    report_ref: str | Path | None = None,
    attachment_refs: Sequence[str] = (),
    change_explanation: str | None = None,
    secret_values: Sequence[str] = (),
) -> ArchivedArtifact:
    """Validate and atomically publish one new immutable record directory."""

    validated = validate_artifact(
        root=root,
        draft_ref=draft_ref,
        record_type=record_type,
        reference_refs=reference_refs,
        report_ref=report_ref,
        attachment_refs=attachment_refs,
        change_explanation=change_explanation,
        secret_values=secret_values,
    )
    root_path = Path(root).resolve(strict=True)
    draft_path = safe_relative_path(root_path, draft_ref)
    draft_bytes, payload = _read_draft(draft_path)
    if _sha256(draft_bytes) != validated.draft_sha256:
        raise ArtifactConflictError("draft changed during validation; retry with a stable draft")
    report_bytes = _reread_frozen_input(
        root_path, validated.report, secret_values=secret_values, require_text=True
    )
    attachment_bytes = tuple(
        _reread_frozen_input(
            root_path, attachment, secret_values=secret_values, require_text=False
        )
        for attachment in validated.attachments
    )
    _verify_provenance(root_path, validated.provenance)
    _verify_relationships(root_path, validated, change_explanation=change_explanation)

    records_ref = "data/records"
    records_candidate = safe_relative_path(root_path, records_ref, must_exist=False)
    records_candidate.mkdir(parents=True, exist_ok=True)
    records_root = records_candidate.resolve(strict=True)
    if not records_root.is_relative_to(root_path):
        raise UnsafePathError("records directory escapes the configured workspace root")

    record_id = _allocate_record_id(records_root)
    final_dir = records_root / record_id
    temp_dir = records_root / f".tmp-{record_id}-{uuid.uuid4().hex}"
    canonical = _validate_payload(payload, record_type, generated_id=record_id)
    archived_at = datetime.now(timezone.utc).isoformat()
    relative_dir = final_dir.relative_to(root_path).as_posix()
    report_archive_ref = f"{relative_dir}/report.md" if validated.report is not None else None
    attachment_archive_refs = tuple(
        f"{relative_dir}/attachments/{index:03d}{_safe_suffix(item.relative_path)}"
        for index, item in enumerate(validated.attachments, start=1)
    )
    canonical_bytes = _json_bytes(canonical.model_dump(mode="json"))
    manifest = {
        "schema_version": "1.1",
        "record_id": record_id,
        "record_type": record_type,
        "archived_at": archived_at,
        "draft": {
            "source_ref": validated.draft_ref,
            "archived_ref": f"{relative_dir}/draft.json",
            "sha256": validated.draft_sha256,
        },
        "canonical_ref": f"{relative_dir}/record.json",
        "provenance": [locator.__dict__ for locator in validated.provenance],
        "report": (
            {
                **validated.report.__dict__,
                "archived_ref": report_archive_ref,
            }
            if validated.report is not None
            else None
        ),
        "attachments": [
            {**item.__dict__, "archived_ref": archived_ref}
            for item, archived_ref in zip(
                validated.attachments, attachment_archive_refs, strict=True
            )
        ],
        "memory_packets": [item.__dict__ for item in validated.memory_packets],
        "decision_change": (
            validated.decision_difference.__dict__
            if validated.decision_difference is not None
            else None
        ),
        "files": {
            "draft.json": {"sha256": validated.draft_sha256, "size": len(draft_bytes)},
            "record.json": {"sha256": _sha256(canonical_bytes), "size": len(canonical_bytes)},
            **(
                {
                    "report.md": {
                        "sha256": validated.report.sha256,
                        "size": validated.report.size,
                    }
                }
                if validated.report is not None
                else {}
            ),
            **{
                f"attachments/{Path(ref).name}": {
                    "sha256": snapshot.sha256,
                    "size": snapshot.size,
                }
                for snapshot, ref in zip(
                    validated.attachments, attachment_archive_refs, strict=True
                )
            },
        },
    }

    try:
        temp_dir.mkdir()
        _write_new(temp_dir / "draft.json", draft_bytes)
        _write_new(temp_dir / "record.json", canonical_bytes)
        if report_bytes is not None:
            _write_new(temp_dir / "report.md", report_bytes)
        if attachment_bytes:
            (temp_dir / "attachments").mkdir()
            for data, archived_ref in zip(
                attachment_bytes, attachment_archive_refs, strict=True
            ):
                _write_new(temp_dir / "attachments" / Path(archived_ref).name, data)
        _write_new(temp_dir / "manifest.json", _json_bytes(manifest))
        if final_dir.exists():
            raise ArtifactConflictError("immutable record already exists")
        os.replace(temp_dir, final_dir)
    except ArtifactConflictError:
        _remove_temp_dir(temp_dir, records_root)
        raise
    except OSError as exc:
        _remove_temp_dir(temp_dir, records_root)
        raise ArtifactError("artifact could not be published as a complete directory") from exc

    return ArchivedArtifact(
        record_id=record_id,
        record_type=record_type,
        relative_path=relative_dir,
        model=canonical,
        provenance=validated.provenance,
        manifest_ref=f"{relative_dir}/manifest.json",
        report_ref=report_archive_ref,
        attachment_refs=attachment_archive_refs,
        memory_packets=validated.memory_packets,
        decision_difference=validated.decision_difference,
    )


def check_artifact(
    *,
    root: str | Path,
    draft_ref: str | Path,
    record_type: RecordType,
    reference_refs: Sequence[str] = (),
    report_ref: str | Path | None = None,
    attachment_refs: Sequence[str] = (),
    change_explanation: str | None = None,
    secret_values: Sequence[str] = (),
    archive: bool = False,
) -> ArtifactValidation | ArchivedArtifact:
    """Validate by default; publish only when ``archive=True`` is explicit."""

    operation = archive_artifact if archive else validate_artifact
    return operation(
        root=root,
        draft_ref=draft_ref,
        record_type=record_type,
        reference_refs=reference_refs,
        report_ref=report_ref,
        attachment_refs=attachment_refs,
        change_explanation=change_explanation,
        secret_values=secret_values,
    )


def _freeze_inputs(
    *,
    root: str | Path,
    report_ref: str | Path | None,
    attachment_refs: Sequence[str],
    secret_values: Sequence[str],
) -> tuple[FrozenFile | None, tuple[FrozenFile, ...]]:
    if isinstance(attachment_refs, (str, bytes)) or any(
        not isinstance(item, str) or not item for item in attachment_refs
    ):
        raise ArtifactError("attachment_refs must contain workspace-relative file references")
    normalized_attachments = tuple(dict.fromkeys(attachment_refs))
    if len(normalized_attachments) != len(attachment_refs):
        raise ArtifactError("attachment_refs cannot contain duplicates")
    report = (
        _snapshot_input(root, str(report_ref), secret_values=secret_values, require_text=True)
        if report_ref is not None
        else None
    )
    if report is None and normalized_attachments:
        raise ArtifactError("attachments require a report_ref")
    attachments = tuple(
        _snapshot_input(root, ref, secret_values=secret_values, require_text=False)
        for ref in normalized_attachments
    )
    if report is not None and any(item.relative_path == report.relative_path for item in attachments):
        raise ArtifactError("report_ref cannot also be an attachment")
    return report, attachments


def _snapshot_input(
    root: str | Path,
    ref: str,
    *,
    secret_values: Sequence[str],
    require_text: bool,
) -> FrozenFile:
    path = safe_relative_path(root, ref)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ArtifactError("report or attachment could not be read") from exc
    _validate_shareable_bytes(
        data,
        path=path,
        secret_values=secret_values,
        require_text=require_text,
    )
    return FrozenFile(
        source_ref=ref,
        relative_path=_relative_ref(root, path),
        sha256=_sha256(data),
        size=len(data),
    )


def _reread_frozen_input(
    root: Path,
    snapshot: FrozenFile | None,
    *,
    secret_values: Sequence[str],
    require_text: bool,
) -> bytes | None:
    if snapshot is None:
        return None
    path = safe_relative_path(root, snapshot.relative_path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ArtifactConflictError("report or attachment changed during validation") from exc
    _validate_shareable_bytes(
        data,
        path=path,
        secret_values=secret_values,
        require_text=require_text,
    )
    if len(data) != snapshot.size or _sha256(data) != snapshot.sha256:
        raise ArtifactConflictError("report or attachment changed during validation")
    return data


def _validate_shareable_bytes(
    data: bytes,
    *,
    path: Path,
    secret_values: Sequence[str],
    require_text: bool,
) -> None:
    for secret in secret_values:
        if isinstance(secret, str) and secret and secret.encode("utf-8") in data:
            raise SecretContentError("shareable artifact contains a configured credential value")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        if require_text or path.suffix.lower() in {".json", ".md", ".txt", ".csv"}:
            raise ArtifactError("report and text attachments must be UTF-8") from None
        text = data.decode("utf-8", errors="ignore")
    reject_secrets(text)
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ArtifactError("JSON attachment must contain valid JSON") from exc
        reject_secrets(payload)


def _reject_known_secret_text(value: str, secret_values: Sequence[str]) -> None:
    if any(isinstance(secret, str) and secret and secret in value for secret in secret_values):
        raise SecretContentError("shareable artifact contains a configured credential value")


def _safe_suffix(relative_path: str) -> str:
    suffix = Path(relative_path).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ".bin"


def _verify_provenance(root: Path, provenance: Sequence[ProvenanceLocator]) -> None:
    for locator in provenance:
        resolved = resolve_reference(root, locator.ref)
        try:
            data = resolved.read_bytes()
        except OSError as exc:
            raise ArtifactConflictError("provenance changed during validation") from exc
        if _relative_ref(root, resolved) != locator.relative_path or _sha256(data) != locator.sha256:
            raise ArtifactConflictError("provenance changed during validation")


def _verify_relationships(
    root: Path,
    validated: ArtifactValidation,
    *,
    change_explanation: str | None,
) -> None:
    try:
        packets = _validate_record_relationships(root, validated.model)
        difference = _decision_difference(
            root=root,
            model=validated.model,
            report_backed=validated.report is not None,
            change_explanation=change_explanation,
            secret_values=(),
        )
    except ArtifactError as exc:
        raise ArtifactConflictError("record relationship changed during validation") from exc
    if packets != validated.memory_packets or difference != validated.decision_difference:
        raise ArtifactConflictError("record relationship changed during validation")


def _validate_record_relationships(
    root: str | Path, model: RecordModel
) -> tuple[MemoryPacketAssociation, ...]:
    if isinstance(model, Decision):
        packets = tuple(
            _memory_packet_association(root, ref, decision_as_of=model.as_of)
            for ref in model.memory_packet_refs
        )
        if model.previous_id is not None:
            previous = _load_archived_decision(root, model.previous_id)
            if previous.security_or_topic != model.security_or_topic:
                raise ArtifactError("previous Decision must describe the same security or topic")
            if previous.as_of > model.as_of:
                raise ArtifactError("previous Decision cannot be from a later knowledge cutoff")
        return packets
    if isinstance(model, Review):
        decision = _load_archived_decision(root, model.decision_id)
        if decision.as_of != model.decision_as_of:
            raise ArtifactError("Review decision_as_of must match the archived Decision")
    return ()


def _load_archived_decision(root: str | Path, ref: str) -> Decision:
    if not _ARCHIVE_ID.fullmatch(ref):
        raise ArtifactError("Decision relationship must use an immutable record ID")
    try:
        path = resolve_reference(root, ref)
        manifest_path = safe_relative_path(root, f"data/records/{ref}/manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record_data = path.read_bytes()
        payload = json.loads(record_data.decode("utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("record_id") != ref
            or manifest.get("record_type") != "Decision"
            or manifest.get("canonical_ref") != f"data/records/{ref}/record.json"
        ):
            raise ValueError
        files = manifest.get("files")
        if files is not None:
            record_entry = files.get("record.json") if isinstance(files, dict) else None
            if (
                not isinstance(record_entry, dict)
                or record_entry.get("sha256") != _sha256(record_data)
                or record_entry.get("size") != len(record_data)
            ):
                raise ValueError
        decision = Decision.model_validate(payload)
        if decision.decision_id != ref:
            raise ValueError
        return decision
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise ArtifactError("Decision relationship does not identify an archived Decision") from None


def _memory_packet_association(
    root: str | Path,
    ref: str,
    *,
    decision_as_of: datetime,
) -> MemoryPacketAssociation:
    try:
        path = resolve_reference(root, ref)
        relative = _relative_ref(root, path)
        parts = PurePosixPath(relative).parts
        if (
            len(parts) != 4
            or parts[0:2] != ("data", "memory-packets")
            or parts[3] != "packet.json"
            or not _MEMORY_PACKET_ID.fullmatch(parts[2])
        ):
            raise ValueError
        packet_id = parts[2]
        payload = json.loads(path.read_text(encoding="utf-8"))
        packet = MemoryPacket.model_validate(payload)
        manifest_path = safe_relative_path(
            root, f"data/memory-packets/{packet_id}/manifest.json"
        )
        manifest_data = manifest_path.read_bytes()
        manifest = json.loads(manifest_data.decode("utf-8"))
        if (
            packet.packet_id != packet_id
            or not isinstance(manifest, dict)
            or manifest.get("packet_id") != packet_id
            or not isinstance(manifest.get("created_at"), str)
            or packet.context_mode == "review"
            or packet.as_of > decision_as_of
        ):
            raise ValueError
        content_path = resolve_reference(root, packet.content_ref)
        if content_path.parent != path.parent or content_path.name != "content.json":
            raise ValueError
        content_data = content_path.read_bytes()
        local_indexes: list[tuple[str, bytes]] = []
        for selected_ref in packet.selected_refs:
            selected_path = resolve_reference(root, selected_ref)
            if selected_path.parent == path.parent:
                if selected_path.name != "index.json":
                    raise ValueError
                local_indexes.append((_relative_ref(root, selected_path), selected_path.read_bytes()))
        if len(local_indexes) > 1:
            raise ValueError
        index_ref, index_data = local_indexes[0] if local_indexes else (None, None)
        data = path.read_bytes()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise ArtifactError("memory_packet_refs must identify matching immutable recall packets") from None
    return MemoryPacketAssociation(
        ref=ref,
        relative_path=relative,
        sha256=_sha256(data),
        manifest_sha256=_sha256(manifest_data),
        content_ref=_relative_ref(root, content_path),
        content_sha256=_sha256(content_data),
        index_ref=index_ref,
        index_sha256=_sha256(index_data) if index_data is not None else None,
        context_mode=packet.context_mode,
        as_of=packet.as_of.isoformat(),
    )


def _decision_difference(
    *,
    root: str | Path,
    model: RecordModel,
    report_backed: bool,
    change_explanation: str | None,
    secret_values: Sequence[str],
) -> DecisionDifference | None:
    if change_explanation is not None:
        if not isinstance(change_explanation, str) or not change_explanation.strip():
            raise ArtifactError("change_explanation must be a non-empty string")
        reject_secrets(change_explanation)
        _reject_known_secret_text(change_explanation, secret_values)
    if not isinstance(model, Decision) or model.previous_id is None:
        if change_explanation is not None:
            raise ArtifactError("change_explanation requires Decision.previous_id")
        return None
    if report_backed and change_explanation is None:
        raise ArtifactError("report-backed Decision correction requires change_explanation")
    previous = _load_archived_decision(root, model.previous_id)
    before = previous.model_dump(mode="json")
    after = model.model_dump(mode="json")
    ignored = {"decision_id", "previous_id"}
    changes = {
        field: {"previous": before.get(field), "current": after.get(field)}
        for field in sorted((set(before) | set(after)) - ignored)
        if field not in ignored and before.get(field) != after.get(field)
    }
    return DecisionDifference(
        previous_id=model.previous_id,
        explanation=change_explanation.strip() if change_explanation is not None else None,
        changed_fields=tuple(changes),
        changes=changes,
    )


def _read_draft(path: Path) -> tuple[bytes, dict[str, object]]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("draft must be readable UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ArtifactError("draft JSON must contain an object")
    reject_secrets(payload)
    return raw, payload


def _validate_payload(
    payload: dict[str, object], record_type: RecordType, generated_id: str | None
) -> RecordModel:
    model_type = _MODEL_BY_TYPE.get(record_type)
    if model_type is None:
        raise ArtifactError("unsupported record type")
    candidate = dict(payload)
    id_field = _ID_FIELD_BY_TYPE[record_type]
    candidate[id_field] = generated_id or candidate.get(id_field) or "validation_only"
    try:
        return model_type.model_validate(candidate)
    except ValidationError:
        raise ArtifactError("draft does not match the selected record contract") from None


def _provenance_locator(root: str | Path, ref: str) -> ProvenanceLocator:
    resolved = resolve_reference(root, ref)
    data = resolved.read_bytes()
    return ProvenanceLocator(
        ref=ref,
        relative_path=_relative_ref(root, resolved),
        sha256=_sha256(data),
    )


def _model_references(model: RecordModel) -> tuple[str, ...]:
    if isinstance(model, Decision):
        refs = (*model.reason_refs, *model.memory_packet_refs)
        return (*refs, model.previous_id) if model.previous_id is not None else refs
    if isinstance(model, WorkRecord):
        return (*model.input_refs, *model.output_refs)
    return (model.decision_id, *model.lesson_refs)


def _allocate_record_id(records_root: Path) -> str:
    for _ in range(8):
        record_id = _new_record_id()
        if not (records_root / record_id).exists():
            return record_id
    raise ArtifactConflictError("could not allocate a unique immutable record ID")


def _new_record_id() -> str:
    return f"rec_{uuid.uuid4().hex}"


def reject_secrets(value: object) -> None:
    """Reject nested credential fields or credential-like shareable content."""

    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(
                normalized == token or normalized.endswith(token)
                for token in _SECRET_KEY_TOKENS
            ):
                raise SecretContentError("shareable artifact contains a credential field")
            reject_secrets(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_secrets(item)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
        raise SecretContentError("shareable artifact contains credential-like content")


def json_pointer_exists(value: object, pointer: str) -> bool:
    """Return whether an RFC 6901-style pointer resolves in a JSON-compatible value."""

    if pointer == "":
        return True
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return False
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True


def _relative_ref(root: str | Path, path: Path) -> str:
    return path.relative_to(Path(root).resolve(strict=True)).as_posix()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _remove_temp_dir(temp_dir: Path, records_root: Path) -> None:
    if not temp_dir.exists():
        return
    resolved = temp_dir.resolve(strict=True)
    if resolved.parent != records_root or not resolved.name.startswith(".tmp-rec_"):
        raise ArtifactError("refused to clean an unexpected temporary directory")
    shutil.rmtree(resolved)
