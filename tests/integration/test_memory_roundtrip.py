from __future__ import annotations

import contextlib
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cash_research.artifacts import archive_artifact
from cash_research.cli import main


ROOT = Path(__file__).parents[2]
T1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 3, 1, tzinfo=timezone.utc)
T3 = datetime(2026, 4, 1, tzinfo=timezone.utc)
T4 = datetime(2026, 5, 1, tzinfo=timezone.utc)
AFTER_ARCHIVE = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _invoke(root: Path, args: list[str]) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(["--root", str(root), *args])
    return code, json.loads(output.getvalue())


def _apply(root: Path, name: str, proposal: dict[str, object]) -> tuple[int, dict[str, object]]:
    path = _write(root / f"requests/{name}.json", proposal)
    return _invoke(root, ["memory", "apply", "--proposal", str(path)])


def _recall(root: Path, name: str, request: dict[str, object]) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    path = _write(root / f"requests/{name}.json", request)
    code, envelope = _invoke(root, ["memory", "recall", "--request", str(path)])
    assert code == 0, envelope
    artifacts = {item["type"]: item["path"] for item in envelope["artifacts"]}
    content = json.loads((root / artifacts["memory_content"]).read_text(encoding="utf-8"))
    state = json.loads((root / artifacts["memory_state"]).read_text(encoding="utf-8"))
    return envelope, content, state


def _packet(root: Path, envelope: dict[str, object]) -> dict[str, object]:
    packet_ref = next(
        item["path"] for item in envelope["artifacts"] if item["type"] == "memory_packet"
    )
    return json.loads((root / packet_ref).read_text(encoding="utf-8"))


def _source(root: Path, name: str, available_at: datetime) -> str:
    ref = f"sources/{name}.json"
    _write(root / ref, {"available_at": available_at.isoformat(), "claim": name})
    return ref


def _topic(topic_id: str, ref: str, thesis: str, expected_version: int) -> dict[str, object]:
    return {
        "request_id": f"apply-{topic_id}-{expected_version + 1}",
        "memory_type": "topic",
        "expected_version": expected_version,
        "topic_id": topic_id,
        "current_thesis": thesis,
        "support_refs": [ref],
        "opposing_refs": [],
        "changes": [thesis],
        "open_questions": ["What changed?"],
        "next_checks": ["Recheck the source."],
        "topics": [topic_id],
        "methods": ["periodic-comparison"],
        "securities": ["SYN-A"],
    }


def _lesson(lesson_id: str, ref: str, validity: str, expected_version: int) -> dict[str, object]:
    return {
        "request_id": f"apply-{lesson_id}-{expected_version + 1}",
        "memory_type": "lesson",
        "expected_version": expected_version,
        "lesson_id": lesson_id,
        "check_or_method": "Trace qualification through shipment and acceptance.",
        "applies_when": "A design win precedes volume shipment.",
        "source_refs": [ref],
        "counterexamples": ["Qualification can expire without an award."],
        "validity": validity,
        "review_condition": "Review at the next production milestone.",
        "topics": ["commercialization"],
        "methods": ["qualification-to-revenue"],
        "securities": [],
    }


def _request(name: str, *, mode: str = "current", as_of: datetime = T4, topic_ids: list[str] | None = None, lesson_ids: list[str] | None = None, query: str = "memory") -> dict[str, object]:
    return {
        "request_id": name,
        "query": query,
        "context_mode": mode,
        "as_of": as_of.isoformat(),
        "topic_ids": topic_ids or [],
        "lesson_ids": lesson_ids or [],
        "budget": {"max_items": 10, "max_chars": 20000},
    }


