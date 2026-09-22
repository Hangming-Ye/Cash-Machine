from __future__ import annotations

import json
import hashlib
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import pytest

import cash_research.calculations.publication as valuation_publication
import cash_research.sources.router as source_router
from cash_research.artifacts import resolve_reference
from cash_research.cli import main
from cash_research.models import Calculation, PortfolioSnapshot
from cash_research.sources.ibkr_flex import IbkrFlexReadOnlyAdapter
from cash_research.sources.longbridge_readonly import LongbridgeOAuthReadOnlyAdapter


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)
SEND_OK = """<?xml version="1.0"?><FlexStatementResponse><Status>Success</Status><ReferenceCode>REF-123</ReferenceCode></FlexStatementResponse>"""
IBKR_REPORT = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="synthetic-readonly" type="AF"><FlexStatements count="2">
<FlexStatement accountId="SYNTH-A" fromDate="20260917" toDate="20260918" whenGenerated="20260919;020000">
<AccountInformation accountId="SYNTH-A" currency="USD"/><CashReportCurrency accountId="SYNTH-A" currency="USD" endingCash="1250.25"/>
<OpenPositions><OpenPosition accountId="SYNTH-A" symbol="ACME" assetCategory="STK" currency="USD" position="10" positionValue="900" costBasisMoney="800" market="US" listingExchange="XNAS"/></OpenPositions></FlexStatement>
<FlexStatement accountId="SYNTH-B" fromDate="20260917" toDate="20260918" whenGenerated="20260919;020000">
<AccountInformation accountId="SYNTH-B" currency="EUR"/><CashReportCurrency accountId="SYNTH-B" currency="EUR" endingCash="500.50"/>
<OpenPositions><OpenPosition accountId="SYNTH-B" symbol="EUCO" assetCategory="STK" currency="EUR" position="5" positionValue="2000" costBasisMoney="1950" market="EU" listingExchange="XETR"/></OpenPositions></FlexStatement>
</FlexStatements></FlexQueryResponse>"""
IBKR_EMPTY = """<FlexQueryResponse type="AF"><FlexStatements count="2"><FlexStatement accountId="SYNTH-A" toDate="20260918" whenGenerated="20260919;020000"><AccountInformation accountId="SYNTH-A" currency="USD"/><CashReportCurrency accountId="SYNTH-A" currency="USD" endingCash="0"/><OpenPositions count="0"/></FlexStatement><FlexStatement accountId="SYNTH-B" toDate="20260918" whenGenerated="20260919;020000"><AccountInformation accountId="SYNTH-B" currency="EUR"/><CashReportCurrency accountId="SYNTH-B" currency="EUR" endingCash="0"/><OpenPositions count="0"/></FlexStatement></FlexStatements></FlexQueryResponse>"""
IBKR_MISSING_POSITIONS = """<FlexQueryResponse type="AF"><FlexStatements count="2"><FlexStatement accountId="SYNTH-A" toDate="20260918" whenGenerated="20260919;020000"><AccountInformation accountId="SYNTH-A" currency="USD"/><CashReportCurrency accountId="SYNTH-A" currency="USD" endingCash="1"/></FlexStatement><FlexStatement accountId="SYNTH-B" toDate="20260918" whenGenerated="20260919;020000"><AccountInformation accountId="SYNTH-B" currency="EUR"/><CashReportCurrency accountId="SYNTH-B" currency="EUR" endingCash="1"/></FlexStatement></FlexStatements></FlexQueryResponse>"""


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _invoke(args: list[str]) -> tuple[int, dict[str, object]]:
    from io import StringIO
    import contextlib

    output = StringIO()
    with contextlib.redirect_stdout(output):
        code = main(args)
    return code, json.loads(output.getvalue())


def _env(path: Path, values: dict[str, str]) -> Path:
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    return path


def _ibkr_request(request_id: str = "ibkr-positions") -> dict[str, object]:
    return {
        "request_id": request_id,
        "source": "ibkr_flex",
        "operation": "positions",
        "subject": "authorized-portfolio",
        "as_of": NOW.isoformat(),
        "parameters": {},
        "required_fields": [
            "account_ref",
            "symbol",
            "market",
            "exchange",
            "currency",
            "quantity",
            "market_value",
            "cost_basis",
        ],
    }


def _ibkr_factory(handler):
    def factory(settings):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        adapter = IbkrFlexReadOnlyAdapter(
            settings,
            client=client,
            sleeper=lambda _seconds: None,
            clock=lambda: NOW,
            monotonic=lambda: 100.0,
        )
        adapter.close = client.close  # type: ignore[attr-defined]
        return adapter

    return factory


class FakeTrade:
    def __init__(self, *, empty: bool = False, fail_funds: bool = False) -> None:
        self.fail_funds = fail_funds
        self.balance = [
            NS(
                currency="HKD",
                total_cash="40000",
                net_assets="100000",
                cash_infos=[NS(currency="HKD", available_cash="25000", frozen_cash="1000", settling_cash="14000")],
            )
        ]
        positions = [] if empty else [
            NS(symbol="700.HK", quantity="100", available_quantity="80", currency="HKD", cost_price="307.5")
        ]
        self.stocks = NS(channels=[NS(account_channel="lb-channel", positions=positions)])

    def account_balance(self):
        return self.balance

    def stock_positions(self):
        return self.stocks

    def fund_positions(self):
        if self.fail_funds:
            raise RuntimeError("synthetic fund read failure")
        return NS(channels=[])

    def today_executions(self):
        return []

    def history_executions(self, **_kwargs):
        return NS(has_more=False, trades=[])


def _longbridge_request(*, include_funds: bool = False, request_id: str = "lb-positions") -> dict[str, object]:
    return {
        "request_id": request_id,
        "source": "longbridge_oauth",
        "operation": "positions",
        "subject": "authorized-portfolio",
        "as_of": NOW.isoformat(),
        "parameters": {"include_funds": include_funds},
        "required_fields": ["account_ref", "symbol", "quantity", "currency"],
    }


def test_builtin_ibkr_and_longbridge_publish_typed_readonly_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = iter([SEND_OK, IBKR_REPORT])
    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES,
        "ibkr_flex",
        _ibkr_factory(lambda _request: httpx.Response(200, text=next(responses))),
    )
    ibkr_env = _env(
        tmp_path / "ibkr.env",
        {
            "IBKR_FLEX_TOKEN": "s3",
            "IBKR_FLEX_QUERY_ID": "synthetic-query",
            "IBKR_FLEX_EXPECTED_ACCOUNT_REFS": "SYNTH-A,SYNTH-B",
            "IBKR_FLEX_QUERY_TIMEZONE": "UTC",
        },
    )
    request_path = _write_json(tmp_path / "ibkr.json", _ibkr_request())
    code, envelope = _invoke(
        ["--root", str(tmp_path), "--env-file", str(ibkr_env), "data", "fetch", "--request", str(request_path)]
    )
    assert code == 0
    snapshots = [item for item in envelope["artifacts"] if item["type"] == "portfolio_snapshot"]
    assert len(snapshots) == 1
    snapshot_path = resolve_reference(tmp_path, snapshots[0]["artifact_id"])
    assert snapshot_path == (tmp_path / snapshots[0]["path"]).resolve()
    ibkr_snapshot = PortfolioSnapshot.model_validate(json.loads(snapshot_path.read_text(encoding="utf-8")))
    assert ibkr_snapshot.broker == "ibkr_flex"
    assert {position.account_ref for position in ibkr_snapshot.positions} == {"SYNTH-A", "SYNTH-B"}
    assert "s3" not in json.dumps(envelope)

    trade = FakeTrade()
    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES,
        "longbridge_oauth",
        lambda settings: LongbridgeOAuthReadOnlyAdapter(settings, trade=trade, clock=lambda: NOW),
    )
    lb_env = _env(
        tmp_path / "lb.env",
        {"LONGBRIDGE_CLIENT_ID": "client-context", "LONGBRIDGE_ACCOUNT_REF": "SYNTH-LB-A"},
    )
    request_path = _write_json(tmp_path / "lb.json", _longbridge_request())
    code, envelope = _invoke(
        ["--root", str(tmp_path), "--env-file", str(lb_env), "data", "fetch", "--request", str(request_path)]
    )
    assert code == 0
    artifact = next(item for item in envelope["artifacts"] if item["type"] == "portfolio_snapshot")
    lb_snapshot = PortfolioSnapshot.model_validate(
        json.loads(resolve_reference(tmp_path, artifact["artifact_id"]).read_text(encoding="utf-8"))
    )
    assert lb_snapshot.accounts[0].account_ref == "SYNTH-LB-A"
    assert lb_snapshot.positions[0].account_ref == "SYNTH-LB-A"


def test_broker_partial_failure_and_confirmed_empty_never_conflate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(
        tmp_path / "lb.env",
        {"LONGBRIDGE_CLIENT_ID": "client-context", "LONGBRIDGE_ACCOUNT_REF": "SYNTH-LB-A"},
    )
    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES,
        "longbridge_oauth",
        lambda settings: LongbridgeOAuthReadOnlyAdapter(
            settings, trade=FakeTrade(fail_funds=True), clock=lambda: NOW
        ),
    )
    request_path = _write_json(
        tmp_path / "partial.json",
        _longbridge_request(include_funds=True, request_id="lb-partial"),
    )
    code, partial = _invoke(
        ["--root", str(tmp_path), "--env-file", str(env), "data", "fetch", "--request", str(request_path)]
    )
    assert code == 0 and partial["status"] == "partial"
    partial_artifact = next(
        item for item in partial["artifacts"] if item["type"] == "portfolio_snapshot"
    )
    partial_snapshot = PortfolioSnapshot.model_validate(
        json.loads((tmp_path / partial_artifact["path"]).read_text(encoding="utf-8"))
    )
    assert partial_snapshot.complete_read is False
    assert partial_snapshot.confirmed_empty is False

    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES,
        "longbridge_oauth",
        lambda settings: LongbridgeOAuthReadOnlyAdapter(
            settings, trade=FakeTrade(empty=True), clock=lambda: NOW
        ),
    )
    request_path = _write_json(
        tmp_path / "empty.json", _longbridge_request(request_id="lb-empty")
    )
    code, empty = _invoke(
        ["--root", str(tmp_path), "--env-file", str(env), "data", "fetch", "--request", str(request_path)]
    )
    assert code == 0 and empty["status"] == "ok"
    artifact = next(item for item in empty["artifacts"] if item["type"] == "portfolio_snapshot")
    snapshot = PortfolioSnapshot.model_validate(
        json.loads((tmp_path / artifact["path"]).read_text(encoding="utf-8"))
    )
    assert snapshot.complete_read and snapshot.confirmed_empty and snapshot.positions == ()

    missing_account_env = _env(tmp_path / "missing-account.env", {"LONGBRIDGE_CLIENT_ID": "client-context"})
    request_path = _write_json(
        tmp_path / "failed.json", _longbridge_request(request_id="lb-failed")
    )
    code, failed = _invoke(
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(missing_account_env),
            "data",
            "fetch",
            "--request",
            str(request_path),
        ]
    )
    assert code == 3 and failed["status"] == "error"
    assert not any(item["type"] == "portfolio_snapshot" for item in failed["artifacts"])


def test_ibkr_partial_failure_and_confirmed_empty_never_conflate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(
        tmp_path / "ibkr.env",
        {
            "IBKR_FLEX_TOKEN": "s3",
            "IBKR_FLEX_QUERY_ID": "synthetic-query",
            "IBKR_FLEX_EXPECTED_ACCOUNT_REFS": "SYNTH-A,SYNTH-B",
            "IBKR_FLEX_QUERY_TIMEZONE": "UTC",
        },
    )

    responses = iter([SEND_OK, IBKR_MISSING_POSITIONS])
    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES,
        "ibkr_flex",
        _ibkr_factory(lambda _request: httpx.Response(200, text=next(responses))),
    )
    request_path = _write_json(tmp_path / "ibkr-partial.json", _ibkr_request("ibkr-partial"))
    code, partial = _invoke(
        ["--root", str(tmp_path), "--env-file", str(env), "data", "fetch", "--request", str(request_path)]
    )
    assert code == 0 and partial["status"] == "partial"
    assert not any(item["type"] == "portfolio_snapshot" for item in partial["artifacts"])

    responses = iter([SEND_OK, IBKR_EMPTY])
    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES,
        "ibkr_flex",
        _ibkr_factory(lambda _request: httpx.Response(200, text=next(responses))),
    )
    request_path = _write_json(tmp_path / "ibkr-empty.json", _ibkr_request("ibkr-empty"))
    code, empty = _invoke(
        ["--root", str(tmp_path), "--env-file", str(env), "data", "fetch", "--request", str(request_path)]
    )
    assert code == 0 and empty["status"] == "ok"
    artifact = next(item for item in empty["artifacts"] if item["type"] == "portfolio_snapshot")
    snapshot = PortfolioSnapshot.model_validate(
        json.loads(resolve_reference(tmp_path, artifact["artifact_id"]).read_text(encoding="utf-8"))
    )
    assert snapshot.complete_read and snapshot.confirmed_empty and snapshot.positions == ()

    missing_token = _env(
        tmp_path / "ibkr-missing.env",
        {
            "IBKR_FLEX_QUERY_ID": "synthetic-query",
            "IBKR_FLEX_EXPECTED_ACCOUNT_REFS": "SYNTH-A,SYNTH-B",
        },
    )
    request_path = _write_json(tmp_path / "ibkr-failed.json", _ibkr_request("ibkr-failed"))
    code, failed = _invoke(
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(missing_token),
            "data",
            "fetch",
            "--request",
            str(request_path),
        ]
    )
    assert code == 2 and failed["status"] == "error"
    assert not any(item["type"] == "portfolio_snapshot" for item in failed["artifacts"])


def test_router_rejects_failed_source_that_claims_a_portfolio_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class InconsistentBrokerAdapter:
        def fetch(self, request, *, output_ref):
            del output_ref
            return {
                "source_result": {
                    "source": "longbridge_oauth",
                    "operation": "positions",
                    "security_or_topic": "authorized-portfolio",
                    "observed_at": None,
                    "retrieved_at": NOW.isoformat(),
                    "available_at": None,
                    "coverage": "synthetic inconsistent failed adapter",
                    "payload_ref": None,
                    "quality": "failed",
                    "errors": ["external"],
                    "unknown_reasons": {
                        "observed_at": "failed adapter",
                        "available_at": "failed adapter",
                    },
                },
                "raw_payload": None,
                "normalized": {"raw_locator": None},
                "evidence": [],
                "gaps": [],
                "portfolio_snapshot": {
                    "snapshot_id": "adapter-supplied-invalid-snapshot",
                    "broker": "longbridge_oauth",
                    "reported_at": None,
                    "retrieved_at": NOW.isoformat(),
                    "accounts": [
                        {
                            "account_ref": "SYNTH-LB-A",
                            "base_currency": "HKD",
                            "balances": [],
                        }
                    ],
                    "positions": [],
                    "coverage": "must not survive a failed source",
                    "complete_read": True,
                    "confirmed_empty": True,
                    "unknown_reasons": {"reported_at": "provider omitted time"},
                },
            }

    monkeypatch.setitem(
        source_router._ADAPTER_FACTORIES,
        "longbridge_oauth",
        lambda _settings: InconsistentBrokerAdapter(),
    )
    request_path = _write_json(
        tmp_path / "inconsistent.json",
        _longbridge_request(request_id="inconsistent-failed-snapshot"),
    )
    code, envelope = _invoke(
        ["--root", str(tmp_path), "data", "fetch", "--request", str(request_path)]
    )
    assert code == 3
    assert envelope["error"] == {
        "reason": "external",
        "message": "operation failed in its external runtime",
    }
    assert not (tmp_path / "data/records").exists()


def _valuation_request(root: Path) -> dict[str, object]:
    shutil.copytree(ROOT / "fixtures/valuation", root / "fixtures/valuation")
    request = json.loads((ROOT / "fixtures/requests/valuation.json").read_text(encoding="utf-8"))
    _write_json(root / "evidence.json", {"evidence_id": "synthetic-input", "available_at": NOW.isoformat()})
    request["evidence_refs"] = ["evidence.json"]
    return request


def test_builtin_valuation_publishes_frozen_reproducible_calculation(
    tmp_path: Path,
) -> None:
    request = _valuation_request(tmp_path)
    request_path = _write_json(tmp_path / "valuation.json", request)
    code, envelope = _invoke(
        ["--root", str(tmp_path), "compute", "valuation", "--request", str(request_path)]
    )
    assert code == 0 and envelope["status"] == "ok"
    calculation_artifact = next(item for item in envelope["artifacts"] if item["type"] == "valuation")
    calculation_path = resolve_reference(tmp_path, calculation_artifact["artifact_id"])
    calculation = Calculation.model_validate(json.loads(calculation_path.read_text(encoding="utf-8")))
    result = json.loads((tmp_path / calculation.result_ref).read_text(encoding="utf-8"))
    expected = json.loads((ROOT / "fixtures/valuation/expected.json").read_text(encoding="utf-8"))
    for name, values in expected["cases"]["dcf_fcff"]["expected"]["scenario_results"].items():
        actual = result["scenario_results"][name]
        assert abs(Decimal(actual["per_share_value"]) - Decimal(values["per_share_value"])) < Decimal("1e-12")
    assert all(ref.startswith("data/records/") for ref in calculation.input_refs)
    frozen_inputs = [tmp_path / ref for ref in calculation.input_refs]
    assert all(path.is_file() for path in frozen_inputs)
    before = [path.read_bytes() for path in frozen_inputs]
    (tmp_path / "fixtures/valuation/financial-inputs.json").write_text("{}", encoding="utf-8")
    assert [path.read_bytes() for path in frozen_inputs] == before
    assert calculation.parameters == request
    assert not ({"decision", "label", "recommendation"} & set(result))


def test_valuation_invalid_input_is_exit_two_and_publish_failure_is_sanitized_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _valuation_request(tmp_path)
    request["scenarios"]["base"]["terminal_growth"] = request["scenarios"]["base"]["wacc"]
    invalid_path = _write_json(tmp_path / "invalid.json", request)
    code, invalid = _invoke(
        ["--root", str(tmp_path), "compute", "valuation", "--request", str(invalid_path)]
    )
    assert code == 2 and invalid["error"]["reason"] == "invalid"

    request = _valuation_request(tmp_path / "runtime")
    runtime_root = tmp_path / "runtime"
    runtime_path = _write_json(runtime_root / "request.json", request)
    monkeypatch.setattr(
        valuation_publication.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("private filesystem detail")),
    )
    code, failed = _invoke(
        ["--root", str(runtime_root), "compute", "valuation", "--request", str(runtime_path)]
    )
    assert code == 3
    assert failed["error"] == {
        "reason": "external",
        "message": "operation failed in its external runtime",
    }
    assert "private filesystem detail" not in json.dumps(failed)
    records = runtime_root / "data/records"
    assert records.is_dir()
    assert list(records.iterdir()) == []


def test_short_configured_secret_in_valuation_input_is_exit_two_without_leak(
    tmp_path: Path,
) -> None:
    request = _valuation_request(tmp_path)
    _write_json(tmp_path / "evidence.json", {"note": "contains s3"})
    request_path = _write_json(tmp_path / "request.json", request)
    env_path = _env(tmp_path / "secret.env", {"FINNHUB_API_KEY": "s3"})
    code, envelope = _invoke(
        [
            "--root",
            str(tmp_path),
            "--env-file",
            str(env_path),
            "compute",
            "valuation",
            "--request",
            str(request_path),
        ]
    )
    assert code == 2 and envelope["error"]["reason"] == "invalid"
    assert "s3" not in json.dumps(envelope)


def test_damaged_canonical_input_is_rejected_not_refrozen_as_legitimate(
    tmp_path: Path,
) -> None:
    request = _valuation_request(tmp_path)
    existing_id = "rec_" + "d" * 32
    evidence_ref = f"data/records/{existing_id}/evidence.json"
    evidence_path = _write_json(tmp_path / evidence_ref, {"claim": "tampered canonical input"})
    _write_json(
        evidence_path.parent / "manifest.json",
        {
            "record_id": existing_id,
            "created_at": NOW.isoformat(),
            "files": {"evidence.json": {"sha256": "0" * 64, "size": evidence_path.stat().st_size}},
        },
    )
    request["evidence_refs"] = [evidence_ref]
    request_path = _write_json(tmp_path / "damaged-input.json", request)
    code, envelope = _invoke(
        ["--root", str(tmp_path), "compute", "valuation", "--request", str(request_path)]
    )
    assert code == 2 and envelope["error"]["reason"] == "invalid"
    assert sorted(path.name for path in (tmp_path / "data/records").iterdir()) == [existing_id]


def test_valid_manifest_hashed_input_keeps_verified_immutable_pointer(
    tmp_path: Path,
) -> None:
    request = _valuation_request(tmp_path)
    source_id = "rec_" + "e" * 32
    evidence_ref = f"data/records/{source_id}/evidence.json"
    evidence_path = _write_json(
        tmp_path / evidence_ref,
        {"claim": "manifest-hashed synthetic evidence", "available_at": NOW.isoformat()},
    )
    evidence_bytes = evidence_path.read_bytes()
    _write_json(
        evidence_path.parent / "manifest.json",
        {
            "record_id": source_id,
            "created_at": NOW.isoformat(),
            "files": {
                "evidence.json": {
                    "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                    "size": len(evidence_bytes),
                }
            },
        },
    )
    request["evidence_refs"] = [evidence_ref]
    request_path = _write_json(tmp_path / "manifest-input.json", request)
    code, envelope = _invoke(
        ["--root", str(tmp_path), "compute", "valuation", "--request", str(request_path)]
    )
    assert code == 0
    calculation_artifact = next(
        item for item in envelope["artifacts"] if item["type"] == "valuation"
    )
    calculation_path = resolve_reference(tmp_path, calculation_artifact["artifact_id"])
    calculation = Calculation.model_validate(
        json.loads(calculation_path.read_text(encoding="utf-8"))
    )
    assert evidence_ref in calculation.input_refs
    manifest = json.loads((calculation_path.parent / "manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["input_provenance"] if item["ref"] == evidence_ref)
    assert entry["frozen_ref"] == evidence_ref
    assert entry["source_manifest_ref"] == f"data/records/{source_id}/manifest.json"


def test_decision_archive_memory_update_and_recall_contains_supported_topic(
    tmp_path: Path,
) -> None:
    request = _valuation_request(tmp_path)
    valuation_path = _write_json(tmp_path / "valuation.json", request)
    code, valuation = _invoke(
        ["--root", str(tmp_path), "compute", "valuation", "--request", str(valuation_path)]
    )
    assert code == 0
    calculation_id = next(item["artifact_id"] for item in valuation["artifacts"] if item["type"] == "valuation")

    recall_request = {
        "request_id": "initial-memory",
        "query": "synthetic portfolio thesis",
        "context_mode": "current",
        "as_of": NOW.isoformat(),
        "topic_ids": [],
        "lesson_ids": [],
        "budget": {"max_items": 5, "max_chars": 8000},
    }
    recall_path = _write_json(tmp_path / "recall.json", recall_request)
    code, recall = _invoke(
        ["--root", str(tmp_path), "memory", "recall", "--request", str(recall_path)]
    )
    assert code == 0
    packet_id = next(item["artifact_id"] for item in recall["artifacts"] if item["type"] == "memory_packet")

    decision = {
        "decision_id": "draft",
        "security_or_topic": {"market": "US", "exchange": "XNAS", "symbol": "SYNV", "currency": "USD"},
        "as_of": NOW.isoformat(),
        "label": "watch",
        "reason_refs": [calculation_id],
        "price_or_conditions": None,
        "price_or_conditions_reason": "synthetic workflow remains evidence-limited",
        "evidence_limited": True,
        "limitations": ["synthetic inputs only"],
        "horizon": "12 months",
        "risks": ["synthetic demand risk"],
        "invalidators": ["synthetic evidence changes"],
        "previous_id": None,
        "memory_packet_refs": [packet_id],
    }
    _write_json(tmp_path / "decision.json", decision)
    (tmp_path / "report.md").write_text("# Synthetic watch decision\n", encoding="utf-8")
    _write_json(tmp_path / "attachment.json", {"calculation_id": calculation_id})
    archive_request = _write_json(
        tmp_path / "archive.json",
        {
            "request_id": "archive-decision",
            "draft_ref": "decision.json",
            "record_type": "Decision",
            "report_ref": "report.md",
            "attachment_refs": ["attachment.json"],
        },
    )
    before = {path.parent for path in (tmp_path / "data/records").glob("*/record.json")}
    check_code, _ = _invoke(
        ["--root", str(tmp_path), "check", "artifact", "--request", str(archive_request)]
    )
    assert check_code == 0
    assert {path.parent for path in (tmp_path / "data/records").glob("*/record.json")} == before
    archive_code, archived = _invoke(
        [
            "--root",
            str(tmp_path),
            "check",
            "artifact",
            "--request",
            str(archive_request),
            "--archive",
        ]
    )
    assert archive_code == 0
    decision_id = next(item["artifact_id"] for item in archived["artifacts"] if item["type"] == "decision")

    proposal = _write_json(
        tmp_path / "topic.json",
        {
            "request_id": "apply-topic",
            "memory_type": "topic",
            "expected_version": 0,
            "topic_id": "synthetic-portfolio-thesis",
            "current_thesis": "The archived synthetic Decision remains evidence-limited.",
            "support_refs": [decision_id],
            "opposing_refs": [],
            "changes": ["Created from the archived Decision."],
            "open_questions": ["Will real evidence support a price condition?"],
            "next_checks": ["Replace synthetic inputs with authorized evidence."],
            "topics": ["portfolio thesis"],
            "methods": ["portfolio research"],
            "securities": ["US:XNAS:SYNV"],
            "aliases": ["synthetic portfolio"],
        },
    )
    code, _ = _invoke(
        ["--root", str(tmp_path), "memory", "apply", "--proposal", str(proposal)]
    )
    assert code == 0
    final_recall = _write_json(
        tmp_path / "final-recall.json",
        {
            "request_id": "final-memory",
            "query": "portfolio thesis",
            "context_mode": "current",
            "as_of": "runtime",
            "topic_ids": ["synthetic-portfolio-thesis"],
            "lesson_ids": [],
            "budget": {"max_items": 5, "max_chars": 12000},
        },
    )
    code, recalled = _invoke(
        ["--root", str(tmp_path), "memory", "recall", "--request", str(final_recall)]
    )
    assert code == 0
    content_ref = next(item["path"] for item in recalled["artifacts"] if item["type"] == "memory_content")
    content = json.loads((tmp_path / content_ref).read_text(encoding="utf-8"))
    rendered = json.dumps(content, ensure_ascii=False)
    assert "The archived synthetic Decision remains evidence-limited." in rendered
    assert decision_id in rendered
