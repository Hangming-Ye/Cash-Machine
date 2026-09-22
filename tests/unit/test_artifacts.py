import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import cash_research.artifacts as artifacts
from cash_research.artifacts import (
    ArtifactConflictError,
    ArtifactError,
    ArchivedArtifact,
    SecretContentError,
    UnsafePathError,
    archive_artifact,
    check_artifact,
    resolve_reference,
    validate_artifact,
)


NOW = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)


def _decision(*, decision_id: str = "draft-id") -> dict[str, object]:
    return {
        "decision_id": decision_id,
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


def _work_record() -> dict[str, object]:
    return {
        "record_id": "draft-id",
        "request_id": "request-1",
        "created_at": NOW.isoformat(),
        "owner": "research-bot",
        "input_refs": [],
        "output_refs": [],
        "outcome": "limited",
        "limitations": ["one source unavailable"],
    }


def _review() -> dict[str, object]:
    return {
        "review_id": "draft-id",
        "decision_id": "rec_" + "a" * 32,
        "decision_as_of": NOW.isoformat(),
        "review_at": NOW.isoformat(),
        "observed_outcome": "not yet due",
        "process_findings": ["source coverage was narrow"],
        "counterevidence": [],
        "lesson_refs": [],
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_check_defaults_to_validation_only_without_mutating_root(tmp_path: Path) -> None:
    _write_json(tmp_path / "drafts" / "decision.json", _decision())

    checked = check_artifact(
        root=tmp_path, draft_ref="drafts/decision.json", record_type="Decision"
    )

    assert checked.record_type == "Decision"
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    ("record_type", "payload", "id_field"),
    [
        ("Decision", _decision(), "decision_id"),
        ("WorkRecord", _work_record(), "record_id"),
    ],
)
def test_each_core_record_type_is_validated_and_receives_program_id(
    tmp_path: Path, record_type: str, payload: dict[str, object], id_field: str
) -> None:
    _write_json(tmp_path / "draft.json", payload)

    archived = archive_artifact(
        root=tmp_path,
        draft_ref="draft.json",
        record_type=record_type,  # type: ignore[arg-type]
    )

    record_path = tmp_path / archived.relative_path / "record.json"
    canonical = json.loads(record_path.read_text(encoding="utf-8"))
    assert canonical[id_field] == archived.record_id


def test_review_requires_and_resolves_archived_decision_id(tmp_path: Path) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    decision = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    review = _review()
    review["decision_id"] = decision.record_id
    _write_json(tmp_path / "review.json", review)

    archived_review = archive_artifact(
        root=tmp_path, draft_ref="review.json", record_type="Review"
    )

    assert archived_review.provenance[0].ref == decision.record_id


@pytest.mark.parametrize(
    "unsafe_ref",
    [
        "../outside.json",
        "/absolute.json",
        "C:/outside.json",
        "C:outside.json",
        "//server/share/file.json",
        "safe/file.json:stream",
    ],
)
def test_path_escape_drive_unc_and_ads_are_rejected(
    tmp_path: Path, unsafe_ref: str
) -> None:
    with pytest.raises(UnsafePathError):
        resolve_reference(tmp_path, unsafe_ref)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "evidence.json").write_text("{}", encoding="utf-8")
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(UnsafePathError):
        resolve_reference(tmp_path, "linked/evidence.json")


