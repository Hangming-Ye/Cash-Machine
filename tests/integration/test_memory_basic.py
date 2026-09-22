from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cash_research.artifacts import archive_artifact
from cash_research.cli import main
from cash_research.memory import apply_lesson, apply_topic, recall_memory


T1 = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 20, 2, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _invoke(capsys: pytest.CaptureFixture[str], root: Path, args: list[str]) -> dict[str, object]:
    assert main(["--root", str(root), *args]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _decision(packet_refs: list[str]) -> dict[str, object]:
    return {
        "decision_id": "draft",
        "security_or_topic": "synthetic topic",
        "as_of": T1.isoformat(),
        "label": "watch",
        "reason_refs": [],
        "price_or_conditions": None,
        "price_or_conditions_reason": "Synthetic evidence does not support a price.",
        "horizon": "one year",
        "risks": ["Synthetic risk."],
        "invalidators": ["Synthetic invalidator."],
        "memory_packet_refs": packet_refs,
    }


def _evidence(root: Path, name: str, available_at: datetime | None) -> str:
    ref = f"fixtures/memory/{name}.json"
    payload = {"evidence_id": name, "available_at": available_at.isoformat() if available_at else None}
    _write(root / ref, payload)
    return ref


def _topic(topic_id: str, ref: str, thesis: str) -> dict[str, object]:
    return {
        "topic_id": topic_id,
        "current_thesis": thesis,
        "support_refs": [ref],
        "opposing_refs": [],
        "changes": ["Evidence updated."],
        "open_questions": ["What changes next?"],
        "next_checks": ["Read the next filing."],
    }


def test_fixture_requests_complete_a_real_cli_write_read_roundtrip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path(__file__).parents[2]
    evidence = json.loads((repository / "fixtures/memory/synthetic-evidence.json").read_text())
    _write(tmp_path / "fixtures/memory/synthetic-evidence.json", evidence)
    update = json.loads((repository / "fixtures/requests/memory-update.json").read_text())
    update["expected_version"] = 0
    update["support_refs"] = ["fixtures/memory/synthetic-evidence.json"]
    update_path = _write(tmp_path / "memory-update.json", update)

    applied = _invoke(
        capsys, tmp_path, ["memory", "apply", "--proposal", str(update_path)]
    )
    recall_path = repository / "fixtures/requests/memory-recall.json"
    recalled = _invoke(
        capsys, tmp_path, ["memory", "recall", "--request", str(recall_path)]
    )

    assert applied["artifacts"][0]["type"] == "topic_summary"
    assert recalled["artifacts"][0]["type"] == "memory_packet"
    content_ref = next(
        item["path"] for item in recalled["artifacts"] if item["type"] == "memory_content"
    )
    content = json.loads((tmp_path / content_ref).read_text(encoding="utf-8"))
    assert content["items"][0]["topic_id"] == "synthetic-memory-topic"


def test_historical_recall_uses_formation_time_and_source_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as storage

    old_source = _evidence(tmp_path, "old-source", T1)
    monkeypatch.setattr(storage, "_utc_now", lambda: T2)
    apply_topic(root=tmp_path, proposal=_topic("chips", old_source, "Formed later."), expected_version=0)

    before_formation = recall_memory(
        root=tmp_path,
        request={
            "request_id": "before",
            "query": "chips",
            "context_mode": "historical",
            "as_of": T1.isoformat(),
            "topic_ids": ["chips"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    before_content = json.loads((tmp_path / before_formation.packet.content_ref).read_text())
    assert before_content["items"] == []

    after_formation = recall_memory(
        root=tmp_path,
        request={
            "request_id": "after",
            "query": "chips",
            "context_mode": "historical",
            "as_of": T3.isoformat(),
            "topic_ids": ["chips"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    after_content = json.loads((tmp_path / after_formation.packet.content_ref).read_text())
    assert after_content["items"][0]["current_thesis"] == "Formed later."


def test_unknown_source_available_at_is_excluded_with_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as storage

    unknown = _evidence(tmp_path, "unknown-source", None)
    monkeypatch.setattr(storage, "_utc_now", lambda: T1)
    apply_topic(root=tmp_path, proposal=_topic("unknown", unknown, "Must not leak."), expected_version=0)
    publication = recall_memory(
        root=tmp_path,
        request={
            "request_id": "unknown",
            "query": "unknown",
            "context_mode": "current",
            "as_of": T2.isoformat(),
            "topic_ids": ["unknown"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    content = json.loads((tmp_path / publication.packet.content_ref).read_text())
    assert content["items"] == []
    assert any("available_at" in gap for gap in publication.gaps)


def test_current_recall_never_uses_a_version_formed_after_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as storage

    ref = _evidence(tmp_path, "timed", T1)
    monkeypatch.setattr(storage, "_utc_now", lambda: T1)
    apply_topic(root=tmp_path, proposal=_topic("timed", ref, "First."), expected_version=0)
    monkeypatch.setattr(storage, "_utc_now", lambda: T3)
    apply_topic(root=tmp_path, proposal=_topic("timed", ref, "Future."), expected_version=1)
    publication = recall_memory(
        root=tmp_path,
        request={
            "request_id": "cutoff",
            "query": "timed",
            "context_mode": "current",
            "as_of": T2.isoformat(),
            "topic_ids": ["timed"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    content = json.loads((tmp_path / publication.packet.content_ref).read_text())
    assert content["items"][0]["current_thesis"] == "First."


def test_review_preserves_original_packet_and_separates_later_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as storage

    first_ref = _evidence(tmp_path, "original-source", T1)
    later_ref = _evidence(tmp_path, "later-source", T2)
    monkeypatch.setattr(storage, "_utc_now", lambda: T1)
    apply_topic(root=tmp_path, proposal=_topic("original", first_ref, "Original."), expected_version=0)
    original = recall_memory(
        root=tmp_path,
        request={
            "request_id": "original-packet",
            "query": "original",
            "context_mode": "historical",
            "as_of": T1.isoformat(),
            "topic_ids": ["original"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    _write(tmp_path / "decision.json", _decision([original.packet_ref]))
    decision = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    monkeypatch.setattr(storage, "_utc_now", lambda: T2)
    apply_topic(root=tmp_path, proposal=_topic("later", later_ref, "Later."), expected_version=0)

    publication = recall_memory(
        root=tmp_path,
        request={
            "request_id": "review",
            "query": "review original decision",
            "context_mode": "review",
            "as_of": T1.isoformat(),
            "review_at": T3.isoformat(),
            "decision_id": decision.record_id,
            "topic_ids": ["later"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 20000},
        },
    )
    content = json.loads((tmp_path / publication.packet.content_ref).read_text())
    assert content["original_inputs"][0]["packet_ref"] == original.packet_ref
    assert content["later_facts_and_lessons"][0]["topic_id"] == "later"


def test_archived_review_can_be_a_time_safe_lesson_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as storage

    evidence = _evidence(tmp_path, "review-chain-source", T1)
    monkeypatch.setattr(storage, "_utc_now", lambda: T1)
    apply_topic(
        root=tmp_path,
        proposal=_topic("review-chain", evidence, "Original chain memory."),
        expected_version=0,
    )
    original = recall_memory(
        root=tmp_path,
        request={
            "request_id": "review-chain-packet",
            "query": "review chain",
            "context_mode": "historical",
            "as_of": T1.isoformat(),
            "topic_ids": ["review-chain"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    _write(tmp_path / "decision.json", _decision([original.packet_ref]))
    decision = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    review_at = datetime.now(timezone.utc)
    _write(
        tmp_path / "review.json",
        {
            "review_id": "draft-review",
            "decision_id": decision.record_id,
            "decision_as_of": T1.isoformat(),
            "review_at": review_at.isoformat(),
            "observed_outcome": "Synthetic review completed.",
            "process_findings": ["Check availability timing."],
            "counterevidence": [],
            "lesson_refs": [],
        },
    )
    review = archive_artifact(root=tmp_path, draft_ref="review.json", record_type="Review")
    after_archive = datetime.now(timezone.utc)
    monkeypatch.setattr(storage, "_utc_now", lambda: after_archive)
    lesson = {
        "lesson_id": "availability-check",
        "check_or_method": "Check source availability.",
        "applies_when": "Reconstructing historical knowledge.",
        "source_refs": [review.record_id],
        "counterexamples": [],
        "validity": "candidate",
        "review_condition": "After another synthetic review.",
    }
    apply_lesson(root=tmp_path, proposal=lesson, expected_version=0)
    publication = recall_memory(
        root=tmp_path,
        request={
            "request_id": "lesson-recall",
            "query": "availability",
            "context_mode": "current",
            "as_of": "runtime",
            "topic_ids": [],
            "lesson_ids": ["availability-check"],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    content = json.loads((tmp_path / publication.packet.content_ref).read_text())
    assert content["items"][0]["lesson_id"] == "availability-check"


def test_small_budget_returns_bounded_content_and_full_index_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as storage

    ref = _evidence(tmp_path, "budget-source", T1)
    monkeypatch.setattr(storage, "_utc_now", lambda: T1)
    apply_topic(
        root=tmp_path,
        proposal=_topic("budget", ref, "x" * 2000),
        expected_version=0,
    )
    publication = recall_memory(
        root=tmp_path,
        request={
            "request_id": "budget",
            "query": "budget",
            "context_mode": "historical",
            "as_of": T2.isoformat(),
            "topic_ids": ["budget"],
            "lesson_ids": [],
            "budget": {"max_items": 1, "max_chars": 300},
        },
    )
    content_path = tmp_path / publication.packet.content_ref
    content = json.loads(content_path.read_text())
    assert len(content_path.read_text()) <= 300
    assert content["items"] == []
    assert (tmp_path / content["full_index_ref"]).is_file()
    assert publication.packet.selected_refs == (content["full_index_ref"],)


def test_review_without_original_packet_reports_gap_without_substitution(tmp_path: Path) -> None:
    _write(tmp_path / "decision.json", _decision([]))
    decision = archive_artifact(
        root=tmp_path, draft_ref="decision.json", record_type="Decision"
    )
    publication = recall_memory(
        root=tmp_path,
        request={
            "request_id": "missing-original",
            "query": "review",
            "context_mode": "review",
            "as_of": T1.isoformat(),
            "review_at": T2.isoformat(),
            "decision_id": decision.record_id,
            "topic_ids": [],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    content = json.loads((tmp_path / publication.packet.content_ref).read_text())
    assert content["original_inputs"] == []
    assert any("original_memory_packet_missing" in gap for gap in publication.gaps)
