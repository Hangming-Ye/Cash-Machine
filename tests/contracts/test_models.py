from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from cash_research.models import (
    AccountState,
    CallResult,
    Calculation,
    DataGap,
    Decision,
    Evidence,
    FactorExperiment,
    Lesson,
    MemoryPacket,
    PortfolioSnapshot,
    Quantity,
    ResearchRequest,
    Review,
    SecurityIdentity,
    SourceResult,
    TopicSummary,
    WorkRecord,
)


NOW = datetime(2026, 9, 21, 2, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 22, 2, 0, tzinfo=timezone.utc)


def test_research_request_rejects_naive_knowledge_cutoff() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        ResearchRequest(
            request_id="req-1",
            question="What changed?",
            scope={"markets": ["US"]},
            horizon="12 months",
            as_of=datetime(2026, 9, 21, 2, 0),
            method_tags=("company",),
            input_refs=(),
        )


def test_unknown_source_times_require_specific_reasons() -> None:
    common = {
        "source": "finnhub",
        "operation": "quote",
        "security_or_topic": "US:XNAS:AAPL",
        "retrieved_at": NOW,
        "coverage": "latest quote",
        "payload_ref": "records/source-1/raw.json",
        "quality": "limited",
        "errors": (),
    }
    with pytest.raises(ValidationError, match="observed_at"):
        SourceResult(observed_at=None, available_at=NOW, unknown_reasons={}, **common)

    result = SourceResult(
        observed_at=None,
        available_at=None,
        unknown_reasons={
            "observed_at": "provider omitted the market timestamp",
            "available_at": "publication time was not exposed",
        },
        **common,
    )
    assert result.observed_at is None


def test_quantity_and_security_preserve_identity_unit_and_currency() -> None:
    security = SecurityIdentity(
        market="HK", exchange="XHKG", symbol="700", currency="HKD"
    )
    amount = Quantity(value=Decimal("123.4500"), unit="shares", currency="HKD")

    assert security.canonical_id == "HK:XHKG:700"
    assert amount.value == Decimal("123.4500")
    with pytest.raises(ValidationError):
        Quantity(value=Decimal("1"), unit="currency")


def test_execution_outcome_is_separate_from_investment_label() -> None:
    work = WorkRecord(
        record_id="work-1",
        request_id="req-1",
        created_at=NOW,
        owner="research-bot",
        input_refs=(),
        output_refs=(),
        outcome="limited",
        limitations=("primary filing unavailable",),
    )
    decision = Decision(
        decision_id="decision-1",
        security_or_topic="US:XNAS:AAPL",
        as_of=NOW,
        label="watch",
        reason_refs=("evidence-1",),
        price_or_conditions=None,
        price_or_conditions_reason="evidence does not support a price range",
        evidence_limited=True,
        limitations=("primary filing unavailable",),
        horizon="12 months",
        risks=("demand weakens",),
        invalidators=("guidance cut",),
        memory_packet_refs=(),
    )

    assert work.outcome == "limited"
    assert decision.label == "watch"


def test_factor_experiment_is_frozen_and_keeps_complete_request_reference() -> None:
    experiment = FactorExperiment(
        experiment_id="exp-1",
        request_ref="requests/factors/exp-1.json",
        request_hash="a" * 64,
        hypothesis="post-earnings drift persists",
        failure_regimes=("high volatility",),
        expression={"operator": "lag", "periods": 1},
        parameter_sets=({"periods": 1},),
        dataset_ref="records/dataset-1/table.csv",
        available_time_rule="published_at <= decision_time",
        target="forward_return",
        horizon="20 sessions",
        bar_interval="1d",
        baseline="market return",
        split={"kind": "walk_forward"},
        primary_metric="information_coefficient",
        metrics={"information_coefficient": 0.03},
        costs={"commission_bps": 2.0},
        trial_group="trial-1",
        result_ref=None,
        result_reason="not executed yet",
    )

    with pytest.raises(ValidationError):
        experiment.horizon = "5 sessions"
    with pytest.raises(ValidationError):
        FactorExperiment(**{**experiment.model_dump(), "request_ref": "../summary.json"})
    with pytest.raises(ValidationError):
        FactorExperiment(**{**experiment.model_dump(), "request_ref": "C:summary.json"})


def test_temporal_summary_and_lesson_versions_cannot_move_backwards() -> None:
    with pytest.raises(ValidationError, match="updated_at"):
        TopicSummary(
            topic_id="topic-1",
            version=2,
            known_at=LATER,
            updated_at=NOW,
            current_thesis="thesis",
            support_refs=(),
            opposing_refs=(),
            changes=("new evidence",),
            open_questions=(),
            next_checks=(),
        )

    lesson = Lesson(
        lesson_id="lesson-1",
        version=1,
        check_or_method="verify disclosure timing",
        applies_when="using point-in-time fundamentals",
        source_refs=("evidence-1",),
        counterexamples=(),
        validity="candidate",
        review_condition="after one complete replay",
        known_at=NOW,
        updated_at=LATER,
    )
    assert lesson.validity == "candidate"


