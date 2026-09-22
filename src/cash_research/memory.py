"""Versioned file storage for topic summaries and research lessons."""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, TypeAlias

from pydantic import ValidationError

from cash_research.artifacts import (
    json_pointer_exists,
    reject_secrets,
    resolve_reference,
    safe_relative_path,
)
from cash_research.models import Decision, Evidence, Lesson, MemoryPacket, SourceResult, TopicSummary


MemoryModel: TypeAlias = TopicSummary | Lesson
MemoryKind: TypeAlias = Literal["topics", "lessons"]
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PERSISTED_EVIDENCE_ID = re.compile(
    r"^evi_[0-9a-f]{32}_[0-9a-f]{32}$"
)


class MemoryError(ValueError):
    """Base error for memory storage failures."""


class MemoryNotFoundError(MemoryError):
    """Raised when no requested memory history exists."""


class MemoryReadError(MemoryError):
    """Raised when existing memory cannot be read or validated."""


class _FrozenInputIntegrityError(MemoryReadError):
    """Raised when an older Decision lacks or violates frozen-input hashes."""


class MemoryConflictError(MemoryError):
    """Raised when expected_version does not match current state."""


class MemoryWriteError(MemoryError):
    """Raised when a proposed version cannot be stored safely."""


class MemoryRequestError(MemoryWriteError):
    """Raised when a recall/apply request is structurally invalid."""


@dataclass(frozen=True)
class RecallPublication:
    packet: MemoryPacket
    packet_ref: str
    state_ref: str
    warnings: tuple[str, ...]
    gaps: tuple[str, ...]


def apply_topic(
    *, root: str | Path, proposal: Mapping[str, object], expected_version: int
) -> TopicSummary:
    """Validate and append one topic version using optimistic concurrency."""

    return _apply(root, "topics", proposal, expected_version, TopicSummary)  # type: ignore[return-value]


def read_topic(
    *, root: str | Path, topic_id: str, version: int | None = None
) -> TopicSummary:
    """Read a topic's current or specific immutable version."""

    return _read(root, "topics", topic_id, version, TopicSummary)  # type: ignore[return-value]


def apply_lesson(
    *, root: str | Path, proposal: Mapping[str, object], expected_version: int
) -> Lesson:
    """Validate and append one lesson version using optimistic concurrency."""

    return _apply(root, "lessons", proposal, expected_version, Lesson)  # type: ignore[return-value]


def read_lesson(
    *, root: str | Path, lesson_id: str, version: int | None = None
) -> Lesson:
    """Read a lesson's current or specific immutable version."""

    return _read(root, "lessons", lesson_id, version, Lesson)  # type: ignore[return-value]


def read_index(*, root: str | Path) -> dict[str, dict[str, dict[str, object]]]:
    """Rebuild the lookup index from authoritative current files."""

    root_path = Path(root).resolve(strict=True)
    result: dict[str, dict[str, dict[str, object]]] = {"topics": {}, "lessons": {}}
    for kind, model_type in (("topics", TopicSummary), ("lessons", Lesson)):
        kind_root = safe_relative_path(root_path, f"data/{kind}", must_exist=False)
        if not kind_root.exists():
            continue
        if not kind_root.is_dir():
            raise MemoryReadError("memory index source is unreadable or corrupt")
        for candidate in kind_root.iterdir():
            if not candidate.is_dir() or not _SAFE_ID.fullmatch(candidate.name):
                raise MemoryReadError("memory index source is unreadable or corrupt")
            current = safe_relative_path(
                root_path, f"data/{kind}/{candidate.name}/current.json", must_exist=False
            )
            if not current.is_file():
                versions = safe_relative_path(
                    root_path, f"data/{kind}/{candidate.name}/versions", must_exist=False
                )
                if versions.exists() and any(versions.iterdir()):
                    raise MemoryReadError("memory index source is unreadable or corrupt")
                continue
            try:
                model = _load_model(current, model_type, candidate.name, None)
            except MemoryReadError:
                raise MemoryReadError("memory index source is unreadable or corrupt") from None
            result[kind][candidate.name] = {
                "version": model.version,
                "known_at": model.known_at.isoformat(),
                "current_ref": f"data/{kind}/{candidate.name}/current.json",
            }
    return result


