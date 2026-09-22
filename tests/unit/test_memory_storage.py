from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cash_research.artifacts import SecretContentError
from cash_research.memory import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryReadError,
    MemoryWriteError,
    apply_lesson,
    apply_topic,
    recall_memory,
    read_index,
    read_lesson,
    read_topic,
)


def _reference(root: Path, name: str = "evidence.json") -> str:
    path = root / "data" / "records" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    return path.relative_to(root).as_posix()


def _topic(root: Path, **overrides: object) -> dict[str, object]:
    proposal: dict[str, object] = {
        "topic_id": "semiconductors",
        "version": 99,
        "known_at": "2000-01-01T00:00:00Z",
        "updated_at": "2000-01-01T00:00:00Z",
        "current_thesis": "Capacity remains constrained.",
        "support_refs": [_reference(root)],
        "opposing_refs": [],
        "changes": ["Added capacity evidence."],
        "open_questions": ["When does supply arrive?"],
        "next_checks": ["Read the next filing."],
    }
    proposal.update(overrides)
    return proposal


def _persisted_source_evidence(
    root: Path, *, available_at: str | None = "2026-01-14T08:00:00Z"
) -> tuple[str, Path]:
    record_hex = "a" * 32
    record_dir = root / "data" / "records" / f"rec_{record_hex}"
    raw = record_dir / "raw.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps({"content": "attributable source text"}), encoding="utf-8")
    evidence_id = f"evi_{record_hex}_{'b' * 32}"
    evidence = record_dir / "evidence" / f"{evidence_id}.json"
    _write = {
        "evidence_id": evidence_id,
        "source_ref": raw.relative_to(root).as_posix(),
        "locator": "/content",
        "published_at": "2026-01-14T08:00:00Z",
        "retrieved_at": "2026-01-15T08:00:00Z",
        "available_at": available_at,
        "content_kind": "third_party_view",
        "claim": "The source contains attributable text.",
        "scope": "one persisted source",
        "units": [],
        "limitations": ["synthetic fixture"],
        "unknown_reasons": (
            {} if available_at is not None else {"available_at": "source availability is unknown"}
        ),
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(_write), encoding="utf-8")
    files = {}
    for relative, source in (
        ("raw.json", raw),
        (f"evidence/{evidence.name}", evidence),
    ):
        data = source.read_bytes()
        files[relative] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
    (record_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "record_id": f"rec_{record_hex}",
                "created_at": "2026-01-15T08:00:00Z",
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    return evidence_id, raw


def _recall_topic(root: Path) -> object:
    return recall_memory(
        root=root,
        request={
            "request_id": "req-persisted-evidence",
            "query": "capacity",
            "context_mode": "current",
            "as_of": "runtime",
            "topic_ids": ["semiconductors"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 10000},
        },
    )


def test_recall_follows_generated_evidence_id_and_validates_persisted_raw(
    tmp_path: Path,
) -> None:
    evidence_id, _ = _persisted_source_evidence(tmp_path)
    apply_topic(
        root=tmp_path,
        proposal=_topic(tmp_path, support_refs=[evidence_id]),
        expected_version=0,
    )

    publication = _recall_topic(tmp_path)
    content = json.loads((tmp_path / publication.packet.content_ref).read_text(encoding="utf-8"))

    assert publication.gaps == ()
    assert content["items"][0]["support_refs"] == [evidence_id]


def test_generated_evidence_with_unknown_availability_remains_excluded(
    tmp_path: Path,
) -> None:
    evidence_id, _ = _persisted_source_evidence(tmp_path, available_at=None)
    apply_topic(
        root=tmp_path,
        proposal=_topic(tmp_path, support_refs=[evidence_id]),
        expected_version=0,
    )

    publication = _recall_topic(tmp_path)
    content = json.loads((tmp_path / publication.packet.content_ref).read_text(encoding="utf-8"))

    assert f"source_available_at_unknown:{evidence_id}" in publication.gaps
    assert content["items"] == []


@pytest.mark.parametrize("damage", ["missing", "same_shape_tamper"])
def test_recall_rejects_missing_or_tampered_raw_behind_generated_evidence_id(
    tmp_path: Path, damage: str
) -> None:
    evidence_id, raw = _persisted_source_evidence(tmp_path)
    apply_topic(
        root=tmp_path,
        proposal=_topic(tmp_path, support_refs=[evidence_id]),
        expected_version=0,
    )
    if damage == "missing":
        raw.unlink()
    else:
        raw.write_text(json.dumps({"content": "altered but same shape"}), encoding="utf-8")

    with pytest.raises(MemoryReadError, match="raw locator"):
        _recall_topic(tmp_path)


def test_generated_source_manifest_symlink_escape_is_rejected(
    tmp_path: Path,
) -> None:
    evidence_id, raw = _persisted_source_evidence(tmp_path)
    apply_topic(
        root=tmp_path,
        proposal=_topic(tmp_path, support_refs=[evidence_id]),
        expected_version=0,
    )
    manifest = raw.parent / "manifest.json"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-manifest.json"
    outside.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
    manifest.unlink()
    try:
        os.symlink(outside, manifest)
    except OSError as exc:
        pytest.skip(f"file symlink is unavailable: {exc}")

    with pytest.raises(MemoryReadError):
        _recall_topic(tmp_path)


def test_topic_write_sets_version_and_server_times_then_reads_current(tmp_path: Path) -> None:
    before = datetime.now(timezone.utc)
    saved = apply_topic(root=tmp_path, proposal=_topic(tmp_path), expected_version=0)
    after = datetime.now(timezone.utc)

    assert saved.version == 1
    assert before <= saved.known_at <= after
    assert saved.updated_at == saved.known_at
    assert read_topic(root=tmp_path, topic_id="semiconductors") == saved
    assert json.loads(
        (tmp_path / "data/topics/semiconductors/current.json").read_text(encoding="utf-8")
    )["version"] == 1


def _competing_write(root: str, thesis: str, start: object, results: object) -> None:
    start.wait()
    proposal = _topic(Path(root), current_thesis=thesis)
    try:
        saved = apply_topic(root=root, proposal=proposal, expected_version=1)
        results.put(("saved", saved.version, thesis))
    except MemoryConflictError:
        results.put(("conflict", None, thesis))


def test_actual_processes_with_same_expected_version_only_one_wins(tmp_path: Path) -> None:
    apply_topic(root=tmp_path, proposal=_topic(tmp_path), expected_version=0)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(target=_competing_write, args=(str(tmp_path), thesis, start, results))
        for thesis in ("First contender", "Second contender")
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    outcomes = sorted(results.get(timeout=2)[0] for _ in processes)
    assert outcomes == ["conflict", "saved"]
    assert read_topic(root=tmp_path, topic_id="semiconductors").version == 2


def test_previous_versions_are_immutable_and_explicitly_readable(tmp_path: Path) -> None:
    first = apply_topic(root=tmp_path, proposal=_topic(tmp_path), expected_version=0)
    second = apply_topic(
        root=tmp_path,
        proposal=_topic(tmp_path, current_thesis="Thesis changed."),
        expected_version=1,
    )

    assert read_topic(root=tmp_path, topic_id="semiconductors", version=1) == first
    assert read_topic(root=tmp_path, topic_id="semiconductors") == second
    assert first.current_thesis == "Capacity remains constrained."


def test_failed_current_replace_leaves_prior_version_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply_topic(root=tmp_path, proposal=_topic(tmp_path), expected_version=0)
    import cash_research.memory as storage

    real_replace = storage.os.replace

    def fail_current(source: str | Path, destination: str | Path) -> None:
        if Path(destination).name == "current.json":
            raise OSError("synthetic replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_current)
    with pytest.raises(MemoryWriteError, match="atomically"):
        apply_topic(
            root=tmp_path,
            proposal=_topic(tmp_path, current_thesis="Must not become current."),
            expected_version=1,
        )

    assert read_topic(root=tmp_path, topic_id="semiconductors").version == 1
    assert not (tmp_path / "data/topics/semiconductors/versions/2.json").exists()
    monkeypatch.setattr(storage.os, "replace", real_replace)
    retried = apply_topic(
        root=tmp_path,
        proposal=_topic(tmp_path, current_thesis="Retry succeeds."),
        expected_version=1,
    )
    assert retried.version == 2


def test_no_history_is_distinct_from_corrupt_storage(tmp_path: Path) -> None:
    with pytest.raises(MemoryNotFoundError):
        read_topic(root=tmp_path, topic_id="never-written")

    current = tmp_path / "data/topics/broken/current.json"
    current.parent.mkdir(parents=True)
    current.write_text("not-json", encoding="utf-8")
    with pytest.raises(MemoryReadError, match="corrupt"):
        read_topic(root=tmp_path, topic_id="broken")


def test_explicit_version_conflict_does_not_overwrite(tmp_path: Path) -> None:
    first = apply_topic(root=tmp_path, proposal=_topic(tmp_path), expected_version=0)
    with pytest.raises(MemoryConflictError, match="expected 0, current 1"):
        apply_topic(
            root=tmp_path,
            proposal=_topic(tmp_path, current_thesis="Lost update."),
            expected_version=0,
        )
    assert read_topic(root=tmp_path, topic_id="semiconductors") == first


def test_lesson_references_must_be_frozen_existing_files(tmp_path: Path) -> None:
    proposal = {
        "lesson_id": "pit-check",
        "version": 40,
        "check_or_method": "Check disclosure availability.",
        "applies_when": "Using point-in-time fundamentals.",
        "source_refs": ["../escape.json"],
        "counterexamples": [],
        "validity": "candidate",
        "review_condition": "After another replay.",
        "known_at": "1999-01-01T00:00:00Z",
        "updated_at": "1999-01-01T00:00:00Z",
    }
    with pytest.raises(MemoryWriteError, match="source reference"):
        apply_lesson(root=tmp_path, proposal=proposal, expected_version=0)

    proposal["source_refs"] = ["data/records/missing.json"]
    with pytest.raises(MemoryWriteError, match="source reference"):
        apply_lesson(root=tmp_path, proposal=proposal, expected_version=0)


def test_lesson_roundtrip_and_index_are_available_to_cli(tmp_path: Path) -> None:
    reference = _reference(tmp_path, "lesson-evidence.json")
    proposal = {
        "lesson_id": "pit-check",
        "check_or_method": "Check disclosure availability.",
        "applies_when": "Using point-in-time fundamentals.",
        "source_refs": [reference],
        "counterexamples": ["Contemporaneous audited data."],
        "validity": "candidate",
        "review_condition": "After another replay.",
    }
    saved = apply_lesson(root=tmp_path, proposal=proposal, expected_version=0)

    assert read_lesson(root=tmp_path, lesson_id="pit-check") == saved
    assert read_index(root=tmp_path)["lessons"]["pit-check"]["version"] == 1


def test_corrupt_index_fails_instead_of_becoming_an_empty_index(tmp_path: Path) -> None:
    current = tmp_path / "data/topics/broken/current.json"
    current.parent.mkdir(parents=True)
    current.write_text("[]", encoding="utf-8")
    with pytest.raises(MemoryReadError, match="index"):
        read_index(root=tmp_path)


def test_index_rebuild_includes_multiple_topics_without_shared_write_state(tmp_path: Path) -> None:
    apply_topic(root=tmp_path, proposal=_topic(tmp_path), expected_version=0)
    apply_topic(
        root=tmp_path,
        proposal=_topic(tmp_path, topic_id="energy", current_thesis="Demand is rising."),
        expected_version=0,
    )
    assert set(read_index(root=tmp_path)["topics"]) == {"semiconductors", "energy"}


def test_existing_history_without_current_is_corruption_not_new_history(tmp_path: Path) -> None:
    version = tmp_path / "data/topics/semiconductors/versions/1.json"
    version.parent.mkdir(parents=True)
    version.write_text("{}\n", encoding="utf-8")
    with pytest.raises(MemoryReadError, match="no current"):
        apply_topic(root=tmp_path, proposal=_topic(tmp_path), expected_version=0)
    with pytest.raises(MemoryReadError, match="no current"):
        read_topic(root=tmp_path, topic_id="semiconductors")


def test_invalid_new_proposal_does_not_poison_index_or_retry(tmp_path: Path) -> None:
    invalid = _topic(tmp_path, support_refs=["data/records/missing.json"])
    with pytest.raises(MemoryWriteError):
        apply_topic(root=tmp_path, proposal=invalid, expected_version=0)
    assert read_index(root=tmp_path) == {"topics": {}, "lessons": {}}

    saved = apply_topic(root=tmp_path, proposal=_topic(tmp_path), expected_version=0)
    assert saved.version == 1


def test_secret_proposal_is_rejected_without_echoing_value(tmp_path: Path) -> None:
    secret = "should-never-appear"
    proposal = _topic(tmp_path, metadata={"api_key": secret})
    with pytest.raises(SecretContentError) as caught:
        apply_topic(root=tmp_path, proposal=proposal, expected_version=0)
    assert secret not in str(caught.value)