def test_review_requires_chronology_and_preserves_counterevidence() -> None:
    with pytest.raises(ValidationError, match="review_at"):
        Review(
            review_id="review-1",
            decision_id="decision-1",
            decision_as_of=LATER,
            review_at=NOW,
            observed_outcome="not yet due",
            process_findings=("source coverage was narrow",),
            counterevidence=("later filing contradicted demand",),
            lesson_refs=(),
        )


def test_memory_packet_modes_enforce_review_fields_and_time_boundaries() -> None:
    with pytest.raises(ValidationError, match="decision_id"):
        MemoryPacket(
            packet_id="packet-1",
            request_id="req-1",
            query="review prior call",
            context_mode="review",
            as_of=NOW,
            selected_refs=(),
            exclusions=(),
            budget={"max_items": 10},
            content_ref="memory-packets/packet-1/content.md",
        )

    packet = MemoryPacket(
        packet_id="packet-1",
        request_id="req-1",
        query="review prior call",
        context_mode="review",
        as_of=NOW,
        decision_id="decision-1",
        review_at=LATER,
        selected_refs=("topics/topic-1/v1.json",),
        exclusions=("superseded lesson",),
        budget={"max_items": 10},
        content_ref="memory-packets/packet-1/content.md",
    )
    assert packet.review_at == LATER


def test_evidence_and_portfolio_unknown_fields_are_never_silently_filled() -> None:
    with pytest.raises(ValidationError, match="published_at"):
        Evidence(
            evidence_id="ev-1",
            source_ref="source-1",
            locator="filing section 2",
            published_at=None,
            retrieved_at=NOW,
            available_at=NOW,
            content_kind="disclosure_fact",
            claim="Revenue increased",
            scope="FY2025",
            units=("USD",),
            limitations=(),
            unknown_reasons={},
        )
    with pytest.raises(ValidationError, match="reported_at"):
        PortfolioSnapshot(
            snapshot_id="snapshot-1",
            broker="ibkr_flex",
            reported_at=None,
            retrieved_at=NOW,
            accounts=(),
            positions=(),
            coverage="failed read",
            complete_read=False,
            unknown_reasons={},
        )


def test_complete_sources_and_empty_portfolios_need_positive_evidence() -> None:
    with pytest.raises(ValidationError, match="payload_ref"):
        SourceResult(
            source="finnhub",
            operation="quote",
            security_or_topic="US:XNAS:AAPL",
            observed_at=NOW,
            retrieved_at=NOW,
            available_at=NOW,
            coverage="latest quote",
            payload_ref=None,
            quality="complete",
            errors=(),
        )

    snapshot = PortfolioSnapshot(
        snapshot_id="snapshot-1",
        broker="ibkr_flex",
        reported_at=NOW,
        retrieved_at=NOW,
        accounts=(AccountState(account_ref="private-account-1", balances=()),),
        positions=(),
        coverage="all configured accounts",
        complete_read=True,
        confirmed_empty=True,
    )
    assert snapshot.confirmed_empty


def test_positions_must_reference_an_account_in_the_snapshot() -> None:
    position = {
        "account_ref": "account-missing",
        "security": {"market": "US", "symbol": "AAPL", "currency": "USD"},
        "quantity": {"value": "1", "unit": "shares"},
    }

    with pytest.raises(ValidationError, match="position account_ref"):
        PortfolioSnapshot(
            snapshot_id="snapshot-account-link",
            broker="ibkr_flex",
            reported_at=NOW,
            retrieved_at=NOW,
            accounts=(AccountState(account_ref="account-present", balances=()),),
            positions=(position,),  # type: ignore[arg-type]
            coverage="one configured account",
            complete_read=True,
        )


def test_gap_attempts_and_calculation_results_are_explicit() -> None:
    gap = DataGap(
        gap_id="gap-1",
        request_id="req-1",
        required_content="point-in-time filing date",
        attempts=({"source": "fmp_stable", "attempted_at": NOW.isoformat(), "result": "missing"},),
        impact="factor cannot be validated",
        next_action="inspect original filing",
    )
    assert gap.attempts[0]["result"] == "missing"

    with pytest.raises(ValidationError, match="result_reason"):
        Calculation(
            calculation_id="calc-1",
            kind="valuation",
            input_refs=("evidence-1",),
            parameters={},
            assumptions=(),
            engine_version="0.1.0",
            result_ref=None,
            warnings=(),
        )


def test_buy_and_sell_require_disambiguated_security_identity() -> None:
    with pytest.raises(ValidationError, match="security identity"):
        Decision(
            decision_id="decision-2",
            security_or_topic="AAPL",
            as_of=NOW,
            label="buy",
            reason_refs=("evidence-1",),
            price_or_conditions=("below supported fair-value range",),
            horizon="12 months",
            risks=(),
            invalidators=(),
            memory_packet_refs=(),
        )


def test_call_result_partial_and_error_have_explicit_payloads() -> None:
    partial = CallResult(
        schema_version="1.0",
        request_id="req-1",
        operation="data.fetch",
        status="partial",
        artifacts=(),
        warnings=("one source unavailable",),
        gaps=("gap-1",),
        error=None,
    )
    assert partial.status == "partial"
    with pytest.raises(ValidationError, match="error"):
        CallResult(
            schema_version="1.0",
            request_id="req-1",
            operation="data.fetch",
            status="error",
            artifacts=(),
            warnings=(),
            gaps=(),
            error=None,
        )
