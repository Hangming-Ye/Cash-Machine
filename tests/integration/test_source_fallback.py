from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr

from cash_research.artifacts import resolve_reference
from cash_research.cli import main
from cash_research.models import SourceResult
from cash_research.sources import router as source_router


NOW = datetime(2026, 1, 15, 19, 0, tzinfo=timezone.utc)
PROJECT_ROOT = Path(__file__).parents[2]


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _invoke(
    capsys: pytest.CaptureFixture[str], root: Path, group: str, command: str, request: Path
) -> tuple[int, dict[str, object]]:
    option = "--proposal" if (group, command) == ("memory", "apply") else "--request"
    code = main(["--root", str(root), group, command, option, str(request)])
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, json.loads(captured.out)


def _fetch_request() -> dict[str, object]:
    return {
        "request_id": "req-primary-failure",
        "source": "finnhub",
        "operation": "quote",
        "subject": {
            "market": "US",
            "exchange": "XNAS",
            "symbol": "SYNQ",
            "currency": "USD",
        },
        "as_of": NOW.isoformat(),
        "parameters": {},
        "required_fields": ["current_price"],
    }


def _ingest_request(path: str, *, request_id: str = "req-substitute") -> dict[str, object]:
    return {
        "request_id": request_id,
        "source": "user_provided_material",
        "operation": "text_ingest",
        "subject": "synthetic capacity constraint",
        "as_of": NOW.isoformat(),
        "parameters": {
            "path": path,
            "locator": "line:1",
            "origin_url": "https://example.test/synthetic-note",
            "source_name": "Synthetic Public Note",
            "author": "Synthetic Author",
            "organization": "Synthetic Publisher",
            "access_scope": "public synthetic fixture",
            "published_at": "2026-01-15T08:00:00Z",
            "available_at": "2026-01-15T08:00:00Z",
            "content_kind": "third_party_view",
            "claim": "The synthetic note states that capacity is constrained.",
            "scope": "one synthetic excerpt",
            "limitations": ["synthetic fixture; semantic truth is not validated"],
            "material_scope": "excerpt",
        },
        "required_fields": [
            "published_at",
            "available_at",
            "source_locator",
            "access_scope",
            "limitations",
        ],
    }


def _copy_fixture(root: Path, name: str) -> str:
    target = root / "fixtures/ingest" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((PROJECT_ROOT / "fixtures/ingest" / name).read_bytes())
    return target.relative_to(root).as_posix()


def _artifact(envelope: dict[str, object], kind: str) -> dict[str, object]:
    return next(item for item in envelope["artifacts"] if item["type"] == kind)  # type: ignore[union-attr]