def test_cli_conflict_preserves_history_then_reread_merge_advances_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as memory

    source_a = _source(tmp_path, "baseline", T1)
    source_b = _source(tmp_path, "increment", T2)
    monkeypatch.setattr(memory, "_utc_now", lambda: T1)
    assert _apply(tmp_path, "v1", _topic("capacity", source_a, "Baseline constrained.", 0))[0] == 0
    v1_path = tmp_path / "data/topics/capacity/versions/1.json"
    v1_bytes = v1_path.read_bytes()

    monkeypatch.setattr(memory, "_utc_now", lambda: T2)
    assert _apply(tmp_path, "writer-a", _topic("capacity", source_a, "One line qualified.", 1))[0] == 0
    v2_path = tmp_path / "data/topics/capacity/versions/2.json"
    v2_bytes = v2_path.read_bytes()
    code, conflict = _apply(tmp_path, "stale-writer", _topic("capacity", source_b, "Demand changed.", 1))
    assert code == 2
    assert conflict["error"]["reason"] == "conflict"
    assert v1_path.read_bytes() == v1_bytes
    assert v2_path.read_bytes() == v2_bytes

    _, recalled, state = _recall(tmp_path, "reread", _request("reread", topic_ids=["capacity"]))
    assert recalled["items"][0]["current_thesis"] == "One line qualified."
    assert state["entries"][0]["current_version"] == 2

    merged = _topic("capacity", source_b, "One line qualified; demand also changed.", 2)
    merged["support_refs"] = [source_a, source_b]
    merged["open_questions"] = ["Will qualification convert?", "Will demand persist?"]
    monkeypatch.setattr(memory, "_utc_now", lambda: T3)
    assert _apply(tmp_path, "merged", merged)[0] == 0
    _, current, state = _recall(tmp_path, "merged-read", _request("merged-read", topic_ids=["capacity"]))
    assert current["items"][0]["current_thesis"] == "One line qualified; demand also changed."
    assert current["items"][0]["support_refs"] == [source_a, source_b]
    assert state["entries"][0]["current_version"] == 3
    assert v1_path.read_bytes() == v1_bytes


def test_historical_version_remains_usable_after_current_is_superseded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as memory

    ref = _source(tmp_path, "qualification", T1)
    monkeypatch.setattr(memory, "_utc_now", lambda: T1)
    assert _apply(tmp_path, "lesson-v1", _lesson("conversion", ref, "usable", 0))[0] == 0
    monkeypatch.setattr(memory, "_utc_now", lambda: T3)
    assert _apply(tmp_path, "lesson-v2", _lesson("conversion", ref, "superseded", 1))[0] == 0

    _, historical, state = _recall(
        tmp_path,
        "historical",
        _request("historical", mode="historical", as_of=T2, lesson_ids=["conversion"]),
    )
    assert historical["items"][0]["version"] == 1
    assert historical["items"][0]["validity"] == "usable"
    assert state["entries"][0]["current_version"] == 2
    envelope, current, _ = _recall(tmp_path, "current", _request("current", lesson_ids=["conversion"]))
    assert current["items"] == []
    assert "superseded_at_cutoff:lessons:conversion" in _packet(tmp_path, envelope)["exclusions"]