def recall_memory(
    *, root: str | Path, request: Mapping[str, object]
) -> RecallPublication:
    """Select time-safe basic memory and publish an immutable packet."""

    root_path = Path(root).resolve(strict=True)
    request_id = _required_string(request, "request_id")
    query = _required_string(request, "query")
    mode = request.get("context_mode")
    if not isinstance(mode, str) or mode not in {"current", "historical", "review"}:
        raise MemoryRequestError("context_mode must be current, historical, or review")
    as_of = _request_time(request.get("as_of"), allow_runtime=mode == "current")
    topic_ids = _id_list(request.get("topic_ids", []), "topic_ids")
    lesson_ids = _id_list(request.get("lesson_ids", []), "lesson_ids")
    budget = _budget(request.get("budget"))
    query_metadata = _query_metadata(request.get("query_metadata"))
    warnings: list[str] = []
    gaps: list[str] = []
    exclusions: list[str] = []
    selected_refs: list[str] = []

    if mode == "review":
        decision_id = _required_string(request, "decision_id")
        review_at = _request_time(request.get("review_at"), allow_runtime=False)
        if review_at < as_of:
            raise MemoryRequestError("review_at cannot precede as_of")
        original_inputs, original_refs = _review_inputs(
            root_path, decision_id, as_of, gaps, warnings
        )
        later_items, later_refs = _select_items(
            root_path, topic_ids, lesson_ids, review_at, exclusions, gaps,
            query=query, query_metadata=query_metadata,
        )
        selected_refs.extend(original_refs)
        selected_refs.extend(later_refs)
        content: dict[str, object] = {
            "schema_version": "1.0",
            "context_mode": "review",
            "original_inputs": original_inputs,
            "later_facts_and_lessons": later_items,
            "exclusions": exclusions,
            "query_metadata": query_metadata,
        }
        review_at_value: datetime | None = review_at
        decision_id_value: str | None = decision_id
        item_count = len(original_inputs) + len(later_items)
    else:
        items, item_refs = _select_items(
            root_path, topic_ids, lesson_ids, as_of, exclusions, gaps,
            query=query, query_metadata=query_metadata,
        )
        selected_refs.extend(item_refs)
        content = {
            "schema_version": "1.0",
            "context_mode": mode,
            "items": items,
            "exclusions": exclusions,
            "query_metadata": query_metadata,
        }
        review_at_value = None
        decision_id_value = None
        item_count = len(items)

    content, full_index = _apply_budget(
        content, selected_refs, item_count, budget, warnings
    )
    state_topics, state_lessons = _selected_memory_ids(selected_refs)
    state = _memory_state(
        root_path,
        tuple(dict.fromkeys((*topic_ids, *state_topics))),
        tuple(dict.fromkeys((*lesson_ids, *state_lessons))),
    )
    return _publish_packet(
        root_path,
        request_id=request_id,
        query=query,
        mode=mode,  # type: ignore[arg-type]
        as_of=as_of,
        decision_id=decision_id_value,
        review_at=review_at_value,
        selected_refs=tuple(dict.fromkeys(selected_refs)),
        exclusions=tuple(exclusions),
        budget=budget,
        content=content,
        full_index=full_index,
        state=state,
        warnings=tuple(warnings),
        gaps=tuple(dict.fromkeys(gaps)),
    )


def _select_items(
    root: Path,
    topic_ids: tuple[str, ...],
    lesson_ids: tuple[str, ...],
    cutoff: datetime,
    exclusions: list[str],
    gaps: list[str],
    *, query: str = "", query_metadata: object = None,
) -> tuple[list[dict[str, object]], list[str]]:
    index = read_index(root=root)
    explicit_topics, explicit_lessons = set(topic_ids), set(lesson_ids)
    query_only = not topic_ids and not lesson_ids
    if query_only:
        topic_ids = tuple(index["topics"])
        lesson_ids = tuple(index["lessons"])
    items: list[dict[str, object]] = []
    refs: list[str] = []
    for kind, ids, reader in (
        ("topics", topic_ids, read_topic),
        ("lessons", lesson_ids, read_lesson),
    ):
        for memory_id in ids:
            entry = index[kind].get(memory_id)
            if entry is None:
                exclusions.append(f"no_history:{kind}:{memory_id}")
                continue
            current_version = entry.get("version")
            if not isinstance(current_version, int):
                raise MemoryReadError("memory index contains an invalid version")
            chosen: MemoryModel | None = None
            for version in range(current_version, 0, -1):
                try:
                    candidate = reader(
                        root=root,
                        **({"topic_id": memory_id} if kind == "topics" else {"lesson_id": memory_id}),
                        version=version,
                    )
                except MemoryNotFoundError:
                    raise MemoryReadError("stored memory version history is incomplete") from None
                if candidate.known_at <= cutoff:
                    chosen = candidate
                    break
            if chosen is None:
                exclusions.append(f"formed_after_cutoff:{kind}:{memory_id}")
                continue
            if isinstance(chosen, Lesson) and chosen.validity == "superseded":
                exclusions.append(f"superseded_at_cutoff:lessons:{memory_id}")
                continue
            explicit = memory_id in (explicit_topics if kind == "topics" else explicit_lessons)
            if not explicit and not _memory_relevant(chosen, query, query_metadata):
                exclusions.append(f"unrelated:{kind}:{memory_id}")
                continue
            if not _sources_available(root, chosen, cutoff, exclusions, gaps):
                continue
            version_ref = f"data/{kind}/{memory_id}/versions/{chosen.version}.json"
            value = chosen.model_dump(mode="json")
            value["memory_ref"] = version_ref
            items.append(value)
            refs.append(version_ref)
    if not query_only:
        return items, refs
    selected_ids = {item.get("lesson_id") for item in items if item.get("lesson_id")}
    relations = {item.get("lesson_id"): item.get("duplicate_of") for item in items if item.get("lesson_id")}
    filtered_items: list[dict[str, object]] = []
    filtered_refs: list[str] = []
    for item, ref in zip(items, refs):
        duplicate_of = item.get("duplicate_of")
        item_id = item.get("lesson_id")
        if duplicate_of and duplicate_of in selected_ids and duplicate_of != item_id and not relations.get(duplicate_of):
            exclusions.append(f"duplicate:{ref}:{duplicate_of}")
            continue
        if duplicate_of and (duplicate_of == item_id or duplicate_of not in selected_ids or relations.get(duplicate_of)):
            gaps.append(f"duplicate_relation_unresolved:{ref}:{duplicate_of}")
        filtered_items.append(item); filtered_refs.append(ref)
    return filtered_items, filtered_refs