def test_explicit_archive_writes_complete_immutable_record_with_provenance(
    tmp_path: Path,
) -> None:
    draft = tmp_path / "drafts" / "decision.json"
    evidence = tmp_path / "data" / "evidence" / "ev-1.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"claim":"reported revenue"}', encoding="utf-8")
    decision = _decision()
    decision["reason_refs"] = ["data/evidence/ev-1.json"]
    _write_json(draft, decision)
    original_draft = draft.read_bytes()
    archived = check_artifact(
        root=tmp_path,
        draft_ref="drafts/decision.json",
        record_type="Decision",
        archive=True,
    )

    assert isinstance(archived, ArchivedArtifact)
    assert archived.record_id.startswith("rec_")
    record_dir = tmp_path / archived.relative_path
    assert sorted(item.name for item in record_dir.iterdir()) == [
        "draft.json",
        "manifest.json",
        "record.json",
    ]
    assert (record_dir / "draft.json").read_bytes() == original_draft
    record = json.loads((record_dir / "record.json").read_text(encoding="utf-8"))
    assert record["decision_id"] == archived.record_id
    manifest = json.loads((record_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["provenance"][0]["ref"] == "data/evidence/ev-1.json"
    assert len(manifest["provenance"][0]["sha256"]) == 64

    draft.write_text("changed later", encoding="utf-8")
    assert (record_dir / "draft.json").read_bytes() == original_draft


def test_dangling_reference_inside_model_is_rejected(tmp_path: Path) -> None:
    decision = _decision()
    decision["reason_refs"] = ["data/evidence/missing.json"]
    _write_json(tmp_path / "decision.json", decision)

    with pytest.raises((ArtifactError, UnsafePathError)):
        validate_artifact(
            root=tmp_path, draft_ref="decision.json", record_type="Decision"
        )


def test_draft_change_between_validation_and_publish_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = tmp_path / "decision.json"
    _write_json(draft, _decision())
    original_validate = artifacts.validate_artifact

    def change_after_validation(**kwargs: object) -> artifacts.ArtifactValidation:
        result = original_validate(**kwargs)  # type: ignore[arg-type]
        changed = _decision()
        changed["risks"] = ["changed after validation"]
        _write_json(draft, changed)
        return result

    monkeypatch.setattr(artifacts, "validate_artifact", change_after_validation)

    with pytest.raises(ArtifactConflictError, match="changed during validation"):
        archive_artifact(root=tmp_path, draft_ref="decision.json", record_type="Decision")

    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "payload",
    [
        {**_decision(), "apiKey": "do-not-print-this"},
        {**_decision(), "notes": "Authorization: Bearer do-not-print-this"},
        {**_decision(), "notes": "-----BEGIN PRIVATE KEY-----\ndo-not-print-this"},
    ],
)
def test_secret_fields_and_values_are_rejected_without_echo(payload: dict[str, object], tmp_path: Path) -> None:
    _write_json(tmp_path / "draft.json", payload)

    with pytest.raises(SecretContentError) as caught:
        archive_artifact(root=tmp_path, draft_ref="draft.json", record_type="Decision")

    assert "do-not-print-this" not in str(caught.value)
    assert not (tmp_path / "data").exists()


def test_invalid_model_never_creates_archive(tmp_path: Path) -> None:
    invalid = _decision()
    invalid["as_of"] = "2026-09-21T03:00:00"
    _write_json(tmp_path / "draft.json", invalid)

    with pytest.raises(ArtifactError, match="does not match"):
        archive_artifact(root=tmp_path, draft_ref="draft.json", record_type="Decision")

    assert not (tmp_path / "data").exists()


def test_existing_record_is_never_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_json(tmp_path / "draft.json", _decision(decision_id="rec_existing"))
    existing = tmp_path / "data" / "records" / "rec_existing"
    existing.mkdir(parents=True)
    marker = existing / "record.json"
    marker.write_text("old immutable judgment", encoding="utf-8")
    monkeypatch.setattr(artifacts, "_new_record_id", lambda: "rec_existing")

    with pytest.raises(ArtifactConflictError):
        archive_artifact(root=tmp_path, draft_ref="draft.json", record_type="Decision")

    assert marker.read_text(encoding="utf-8") == "old immutable judgment"


def test_mutable_draft_cannot_be_used_as_historical_provenance(tmp_path: Path) -> None:
    _write_json(tmp_path / "drafts" / "decision.json", _decision())
    _write_json(tmp_path / "drafts" / "evidence.json", {"claim": "mutable"})

    with pytest.raises(ArtifactError, match="mutable draft"):
        validate_artifact(
            root=tmp_path,
            draft_ref="drafts/decision.json",
            record_type="Decision",
            reference_refs=("drafts/evidence.json",),
        )

    current = tmp_path / "data" / "topics" / "topic-1" / "current.json"
    _write_json(current, {"version": 2})
    with pytest.raises(ArtifactError, match="mutable draft/current"):
        resolve_reference(tmp_path, "data/topics/topic-1/current.json")


def test_archived_record_id_resolves_for_later_memory_and_cli_checks(tmp_path: Path) -> None:
    _write_json(tmp_path / "draft.json", _decision())
    archived = archive_artifact(
        root=tmp_path, draft_ref="draft.json", record_type="Decision"
    )

    resolved = resolve_reference(tmp_path, archived.record_id)

    assert resolved == (tmp_path / archived.relative_path / "record.json").resolve()


@pytest.mark.parametrize(
    "prefix,relative",
    [
        ("evi", "evidence/{item_id}.json"),
        ("gap", "gaps/{item_id}.json"),
        ("src", "source-result.json"),
        ("norm", "normalized.json"),
        ("raw", "raw.json"),
        ("manifest", "manifest.json"),
    ],
)
def test_record_scoped_source_ids_resolve_without_manifest_path_execution(
    tmp_path: Path, prefix: str, relative: str
) -> None:
    record_hex = "a" * 32
    item_id = (
        f"{prefix}_{record_hex}_{'b' * 32}"
        if prefix in {"evi", "gap"}
        else f"{prefix}_{record_hex}"
    )
    target = (
        tmp_path
        / "data"
        / "records"
        / f"rec_{record_hex}"
        / relative.format(item_id=item_id)
    )
    _write_json(target, {"id": item_id})

    assert resolve_reference(tmp_path, item_id) == target.resolve()


@pytest.mark.parametrize(
    "unsafe_id",
    [
        f"evi_{'a' * 31}_{'b' * 32}",
        f"gap_{'a' * 32}_{'b' * 31}",
        f"evi_{'a' * 32}_../{'b' * 32}",
        f"gap_{'a' * 32}\\{'b' * 32}",
        f"src_{'a' * 31}",
        f"raw_{'a' * 32}/extra",
        f"calc_{'a' * 31}",
        f"snap_{'a' * 32}/extra",
    ],
)
def test_invalid_record_scoped_ids_do_not_resolve_as_generated_references(
    tmp_path: Path, unsafe_id: str
) -> None:
    candidate = tmp_path / unsafe_id
    if "/" not in unsafe_id and "\\" not in unsafe_id and candidate.is_relative_to(tmp_path):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        if not candidate.exists():
            candidate.write_text("{}", encoding="utf-8")
    with pytest.raises((ArtifactError, UnsafePathError)):
        resolve_reference(tmp_path, unsafe_id)


def test_manifest_id_path_text_is_not_used_as_an_executable_reference(
    tmp_path: Path,
) -> None:
    record_hex = "c" * 32
    source_id = f"src_{record_hex}"
    record_dir = tmp_path / "data" / "records" / f"rec_{record_hex}"
    expected = record_dir / "source-result.json"
    _write_json(expected, {"source": "synthetic"})
    _write_json(
        record_dir / "manifest.json",
        {"id_paths": {source_id: "../../outside.json"}},
    )

    assert resolve_reference(tmp_path, source_id) == expected.resolve()


def test_failed_directory_publish_leaves_no_partial_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_json(tmp_path / "draft.json", _decision())
    monkeypatch.setattr(artifacts.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("publish failed")))

    with pytest.raises(ArtifactError, match="could not be published"):
        archive_artifact(root=tmp_path, draft_ref="draft.json", record_type="Decision")

    records = tmp_path / "data" / "records"
    assert records.is_dir()
    assert list(records.iterdir()) == []
