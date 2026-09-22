from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import cash_research.artifacts as artifacts
from cash_research.artifacts import (
    ArtifactConflictError,
    ArtifactError,
    SecretContentError,
    UnsafePathError,
    archive_artifact,
    check_artifact,
    resolve_reference,
)
from cash_research.memory import MemoryReadError, recall_memory


NOW = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _decision(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "decision_id": "draft-decision",
        "security_or_topic": {
            "market": "US",
            "exchange": "XNAS",
            "symbol": "SYNV",
            "currency": "USD",
        },
        "as_of": NOW.isoformat(),
        "label": "watch",
        "reason_refs": [],
        "price_or_conditions": None,
        "price_or_conditions_reason": "calculation is not yet available",
        "evidence_limited": True,
        "limitations": ["synthetic fixture evidence only"],
        "horizon": "12 months",
        "risks": ["demand weakens"],
        "invalidators": ["guidance is withdrawn"],
        "previous_id": None,
        "memory_packet_refs": [],
    }
    value.update(overrides)
    return value


def _memory_packet(root: Path, *, as_of: datetime = NOW) -> str:
    publication = recall_memory(
        root=root,
        request={
            "request_id": "decision-memory",
            "query": "synthetic portfolio decision",
            "context_mode": "current",
            "as_of": as_of.isoformat(),
            "topic_ids": [],
            "lesson_ids": [],
            "budget": {"max_items": 3, "max_chars": 4000},
        },
    )
    return publication.packet.packet_id


def _indexed_memory_packet(root: Path) -> str:
    packet_id = "mem_" + "b" * 32
    packet_dir = root / "data/memory-packets" / packet_id
    content_ref = f"data/memory-packets/{packet_id}/content.json"
    index_ref = f"data/memory-packets/{packet_id}/index.json"
    _write_json(packet_dir / "content.json", {"full_index_ref": index_ref, "items": []})
    _write_json(packet_dir / "index.json", {"items": [{"memory_ref": "synthetic"}]})
    _write_json(
        packet_dir / "packet.json",
        {
            "packet_id": packet_id,
            "request_id": "indexed-memory",
            "query": "synthetic indexed packet",
            "context_mode": "current",
            "as_of": NOW.isoformat(),
            "decision_id": None,
            "review_at": None,
            "selected_refs": [index_ref],
            "exclusions": [],
            "budget": {"max_items": 0, "max_chars": 200},
            "content_ref": content_ref,
        },
    )
    _write_json(
        packet_dir / "manifest.json",
        {"schema_version": "1.0", "packet_id": packet_id, "created_at": NOW.isoformat()},
    )
    return packet_id


def _report_inputs(root: Path) -> tuple[Path, Path]:
    report = root / "work" / "report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# Synthetic decision\n\nEvidence-limited watch.\n", encoding="utf-8")
    attachment = _write_json(
        root / "work" / "support.json",
        {"kind": "synthetic_table", "rows": [{"scenario": "base", "value": None}]},
    )
    return report, attachment


def test_report_backed_check_reads_every_input_but_does_not_write(tmp_path: Path) -> None:
    packet_id = _memory_packet(tmp_path)
    _write_json(
        tmp_path / "decision.json",
        _decision(memory_packet_refs=[packet_id]),
    )
    report, attachment = _report_inputs(tmp_path)

    checked = check_artifact(
        root=tmp_path,
        draft_ref="decision.json",
        record_type="Decision",
        report_ref=report.relative_to(tmp_path).as_posix(),
        attachment_refs=(attachment.relative_to(tmp_path).as_posix(),),
    )

    assert checked.report is not None
    assert checked.attachments[0].sha256 == hashlib.sha256(attachment.read_bytes()).hexdigest()
    assert not (tmp_path / "data" / "records").exists()