def _memory_relevant(model: MemoryModel, query: str, metadata: object) -> bool:
    query_terms = _terms(query)
    meta = metadata if isinstance(metadata, Mapping) else {}
    requested_topics = {_normalize_term(v) for v in meta.get("topics", []) if isinstance(v, str)}
    requested_methods = {_normalize_term(v) for v in meta.get("methods", []) if isinstance(v, str)}
    requested_securities = {_normalize_term(v) for v in meta.get("securities", []) if isinstance(v, str)}
    topics = {_normalize_term(v) for v in model.topics}
    methods = {_normalize_term(v) for v in model.methods}
    securities = {_normalize_term(v) for v in model.securities}
    aliases = {_normalize_term(v) for v in model.aliases}
    text = " ".join((model.current_thesis, *model.open_questions, *model.next_checks)) if isinstance(model, TopicSummary) else " ".join((model.check_or_method, model.applies_when, *model.counterexamples))
    query_normalized = _normalize_term(query)
    metadata_phrases = topics | methods | aliases
    lexical = bool(query_terms & _terms(text)) or any(phrase and phrase in query_normalized for phrase in metadata_phrases)
    topic_match = bool(requested_topics & topics)
    method_match = bool(requested_methods & methods)
    free_text_securities = {
        match.casefold() for match in re.findall(r"\b[A-Za-z]{2,6}:[A-Za-z0-9.:-]+\b", query)
    }
    stored_security_ids = {value.casefold() for value in model.securities}
    structured_security_match = bool(requested_securities & securities)
    free_text_security_match = bool(free_text_securities & stored_security_ids)
    security_match = (
        structured_security_match
        if requested_securities and securities
        else free_text_security_match
        if free_text_securities and stored_security_ids
        else True
    )
    return security_match and (
        topic_match or method_match or lexical or structured_security_match or free_text_security_match
    )