def test_primary_failure_then_imported_substitute_is_durable_and_referenceable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    failed_request = _write_json(tmp_path / "requests/fetch.json", _fetch_request())

    failed_code, failed = _invoke(capsys, tmp_path, "data", "fetch", failed_request)

    assert failed_code == 3
    assert failed["status"] == "error"
    assert failed["error"]["reason"] == "unauthorized"  # type: ignore[index]
    failed_record = _artifact(failed, "source_record")
    failed_gap = _artifact(failed, "data_gap")
    assert (tmp_path / failed_record["path"]).is_file()
    assert (tmp_path / failed_gap["path"]).is_file()
    assert failed["gaps"] == [failed_gap["path"]]

    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    ingest_request = _write_json(tmp_path / "requests/ingest.json", _ingest_request(input_ref))
    ingest_code, ingested = _invoke(capsys, tmp_path, "data", "ingest", ingest_request)

    assert ingest_code == 0
    assert ingested["status"] == "partial"
    evidence = _artifact(ingested, "evidence")
    raw = _artifact(ingested, "source_raw")
    normalized = _artifact(ingested, "source_normalized")
    for item in ingested["artifacts"]:  # type: ignore[union-attr]
        assert (tmp_path / item["path"]).is_file()
        assert resolve_reference(tmp_path, item["artifact_id"]) == (tmp_path / item["path"]).resolve()
    evidence_payload = json.loads((tmp_path / evidence["path"]).read_text(encoding="utf-8"))
    assert evidence_payload["source_ref"] == raw["path"]
    assert evidence_payload["locator"] == "/content_utf8"
    raw_payload = json.loads((tmp_path / raw["path"]).read_text(encoding="utf-8"))
    assert raw_payload["content_utf8"] == (tmp_path / input_ref).read_text(encoding="utf-8")
    assert json.loads((tmp_path / normalized["path"]).read_text(encoding="utf-8"))["semantic_validation"] == "not_claimed"
    manifest_artifact = _artifact(ingested, "source_manifest")
    manifest = json.loads((tmp_path / manifest_artifact["path"]).read_text(encoding="utf-8"))
    assert manifest["id_paths"][evidence["artifact_id"]] == evidence["path"]
    assert manifest["id_paths"][raw["artifact_id"]] == raw["path"]
    assert resolve_reference(tmp_path, evidence["artifact_id"]) == (tmp_path / evidence["path"]).resolve()

    decision = {
        "decision_id": "draft-id",
        "security_or_topic": "synthetic capacity constraint",
        "as_of": NOW.isoformat(),
        "label": "watch",
        "reason_refs": [evidence["artifact_id"]],
        "price_or_conditions": None,
        "price_or_conditions_reason": "synthetic evidence is limited",
        "horizon": "one month",
        "risks": ["source is synthetic"],
        "invalidators": ["complete source contradicts the excerpt"],
        "memory_packet_refs": [],
    }
    _write_json(tmp_path / "decision.json", decision)
    check_request = _write_json(
        tmp_path / "requests/check.json",
        {"request_id": "req-check-evidence", "draft_ref": "decision.json", "record_type": "Decision"},
    )
    check_code, checked = _invoke(capsys, tmp_path, "check", "artifact", check_request)
    assert check_code == 0 and checked["status"] == "ok"

    proposal = _write_json(
        tmp_path / "requests/topic.json",
        {
            "request_id": "req-memory-evidence",
            "memory_type": "topic",
            "expected_version": 0,
            "topic_id": "synthetic-capacity",
            "current_thesis": "The imported excerpt is a limited lead.",
            "support_refs": [evidence["artifact_id"], _artifact(ingested, "source_record")["artifact_id"]],
            "opposing_refs": [],
            "changes": ["Imported a traceable substitute."],
            "open_questions": ["Does the complete document support the claim?"],
            "next_checks": ["Obtain the complete public document."],
        },
    )
    memory_code, memory = _invoke(capsys, tmp_path, "memory", "apply", proposal)
    assert memory_code == 0 and memory["status"] == "ok"
    recall_request = _write_json(
        tmp_path / "requests/recall.json",
        {
            "request_id": "req-recall-evidence",
            "query": "synthetic capacity",
            "context_mode": "current",
            "as_of": "runtime",
            "topic_ids": ["synthetic-capacity"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 10000},
        },
    )
    recall_code, recalled = _invoke(capsys, tmp_path, "memory", "recall", recall_request)
    assert recall_code == 0 and recalled["status"] == "ok"


def test_repeated_ingest_creates_distinct_records_without_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    request = _write_json(tmp_path / "requests/ingest.json", _ingest_request(input_ref))
    first_code, first = _invoke(capsys, tmp_path, "data", "ingest", request)
    first_record = _artifact(first, "source_record")
    first_bytes = (tmp_path / first_record["path"]).read_bytes()

    second_code, second = _invoke(capsys, tmp_path, "data", "ingest", request)
    second_record = _artifact(second, "source_record")

    assert first_code == second_code == 0
    assert first_record["artifact_id"] != second_record["artifact_id"]
    assert first_record["path"] != second_record["path"]
    assert (tmp_path / first_record["path"]).read_bytes() == first_bytes


