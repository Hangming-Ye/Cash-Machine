from __future__ import annotations

import json
import math
import os
import shutil
import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr

from cash_research.config import Settings
from cash_research.models import DataGap, Evidence, SourceResult
from cash_research.sources.ingest import MaterialIngestAdapter


NOW = datetime(2026, 1, 15, 19, 0, tzinfo=timezone.utc)
PROJECT_ROOT = Path(__file__).parents[2]


def _copy_fixture(root: Path, name: str) -> str:
    source = PROJECT_ROOT / "fixtures/ingest" / name
    target = root / "fixtures/ingest" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.relative_to(root).as_posix()


def _adapter(root: Path) -> MaterialIngestAdapter:
    return MaterialIngestAdapter(Settings(root=root), clock=lambda: NOW)


def _text_request(path: str, **overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {
        "path": path,
        "locator": "line:3",
        "origin_url": "https://example.test/note",
        "source_name": "Synthetic Publisher",
        "author": "Synthetic Analyst",
        "organization": "Synthetic Publisher",
        "access_scope": "public synthetic fixture",
        "published_at": "2026-01-10T09:00:00Z",
        "available_at": "2026-01-10T09:00:00Z",
        "content_kind": "third_party_view",
        "claim": "The synthetic note states that capacity is constrained.",
        "scope": "one complete synthetic note",
        "limitations": ["synthetic fixture; semantic truth is not validated"],
        "material_scope": "complete_document",
    }
    parameters.update(overrides)
    return {
        "request_id": "req-text",
        "source": "user_provided_material",
        "operation": "text_ingest",
        "subject": "synthetic capacity",
        "as_of": NOW.isoformat(),
        "parameters": parameters,
        "required_fields": [
            "published_at",
            "available_at",
            "source_locator",
            "access_scope",
            "limitations",
        ],
    }


def _series_request(path: str, **overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {
        "path": path,
        "locator": "rows:2-3",
        "origin_url": "https://example.test/series.csv",
        "source_name": "Synthetic Data Publisher",
        "organization": "Synthetic Data Publisher",
        "access_scope": "public synthetic fixture",
        "published_at": "2026-01-15T08:00:00Z",
        "available_at": "2026-01-15T08:00:00Z",
        "timestamp_field": "date",
        "value_fields": ["close"],
        "unit": "HKD/share",
        "currency": "HKD",
        "market_timezone": "Asia/Hong_Kong",
        "bar_interval": "1d",
        "price_basis": "raw",
        "adjustment_status": "unadjusted",
        "revision_status": "publisher_snapshot",
        "point_in_time_status": "not_proven",
        "requested_start": "2026-01-13",
        "requested_end": "2026-01-14",
        "series_scope": "complete_requested_range",
        "expected_timestamps": ["2026-01-13", "2026-01-14"],
        "coverage_basis": "synthetic publisher-declared expected rows",
        "limitations": ["synthetic series; market calendar was not supplied"],
    }
    parameters.update(overrides)
    return {
        "request_id": "req-series",
        "source": "user_provided_series",
        "operation": "series_ingest",
        "subject": {
            "market": "HK",
            "exchange": "XHKG",
            "symbol": "SYNH",
            "currency": "HKD",
        },
        "as_of": NOW.isoformat(),
        "parameters": parameters,
        "required_fields": [
            "schema",
            "coverage",
            "market_date",
            "currency",
            "unit",
            "adjustment_status",
        ],
    }


def test_text_ingest_preserves_original_provenance_and_does_not_claim_truth(
    tmp_path: Path,
) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    output_ref = "data/source-payloads/req-text/raw.json"
    result = _adapter(tmp_path).fetch(_text_request(input_ref), output_ref=output_ref)

    source_result = SourceResult.model_validate(result["source_result"])
    evidence = Evidence.model_validate(result["evidence"][0])
    assert source_result.quality == "complete"
    assert source_result.payload_ref == output_ref
    assert result["raw_payload"]["content_utf8"] == (
        tmp_path / input_ref
    ).read_text(encoding="utf-8")
    assert result["raw_payload"]["sha256"]
    assert result["normalized"]["origin_url"] == "https://example.test/note"
    assert result["normalized"]["access_scope"] == "public synthetic fixture"
    assert result["normalized"]["semantic_validation"] == "not_claimed"
    assert evidence.source_ref == output_ref
    assert evidence.locator == "/content_utf8"
    assert result["normalized"]["original_locator"] == "line:3"
    assert evidence.limitations
    assert result["gaps"] == []
    assert not (tmp_path / output_ref).exists()


def test_packaged_request_template_runs_after_fixture_is_copied_to_root(
    tmp_path: Path,
) -> None:
    request = json.loads(
        (PROJECT_ROOT / "fixtures/requests/evidence-ingest.json").read_text(encoding="utf-8")
    )
    _copy_fixture(tmp_path, "synthetic-note.md")
    result = _adapter(tmp_path).fetch(
        request, output_ref="data/source-payloads/fixture-evidence/raw.json"
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "complete"
    assert Evidence.model_validate(result["evidence"][0]).claim.startswith(
        "The synthetic note states"
    )


def test_pdf_is_archived_losslessly_without_fabricated_text_or_semantics(
    tmp_path: Path,
) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-opaque.pdf")
    original = (tmp_path / input_ref).read_bytes()
    request = _text_request(
        input_ref,
        locator="page:1",
        claim="This declared claim must not be presented as extracted PDF text.",
        scope="one synthetic PDF",
    )
    result = _adapter(tmp_path).fetch(
        request, output_ref="data/source-payloads/opaque-pdf/raw.json"
    )
    source_result = SourceResult.model_validate(result["source_result"])
    evidence = Evidence.model_validate(result["evidence"][0])
    raw = result["raw_payload"]
    assert source_result.quality == "limited"
    assert raw["media_type"] == "application/pdf"
    assert base64.b64decode(raw["content_base64"]) == original
    assert raw["sha256"] == hashlib.sha256(original).hexdigest()
    assert "content_utf8" not in raw
    assert result["normalized"]["text_extracted"] is False
    assert result["normalized"]["semantic_validation"] == "not_claimed"
    assert result["normalized"]["original_locator"] == "page:1"
    assert evidence.locator == "/content_base64"
    assert "declared claim" not in evidence.claim.lower()
    assert any("no text was extracted" in gap["attempts"][0]["result"] for gap in result["gaps"])


def test_malformed_pdf_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "fixtures/ingest/not-a-pdf.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a PDF\n%%EOF\n")
    result = _adapter(tmp_path).fetch(
        _text_request(path.relative_to(tmp_path).as_posix(), locator="page:1"),
        output_ref="data/source-payloads/not-pdf/raw.json",
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "failed"
    assert result["evidence"] == []


def test_complete_numeric_csv_validates_identity_units_order_and_coverage(
    tmp_path: Path,
) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-series.csv")
    result = _adapter(tmp_path).fetch(
        _series_request(input_ref), output_ref="data/source-payloads/req-series/raw.json"
    )

    source_result = SourceResult.model_validate(result["source_result"])
    evidence = Evidence.model_validate(result["evidence"][0])
    normalized = result["normalized"]
    assert source_result.quality == "complete"
    assert normalized["coverage_start"] == "2026-01-13"
    assert normalized["coverage_end"] == "2026-01-14"
    assert normalized["row_count"] == 2
    assert normalized["unit"] == "HKD/share"
    assert normalized["column_units"] == {"close": "HKD/share"}
    assert normalized["currency"] == "HKD"
    assert normalized["price_basis"] == "raw"
    assert normalized["bar_interval"] == "1d"
    assert normalized["observed_date_gaps"] == []
    assert normalized["rows"][0]["close"] == 50.0
    assert evidence.units == ("HKD/share",)
    assert result["gaps"] == []


def test_fragment_is_limited_and_never_represented_as_complete_history(tmp_path: Path) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-series.csv")
    request = _series_request(
        input_ref,
        series_scope="fragment",
        requested_start="2025-01-01",
        requested_end="2026-01-14",
    )
    result = _adapter(tmp_path).fetch(
        request, output_ref="data/source-payloads/fragment/raw.json"
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"
    assert result["normalized"]["series_scope"] == "fragment"
    assert result["normalized"]["complete_requested_range"] is False
    assert any("coverage" in DataGap.model_validate(gap).required_content for gap in result["gaps"])


def test_endpoint_coverage_without_expected_timestamps_is_not_verified_complete(
    tmp_path: Path,
) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-series.csv")
    result = _adapter(tmp_path).fetch(
        _series_request(input_ref, expected_timestamps=None),
        output_ref="data/source-payloads/unverified-interior/raw.json",
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"
    assert result["normalized"]["complete_requested_range"] is False
    assert result["normalized"]["coverage_verification"] == "unverified_or_incomplete"
    assert any("coverage" in gap["required_content"] for gap in result["gaps"])


def test_text_excerpt_is_limited_and_never_claimed_as_full_document(tmp_path: Path) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    result = _adapter(tmp_path).fetch(
        _text_request(input_ref, material_scope="excerpt"),
        output_ref="data/source-payloads/excerpt/raw.json",
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"
    assert result["normalized"]["material_scope"] == "excerpt"
    assert any("complete original document" in gap["required_content"] for gap in result["gaps"])


def test_unknown_availability_and_required_field_produce_explicit_gap(tmp_path: Path) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    request = _text_request(input_ref, available_at=None)
    result = _adapter(tmp_path).fetch(
        request, output_ref="data/source-payloads/unknown-time/raw.json"
    )
    source_result = SourceResult.model_validate(result["source_result"])
    evidence = Evidence.model_validate(result["evidence"][0])
    assert source_result.quality == "limited"
    assert source_result.available_at is None
    assert source_result.unknown_reasons["available_at"]
    assert evidence.unknown_reasons["available_at"]
    assert any("available_at" in DataGap.model_validate(gap).required_content for gap in result["gaps"])


@pytest.mark.parametrize("time_field", ["published_at", "available_at"])
def test_material_time_after_as_of_is_rejected(tmp_path: Path, time_field: str) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    request = _text_request(input_ref, **{time_field: "2026-01-16T00:00:00Z"})
    result = _adapter(tmp_path).fetch(
        request, output_ref="data/source-payloads/future/raw.json"
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "failed"
    assert result["source_result"]["errors"] == ["invalid"]
    assert result["evidence"] == []


def test_future_series_row_is_rejected_with_specific_gap(tmp_path: Path) -> None:
    path = tmp_path / "fixtures/ingest/future.csv"
    path.parent.mkdir(parents=True)
    path.write_text("date,close,currency\n2026-01-16,50,HKD\n", encoding="utf-8")
    result = _adapter(tmp_path).fetch(
        _series_request(
            path.relative_to(tmp_path).as_posix(),
            requested_start="2026-01-16",
            requested_end="2026-01-16",
            expected_timestamps=["2026-01-16"],
        ),
        output_ref="data/source-payloads/future-row/raw.json",
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "failed"
    gap = DataGap.model_validate(result["gaps"][0])
    assert "no later than as_of" in gap.required_content
    assert "future row" in gap.impact


def test_ingest_never_promotes_caller_pit_claim_to_proven(tmp_path: Path) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-series.csv")
    request = _series_request(input_ref, point_in_time_status="proven")
    request["required_fields"].append("point_in_time_status")
    result = _adapter(tmp_path).fetch(
        request,
        output_ref="data/source-payloads/pit-claim/raw.json",
    )
    assert result["normalized"]["declared_point_in_time_status"] == "proven"
    assert result["normalized"]["point_in_time_status"] == "not_proven_by_ingest"
    assert any("not proven by ingest" in item for item in result["normalized"]["limitations"])
    assert SourceResult.model_validate(result["source_result"]).quality == "limited"
    assert any(gap["required_content"] == "point_in_time_status" for gap in result["gaps"])


def test_mixed_numeric_fields_require_and_preserve_per_column_units(tmp_path: Path) -> None:
    path = tmp_path / "fixtures/ingest/mixed.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            [
                {"date": "2026-01-13", "close": 50, "volume": 1000, "currency": "HKD"},
                {"date": "2026-01-14", "close": 51, "volume": 1100, "currency": "HKD"},
            ]
        ),
        encoding="utf-8",
    )
    request = _series_request(
        path.relative_to(tmp_path).as_posix(),
        value_fields=["close", "volume"],
        unit=None,
        column_units={"close": "HKD/share", "volume": "shares"},
    )
    request["required_fields"] = ["schema", "coverage", "column_units", "currency"]
    result = _adapter(tmp_path).fetch(
        request, output_ref="data/source-payloads/mixed/raw.json"
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "complete"
    assert result["normalized"]["unit"] is None
    assert result["normalized"]["column_units"] == {
        "close": "HKD/share",
        "volume": "shares",
    }
    assert result["normalized"]["rows"][0]["volume"] == 1000.0
    assert set(Evidence.model_validate(result["evidence"][0]).units) == {
        "HKD/share",
        "shares",
    }


@pytest.mark.parametrize(
    "request_factory, input_name, mutation",
    [
        (_series_request, "synthetic-series.csv", {"unit": None}),
        (_series_request, "synthetic-series.csv", {"currency": None}),
    ],
)
def test_series_missing_units_or_currency_is_rejected(
    tmp_path: Path, request_factory: object, input_name: str, mutation: dict[str, object]
) -> None:
    input_ref = _copy_fixture(tmp_path, input_name)
    request = request_factory(input_ref, **mutation)
    result = _adapter(tmp_path).fetch(
        request, output_ref="data/source-payloads/missing-units/raw.json"
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "failed"
    assert result["evidence"] == []


def test_duplicate_or_nonfinite_series_values_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "fixtures/ingest/duplicate.csv"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(
        "date,close,currency\n2026-01-13,50,HKD\n2026-01-13,NaN,HKD\n",
        encoding="utf-8",
    )
    result = _adapter(tmp_path).fetch(
        _series_request(duplicate.relative_to(tmp_path).as_posix()),
        output_ref="data/source-payloads/duplicate/raw.json",
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "failed"
    assert not any(
        isinstance(value, float) and not math.isfinite(value)
        for row in result.get("normalized", {}).get("rows", [])
        for value in row.values()
    )


@pytest.mark.parametrize("bad_value", ["NaN", True])
def test_unique_nonfinite_or_boolean_numeric_value_is_rejected(
    tmp_path: Path, bad_value: object
) -> None:
    path = tmp_path / "fixtures/ingest/bad-value.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            [
                {"date": "2026-01-13", "close": 50, "currency": "HKD"},
                {"date": "2026-01-14", "close": bad_value, "currency": "HKD"},
            ]
        ),
        encoding="utf-8",
    )
    result = _adapter(tmp_path).fetch(
        _series_request(path.relative_to(tmp_path).as_posix()),
        output_ref="data/source-payloads/bad-value/raw.json",
    )
    assert SourceResult.model_validate(result["source_result"]).quality == "failed"
    assert result["evidence"] == []


def test_input_and_output_path_escape_are_rejected_without_reading_outside(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside-ingest.txt"
    outside.write_text("SYNTHETIC_OUTSIDE_CANARY", encoding="utf-8")
    input_result = _adapter(tmp_path).fetch(
        _text_request("../outside-ingest.txt"),
        output_ref="data/source-payloads/escape/raw.json",
    )
    output_result = _adapter(tmp_path).fetch(
        _text_request(_copy_fixture(tmp_path, "synthetic-note.md")),
        output_ref="../outside-output.json",
    )
    assert input_result["source_result"]["errors"] == ["invalid"]
    assert output_result["source_result"]["errors"] == ["invalid"]
    assert outside.read_text(encoding="utf-8") == "SYNTHETIC_OUTSIDE_CANARY"


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-note.md"
    outside.write_text("SYNTHETIC_OUTSIDE_CANARY", encoding="utf-8")
    link = tmp_path / "fixtures/ingest/linked.md"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(outside, link)
    except OSError as exc:
        pytest.skip(f"file symlink is unavailable: {exc}")
    result = _adapter(tmp_path).fetch(
        _text_request(link.relative_to(tmp_path).as_posix()),
        output_ref="data/source-payloads/symlink/raw.json",
    )
    assert result["source_result"]["errors"] == ["invalid"]


def test_internal_symlink_is_also_rejected_when_supported(tmp_path: Path) -> None:
    input_ref = _copy_fixture(tmp_path, "synthetic-note.md")
    link = tmp_path / "fixtures/ingest/internal-link.md"
    try:
        os.symlink(tmp_path / input_ref, link)
    except OSError as exc:
        pytest.skip(f"file symlink is unavailable: {exc}")
    result = _adapter(tmp_path).fetch(
        _text_request(link.relative_to(tmp_path).as_posix()),
        output_ref="data/source-payloads/internal-symlink/raw.json",
    )
    assert result["source_result"]["errors"] == ["invalid"]


def test_secret_or_malformed_material_is_rejected_without_echo(tmp_path: Path) -> None:
    secret = "should-never-appear"
    path = tmp_path / "fixtures/ingest/secret.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"api_key": secret}), encoding="utf-8")
    result = _adapter(tmp_path).fetch(
        _text_request(path.relative_to(tmp_path).as_posix()),
        output_ref="data/source-payloads/secret/raw.json",
    )
    assert result["source_result"]["errors"] == ["invalid"]
    assert secret not in json.dumps(result)

    malformed = tmp_path / "fixtures/ingest/malformed.json"
    malformed.write_text("{", encoding="utf-8")
    malformed_result = _adapter(tmp_path).fetch(
        _text_request(malformed.relative_to(tmp_path).as_posix()),
        output_ref="data/source-payloads/malformed/raw.json",
    )
    assert malformed_result["source_result"]["errors"] == ["invalid"]


def test_plain_credential_assignment_and_loaded_secret_value_are_rejected(
    tmp_path: Path,
) -> None:
    assignment = tmp_path / "fixtures/ingest/assignment.md"
    assignment.parent.mkdir(parents=True)
    assignment.write_text("API_KEY=plain-secret-value\n", encoding="utf-8")
    assignment_result = _adapter(tmp_path).fetch(
        _text_request(assignment.relative_to(tmp_path).as_posix()),
        output_ref="data/source-payloads/assignment/raw.json",
    )
    assert assignment_result["source_result"]["errors"] == ["invalid"]
    assert "plain-secret-value" not in json.dumps(assignment_result)

    known_secret = "known-secret-value"
    known = tmp_path / "fixtures/ingest/known.md"
    known.write_text(f"A note containing {known_secret}.\n", encoding="utf-8")
    settings = Settings(root=tmp_path, credentials={"SOURCE_KEY": SecretStr(known_secret)})
    result = MaterialIngestAdapter(settings, clock=lambda: NOW).fetch(
        _text_request(known.relative_to(tmp_path).as_posix()),
        output_ref="data/source-payloads/known-secret/raw.json",
    )
    assert result["source_result"]["errors"] == ["invalid"]
    assert known_secret not in json.dumps(result)