def _normalize_term(value: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", " ", value.casefold()).strip()


def _terms(value: str) -> set[str]:
    normalized = _normalize_term(value)
    stop = {"the", "and", "to", "of", "a", "an", "in", "for", "with", "is", "are"}
    return {term for term in normalized.split() if len(term) > 1 and term not in stop}


def _selected_memory_ids(refs: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    topics: list[str] = []
    lessons: list[str] = []
    for ref in refs:
        parts = Path(ref).parts
        if len(parts) >= 4 and parts[0] == "data" and parts[1] in {"topics", "lessons"}:
            (topics if parts[1] == "topics" else lessons).append(parts[2])
    return tuple(dict.fromkeys(topics)), tuple(dict.fromkeys(lessons))


def _query_metadata(value: object) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or set(value) - {"topics", "methods", "securities"}:
        raise MemoryRequestError("query_metadata supports only topics, methods, and securities")
    result: dict[str, tuple[str, ...]] = {}
    for key, raw in value.items():
        if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
            raise MemoryRequestError("query_metadata values must be lists of non-empty strings")
        result[str(key)] = tuple(raw)
    return result


def _sources_available(
    root: Path,
    model: MemoryModel,
    cutoff: datetime,
    exclusions: list[str],
    gaps: list[str],
) -> bool:
    source_refs = (
        (*model.support_refs, *model.opposing_refs)
        if isinstance(model, TopicSummary)
        else model.source_refs
    )
    allowed = True
    for ref in source_refs:
        try:
            available_at, unknown_refs = _reference_availability(root, ref)
        except MemoryReadError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise MemoryReadError("memory source reference cannot be read safely") from None
        for unknown_ref in unknown_refs:
            gaps.append(f"source_available_at_unknown:{unknown_ref}")
            exclusions.append(f"unknown_source_availability:{unknown_ref}")
            allowed = False
        if available_at is None:
            continue
        if available_at > cutoff:
            exclusions.append(f"source_available_after_cutoff:{ref}")
            allowed = False
    return allowed


def _reference_availability(
    root: Path, ref: str
) -> tuple[datetime | None, tuple[str, ...]]:
    pending = [ref]
    visited: set[str] = set()
    times: list[datetime] = []
    unknown: list[str] = []
    while pending:
        current_ref = pending.pop()
        path = resolve_reference(root, current_ref)
        canonical = path.relative_to(root).as_posix()
        if canonical in visited:
            continue
        visited.add(canonical)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            unknown.append(current_ref)
            continue
        evidence_id = payload.get("evidence_id")
        if isinstance(evidence_id, str) and _PERSISTED_EVIDENCE_ID.fullmatch(evidence_id):
            try:
                evidence = Evidence.model_validate(payload)
                record_dir = path.parent.parent
                manifest = _source_manifest(root, record_dir)
                _verify_source_file(
                    manifest,
                    f"evidence/{path.name}",
                    path,
                )
                source_path = resolve_reference(root, evidence.source_ref)
                expected_source = (record_dir / "raw.json").resolve(strict=True)
                if evidence.evidence_id != path.stem or source_path != expected_source:
                    raise ValueError
                _verify_source_file(manifest, "raw.json", source_path)
                raw_payload = json.loads(source_path.read_text(encoding="utf-8"))
                if not json_pointer_exists(raw_payload, evidence.locator):
                    raise ValueError
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
                raise MemoryReadError("evidence source reference or raw locator is invalid") from None
        has_formation_time = False
        if payload.get("available_at") is not None:
            try:
                times.append(_parse_time(payload["available_at"]))
            except MemoryRequestError:
                raise MemoryReadError("memory source available_at is invalid") from None
            has_formation_time = True
        relative_parts = Path(canonical).parts
        if (
            payload.get("known_at") is not None
            and len(relative_parts) >= 5
            and relative_parts[0] == "data"
            and relative_parts[1] in {"topics", "lessons"}
            and relative_parts[-2] == "versions"
        ):
            try:
                times.append(_parse_time(payload["known_at"]))
            except MemoryRequestError:
                raise MemoryReadError("memory version known_at is invalid") from None
            has_formation_time = True
        manifest_relative = f"{path.parent.relative_to(root).as_posix()}/manifest.json"
        manifest_path = safe_relative_path(root, manifest_relative, must_exist=False)
        publication_manifest_path: Path | None = None
        if (
            len(relative_parts) >= 4
            and relative_parts[0:2] == ("data", "records")
            and str(relative_parts[2]).startswith("rec_")
        ):
            publication_manifest_path = safe_relative_path(
                root,
                f"data/records/{relative_parts[2]}/manifest.json",
                must_exist=False,
            )
        source_result_ref = payload.get("source_result_ref")
        if path.name == "record.json" and isinstance(source_result_ref, str):
            try:
                manifest = _source_manifest(root, path.parent)
                _verify_source_file(manifest, "record.json", path)
                source_result_path = resolve_reference(root, source_result_ref)
                if source_result_path != (path.parent / "source-result.json").resolve(strict=True):
                    raise ValueError
                _verify_source_file(manifest, "source-result.json", source_result_path)
                SourceResult.model_validate(
                    json.loads(source_result_path.read_text(encoding="utf-8"))
                )
                times.append(_parse_time(manifest["created_at"]))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
                raise MemoryReadError("source record has invalid typed source-result provenance") from None
            pending.append(source_result_ref)
            has_formation_time = True
        elif publication_manifest_path is not None and publication_manifest_path.is_file():
            try:
                publication_manifest = json.loads(
                    publication_manifest_path.read_text(encoding="utf-8")
                )
                inside_record = path.relative_to(publication_manifest_path.parent).as_posix()
                typed_calculation = (
                    isinstance(publication_manifest, dict)
                    and publication_manifest.get("record_type") == "Calculation"
                )
                typed_snapshot = path.name == "portfolio-snapshot.json"
                if not (typed_calculation or typed_snapshot):
                    raise KeyError
                if not isinstance(publication_manifest, dict) or publication_manifest.get(
                    "created_at"
                ) is None:
                    raise ValueError
                _verify_source_file(publication_manifest, inside_record, path)
                times.append(_parse_time(publication_manifest["created_at"]))
                has_formation_time = True
            except KeyError:
                pass
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                MemoryRequestError,
                ValueError,
            ):
                raise MemoryReadError(
                    "calculation or portfolio publication has invalid typed provenance"
                ) from None
        if not has_formation_time and path.name == "record.json" and manifest_path.is_file():
            manifest_path = safe_relative_path(root, manifest_relative)
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                expected_ref = f"data/records/{path.parent.name}/record.json"
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("record_id") != path.parent.name
                    or manifest.get("record_type") not in {"Decision", "Review", "WorkRecord"}
                    or manifest.get("canonical_ref") != expected_ref
                    or manifest.get("archived_at") is None
                ):
                    raise ValueError
                if manifest.get("files") is None:
                    unknown.append(current_ref)
                else:
                    _verify_source_file(manifest, "record.json", path)
                times.append(_parse_time(manifest["archived_at"]))
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                MemoryRequestError,
                ValueError,
            ):
                raise MemoryReadError("archived memory source has invalid provenance") from None
            has_formation_time = True
        elif not has_formation_time and path.name == "packet.json" and manifest_path.is_file():
            manifest_path = safe_relative_path(root, manifest_relative)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or manifest.get("created_at") is None:
                raise MemoryReadError("memory packet has invalid formation provenance")
            try:
                times.append(_parse_time(manifest["created_at"]))
            except MemoryRequestError:
                raise MemoryReadError("memory packet has invalid formation provenance") from None
            has_formation_time = True
        nested = _nested_references(payload)
        pending.extend(nested)
        if not has_formation_time:
            unknown.append(current_ref)
    return max(times) if times else None, tuple(dict.fromkeys(unknown))


