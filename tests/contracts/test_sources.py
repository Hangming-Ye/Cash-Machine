"""Synthetic source contracts for T018-T024 implementations.

Adapters expose ``fetch(request, *, output_ref)`` and return the mapping validated by
``assert_adapter_result``.  Provider unit tests may reuse this assertion; this
module does not provide a production adapter or claim live source access.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import pytest

from cash_research.models import DataGap, Evidence, SourceResult
from cash_research.artifacts import reject_secrets


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "fixtures" / "sources" / "expected.json"
REQUEST_KEYS = {
    "request_id",
    "source",
    "operation",
    "subject",
    "as_of",
    "parameters",
    "required_fields",
}
RESULT_KEYS = {"source_result", "raw_payload", "normalized", "evidence", "gaps"}
SOURCE_OPERATIONS = {
    "quote",
    "bars",
    "news",
    "profile",
    "statements",
    "text_ingest",
    "series_ingest",
}
DATA_ERROR_CASES = {
    "wrong_security",
    "unsupported",
    "unauthorized",
    "rate_limited",
    "empty",
    "stale",
    "revision_conflict",
}


class SourceAdapter(Protocol):
    """Construct with Settings/injected read-only client; never load global secrets."""

    def fetch(
        self, request: Mapping[str, object], *, output_ref: str
    ) -> Mapping[str, object]: ...


@pytest.fixture(scope="module")
def source_fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def assert_adapter_result(
    request: Mapping[str, object],
    result: Mapping[str, object],
    *,
    output_ref: str = "fixtures/sources/expected.json",
) -> tuple[SourceResult, tuple[Evidence, ...], tuple[DataGap, ...]]:
    """Validate the stable adapter mapping without a CLI result envelope."""

    assert REQUEST_KEYS <= set(request)
    reject_secrets(request)
    assert request["operation"] in SOURCE_OPERATIONS
    assert not str(request["operation"]).endswith("order")
    assert RESULT_KEYS <= set(result)
    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.source == request["source"]
    assert source_result.operation == request["operation"]
    assert isinstance(result["normalized"], dict)
    evidence_value = result["evidence"]
    gap_value = result["gaps"]
    assert isinstance(evidence_value, list)
    assert isinstance(gap_value, list)
    evidence = tuple(Evidence.model_validate(item) for item in evidence_value)
    gaps = tuple(DataGap.model_validate(item) for item in gap_value)

    raw = result["raw_payload"]
    raw_locator = result["normalized"].get("raw_locator")
    if raw is None:
        assert source_result.payload_ref is None
        assert raw_locator is None
        assert source_result.quality == "failed"
        assert source_result.errors
    else:
        assert source_result.payload_ref == output_ref
        assert isinstance(raw_locator, str)
        assert raw_locator == "" or raw_locator.startswith("/")
    return source_result, evidence, gaps


def _all_cases(fixture: Mapping[str, object]) -> list[tuple[str, Mapping[str, object]]]:
    cases: list[tuple[str, Mapping[str, object]]] = []
    for group_name in ("success_cases", "data_error_cases"):
        group = fixture[group_name]
        assert isinstance(group, dict)
        cases.extend((case_id, case) for case_id, case in group.items())
    return cases


def test_fixture_declares_synthetic_contract_and_exact_callable_shape(
    source_fixture: dict[str, object],
) -> None:
    assert source_fixture["schema_version"] == "1.0"
    assert source_fixture["synthetic"] is True
    assert source_fixture["evidence_level"] == "synthetic_contract"
    contract = source_fixture["adapter_contract"]
    assert isinstance(contract, dict)
    assert contract["construction"] == "adapter(settings, client=injected_read_only_client)"
    assert contract["call"] == "fetch(request: Mapping[str, object], *, output_ref: str) -> Mapping[str, object]"
    assert set(contract["required_request_keys"]) == REQUEST_KEYS
    assert set(contract["required_result_keys"]) == RESULT_KEYS
    assert "T024 persists raw_payload" in contract["persistence"]


def test_fixture_covers_all_required_operations_partial_and_seven_errors(
    source_fixture: dict[str, object],
) -> None:
    successes = source_fixture["success_cases"]
    errors = source_fixture["data_error_cases"]
    assert isinstance(successes, dict) and isinstance(errors, dict)
    assert set(successes) == {
        "quote",
        "bars",
        "news",
        "profile",
        "statements",
        "text_ingest",
        "series_ingest",
        "partial_success",
    }
    assert {case["request"]["operation"] for case in successes.values()} == SOURCE_OPERATIONS
    assert set(errors) == DATA_ERROR_CASES


def test_every_case_conforms_to_shared_models_and_preserves_raw_payload(
    source_fixture: dict[str, object],
) -> None:
    for case_id, case in _all_cases(source_fixture):
        assert isinstance(case, dict), case_id
        request = case["request"]
        result = case["result"]
        assert isinstance(request, dict) and isinstance(result, dict), case_id
        source_result, evidence, gaps = assert_adapter_result(request, result)
        assert source_result.retrieved_at.tzinfo is not None, case_id
        for item in evidence:
            assert (ROOT / item.source_ref).is_file(), case_id
            assert item.locator.startswith("/"), case_id
        for gap in gaps:
            assert gap.request_id == request["request_id"], case_id
            assert gap.attempts and gap.impact and gap.next_action, case_id


def test_runtime_whole_raw_payload_may_use_root_json_pointer(
    source_fixture: dict[str, object],
) -> None:
    case = json.loads(json.dumps(source_fixture["success_cases"]["quote"]))
    output_ref = "data/records/rec_00000000000000000000000000000000/sources/finnhub-quote.json"
    case["result"]["source_result"]["payload_ref"] = output_ref
    case["result"]["normalized"]["raw_locator"] = ""

    assert_adapter_result(case["request"], case["result"], output_ref=output_ref)


def test_unknown_times_are_null_with_reasons_not_epoch_or_retrieval_defaults(
    source_fixture: dict[str, object],
) -> None:
    for case_id, case in _all_cases(source_fixture):
        model = SourceResult.model_validate(case["result"]["source_result"])
        for field in ("observed_at", "available_at"):
            value = getattr(model, field)
            if value is None:
                assert model.unknown_reasons.get(field), case_id
            else:
                assert value.year > 1970, case_id
        assert model.observed_at != model.retrieved_at or case_id not in {
            "quote",
            "profile",
            "statements",
        }


def test_bars_keep_raw_and_adjusted_bases_corporate_actions_and_null_volume(
    source_fixture: dict[str, object],
) -> None:
    result = source_fixture["success_cases"]["bars"]["result"]
    raw_rows = result["raw_payload"]
    normalized = result["normalized"]
    assert normalized["price_basis"] == normalized["volume_basis"] == "raw"
    assert {"adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume", "divCash", "splitFactor"} <= set(raw_rows[0])
    assert raw_rows[1]["volume"] is None and raw_rows[1]["adjVolume"] == 2100
    assert normalized["rows"][1]["volume"] is None
    assert "adjusted volume was not substituted" in normalized["rows"][1]["volume_unknown_reason"]
    assert normalized["revision_status"] != "final"


def test_news_and_profile_keep_actual_provider_fields_without_semantic_invention(
    source_fixture: dict[str, object],
) -> None:
    news = source_fixture["success_cases"]["news"]["result"]
    assert news["normalized"]["actual_source"] == "finnhub:/company-news"
    assert news["evidence"][0]["content_kind"] == "third_party_view"
    assert news["evidence"][0]["available_at"] is None

    profile = source_fixture["success_cases"]["profile"]["result"]
    raw = profile["raw_payload"][0]
    assert {"marketCap", "lastDividend", "exchange", "currency"} <= set(raw)
    assert not {"mktCap", "lastDiv", "exchangeShortName"} & set(raw)
    assert profile["normalized"]["last_dividend"]["unit"] == "currency_per_share"


def test_statements_preserve_filing_revision_currency_and_do_not_claim_pit(
    source_fixture: dict[str, object],
) -> None:
    result = source_fixture["success_cases"]["statements"]["result"]
    assert set(result["raw_payload"]) == {"income", "balance", "cash"}
    for rows in result["raw_payload"].values():
        row = rows[0]
        assert {"date", "reportedCurrency", "filingDate", "acceptedDate", "fiscalYear", "period"} <= set(row)
    normalized = result["normalized"]
    assert normalized["reported_currency"] == "USD"
    assert normalized["accepted_timezone"] is None
    assert normalized["point_in_time_status"].startswith("not_proven")
    assert result["source_result"]["available_at"] is None


def test_ingest_contract_preserves_locator_coverage_units_and_limitations(
    source_fixture: dict[str, object],
) -> None:
    text = source_fixture["success_cases"]["text_ingest"]["result"]
    assert text["normalized"]["semantic_validation"] == "not_claimed"
    assert text["evidence"][0]["limitations"]

    series = source_fixture["success_cases"]["series_ingest"]["result"]
    normalized = series["normalized"]
    assert normalized["row_count"] == len(series["raw_payload"]) == 2
    assert normalized["coverage_start"] == "2026-01-13"
    assert normalized["coverage_end"] == "2026-01-14"
    assert normalized["unit"] == "currency_per_share"
    assert normalized["adjustment_status"] == "unknown"
    assert normalized["point_in_time_status"] == "not_proven"


def test_partial_success_names_successful_failed_and_actual_underlying_sources(
    source_fixture: dict[str, object],
) -> None:
    result = source_fixture["success_cases"]["partial_success"]["result"]
    source_result = SourceResult.model_validate(result["source_result"])
    assert source_result.quality == "limited"
    assert source_result.errors == ("primary_endpoint_failed",)
    assert result["normalized"]["successful_endpoints"] == ["fallback"]
    assert result["normalized"]["failed_endpoints"] == ["primary"]
    assert result["normalized"]["actual_source"] == "akshare:fallback-synthetic"
    assert result["gaps"]


def test_seven_error_classes_keep_empty_distinct_from_failed_and_revision_unresolved(
    source_fixture: dict[str, object],
) -> None:
    errors = source_fixture["data_error_cases"]
    expected_reasons = {
        "wrong_security": "invalid",
        "unsupported": "unsupported",
        "unauthorized": "unauthorized",
        "rate_limited": "rate_limited",
        "empty": "empty",
        "stale": "stale",
        "revision_conflict": "conflict",
    }
    assert set(errors) == set(expected_reasons)
    for case_id, reason in expected_reasons.items():
        result = errors[case_id]["result"]
        assert result["normalized"]["error_reason"] == reason
        assert result["gaps"], case_id

    empty = errors["empty"]["result"]
    assert empty["raw_payload"] == []
    assert empty["source_result"]["quality"] == "limited"
    assert empty["source_result"]["errors"] == []
    assert empty["normalized"]["empty_is_failure"] is False
    for case_id in ("unsupported", "unauthorized", "rate_limited"):
        failed = errors[case_id]["result"]
        assert failed["raw_payload"] is None
        assert failed["source_result"]["quality"] == "failed"
        assert failed["source_result"]["errors"]

    revision = errors["revision_conflict"]["result"]
    assert len(revision["raw_payload"]) == 2
    assert revision["normalized"]["revision_status"] == "unresolved"
    assert revision["normalized"]["point_in_time_status"] == "not_proven"


def test_fixture_has_no_cli_envelope_live_success_or_credential_material(
    source_fixture: dict[str, object],
) -> None:
    rendered = json.dumps(source_fixture, sort_keys=True)
    assert '"status"' not in rendered
    assert '"artifacts"' not in rendered
    assert '"api_key"' not in rendered.lower()
    assert '"token"' not in rendered.lower()
    assert '"http_status": 200' not in rendered
