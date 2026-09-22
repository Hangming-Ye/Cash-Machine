from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cash_research.artifacts import reject_secrets
from cash_research.config import RequestBoundaryError, validate_read_request
from cash_research.models import (
    AccountState,
    DataGap,
    Evidence,
    PortfolioSnapshot,
    SourceResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = PROJECT_ROOT / "fixtures" / "brokers" / "expected.json"
REQUEST_KEYS = {
    "request_id",
    "source",
    "operation",
    "subject",
    "as_of",
    "parameters",
    "required_fields",
}
COMMON_RESULT_KEYS = {
    "source_result",
    "raw_payload",
    "normalized",
    "evidence",
    "gaps",
}
BROKER_RESULT_KEYS = {"portfolio_snapshot"}


@pytest.fixture(scope="module")
def broker_fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _cases(broker_fixture: dict[str, object]) -> dict[str, dict[str, object]]:
    cases = broker_fixture["cases"]
    assert isinstance(cases, dict)
    return cases  # type: ignore[return-value]


def _result(case: dict[str, object]) -> dict[str, object]:
    result = case["result"]
    assert isinstance(result, dict)
    return result


def _resolve_pointer(document: object, pointer: str) -> object:
    current = document
    for encoded in pointer.lstrip("/").split("/"):
        part = encoded.replace("~1", "/").replace("~0", "~")
        assert isinstance(current, dict)
        current = current[part]
    return current


def test_contract_matches_common_source_boundary_without_cli_or_platform_dto(
    broker_fixture: dict[str, object],
) -> None:
    contract = broker_fixture["adapter_contract"]
    assert isinstance(contract, dict)
    assert contract["callable"] == "fetch(request, *, output_ref)"
    assert set(contract["required_request_keys"]) == REQUEST_KEYS
    assert set(contract["required_result_keys"]) == COMMON_RESULT_KEYS
    assert set(contract["broker_result_extensions"]) == BROKER_RESULT_KEYS
    assert contract["router_boundary"] == "CallResult wrapping is deferred to T033"
    assert "Settings" in contract["credential_injection"]

    for case in _cases(broker_fixture).values():
        assert REQUEST_KEYS <= set(case["request"])  # type: ignore[arg-type]
        assert COMMON_RESULT_KEYS <= set(_result(case))
        assert BROKER_RESULT_KEYS <= set(_result(case))
        output_ref = case["output_ref"]
        assert isinstance(output_ref, str)
        assert output_ref.startswith("data/records/")
        assert "fixtures/" not in output_ref
        assert "output_ref" not in case["request"]["parameters"]  # type: ignore[index]


def test_all_requests_stay_inside_two_brokers_and_three_read_operations(
    broker_fixture: dict[str, object],
) -> None:
    sources: set[str] = set()
    operations: set[str] = set()
    for case in _cases(broker_fixture).values():
        request = case["request"]
        assert isinstance(request, dict)
        validate_read_request(request)
        sources.add(str(request["source"]))
        operations.add(str(request["operation"]))

    assert sources == {"ibkr_flex", "longbridge_oauth"}
    assert operations == {"accounts", "positions", "executions"}


@pytest.mark.parametrize(
    "operation", ["submit_order", "replace_order", "cancel_order", "watchlist"]
)
@pytest.mark.parametrize("source", ["ibkr_flex", "longbridge_oauth"])
def test_orders_and_unverified_watchlist_are_outside_the_read_boundary(
    source: str, operation: str
) -> None:
    with pytest.raises(RequestBoundaryError):
        validate_read_request({"source": source, "operation": operation})


def test_every_source_result_and_gap_uses_shared_models(
    broker_fixture: dict[str, object],
) -> None:
    for case in _cases(broker_fixture).values():
        result = _result(case)
        source_result = SourceResult.model_validate(result["source_result"])
        gaps = tuple(DataGap.model_validate(item) for item in result["gaps"])  # type: ignore[union-attr]
        evidence = tuple(Evidence.model_validate(item) for item in result["evidence"])  # type: ignore[union-attr]
        assert evidence == ()
        if source_result.quality == "failed":
            assert source_result.payload_ref is None
            assert result["raw_payload"] is None
            assert result["portfolio_snapshot"] is None
            assert gaps
        else:
            assert source_result.payload_ref == case["output_ref"]
            normalized = result["normalized"]
            assert isinstance(normalized, dict)
            locator = normalized["raw_locator"]
            assert isinstance(locator, str)
            assert _resolve_pointer(broker_fixture, locator) == result["raw_payload"]
        for gap in gaps:
            assert gap.request_id == case["request"]["request_id"]  # type: ignore[index]


def test_raw_and_normalized_fixture_contains_no_credentials(
    broker_fixture: dict[str, object]
) -> None:
    reject_secrets(broker_fixture)
    serialized = json.dumps(broker_fixture)
    assert "LB-PENDING" not in serialized
    assert '"IBKR-FLEX"' not in serialized
    assert "sec-analysis.env" not in serialized


def test_portfolio_snapshots_validate_only_when_required_identity_exists(
    broker_fixture: dict[str, object],
) -> None:
    snapshots: list[PortfolioSnapshot] = []
    for case in _cases(broker_fixture).values():
        snapshot = _result(case)["portfolio_snapshot"]
        if snapshot is not None:
            snapshots.append(PortfolioSnapshot.model_validate(snapshot))

    assert {snapshot.broker for snapshot in snapshots} == {
        "ibkr_flex",
        "longbridge_oauth",
    }
    assert len(snapshots) == 3

    unknown = _result(_cases(broker_fixture)["unknown_identity_time_currency"])
    normalized = unknown["normalized"]
    assert isinstance(normalized, dict)
    assert normalized["account_ref"] is None
    assert normalized["reported_at"] is None
    assert normalized["currency"] is None
    assert set(normalized["unknown_reasons"]) == {  # type: ignore[arg-type]
        "account_ref",
        "reported_at",
        "currency",
    }
    assert unknown["portfolio_snapshot"] is None


def test_ibkr_fixture_preserves_two_accounts_currencies_and_t_plus_one(
    broker_fixture: dict[str, object],
) -> None:
    result = _result(_cases(broker_fixture)["ibkr_multi_account_positions"])
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    normalized = result["normalized"]
    assert isinstance(normalized, dict)

    assert normalized["query_kind"] == "activity_flex"
    assert normalized["freshness"] == "T+1"
    assert normalized["t_plus_one"] is True
    assert normalized["report_to_date"] == "20260918"
    assert normalized["date_coverage_only"] is True
    assert snapshot.reported_at is None
    assert len(snapshot.accounts) == 2
    assert {account.account_ref for account in snapshot.accounts} == {
        "SYNTH-IBKR-A",
        "SYNTH-IBKR-B",
    }
    assert {account.base_currency for account in snapshot.accounts} == {"USD", "EUR"}
    assert snapshot.complete_read is True


def test_longbridge_accounts_preserve_every_currency_without_claiming_empty_positions(
    broker_fixture: dict[str, object],
) -> None:
    result = _result(_cases(broker_fixture)["longbridge_multi_currency_accounts"])
    normalized = result["normalized"]
    assert isinstance(normalized, dict)
    accounts = tuple(AccountState.model_validate(item) for item in normalized["accounts"])

    assert normalized["auth"] == "oauth_existing_store"
    assert normalized["authorization_started_by_read"] is False
    assert normalized["currency_rows"] == ["HKD", "USD"]
    assert {balance.currency for balance in accounts[0].balances} == {"HKD", "USD"}
    assert result["portfolio_snapshot"] is None


def test_partial_subread_is_limited_and_does_not_hide_the_failed_part(
    broker_fixture: dict[str, object],
) -> None:
    result = _result(_cases(broker_fixture)["longbridge_partial_positions"])
    source_result = SourceResult.model_validate(result["source_result"])
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    normalized = result["normalized"]
    assert isinstance(normalized, dict)

    assert source_result.quality == "limited"
    assert source_result.errors == ("fund_positions: external",)
    assert normalized["successful_subreads"] == ["stock_positions"]
    assert normalized["failed_subreads"] == ["fund_positions"]
    assert snapshot.complete_read is False
    assert snapshot.confirmed_empty is False
    assert len(snapshot.positions) == 1
    assert len(result["gaps"]) == 1  # type: ignore[arg-type]
    assert snapshot.positions[0].account_ref == snapshot.accounts[0].account_ref


def test_only_a_complete_read_can_confirm_an_empty_portfolio(
    broker_fixture: dict[str, object],
) -> None:
    result = _result(_cases(broker_fixture)["ibkr_confirmed_empty_positions"])
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    assert snapshot.complete_read is True
    assert snapshot.confirmed_empty is True
    assert snapshot.positions == ()

    invalid = snapshot.model_dump()
    invalid["complete_read"] = False
    with pytest.raises(ValidationError, match="empty positions"):
        PortfolioSnapshot.model_validate(invalid)


def test_failed_broker_read_is_not_an_empty_snapshot(
    broker_fixture: dict[str, object],
) -> None:
    result = _result(_cases(broker_fixture)["longbridge_read_failure"])
    source_result = SourceResult.model_validate(result["source_result"])

    assert source_result.quality == "failed"
    assert source_result.errors == ("unauthorized: existing OAuth login unavailable",)
    assert result["portfolio_snapshot"] is None
    assert result["normalized"] == {
        "raw_locator": None,
        "complete_read": False,
        "confirmed_empty": False,
    }


def test_longbridge_execution_contract_separates_today_and_history_coverage(
    broker_fixture: dict[str, object],
) -> None:
    result = _result(_cases(broker_fixture)["longbridge_today_history_executions"])
    source_result = SourceResult.model_validate(result["source_result"])
    raw = result["raw_payload"]
    normalized = result["normalized"]
    assert isinstance(raw, dict)
    assert isinstance(normalized, dict)

    assert source_result.quality == "complete"
    assert len(raw["today"]) == 1
    assert len(raw["history"]) == 1
    assert normalized["history_excludes_today"] is True
    assert normalized["history_pages_complete"] is True
    assert normalized["dedupe_key"] == "trade_id"
    trade_ids = [row["trade_id"] for row in normalized["executions"]]  # type: ignore[index]
    assert len(trade_ids) == len(set(trade_ids)) == 2


def test_supporting_raw_fixtures_are_synthetic_and_nonempty() -> None:
    ibkr = (PROJECT_ROOT / "fixtures" / "brokers" / "ibkr-flex-multi-account.xml")
    longbridge = PROJECT_ROOT / "fixtures" / "brokers" / "longbridge-readonly.json"

    assert "SYNTH-IBKR-A" in ibkr.read_text(encoding="utf-8")
    raw_longbridge = json.loads(longbridge.read_text(encoding="utf-8"))
    assert raw_longbridge["synthetic"] is True
    assert raw_longbridge["today_executions"]
    assert raw_longbridge["history_executions"]


@pytest.mark.parametrize(
    ("case_id", "fixture_name"),
    [
        ("ibkr_multi_account_positions", "ibkr-flex-multi-account.xml"),
        ("ibkr_confirmed_empty_positions", "ibkr-flex-empty.xml"),
        ("unknown_identity_time_currency", "ibkr-flex-missing-fields.xml"),
    ],
)
def test_ibkr_raw_payload_is_the_exact_synthetic_xml_body(
    case_id: str,
    fixture_name: str,
    broker_fixture: dict[str, object],
) -> None:
    raw_payload = _result(_cases(broker_fixture)[case_id])["raw_payload"]
    source_body = (PROJECT_ROOT / "fixtures" / "brokers" / fixture_name).read_text(
        encoding="utf-8"
    )

    assert raw_payload == source_body


@pytest.mark.parametrize(
    "case_id", ["ibkr_multi_account_positions", "ibkr_confirmed_empty_positions"]
)
def test_ibkr_date_precision_is_not_promoted_to_invented_utc_instants(
    case_id: str, broker_fixture: dict[str, object]
) -> None:
    result = _result(_cases(broker_fixture)[case_id])
    source_result = SourceResult.model_validate(result["source_result"])
    snapshot = PortfolioSnapshot.model_validate(result["portfolio_snapshot"])
    normalized = result["normalized"]
    assert isinstance(normalized, dict)

    assert source_result.observed_at is None
    assert source_result.available_at is None
    assert snapshot.reported_at is None
    assert normalized["report_to_date"] == "20260918"
    assert normalized["when_generated"] == "20260919;020000"
    assert normalized["when_generated_timezone"] is None
    assert normalized["date_coverage_only"] is True
    serialized = json.dumps(result)
    assert "T23:59:59Z" not in serialized
    assert "2026-09-19T02:00:00Z" not in serialized