def _source_manifest(root: Path, record_dir: Path) -> dict[str, object]:
    manifest_ref = f"{record_dir.relative_to(root).as_posix()}/manifest.json"
    manifest_path = safe_relative_path(root, manifest_ref)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("record_id") != record_dir.name
        or not isinstance(payload.get("created_at"), str)
        or not isinstance(payload.get("files"), dict)
    ):
        raise MemoryReadError("generated source manifest is invalid")
    return payload


def _verify_source_file(
    manifest: Mapping[str, object], relative: str, path: Path
) -> None:
    files = manifest.get("files")
    entry = files.get(relative) if isinstance(files, dict) else None
    if not isinstance(entry, dict):
        raise MemoryReadError("generated source manifest is missing a file hash")
    data = path.read_bytes()
    if (
        entry.get("sha256") != hashlib.sha256(data).hexdigest()
        or entry.get("size") != len(data)
    ):
        raise MemoryReadError("generated source file does not match its immutable manifest")


def _nested_references(payload: Mapping[str, object]) -> tuple[str, ...]:
    fields = {
        "reason_refs",
        "memory_packet_refs",
        "input_refs",
        "output_refs",
        "source_refs",
        "support_refs",
        "opposing_refs",
        "lesson_refs",
        "selected_refs",
        "calculation_refs",
    }
    refs: list[str] = []
    for field in fields:
        value = payload.get(field)
        if isinstance(value, list):
            refs.extend(item for item in value if isinstance(item, str))
    for field in (
        "decision_id",
        "previous_id",
        "calculation_ref",
        "portfolio_snapshot_ref",
    ):
        value = payload.get(field)
        if isinstance(value, str) and (value.startswith("rec_") or "/" in value):
            refs.append(value)
    return tuple(dict.fromkeys(refs))