def test_memory_rejects_same_shape_tamper_of_persisted_source_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    ingest_request = _write_json(tmp_path / "requests/ingest.json", _ingest_request(input_ref))
    _, ingested = _invoke(capsys, tmp_path, "data", "ingest", ingest_request)
    record = _artifact(ingested, "source_record")
    source_result = _artifact(ingested, "source_result")
    proposal = _write_json(
        tmp_path / "requests/topic.json",
        {
            "request_id": "req-source-record-topic",
            "memory_type": "topic",
            "expected_version": 0,
            "topic_id": "source-record-integrity",
            "current_thesis": "The source record is intact.",
            "support_refs": [record["artifact_id"]],
            "opposing_refs": [],
            "changes": ["Added source record."],
            "open_questions": [],
            "next_checks": ["Verify integrity."],
        },
    )
    code, _ = _invoke(capsys, tmp_path, "memory", "apply", proposal)
    assert code == 0
    source_path = tmp_path / source_result["path"]
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["coverage"] = "tampered but still valid text"
    source_path.write_text(json.dumps(payload), encoding="utf-8")
    recall = _write_json(
        tmp_path / "requests/recall.json",
        {
            "request_id": "req-source-record-recall",
            "query": "integrity",
            "context_mode": "current",
            "as_of": "runtime",
            "topic_ids": ["source-record-integrity"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 10000},
        },
    )
    recall_code, envelope = _invoke(capsys, tmp_path, "memory", "recall", recall)
    assert recall_code == 3
    assert envelope["status"] == "error" and envelope["artifacts"] == []


def test_pdf_original_bytes_and_hash_survive_router_persistence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-opaque.pdf")
    original = (tmp_path / input_ref).read_bytes()
    request_value = _ingest_request(input_ref, request_id="req-pdf")
    request_value["parameters"].update(  # type: ignore[union-attr]
        {"locator": "page:1", "material_scope": "complete_document"}
    )
    request = _write_json(tmp_path / "requests/pdf.json", request_value)

    code, envelope = _invoke(capsys, tmp_path, "data", "ingest", request)
    raw = _artifact(envelope, "source_raw")
    payload = json.loads((tmp_path / raw["path"]).read_text(encoding="utf-8"))

    assert code == 0 and envelope["status"] == "partial"
    assert base64.b64decode(payload["content_base64"]) == original
    assert payload["sha256"] == hashlib.sha256(original).hexdigest()


def test_missing_input_and_path_escape_persist_only_safe_failure_gaps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path.parent / "router-outside-note.md"
    outside.write_text("outside canary", encoding="utf-8")
    for request_id, ref in (("req-missing", "fixtures/missing.md"), ("req-escape", "../router-outside-note.md")):
        request = _write_json(
            tmp_path / f"requests/{request_id}.json",
            _ingest_request(ref, request_id=request_id),
        )
        code, envelope = _invoke(capsys, tmp_path, "data", "ingest", request)
        assert code == 2 and envelope["status"] == "error"
        assert not any(item["type"] == "source_raw" for item in envelope["artifacts"])  # type: ignore[union-attr]
        assert (tmp_path / _artifact(envelope, "data_gap")["path"]).is_file()
    assert outside.read_text(encoding="utf-8") == "outside canary"


def test_unsupported_ingest_and_request_secret_write_no_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unsupported = _write_json(
        tmp_path / "requests/unsupported.json",
        {"request_id": "req-unsupported", "source": "web_search", "operation": "text_ingest"},
    )
    code, envelope = _invoke(capsys, tmp_path, "data", "ingest", unsupported)
    assert code == 2 and envelope["error"]["reason"] == "unsupported"  # type: ignore[index]
    assert envelope["artifacts"] == []

    secret = "never-persist-this"
    unsafe = _write_json(
        tmp_path / "requests/secret.json",
        {"request_id": "req-secret", "source": "user_provided_material", "operation": "text_ingest", "nested": {"apiKey": secret}},
    )
    code, envelope = _invoke(capsys, tmp_path, "data", "ingest", unsafe)
    assert code == 2 and envelope["artifacts"] == []
    assert secret not in json.dumps(envelope)
    assert not (tmp_path / "data/records").exists()