def test_archive_freezes_exact_report_and_attachment_bytes_with_hash_manifest(
    tmp_path: Path,
) -> None:
    packet_id = _memory_packet(tmp_path)
    draft = _write_json(
        tmp_path / "decision.json",
        _decision(memory_packet_refs=[packet_id]),
    )
    report, attachment = _report_inputs(tmp_path)
    original = {path.name: path.read_bytes() for path in (draft, report, attachment)}

    archived = archive_artifact(
        root=tmp_path,
        draft_ref="decision.json",
        record_type="Decision",
        report_ref="work/report.md",
        attachment_refs=("work/support.json",),
    )

    record_dir = tmp_path / archived.relative_path
    assert (record_dir / "draft.json").read_bytes() == original["decision.json"]
    assert (record_dir / "report.md").read_bytes() == original["report.md"]
    assert (record_dir / "attachments/001.json").read_bytes() == original["support.json"]
    assert archived.report_ref == f"{archived.relative_path}/report.md"
    assert archived.attachment_refs == (f"{archived.relative_path}/attachments/001.json",)
    manifest = json.loads((record_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["report.md"] == {
        "sha256": hashlib.sha256(original["report.md"]).hexdigest(),
        "size": len(original["report.md"]),
    }
    assert manifest["memory_packets"][0]["ref"] == packet_id

    report.write_text("changed after archive", encoding="utf-8")
    attachment.write_text("changed after archive", encoding="utf-8")
    assert (record_dir / "report.md").read_bytes() == original["report.md"]
    assert (record_dir / "attachments/001.json").read_bytes() == original["support.json"]


def test_bare_memory_packet_id_resolves_and_must_match_decision_cutoff(tmp_path: Path) -> None:
    packet_as_of = NOW - timedelta(minutes=1)
    packet_id = _memory_packet(tmp_path, as_of=packet_as_of)
    assert resolve_reference(tmp_path, packet_id) == (
        tmp_path / f"data/memory-packets/{packet_id}/packet.json"
    ).resolve()
    _write_json(tmp_path / "decision.json", _decision(memory_packet_refs=[packet_id]))
    checked = check_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    assert checked.memory_packets[0].context_mode == "current"
    assert checked.memory_packets[0].as_of == packet_as_of.isoformat()

    later_packet = _memory_packet(tmp_path, as_of=NOW + timedelta(minutes=1))
    _write_json(tmp_path / "decision.json", _decision(memory_packet_refs=[later_packet]))
    with pytest.raises(ArtifactError, match="matching immutable recall packets"):
        check_artifact(root=tmp_path, draft_ref="decision.json", record_type="Decision")


def test_indexed_memory_packet_dependencies_are_hashed_and_verified_on_review(
    tmp_path: Path,
) -> None:
    packet_id = _indexed_memory_packet(tmp_path)
    _write_json(tmp_path / "decision.json", _decision(memory_packet_refs=[packet_id]))
    archived = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    association = archived.memory_packets[0]
    assert association.index_ref == f"data/memory-packets/{packet_id}/index.json"
    assert association.index_sha256 == hashlib.sha256(
        (tmp_path / association.index_ref).read_bytes()
    ).hexdigest()

    (tmp_path / association.index_ref).write_text('{"items":[]}', encoding="utf-8")
    review = recall_memory(
        root=tmp_path,
        request={
            "request_id": "review-indexed-memory",
            "query": "review synthetic decision",
            "context_mode": "review",
            "as_of": NOW.isoformat(),
            "decision_id": archived.record_id,
            "review_at": (NOW + timedelta(days=1)).isoformat(),
            "topic_ids": [],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 8000},
        },
    )
    assert f"original_memory_packet_integrity_unavailable:{packet_id}" in review.gaps
    review_content = json.loads(
        (tmp_path / review.packet.content_ref).read_text(encoding="utf-8")
    )
    assert review_content["original_inputs"] == []


@pytest.mark.parametrize("bad_ref", ["mem_bad", "data/memory-packets/mem_bad/packet.json"])
def test_invalid_or_missing_memory_packet_never_becomes_frozen_input(
    tmp_path: Path, bad_ref: str
) -> None:
    _write_json(tmp_path / "decision.json", _decision(memory_packet_refs=[bad_ref]))
    with pytest.raises((ArtifactError, UnsafePathError)):
        check_artifact(root=tmp_path, draft_ref="decision.json", record_type="Decision")
    assert not (tmp_path / "data" / "records").exists()


def test_previous_decision_is_typed_same_entity_nonfuture_and_diffed(tmp_path: Path) -> None:
    previous_draft = _write_json(tmp_path / "previous.json", _decision())
    previous = archive_artifact(
        root=tmp_path, draft_ref=previous_draft.name, record_type="Decision"
    )
    original_record = (tmp_path / previous.relative_path / "record.json").read_bytes()
    corrected = _decision(
        previous_id=previous.record_id,
        label="buy",
        evidence_limited=False,
        limitations=[],
        price_or_conditions=["buy only below a program-supported threshold"],
        price_or_conditions_reason=None,
        horizon="18 months",
    )
    _write_json(tmp_path / "corrected.json", corrected)
    _report_inputs(tmp_path)

    archived = archive_artifact(
        root=tmp_path,
        draft_ref="corrected.json",
        record_type="Decision",
        report_ref="work/report.md",
        change_explanation="New evidence changed label, conditions, and horizon.",
    )

    assert archived.record_id != previous.record_id
    assert (tmp_path / previous.relative_path / "record.json").read_bytes() == original_record
    difference = archived.decision_difference
    assert difference is not None
    assert {"label", "horizon", "price_or_conditions", "evidence_limited", "limitations"} <= set(
        difference.changed_fields
    )
    assert difference.explanation == "New evidence changed label, conditions, and horizon."
    manifest = json.loads(
        (tmp_path / archived.relative_path / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["decision_change"]["previous_id"] == previous.record_id


def test_unchanged_decision_correction_is_new_record_with_empty_diff(tmp_path: Path) -> None:
    _write_json(tmp_path / "first.json", _decision())
    first = archive_artifact(root=tmp_path, draft_ref="first.json", record_type="Decision")
    second_payload = _decision(previous_id=first.record_id)
    _write_json(tmp_path / "second.json", second_payload)
    _report_inputs(tmp_path)
    second = archive_artifact(
        root=tmp_path,
        draft_ref="second.json",
        record_type="Decision",
        report_ref="work/report.md",
        change_explanation="Scheduled refresh found no field change.",
    )
    assert second.record_id != first.record_id
    assert second.decision_difference is not None
    assert second.decision_difference.changed_fields == ()


def test_previous_relationship_rejects_wrong_entity_future_or_nondecision(tmp_path: Path) -> None:
    _write_json(tmp_path / "previous.json", _decision(as_of=(NOW + timedelta(days=1)).isoformat()))
    future = archive_artifact(root=tmp_path, draft_ref="previous.json", record_type="Decision")
    current = _decision(previous_id=future.record_id)
    _write_json(tmp_path / "current.json", current)
    with pytest.raises(ArtifactError, match="later knowledge cutoff"):
        check_artifact(root=tmp_path, draft_ref="current.json", record_type="Decision")

    _write_json(tmp_path / "prior.json", _decision())
    prior = archive_artifact(root=tmp_path, draft_ref="prior.json", record_type="Decision")
    other = _decision(previous_id=prior.record_id)
    other["security_or_topic"] = {
        "market": "US",
        "exchange": "XNYS",
        "symbol": "OTHER",
        "currency": "USD",
    }
    _write_json(tmp_path / "other.json", other)
    with pytest.raises(ArtifactError, match="same security or topic"):
        check_artifact(root=tmp_path, draft_ref="other.json", record_type="Decision")

    fake_id = "rec_" + "a" * 32
    fake_dir = tmp_path / "data/records" / fake_id
    _write_json(fake_dir / "record.json", _decision(decision_id=fake_id))
    _write_json(fake_dir / "manifest.json", {"record_id": fake_id, "created_at": NOW.isoformat()})
    fake = _decision(previous_id=fake_id)
    _write_json(tmp_path / "fake.json", fake)
    with pytest.raises(ArtifactError, match="archived Decision"):
        check_artifact(root=tmp_path, draft_ref="fake.json", record_type="Decision")


def test_tampered_previous_record_fails_manifest_hash_before_diff(tmp_path: Path) -> None:
    _write_json(tmp_path / "first.json", _decision())
    first = archive_artifact(root=tmp_path, draft_ref="first.json", record_type="Decision")
    record_path = tmp_path / first.relative_path / "record.json"
    tampered = json.loads(record_path.read_text(encoding="utf-8"))
    tampered["horizon"] = "tampered horizon"
    _write_json(record_path, tampered)
    _write_json(tmp_path / "second.json", _decision(previous_id=first.record_id))
    with pytest.raises(ArtifactError, match="archived Decision"):
        check_artifact(root=tmp_path, draft_ref="second.json", record_type="Decision")


def test_tampered_decision_cannot_be_restored_as_review_ground_truth(tmp_path: Path) -> None:
    packet_id = _memory_packet(tmp_path)
    _write_json(
        tmp_path / "decision.json",
        _decision(memory_packet_refs=[packet_id]),
    )
    decision = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    record_path = tmp_path / decision.relative_path / "record.json"
    tampered = json.loads(record_path.read_text(encoding="utf-8"))
    tampered["horizon"] = "tampered historical horizon"
    _write_json(record_path, tampered)

    with pytest.raises(MemoryReadError, match="manifest is unreadable or not typed"):
        recall_memory(
            root=tmp_path,
            request={
                "request_id": "review-tampered-decision",
                "query": "review original decision",
                "context_mode": "review",
                "as_of": NOW.isoformat(),
                "decision_id": decision.record_id,
                "review_at": (NOW + timedelta(days=1)).isoformat(),
                "topic_ids": [],
                "lesson_ids": [],
                "budget": {"max_items": 5, "max_chars": 8000},
            },
        )


def test_report_backed_correction_requires_explanation(tmp_path: Path) -> None:
    _write_json(tmp_path / "first.json", _decision())
    first = archive_artifact(root=tmp_path, draft_ref="first.json", record_type="Decision")
    _write_json(tmp_path / "second.json", _decision(previous_id=first.record_id))
    _report_inputs(tmp_path)
    with pytest.raises(ArtifactError, match="requires change_explanation"):
        check_artifact(
            root=tmp_path,
            draft_ref="second.json",
            record_type="Decision",
            report_ref="work/report.md",
        )


def test_review_requires_typed_decision_and_matching_original_cutoff(tmp_path: Path) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    decision = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    review = {
        "review_id": "draft-review",
        "decision_id": decision.record_id,
        "decision_as_of": (NOW - timedelta(minutes=1)).isoformat(),
        "review_at": (NOW + timedelta(days=30)).isoformat(),
        "observed_outcome": "synthetic later outcome",
        "process_findings": ["check the original evidence"],
        "counterevidence": [],
        "lesson_refs": [],
    }
    _write_json(tmp_path / "review.json", review)
    with pytest.raises(ArtifactError, match="decision_as_of must match"):
        check_artifact(root=tmp_path, draft_ref="review.json", record_type="Review")
    review["decision_as_of"] = NOW.isoformat()
    _write_json(tmp_path / "review.json", review)
    archived = archive_artifact(root=tmp_path, draft_ref="review.json", record_type="Review")
    assert archived.provenance[0].ref == decision.record_id


@pytest.mark.parametrize(
    "report_text",
    [
        "api_key = do-not-archive-this",
        "Authorization: Bearer do-not-archive-this",
        "-----BEGIN PRIVATE KEY-----\ndo-not-archive-this",
    ],
)
def test_report_secret_assignments_are_rejected(report_text: str, tmp_path: Path) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    report = tmp_path / "report.md"
    report.write_text(report_text, encoding="utf-8")
    with pytest.raises(SecretContentError):
        archive_artifact(
            root=tmp_path,
            draft_ref="decision.json",
            record_type="Decision",
            report_ref="report.md",
        )
    assert not (tmp_path / "data").exists()


def test_configured_credential_in_attachment_is_rejected_without_echo(tmp_path: Path) -> None:
    secret = "configured-secret-value"
    _write_json(tmp_path / "decision.json", _decision())
    report, attachment = _report_inputs(tmp_path)
    attachment.write_text(f"ordinary notes {secret}", encoding="utf-8")
    with pytest.raises(SecretContentError) as caught:
        archive_artifact(
            root=tmp_path,
            draft_ref="decision.json",
            record_type="Decision",
            report_ref=report.relative_to(tmp_path).as_posix(),
            attachment_refs=(attachment.relative_to(tmp_path).as_posix(),),
            secret_values=(secret,),
        )
    assert secret not in str(caught.value)


def test_short_configured_secret_is_rejected_from_change_explanation(tmp_path: Path) -> None:
    _write_json(tmp_path / "first.json", _decision())
    first = archive_artifact(root=tmp_path, draft_ref="first.json", record_type="Decision")
    _write_json(tmp_path / "second.json", _decision(previous_id=first.record_id))
    _report_inputs(tmp_path)
    with pytest.raises(SecretContentError):
        check_artifact(
            root=tmp_path,
            draft_ref="second.json",
            record_type="Decision",
            report_ref="work/report.md",
            change_explanation="new evidence includes s3",
            secret_values=("s3",),
        )


def test_report_and_attachment_paths_cannot_escape_or_collide(tmp_path: Path) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    _report_inputs(tmp_path)
    with pytest.raises(UnsafePathError):
        check_artifact(
            root=tmp_path,
            draft_ref="decision.json",
            record_type="Decision",
            report_ref="../outside.md",
        )
    with pytest.raises(ArtifactError, match="duplicates"):
        check_artifact(
            root=tmp_path,
            draft_ref="decision.json",
            record_type="Decision",
            report_ref="work/report.md",
            attachment_refs=("work/support.json", "work/support.json"),
        )


def test_two_same_named_attachments_receive_generated_collision_free_names(tmp_path: Path) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    report, _ = _report_inputs(tmp_path)
    _write_json(tmp_path / "one/table.json", {"row": 1})
    _write_json(tmp_path / "two/table.json", {"row": 2})
    archived = archive_artifact(
        root=tmp_path,
        draft_ref="decision.json",
        record_type="Decision",
        report_ref=report.relative_to(tmp_path).as_posix(),
        attachment_refs=("one/table.json", "two/table.json"),
    )
    assert archived.attachment_refs == (
        f"{archived.relative_path}/attachments/001.json",
        f"{archived.relative_path}/attachments/002.json",
    )


def test_report_mutation_after_validation_aborts_without_final_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    report, _ = _report_inputs(tmp_path)
    original_validate = artifacts.validate_artifact

    def mutate_after_validation(**kwargs: object) -> artifacts.ArtifactValidation:
        result = original_validate(**kwargs)  # type: ignore[arg-type]
        report.write_text("mutated after validation", encoding="utf-8")
        return result

    monkeypatch.setattr(artifacts, "validate_artifact", mutate_after_validation)
    with pytest.raises(ArtifactConflictError, match="changed during validation"):
        archive_artifact(
            root=tmp_path,
            draft_ref="decision.json",
            record_type="Decision",
            report_ref="work/report.md",
        )
    assert not (tmp_path / "data" / "records").exists()


def test_provenance_mutation_after_validation_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = _write_json(tmp_path / "evidence.json", {"claim": "immutable snapshot"})
    _write_json(tmp_path / "decision.json", _decision(reason_refs=["evidence.json"]))
    original_validate = artifacts.validate_artifact

    def mutate_after_validation(**kwargs: object) -> artifacts.ArtifactValidation:
        result = original_validate(**kwargs)  # type: ignore[arg-type]
        evidence.write_text('{"claim":"changed"}', encoding="utf-8")
        return result

    monkeypatch.setattr(artifacts, "validate_artifact", mutate_after_validation)
    with pytest.raises(ArtifactConflictError, match="provenance changed"):
        archive_artifact(root=tmp_path, draft_ref="decision.json", record_type="Decision")
    assert not (tmp_path / "data" / "records").exists()


def test_memory_packet_content_mutation_after_validation_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packet_id = _memory_packet(tmp_path)
    _write_json(
        tmp_path / "decision.json",
        _decision(memory_packet_refs=[packet_id]),
    )
    content = tmp_path / f"data/memory-packets/{packet_id}/content.json"
    original_validate = artifacts.validate_artifact

    def mutate_after_validation(**kwargs: object) -> artifacts.ArtifactValidation:
        result = original_validate(**kwargs)  # type: ignore[arg-type]
        content.write_text('{"changed":true}', encoding="utf-8")
        return result

    monkeypatch.setattr(artifacts, "validate_artifact", mutate_after_validation)
    with pytest.raises(ArtifactConflictError, match="relationship changed"):
        archive_artifact(root=tmp_path, draft_ref="decision.json", record_type="Decision")
    assert not (tmp_path / "data" / "records").exists()


def test_publish_failure_cleans_owned_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_json(tmp_path / "decision.json", _decision())
    _report_inputs(tmp_path)
    original_write = artifacts._write_new

    def fail_manifest(path: Path, data: bytes) -> None:
        if path.name == "manifest.json":
            raise OSError("synthetic manifest failure")
        original_write(path, data)

    monkeypatch.setattr(artifacts, "_write_new", fail_manifest)
    with pytest.raises(ArtifactError, match="could not be published"):
        archive_artifact(
            root=tmp_path,
            draft_ref="decision.json",
            record_type="Decision",
            report_ref="work/report.md",
        )
    records = tmp_path / "data/records"
    assert records.is_dir()
    assert list(records.iterdir()) == []


def test_existing_immutable_reference_is_hashed_not_copied(tmp_path: Path) -> None:
    evidence = _write_json(tmp_path / "immutable-evidence.json", {"claim": "synthetic"})
    _write_json(
        tmp_path / "decision.json",
        _decision(reason_refs=[evidence.relative_to(tmp_path).as_posix()]),
    )
    archived = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    files = {path.relative_to(tmp_path / archived.relative_path).as_posix() for path in (tmp_path / archived.relative_path).rglob("*") if path.is_file()}
    assert files == {"draft.json", "manifest.json", "record.json"}
    assert archived.provenance[0].sha256 == hashlib.sha256(evidence.read_bytes()).hexdigest()