def _review_inputs(
    root: Path,
    decision_ref: str,
    as_of: datetime,
    gaps: list[str],
    warnings: list[str],
) -> tuple[list[dict[str, object]], list[str]]:
    try:
        decision_path = resolve_reference(root, decision_ref)
    except ValueError:
        raise MemoryRequestError("review decision_id is not a valid frozen reference") from None
    try:
        decision_data = decision_path.read_bytes()
        decision = Decision.model_validate(json.loads(decision_data.decode("utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        raise MemoryReadError("review decision record is unreadable or corrupt") from None
    if decision.as_of != as_of:
        raise MemoryRequestError("review as_of must equal the decision knowledge cutoff")
    try:
        decision_manifest_path = safe_relative_path(
            root, f"{decision_path.parent.relative_to(root).as_posix()}/manifest.json"
        )
        decision_manifest = json.loads(decision_manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(decision_manifest, dict)
            or decision_manifest.get("record_id") != decision.decision_id
            or decision_manifest.get("record_type") != "Decision"
            or decision_manifest.get("canonical_ref")
            != decision_path.relative_to(root).as_posix()
        ):
            raise ValueError
        files = decision_manifest.get("files")
        if files is not None:
            record_entry = files.get("record.json") if isinstance(files, dict) else None
            if (
                not isinstance(record_entry, dict)
                or record_entry.get("sha256") != hashlib.sha256(decision_data).hexdigest()
                or record_entry.get("size") != len(decision_data)
            ):
                raise ValueError
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise MemoryReadError("review Decision manifest is unreadable or not typed") from None

    originals: list[dict[str, object]] = []
    refs: list[str] = []
    for packet_ref in decision.memory_packet_refs:
        try:
            packet, content = _frozen_original_packet(
                root, decision_manifest, packet_ref
            )
            if packet.context_mode == "review" or packet.as_of > as_of:
                raise ValueError
        except _FrozenInputIntegrityError:
            gaps.append(f"original_memory_packet_integrity_unavailable:{packet_ref}")
            continue
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
            gaps.append(f"original_memory_packet_unavailable:{packet_ref}")
            continue
        originals.append(
            {
                "packet_ref": packet_ref,
                "packet": packet.model_dump(mode="json"),
                "content": content,
            }
        )
        refs.append(packet_ref)
    if not decision.memory_packet_refs:
        gaps.append(f"original_memory_packet_missing:{decision_ref}")
    if gaps:
        warnings.append("review original inputs are incomplete; no current memory was substituted")
    return originals, refs


def _frozen_original_packet(
    root: Path,
    decision_manifest: Mapping[str, object],
    packet_ref: str,
) -> tuple[MemoryPacket, dict[str, object]]:
    associations = decision_manifest.get("memory_packets")
    if not isinstance(associations, list):
        raise _FrozenInputIntegrityError("Decision predates frozen memory packet hashes")
    matches = [
        item for item in associations if isinstance(item, dict) and item.get("ref") == packet_ref
    ]
    if len(matches) != 1:
        raise _FrozenInputIntegrityError("Decision memory packet association is missing or ambiguous")
    association = matches[0]
    try:
        packet_path = resolve_reference(root, packet_ref)
        packet_data = packet_path.read_bytes()
        if (
            association.get("relative_path") != packet_path.relative_to(root).as_posix()
            or association.get("sha256") != hashlib.sha256(packet_data).hexdigest()
        ):
            raise ValueError
        packet = MemoryPacket.model_validate(json.loads(packet_data.decode("utf-8")))
        packet_manifest_path = safe_relative_path(
            root, f"{packet_path.parent.relative_to(root).as_posix()}/manifest.json"
        )
        packet_manifest_data = packet_manifest_path.read_bytes()
        if association.get("manifest_sha256") != hashlib.sha256(
            packet_manifest_data
        ).hexdigest():
            raise ValueError
        content_path = resolve_reference(root, packet.content_ref)
        content_data = content_path.read_bytes()
        if (
            association.get("content_ref") != content_path.relative_to(root).as_posix()
            or association.get("content_sha256") != hashlib.sha256(content_data).hexdigest()
        ):
            raise ValueError
        content = json.loads(content_data.decode("utf-8"))
        if not isinstance(content, dict):
            raise ValueError
        index_ref = association.get("index_ref")
        index_sha256 = association.get("index_sha256")
        local_index_refs = []
        for selected_ref in packet.selected_refs:
            selected_path = resolve_reference(root, selected_ref)
            if selected_path.parent == packet_path.parent:
                local_index_refs.append(selected_path.relative_to(root).as_posix())
        if local_index_refs != ([index_ref] if isinstance(index_ref, str) else []):
            raise ValueError
        if index_ref is not None or index_sha256 is not None:
            if not isinstance(index_ref, str) or not isinstance(index_sha256, str):
                raise ValueError
            index_path = resolve_reference(root, index_ref)
            if hashlib.sha256(index_path.read_bytes()).hexdigest() != index_sha256:
                raise ValueError
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise _FrozenInputIntegrityError("frozen memory packet dependency failed hash validation") from None
    return packet, content


def _apply_budget(
    content: dict[str, object],
    selected_refs: list[str],
    item_count: int,
    budget: dict[str, int],
    warnings: list[str],
) -> tuple[dict[str, object], dict[str, object] | None]:
    rendered = json.dumps(content, ensure_ascii=False, sort_keys=True)
    if item_count <= budget["max_items"] and len(rendered) <= budget["max_chars"]:
        return content, None
    warnings.append("complete memory items exceed budget; returned a compact index for follow-up reads")
    if content["context_mode"] == "review":
        originals = content.get("original_inputs", [])
        later = content.get("later_facts_and_lessons", [])
        assert isinstance(originals, list) and isinstance(later, list)
        full_index: dict[str, object] = {
            "original_inputs": [item.get("packet_ref") for item in originals],
            "later_facts_and_lessons": [item.get("memory_ref") for item in later],
            "exclusions": content.get("exclusions", []),
        }
        compact: dict[str, object] = {
            "schema_version": "1.0",
            "context_mode": "review",
            "original_inputs": [],
            "later_facts_and_lessons": [],
            "item_count": item_count,
            "full_index_ref": "__FULL_INDEX_REF__",
        }
    else:
        full_index = {
            "items": [{"memory_ref": ref} for ref in selected_refs],
            "exclusions": content.get("exclusions", []),
        }
        compact = {
            "schema_version": "1.0",
            "context_mode": content["context_mode"],
            "items": [],
            "item_count": item_count,
            "full_index_ref": "__FULL_INDEX_REF__",
        }
    conservative_ref = "data/memory-packets/mem_00000000000000000000000000000000/index.json"
    measured = json.dumps(compact, ensure_ascii=False, sort_keys=True).replace(
        "__FULL_INDEX_REF__", conservative_ref
    )
    if len(measured) > budget["max_chars"]:
        raise MemoryRequestError("memory budget is too small for the compact index reference")
    return compact, full_index


def _memory_state(
    root: Path, topic_ids: tuple[str, ...], lesson_ids: tuple[str, ...]
) -> dict[str, object]:
    index = read_index(root=root)
    entries: list[dict[str, object]] = []
    for kind, ids in (("topics", topic_ids), ("lessons", lesson_ids)):
        for memory_id in ids:
            current = index[kind].get(memory_id, {}).get("version", 0)
            entries.append(
                {
                    "memory_type": kind[:-1],
                    "memory_id": memory_id,
                    "current_version": current,
                    "expected_version": current,
                }
            )
    state: dict[str, object] = {"entries": entries}
    if len(entries) == 1:
        state["current_version"] = entries[0]["current_version"]
        state["expected_version"] = entries[0]["expected_version"]
    return state


def _publish_packet(
    root: Path,
    *,
    request_id: str,
    query: str,
    mode: Literal["current", "historical", "review"],
    as_of: datetime,
    decision_id: str | None,
    review_at: datetime | None,
    selected_refs: tuple[str, ...],
    exclusions: tuple[str, ...],
    budget: dict[str, int],
    content: dict[str, object],
    full_index: dict[str, object] | None,
    state: dict[str, object],
    warnings: tuple[str, ...],
    gaps: tuple[str, ...],
) -> RecallPublication:
    packets_root = safe_relative_path(root, "data/memory-packets", must_exist=False)
    packets_root.mkdir(parents=True, exist_ok=True)
    packets_root = safe_relative_path(root, "data/memory-packets", must_exist=False)
    for _ in range(8):
        packet_id = f"mem_{uuid.uuid4().hex}"
        final_dir = safe_relative_path(
            root, f"data/memory-packets/{packet_id}", must_exist=False
        )
        if not final_dir.exists():
            break
    else:
        raise MemoryWriteError("could not allocate a unique memory packet ID")
    relative_dir = f"data/memory-packets/{packet_id}"
    content_ref = f"{relative_dir}/content.json"
    packet_ref = f"{relative_dir}/packet.json"
    state_ref = f"{relative_dir}/state.json"
    index_ref = f"{relative_dir}/index.json"
    if full_index is not None:
        content = json.loads(
            json.dumps(content).replace("__FULL_INDEX_REF__", index_ref)
        )
        selected_refs = (index_ref,)
    packet = MemoryPacket(
        packet_id=packet_id,
        request_id=request_id,
        query=query,
        context_mode=mode,
        as_of=as_of,
        decision_id=decision_id,
        review_at=review_at,
        selected_refs=selected_refs,
        exclusions=exclusions,
        budget=budget,
        content_ref=content_ref,
    )
    packet_manifest = {
        "schema_version": "1.0",
        "packet_id": packet_id,
        "created_at": _utc_now().isoformat(),
    }
    temporary = packets_root / f".tmp-{packet_id}-{uuid.uuid4().hex}"
    try:
        temporary.mkdir()
        _write_new(temporary / "content.json", _json_bytes(content))
        _write_new(temporary / "packet.json", _json_bytes(packet.model_dump(mode="json")))
        _write_new(temporary / "manifest.json", _json_bytes(packet_manifest))
        _write_new(temporary / "state.json", _json_bytes(state))
        if full_index is not None:
            _write_new(temporary / "index.json", _json_bytes(full_index))
        os.replace(temporary, final_dir)
    except OSError as exc:
        _clean_packet_temp(temporary, packets_root)
        raise MemoryWriteError("memory packet could not be published atomically") from exc
    return RecallPublication(
        packet=packet,
        packet_ref=packet_ref,
        state_ref=state_ref,
        warnings=warnings,
        gaps=gaps,
    )


def _clean_packet_temp(path: Path, packets_root: Path) -> None:
    if not path.exists():
        return
    resolved = path.resolve(strict=True)
    if resolved.parent != packets_root or not resolved.name.startswith(".tmp-mem_"):
        raise MemoryWriteError("refused to clean an unexpected packet directory")
    import shutil

    shutil.rmtree(resolved)


def _write_new(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _required_string(request: Mapping[str, object], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value:
        raise MemoryRequestError(f"{field} must be a non-empty string")
    return value


def _id_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and _SAFE_ID.fullmatch(item) for item in value
    ):
        raise MemoryRequestError(f"{field} must be a list of safe memory IDs")
    if len(set(value)) != len(value):
        raise MemoryRequestError(f"{field} contains duplicates")
    return tuple(value)


def _budget(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != {"max_items", "max_chars"}:
        raise MemoryRequestError("budget must contain max_items and max_chars")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value.values()):
        raise MemoryRequestError("memory budget values must be non-negative integers")
    return {"max_items": value["max_items"], "max_chars": value["max_chars"]}


def _request_time(value: object, *, allow_runtime: bool) -> datetime:
    if value == "runtime":
        if not allow_runtime:
            raise MemoryRequestError("runtime as_of is only valid for current context")
        return _utc_now()
    return _parse_time(value)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise MemoryRequestError("memory time must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MemoryRequestError("memory time must be an ISO-8601 string") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryRequestError("memory time must include a timezone")
    return parsed


def _apply(
    root: str | Path,
    kind: MemoryKind,
    proposal: Mapping[str, object],
    expected_version: int,
    model_type: type[MemoryModel],
) -> MemoryModel:
    root_path = Path(root).resolve(strict=True)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
        raise MemoryConflictError("expected_version must be zero or greater")
    reject_secrets(proposal)
    id_field = "topic_id" if kind == "topics" else "lesson_id"
    memory_id = proposal.get(id_field)
    if not isinstance(memory_id, str) or not _SAFE_ID.fullmatch(memory_id):
        raise MemoryWriteError("memory ID contains unsupported characters")
    validation_time = _utc_now()
    validation_candidate = dict(proposal)
    validation_candidate["version"] = 1
    validation_candidate["known_at"] = validation_time
    validation_candidate["updated_at"] = validation_time
    try:
        validated_proposal = model_type.model_validate(validation_candidate)
    except ValidationError:
        raise MemoryWriteError("memory proposal does not match its contract") from None
    _validate_references(root_path, validated_proposal)
    record_dir = safe_relative_path(root_path, f"data/{kind}/{memory_id}", must_exist=False)
    record_dir.mkdir(parents=True, exist_ok=True)
    record_dir = safe_relative_path(root_path, f"data/{kind}/{memory_id}", must_exist=False)
    lock_path = safe_relative_path(
        root_path, f"data/{kind}/{memory_id}/.lock", must_exist=False
    )
    with _file_lock(lock_path):
        current_path = safe_relative_path(
            root_path, f"data/{kind}/{memory_id}/current.json", must_exist=False
        )
        versions_dir = safe_relative_path(
            root_path, f"data/{kind}/{memory_id}/versions", must_exist=False
        )
        current_version = 0
        if current_path.exists():
            current_path = safe_relative_path(
                root_path, f"data/{kind}/{memory_id}/current.json"
            )
            current = _load_model(current_path, model_type, memory_id, None)
            current_version = current.version
        elif versions_dir.exists() and any(versions_dir.iterdir()):
            raise MemoryReadError("stored memory has history but no current version")
        if current_version != expected_version:
            raise MemoryConflictError(
                f"version conflict: expected {expected_version}, current {current_version}"
            )
        now = _utc_now()
        candidate = dict(proposal)
        candidate["version"] = current_version + 1
        candidate["known_at"] = now
        candidate["updated_at"] = now
        try:
            saved = model_type.model_validate(candidate)
        except ValidationError:
            raise MemoryWriteError("memory proposal does not match its contract") from None
        _validate_references(root_path, saved)
        payload = _json_bytes(saved.model_dump(mode="json"))
        versions_dir.mkdir(exist_ok=True)
        versions_dir = safe_relative_path(
            root_path, f"data/{kind}/{memory_id}/versions", must_exist=False
        )
        version_path = safe_relative_path(
            root_path,
            f"data/{kind}/{memory_id}/versions/{saved.version}.json",
            must_exist=False,
        )
        if version_path.exists():
            raise MemoryConflictError("immutable memory version already exists")
        _publish_version_and_current(version_path, current_path, payload)
        return saved


def _read(
    root: str | Path,
    kind: MemoryKind,
    memory_id: str,
    version: int | None,
    model_type: type[MemoryModel],
) -> MemoryModel:
    root_path = Path(root).resolve(strict=True)
    if not _SAFE_ID.fullmatch(memory_id):
        raise MemoryReadError("memory ID contains unsupported characters")
    if version is not None and (
        isinstance(version, bool) or not isinstance(version, int) or version < 1
    ):
        raise MemoryReadError("memory version must be a positive integer")
    relative = (
        f"data/{kind}/{memory_id}/current.json"
        if version is None
        else f"data/{kind}/{memory_id}/versions/{version}.json"
    )
    path = safe_relative_path(root_path, relative, must_exist=False)
    if not path.is_file():
        if version is None:
            versions = safe_relative_path(
                root_path, f"data/{kind}/{memory_id}/versions", must_exist=False
            )
            if versions.exists() and any(versions.iterdir()):
                raise MemoryReadError("stored memory has history but no current version")
        raise MemoryNotFoundError("requested memory history does not exist")
    return _load_model(path, model_type, memory_id, version)


def _load_model(
    path: Path,
    model_type: type[MemoryModel],
    expected_id: str,
    expected_version: int | None,
) -> MemoryModel:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        model = model_type.model_validate(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        raise MemoryReadError("stored memory is unreadable or corrupt") from None
    actual_id = model.topic_id if isinstance(model, TopicSummary) else model.lesson_id
    if actual_id != expected_id or (expected_version is not None and model.version != expected_version):
        raise MemoryReadError("stored memory identity or version is corrupt")
    return model


def _validate_references(root: Path, model: MemoryModel) -> None:
    refs = (
        (*model.support_refs, *model.opposing_refs)
        if isinstance(model, TopicSummary)
        else model.source_refs
    )
    try:
        for ref in refs:
            resolve_reference(root, ref)
    except ValueError:
        raise MemoryWriteError("memory proposal contains an invalid source reference") from None


def _publish_version_and_current(version_path: Path, current_path: Path, payload: bytes) -> None:
    version_temp = _write_temp(version_path.parent, payload)
    current_temp = _write_temp(current_path.parent, payload)
    published_version = False
    try:
        os.replace(version_temp, version_path)
        published_version = True
        os.replace(current_temp, current_path)
    except OSError as exc:
        if published_version:
            version_path.unlink(missing_ok=True)
        raise MemoryWriteError("memory write could not be published atomically") from exc
    finally:
        version_temp.unlink(missing_ok=True)
        current_temp.unlink(missing_ok=True)


def _write_temp(parent: Path, payload: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=".memory-", suffix=".tmp", dir=parent)
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
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