def test_known_secret_reflection_is_rejected_before_any_record_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "loaded-known-secret"

    class UnsafeAdapter:
        def fetch(self, request: object, *, output_ref: str) -> dict[str, object]:
            return {
                "source_result": {
                    "source": "finnhub",
                    "operation": "quote",
                    "security_or_topic": _fetch_request()["subject"],
                    "observed_at": None,
                    "retrieved_at": NOW.isoformat(),
                    "available_at": None,
                    "coverage": "synthetic unsafe response",
                    "payload_ref": output_ref,
                    "quality": "complete",
                    "errors": [],
                    "unknown_reasons": {"observed_at": "unknown", "available_at": "unknown"},
                },
                "raw_payload": {"message": f"upstream reflected {secret}"},
                "normalized": {"raw_locator": ""},
                "evidence": [],
                "gaps": [],
            }

    monkeypatch.setitem(source_router._ADAPTER_FACTORIES, "finnhub", lambda settings: UnsafeAdapter())
    env_file = tmp_path / "credentials.env"
    env_file.write_text(f"FINNHUB_API_KEY={secret}\n", encoding="utf-8")
    request = _write_json(tmp_path / "requests/fetch.json", _fetch_request())
    code = main(
        ["--root", str(tmp_path), "--env-file", str(env_file), "data", "fetch", "--request", str(request)]
    )
    envelope = json.loads(capsys.readouterr().out)
    assert code == 3 and envelope["artifacts"] == []
    assert secret not in json.dumps(envelope)
    assert not (tmp_path / "data/records").exists()


@pytest.mark.parametrize("wrong_kind", ["payload", "evidence"])
def test_adapter_cannot_relabel_wrong_payload_or_evidence_reference(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    wrong_kind: str,
) -> None:
    class WrongReferenceAdapter:
        def fetch(self, request: dict[str, object], *, output_ref: str) -> dict[str, object]:
            payload_ref = "data/wrong/raw.json" if wrong_kind == "payload" else output_ref
            evidence_ref = "data/wrong/raw.json" if wrong_kind == "evidence" else output_ref
            return {
                "source_result": {
                    "source": "finnhub",
                    "operation": "quote",
                    "security_or_topic": request["subject"],
                    "observed_at": NOW.isoformat(),
                    "retrieved_at": NOW.isoformat(),
                    "available_at": NOW.isoformat(),
                    "coverage": "synthetic wrong reference",
                    "payload_ref": payload_ref,
                    "quality": "complete",
                    "errors": [],
                    "unknown_reasons": {},
                },
                "raw_payload": {"value": 1},
                "normalized": {"raw_locator": ""},
                "evidence": [
                    {
                        "evidence_id": "caller-evidence",
                        "source_ref": evidence_ref,
                        "locator": "/value",
                        "published_at": NOW.isoformat(),
                        "retrieved_at": NOW.isoformat(),
                        "available_at": NOW.isoformat(),
                        "content_kind": "third_party_view",
                        "claim": "Synthetic claim.",
                        "scope": "one value",
                        "units": [],
                        "limitations": ["synthetic"],
                        "unknown_reasons": {},
                    }
                ],
                "gaps": [],
            }

    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES, "finnhub", lambda settings: WrongReferenceAdapter()
    )
    request = _write_json(tmp_path / "requests/fetch.json", _fetch_request())
    code, envelope = _invoke(capsys, tmp_path, "data", "fetch", request)
    assert code == 3 and envelope["artifacts"] == []
    assert not (tmp_path / "data/records").exists()