def test_normal_query_exact_id_and_review_partitions_use_real_packet_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as memory

    periodic = json.loads((ROOT / "fixtures/scenarios/periodic-delta/cases.json").read_text(encoding="utf-8"))
    long_term = json.loads((ROOT / "fixtures/scenarios/long-term-thesis/cases.json").read_text(encoding="utf-8"))
    for payload in (periodic, long_term):
        for ref, value in payload["sources"].items():
            _write(tmp_path / ref, value)
        for candidate in payload["candidates"]:
            proposal = {
                "request_id": f"seed-{candidate['id']}",
                "memory_type": candidate["kind"],
                "expected_version": 0,
                **candidate["proposal"],
                **candidate["index_metadata"],
            }
            if candidate.get("duplicate_of"):
                proposal["duplicate_of"] = candidate["duplicate_of"]
            monkeypatch.setattr(memory, "_utc_now", lambda stamp=candidate["known_at"]: datetime.fromisoformat(stamp.replace("Z", "+00:00")))
            assert _apply(tmp_path, candidate["id"], proposal)[0] == 0

    case = periodic["cases"][0]
    _, content, _ = _recall(tmp_path, "periodic-query", _request("periodic-query", query=case["query"]))
    selected = {item.get("topic_id") or item.get("lesson_id") for item in content["items"]}
    assert selected == {"synthetic-capacity", "verify-order-to-revenue"}
    _, exact, _ = _recall(tmp_path, "exact-unrelated", _request("exact-unrelated", lesson_ids=["unrelated-fx"], query="none"))
    assert exact["items"][0]["lesson_id"] == "unrelated-fx"
    _, cross, _ = _recall(tmp_path, "cross-method", {**_request("cross-method", query=long_term["cases"][0]["query"]), "query_metadata": long_term["cases"][0]["query_metadata"]})
    assert cross["items"][0]["lesson_id"] == "qualification-conversion"
    assert cross["items"][0]["review_condition"]
    assert cross["items"][0]["counterexamples"]

    original_source = _source(tmp_path, "old-deep-input", T1)
    monkeypatch.setattr(memory, "_utc_now", lambda: T1)
    assert _apply(tmp_path, "deep-original", _topic("deep-revision", original_source, "Original assumption.", 0))[0] == 0
    original_envelope, original_content, _ = _recall(tmp_path, "original-packet", _request("original-packet", mode="historical", as_of=T1, topic_ids=["deep-revision"]))
    packet_id = _packet(tmp_path, original_envelope)["packet_id"]
    draft = {
        "decision_id": "draft",
        "security_or_topic": "synthetic deep revision",
        "as_of": T1.isoformat(),
        "label": "watch",
        "reason_refs": [],
        "price_or_conditions": None,
        "price_or_conditions_reason": "No price conclusion.",
        "horizon": "one year",
        "risks": ["Assumption may change."],
        "invalidators": ["Contrary evidence."],
        "memory_packet_refs": [packet_id],
    }
    _write(tmp_path / "decision.json", draft)
    decision = archive_artifact(root=tmp_path, draft_ref="decision.json", record_type="Decision")
    later_source = _source(tmp_path, "later-deep-input", T3)
    monkeypatch.setattr(memory, "_utc_now", lambda: T3)
    assert _apply(tmp_path, "deep-later", _topic("deep-revision", later_source, "Changed assumption; recompute dependency.", 1))[0] == 0
    review_request = {
        **_request("deep-review", mode="review", as_of=T1, topic_ids=["deep-revision"], query="recompute changed assumption"),
        "review_at": T4.isoformat(),
        "decision_id": decision.record_id,
    }
    _, review, _ = _recall(tmp_path, "deep-review", review_request)
    assert "Original assumption." in json.dumps(review["original_inputs"])
    assert review["later_facts_and_lessons"][0]["current_thesis"] == "Changed assumption; recompute dependency."
    assert "Changed assumption" not in json.dumps(review["original_inputs"])


def test_missing_and_tampered_archived_sources_cannot_masquerade_as_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cash_research.memory as memory

    monkeypatch.setattr(memory, "_utc_now", lambda: T2)
    code, invalid = _apply(tmp_path, "missing", _topic("missing", "missing.json", "Invalid.", 0))
    assert code == 2
    assert invalid["error"]["reason"] == "invalid"
    assert not (tmp_path / "data/topics/missing/versions/1.json").exists()

    _write(
        tmp_path / "decision.json",
        {
            "decision_id": "draft",
            "security_or_topic": "integrity source",
            "as_of": T1.isoformat(),
            "label": "watch",
            "reason_refs": [],
            "price_or_conditions": None,
            "price_or_conditions_reason": "No price conclusion.",
            "horizon": "one year",
            "risks": [],
            "invalidators": [],
            "memory_packet_refs": [],
        },
    )
    decision = archive_artifact(root=tmp_path, draft_ref="decision.json", record_type="Decision")
    assert _apply(tmp_path, "archived-source", _topic("archived-source", decision.record_id, "Integrity required.", 0))[0] == 0
    _, before, _ = _recall(tmp_path, "before-tamper", _request("before-tamper", as_of=AFTER_ARCHIVE, topic_ids=["archived-source"]))
    assert before["items"][0]["support_refs"] == [decision.record_id]

    record_path = tmp_path / f"data/records/{decision.record_id}/record.json"
    manifest = json.loads(
        (tmp_path / f"data/records/{decision.record_id}/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    original = record_path.read_bytes()
    assert manifest["canonical_ref"] == f"data/records/{decision.record_id}/record.json"
    assert manifest["files"]["record.json"] == {
        "sha256": hashlib.sha256(original).hexdigest(),
        "size": len(original),
    }
    record_path.write_bytes(original + b" ")
    request_path = _write(tmp_path / "requests/after-tamper.json", _request("after-tamper", as_of=AFTER_ARCHIVE, topic_ids=["archived-source"]))
    code, failed = _invoke(tmp_path, ["memory", "recall", "--request", str(request_path)])
    assert code == 3
    assert failed["status"] == "error"
    assert failed["error"]["message"] == "operation failed in its external runtime"
