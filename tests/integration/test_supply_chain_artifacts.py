from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from cash_research.artifacts import (
    archive_artifact,
    json_pointer_exists,
    resolve_reference,
    validate_artifact,
)
from cash_research.models import Decision, Evidence


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "fixtures/scenarios/supply-chain/cases.json"
CHAIN_STEPS = {
    "demand",
    "bottleneck_or_substitute",
    "company_exposure",
    "profit_and_valuation",
    "countercase",
    "next_check",
}


def load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path.relative_to(path.parents[2]).as_posix()


def materialize_case(root: Path, case: dict[str, object]) -> tuple[str, str, str, dict[str, str]]:
    case_id = str(case["case_id"])
    material_refs: dict[str, str] = {}
    evidence_refs: dict[str, str] = {}
    for material in case["materials"]:
        material_id = material["material_id"]
        source_ref = f"case-inputs/{case_id}/sources/{material_id}.json"
        source_payload = {
            "material_id": material_id,
            "title": material["title"],
            "origin_url": material["origin_url"],
            "source_type": material["source_type"],
            "text": material["text"],
        }
        write_json(root / source_ref, source_payload)
        material_refs[material_id] = source_ref
        evidence_ref = f"case-inputs/{case_id}/evidence/{material_id}.json"
        evidence = Evidence(
            evidence_id=f"evidence-{case_id}-{material_id}",
            source_ref=source_ref,
            locator=material["locator"],
            published_at=material["published_at"],
            retrieved_at=material["retrieved_at"],
            available_at=material["available_at"],
            content_kind=material["content_kind"],
            claim=material["text"],
            scope=f"synthetic fixture {case_id}",
            units=tuple(material["units"]),
            limitations=tuple(material["limitations"]),
            unknown_reasons={},
        )
        write_json(root / evidence_ref, evidence.model_dump(mode="json"))
        evidence_refs[material_id] = evidence_ref

    decision_value = dict(case["decision"])
    decision_value.update(
        {
            "decision_id": "draft-id-is-replaced-on-archive",
            "reason_refs": list(evidence_refs.values()),
            "previous_id": None,
            "memory_packet_refs": [],
        }
    )
    draft_ref = f"case-inputs/{case_id}/decision.json"
    write_json(root / draft_ref, decision_value)
    report_ref = f"case-inputs/{case_id}/report.md"
    report_lines = [
        f"# {case['user_question_zh']}",
        "",
        f"Outcome: {case['expected_outcome']['research_status']}",
        "",
        "## Evidence chain",
    ]
    report_lines.extend(
        f"- [{item['claim_type']}] {item['step']}: {item['statement']}"
        for item in case["analysis_chain"]
    )
    (root / report_ref).write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    attachment_ref = f"case-inputs/{case_id}/evidence-chain.json"
    write_json(
        root / attachment_ref,
        {
            "case_id": case_id,
            "analysis_chain": case["analysis_chain"],
            "material_refs": material_refs,
            "semantic_validation": "reviewer_required_program_not_authoritative",
        },
    )
    return draft_ref, report_ref, attachment_ref, material_refs