def test_atomic_write_failure_returns_no_dangling_success_references(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    request = _write_json(tmp_path / "requests/ingest.json", _ingest_request(input_ref))
    real_write = source_router._write_new
    calls = 0

    def fail_after_first(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic write failure")
        real_write(path, data)

    monkeypatch.setattr(source_router, "_write_new", fail_after_first)
    code, envelope = _invoke(capsys, tmp_path, "data", "ingest", request)

    assert code == 3 and envelope["artifacts"] == []
    records = tmp_path / "data/records"
    assert not records.exists() or list(records.iterdir()) == []


def test_daily_bars_alias_is_canonicalized_before_programmatic_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    class AliasAdapter:
        def fetch(self, request: dict[str, object], *, output_ref: str) -> dict[str, object]:
            seen.update(request)
            return {
                "source_result": {
                    "source": "tiingo",
                    "operation": "bars",
                    "security_or_topic": request["subject"],
                    "observed_at": None,
                    "retrieved_at": NOW.isoformat(),
                    "available_at": None,
                    "coverage": "synthetic alias with unresolved gap",
                    "payload_ref": output_ref,
                    "quality": "complete",
                    "errors": [],
                    "unknown_reasons": {"observed_at": "date rows", "available_at": "unknown"},
                },
                "raw_payload": [],
                "normalized": {"raw_locator": "", "rows": []},
                "evidence": [],
                "gaps": [
                    {
                        "gap_id": "caller-controlled-id",
                        "request_id": request["request_id"],
                        "required_content": "daily rows",
                        "attempts": [{"source": "synthetic", "at": NOW.isoformat(), "result": "empty"}],
                        "impact": "no rows",
                        "next_action": "supply rows",
                    }
                ],
            }

    monkeypatch.setitem(source_router._ADAPTER_FACTORIES, "tiingo", lambda settings: AliasAdapter())
    settings = source_router.Settings(root=tmp_path, enabled_sources=("tiingo",))
    request = {
        "request_id": "req-alias",
        "source": "tiingo",
        "operation": "daily_bars",
        "subject": {"market": "US", "exchange": "XNAS", "symbol": "SYNB", "currency": "USD"},
        "as_of": NOW.isoformat(),
        "parameters": {},
        "required_fields": [],
    }
    result = source_router.data_fetch_handler(root=tmp_path, settings=settings, request=request)
    assert seen["operation"] == "bars"
    assert result.status == "partial"
    gap = next(item for item in result.artifacts if item.type == "data_gap")
    assert gap.artifact_id.startswith("gap_") and gap.artifact_id != "caller-controlled-id"
    assert (tmp_path / gap.path).is_file()


@pytest.mark.parametrize(
    "payload,enabled",
    [
        ({"request_id": "req-unknown", "source": "unknown", "operation": "quote"}, ("finnhub",)),
        ({"request_id": "req-order", "source": "finnhub", "operation": "place_order"}, ("finnhub",)),
        ({"request_id": "req-disabled", "source": "finnhub", "operation": "quote"}, ("tiingo",)),
    ],
)
def test_programmatic_fetch_handler_enforces_whitelist_and_enabled_sources(
    tmp_path: Path, payload: dict[str, object], enabled: tuple[str, ...]
) -> None:
    settings = source_router.Settings(root=tmp_path, enabled_sources=enabled)
    result = source_router.data_fetch_handler(root=tmp_path, settings=settings, request=payload)
    assert result.status == "error"
    assert result.error is not None and result.error.reason == "unsupported"
    assert result.artifacts == ()
    assert not (tmp_path / "data/records").exists()


def test_scalar_raw_json_root_is_persisted_for_future_read_only_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_value = "synthetic scalar raw response"

    class ScalarAdapter:
        def fetch(self, request: dict[str, object], *, output_ref: str) -> dict[str, object]:
            return {
                "source_result": {
                    "source": "finnhub",
                    "operation": "quote",
                    "security_or_topic": request["subject"],
                    "observed_at": None,
                    "retrieved_at": NOW.isoformat(),
                    "available_at": None,
                    "coverage": "one synthetic scalar payload",
                    "payload_ref": output_ref,
                    "quality": "complete",
                    "errors": [],
                    "unknown_reasons": {"observed_at": "unknown", "available_at": "unknown"},
                },
                "raw_payload": raw_value,
                "normalized": {"raw_locator": "", "value": raw_value},
                "evidence": [],
                "gaps": [],
            }

    monkeypatch.setitem(source_router._ADAPTER_FACTORIES, "finnhub", lambda settings: ScalarAdapter())
    settings = source_router.Settings(root=tmp_path, enabled_sources=("finnhub",))
    result = source_router.data_fetch_handler(
        root=tmp_path, settings=settings, request=_fetch_request()
    )
    raw = next(item for item in result.artifacts if item.type == "source_raw")
    assert result.status == "ok"
    assert json.loads((tmp_path / raw.path).read_text(encoding="utf-8")) == raw_value


def test_complete_result_with_errors_gets_generated_gap_and_partial_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ErrorWithoutGapAdapter:
        def fetch(self, request: dict[str, object], *, output_ref: str) -> dict[str, object]:
            return {
                "source_result": {
                    "source": "finnhub",
                    "operation": "quote",
                    "security_or_topic": request["subject"],
                    "observed_at": None,
                    "retrieved_at": NOW.isoformat(),
                    "available_at": None,
                    "coverage": "synthetic current value with stale limitation",
                    "payload_ref": output_ref,
                    "quality": "complete",
                    "errors": ["stale"],
                    "unknown_reasons": {"observed_at": "unknown", "available_at": "unknown"},
                },
                "raw_payload": {"value": 1},
                "normalized": {"raw_locator": "", "value": 1},
                "evidence": [],
                "gaps": [],
            }

    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES, "finnhub", lambda settings: ErrorWithoutGapAdapter()
    )
    settings = source_router.Settings(root=tmp_path, enabled_sources=("finnhub",))
    result = source_router.data_fetch_handler(
        root=tmp_path, settings=settings, request=_fetch_request()
    )
    assert result.status == "partial" and result.error is None
    assert len(result.gaps) == 1
    gap = next(item for item in result.artifacts if item.type == "data_gap")
    assert gap.path == result.gaps[0]
    assert resolve_reference(tmp_path, gap.artifact_id) == (tmp_path / gap.path).resolve()


@pytest.mark.parametrize(
    ("quality", "errors", "raw_payload", "expected_status", "expected_reason"),
    [
        ("limited", [], [], "partial", None),
        ("failed", ["empty"], None, "error", "empty"),
    ],
)
def test_legitimate_empty_news_is_distinct_from_failed_missing_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    quality: str,
    errors: list[str],
    raw_payload: object,
    expected_status: str,
    expected_reason: str | None,
) -> None:
    class EmptyAdapter:
        def fetch(self, request: dict[str, object], *, output_ref: str) -> dict[str, object]:
            return {
                "source_result": {
                    "source": "finnhub",
                    "operation": "news",
                    "security_or_topic": request["subject"],
                    "observed_at": None,
                    "retrieved_at": NOW.isoformat(),
                    "available_at": None,
                    "coverage": "valid empty news" if quality == "limited" else "required dataset missing",
                    "payload_ref": output_ref if raw_payload is not None else None,
                    "quality": quality,
                    "errors": errors,
                    "unknown_reasons": {"observed_at": "no rows", "available_at": "no rows"},
                },
                "raw_payload": raw_payload,
                "normalized": {
                    "raw_locator": "" if raw_payload is not None else None,
                    "empty_is_failure": quality == "failed",
                },
                "evidence": [],
                "gaps": [
                    {
                        "gap_id": "caller-gap",
                        "request_id": request["request_id"],
                        "required_content": "news rows",
                        "attempts": [{"source": "synthetic", "at": NOW.isoformat(), "result": "empty"}],
                        "impact": "no usable rows",
                        "next_action": "retain the distinction and follow up",
                    }
                ],
            }

    monkeypatch.setitem(source_router._ADAPTER_FACTORIES, "finnhub", lambda settings: EmptyAdapter())
    settings = source_router.Settings(root=tmp_path, enabled_sources=("finnhub",))
    request = _fetch_request() | {"operation": "news", "parameters": {"from": "2026-01-15", "to": "2026-01-15"}}
    result = source_router.data_fetch_handler(root=tmp_path, settings=settings, request=request)
    assert result.status == expected_status
    assert (result.error.reason if result.error is not None else None) == expected_reason