def test_manifest_maps_all_fixture_cases_without_claiming_native_acceptance() -> None:
    fixture = load_fixture()
    cases = {case["case_id"]: case for case in fixture["cases"]}
    mapping = fixture["market_manifest"]

    assert set(mapping) == {"US", "HK", "CN"}
    assert {case_id for case_ids in mapping.values() for case_id in case_ids} == set(cases)
    for market, case_ids in mapping.items():
        assert all(cases[case_id]["market"] == market for case_id in case_ids)
    assert fixture["fixture_scope"] == "synthetic_static_artifact_contract_only"
    assert fixture["native_acceptance_case_count"] == 0
    assert "autonomously" in " ".join(fixture["program_does_not_check"])
    assert all(case["user_question_zh"] for case in cases.values())
    assert not any(
        isinstance(value, str) and value.startswith("rec_")
        for value in _walk_values(fixture)
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "theme-only-discovery",
        "candidate-rejected-by-counterevidence",
        "conflicting-evidence",
        "no-qualified-opportunity",
    ],
)
def test_claim_chain_has_typed_traceable_sources_and_explicit_semantic_review(
    tmp_path: Path, case_id: str
) -> None:
    fixture = load_fixture()
    case = next(item for item in fixture["cases"] if item["case_id"] == case_id)
    _, _, _, source_refs = materialize_case(tmp_path, case)
    materials = {item["material_id"]: item for item in case["materials"]}

    assert {item["step"] for item in case["analysis_chain"]} == CHAIN_STEPS
    assert all(item["evidence_refs"] for item in case["analysis_chain"])
    assert all(item["review_required"] is True for item in case["analysis_chain"])
    assert all(item["semantic_expectation"] for item in case["analysis_chain"])
    for claim in case["analysis_chain"]:
        assert claim["claim_type"] in {"fact", "opinion", "inference", "conflict"}
        for material_id in claim["evidence_refs"]:
            material = materials[material_id]
            source = json.loads((tmp_path / source_refs[material_id]).read_text("utf-8"))
            assert json_pointer_exists(source, material["locator"])
            assert material["origin_url"].startswith("https://example.test/")
            assert datetime.fromisoformat(material["available_at"]).tzinfo is not None
            assert datetime.fromisoformat(material["retrieved_at"]).tzinfo is not None
            assert material["limitations"]
    assert Decision.model_validate(
        {
            **case["decision"],
            "decision_id": "draft",
            "reason_refs": [f"evidence/{name}.json" for name in materials],
            "previous_id": None,
            "memory_packet_refs": [],
        }
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "theme-only-discovery",
        "candidate-rejected-by-counterevidence",
        "conflicting-evidence",
        "no-qualified-opportunity",
    ],
)
def test_default_check_then_explicit_archive_freezes_body_attachment_and_provenance(
    tmp_path: Path, case_id: str
) -> None:
    fixture = load_fixture()
    case = next(item for item in fixture["cases"] if item["case_id"] == case_id)
    draft_ref, report_ref, attachment_ref, source_refs = materialize_case(tmp_path, case)

    checked = validate_artifact(
        root=tmp_path,
        draft_ref=draft_ref,
        record_type="Decision",
        reference_refs=list(source_refs.values()),
        report_ref=report_ref,
        attachment_refs=[attachment_ref],
    )
    assert checked.model.decision_id == "draft-id-is-replaced-on-archive"
    assert checked.report is not None
    assert len(checked.attachments) == 1
    assert len(checked.provenance) == 2 * len(case["materials"])
    assert not (tmp_path / "data/records").exists()

    archived = archive_artifact(
        root=tmp_path,
        draft_ref=draft_ref,
        record_type="Decision",
        reference_refs=list(source_refs.values()),
        report_ref=report_ref,
        attachment_refs=[attachment_ref],
    )
    assert archived.record_id.startswith("rec_")
    assert archived.model.decision_id == archived.record_id
    assert archived.model.label == case["decision"]["label"]
    if case_id == "no-qualified-opportunity":
        assert archived.model.label == "no_opportunity"
    assert resolve_reference(tmp_path, archived.record_id) == (
        tmp_path / archived.relative_path / "record.json"
    ).resolve()
    assert archived.report_ref is not None
    assert len(archived.attachment_refs) == 1
    manifest = json.loads((tmp_path / archived.manifest_ref).read_text("utf-8"))
    assert manifest["record_type"] == "Decision"
    assert manifest["report"]["archived_ref"] == archived.report_ref
    assert manifest["attachments"][0]["archived_ref"] == archived.attachment_refs[0]
    assert len(manifest["provenance"]) == 2 * len(case["materials"])
    for locator in manifest["provenance"]:
        referenced = tmp_path / locator["relative_path"]
        assert referenced.is_file()
        assert hashlib.sha256(referenced.read_bytes()).hexdigest() == locator["sha256"]
    assert (tmp_path / archived.report_ref).read_text("utf-8").startswith("# ")
    attachment = json.loads((tmp_path / archived.attachment_refs[0]).read_text("utf-8"))
    assert attachment["case_id"] == case_id
    assert attachment["semantic_validation"] == "reviewer_required_program_not_authoritative"


def test_negative_and_no_opportunity_cases_are_research_outcomes_not_execution_failures() -> None:
    cases = {case["case_id"]: case for case in load_fixture()["cases"]}
    assert cases["candidate-rejected-by-counterevidence"]["expected_outcome"] == {
        "research_status": "candidate_rejected",
        "execution_outcome": "complete",
        "candidate_status": "reject",
        "reason": "Counterevidence shows no qualified product and no supported profit transmission.",
    }
    assert cases["no-qualified-opportunity"]["expected_outcome"]["execution_outcome"] == "complete"
    assert cases["no-qualified-opportunity"]["expected_outcome"]["candidate_status"] == "none"
    assert cases["no-qualified-opportunity"]["decision"]["label"] == "no_opportunity"
    assert cases["conflicting-evidence"]["expected_outcome"]["execution_outcome"] == "limited"
    assert cases["conflicting-evidence"]["decision"]["evidence_limited"] is True


def _walk_values(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value
