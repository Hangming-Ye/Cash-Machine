"""Shared, strict contracts for research records and CLI results."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


AwareDateTime = Annotated[datetime, AfterValidator(_timezone_aware)]
Reference = Annotated[str, Field(min_length=1)]
ExecutionOutcome = Literal["complete", "limited", "failed"]
DecisionLabel = Literal["buy", "sell", "watch", "no_opportunity", "no_factor_increment"]
MemoryContextMode = Literal["current", "historical", "review"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SecurityIdentity(ContractModel):
    market: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    exchange: str | None = None

    @property
    def canonical_id(self) -> str:
        parts = (self.market, self.exchange, self.symbol) if self.exchange else (self.market, self.symbol)
        return ":".join(parts)


class Quantity(ContractModel):
    value: Decimal | None
    unit: str = Field(min_length=1)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    identity: str | None = None
    unknown_reason: str | None = None

    @model_validator(mode="after")
    def validate_value_context(self) -> "Quantity":
        if self.value is None and not self.unknown_reason:
            raise ValueError("unknown numeric value requires unknown_reason")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("numeric value must be finite")
        if self.unit.lower() in {"currency", "money"} and self.currency is None:
            raise ValueError("currency-valued quantity requires currency")
        return self


class ResearchRequest(ContractModel):
    request_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    scope: dict[str, Any]
    horizon: str = Field(min_length=1)
    as_of: AwareDateTime
    method_tags: tuple[str, ...]
    input_refs: tuple[Reference, ...]


class WorkRecord(ContractModel):
    record_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    created_at: AwareDateTime
    owner: str = Field(min_length=1)
    input_refs: tuple[Reference, ...]
    output_refs: tuple[Reference, ...]
    outcome: ExecutionOutcome
    limitations: tuple[str, ...]
    run_manifest_ref: str | None = None


class SourceResult(ContractModel):
    source: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    security_or_topic: SecurityIdentity | str
    observed_at: AwareDateTime | None
    retrieved_at: AwareDateTime
    available_at: AwareDateTime | None
    coverage: str = Field(min_length=1)
    payload_ref: Reference | None
    quality: ExecutionOutcome
    errors: tuple[str, ...]
    unknown_reasons: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_unknown_time_reasons(self) -> "SourceResult":
        _require_unknown_reasons(self, ("observed_at", "available_at"))
        if self.quality == "failed" and not self.errors:
            raise ValueError("failed source result requires errors")
        if self.quality == "complete" and self.payload_ref is None:
            raise ValueError("complete source result requires payload_ref")
        return self


class Evidence(ContractModel):
    evidence_id: str = Field(min_length=1)
    source_ref: Reference
    locator: str = Field(min_length=1)
    published_at: AwareDateTime | None
    retrieved_at: AwareDateTime
    available_at: AwareDateTime | None
    content_kind: Literal["disclosure_fact", "third_party_view", "research_hypothesis", "calculation_result"]
    claim: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    units: tuple[str, ...]
    limitations: tuple[str, ...]
    unknown_reasons: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_published_time_reason(self) -> "Evidence":
        _require_unknown_reasons(self, ("published_at", "available_at"))
        return self


class AccountState(ContractModel):
    account_ref: str = Field(min_length=1)
    base_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    balances: tuple[Quantity, ...]


class Position(ContractModel):
    account_ref: str = Field(min_length=1)
    security: SecurityIdentity
    quantity: Quantity
    market_value: Quantity | None = None
    cost_basis: Quantity | None = None


class PortfolioSnapshot(ContractModel):
    snapshot_id: str = Field(min_length=1)
    broker: Literal["ibkr_flex", "longbridge_oauth"]
    reported_at: AwareDateTime | None
    retrieved_at: AwareDateTime
    accounts: tuple[AccountState, ...]
    positions: tuple[Position, ...]
    coverage: str = Field(min_length=1)
    complete_read: bool
    confirmed_empty: bool = False
    unknown_reasons: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reported_time_reason(self) -> "PortfolioSnapshot":
        _require_unknown_reasons(self, ("reported_at",))
        if not self.accounts:
            raise ValueError("portfolio snapshot requires at least one successfully read account")
        account_refs = {account.account_ref for account in self.accounts}
        unknown_accounts = sorted(
            {position.account_ref for position in self.positions} - account_refs
        )
        if unknown_accounts:
            raise ValueError("each position account_ref must identify an account in the snapshot")
        if not self.positions and not (self.complete_read and self.confirmed_empty):
            raise ValueError("empty positions require a complete, explicitly confirmed empty read")
        if self.confirmed_empty and self.positions:
            raise ValueError("confirmed_empty conflicts with returned positions")
        return self


class DataGap(ContractModel):
    gap_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    required_content: str = Field(min_length=1)
    attempts: tuple[dict[str, Any], ...]
    impact: str = Field(min_length=1)
    next_action: str = Field(min_length=1)


class Calculation(ContractModel):
    calculation_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    input_refs: tuple[Reference, ...]
    parameters: dict[str, Any]
    assumptions: tuple[str, ...]
    engine_version: str = Field(min_length=1)
    result_ref: Reference | None
    result_reason: str | None = None
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def explain_missing_result(self) -> "Calculation":
        if self.result_ref is None and not self.result_reason:
            raise ValueError("missing result_ref requires result_reason")
        return self


class FactorExperiment(ContractModel):
    experiment_id: str = Field(min_length=1)
    request_ref: Reference
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hypothesis: str = Field(min_length=1)
    failure_regimes: tuple[str, ...]
    expression: dict[str, Any]
    parameter_sets: tuple[dict[str, Any], ...]
    dataset_ref: Reference
    available_time_rule: str = Field(min_length=1)
    target: str = Field(min_length=1)
    horizon: str = Field(min_length=1)
    bar_interval: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    split: dict[str, Any]
    primary_metric: str = Field(min_length=1)
    metrics: dict[str, float | None]
    costs: dict[str, float | str | None]
    trial_group: str = Field(min_length=1)
    result_ref: Reference | None
    result_reason: str | None = None

    @model_validator(mode="after")
    def validate_frozen_request_and_result(self) -> "FactorExperiment":
        normalized = self.request_ref.replace("\\", "/")
        posix = PurePosixPath(normalized)
        if (
            not normalized.endswith(".json")
            or posix.is_absolute()
            or PureWindowsPath(self.request_ref).is_absolute()
            or bool(PureWindowsPath(self.request_ref).drive)
            or ".." in posix.parts
        ):
            raise ValueError("request_ref must identify the complete frozen JSON request")
        if not self.parameter_sets:
            raise ValueError("parameter_sets must preserve every planned parameter combination")
        if self.primary_metric not in self.metrics:
            raise ValueError("metrics must include primary_metric")
        if self.result_ref is None and not self.result_reason:
            raise ValueError("missing result_ref requires result_reason")
        numeric_values = list(self.metrics.values()) + [
            value for value in self.costs.values() if isinstance(value, float)
        ]
        if any(value is not None and not math.isfinite(value) for value in numeric_values):
            raise ValueError("metrics and numeric costs must contain finite values or null")
        return self


class Decision(ContractModel):
    decision_id: str = Field(min_length=1)
    security_or_topic: SecurityIdentity | str
    as_of: AwareDateTime
    label: DecisionLabel
    reason_refs: tuple[Reference, ...]
    price_or_conditions: tuple[Quantity | str, ...] | None
    price_or_conditions_reason: str | None = None
    evidence_limited: bool = False
    limitations: tuple[str, ...] = ()
    horizon: str = Field(min_length=1)
    risks: tuple[str, ...]
    invalidators: tuple[str, ...]
    previous_id: str | None = None
    memory_packet_refs: tuple[Reference, ...]
    run_manifest_ref: str | None = None

    @model_validator(mode="after")
    def explain_missing_price(self) -> "Decision":
        if self.price_or_conditions is None and not self.price_or_conditions_reason:
            raise ValueError("missing price_or_conditions requires a reason")
        if self.label in {"buy", "sell"} and not isinstance(
            self.security_or_topic, SecurityIdentity
        ):
            raise ValueError("buy and sell decisions require a disambiguated security identity")
        if self.evidence_limited and not self.limitations:
            raise ValueError("evidence_limited decision requires limitations")
        return self


class Review(ContractModel):
    review_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    decision_as_of: AwareDateTime
    review_at: AwareDateTime
    observed_outcome: str = Field(min_length=1)
    process_findings: tuple[str, ...]
    counterevidence: tuple[str, ...]
    lesson_refs: tuple[Reference, ...]

    @model_validator(mode="after")
    def validate_chronology(self) -> "Review":
        if self.review_at < self.decision_as_of:
            raise ValueError("review_at cannot precede the decision knowledge cutoff")
        return self


class TopicSummary(ContractModel):
    topic_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    known_at: AwareDateTime
    updated_at: AwareDateTime
    current_thesis: str = Field(min_length=1)
    support_refs: tuple[Reference, ...]
    opposing_refs: tuple[Reference, ...]
    changes: tuple[str, ...]
    open_questions: tuple[str, ...]
    next_checks: tuple[str, ...]
    topics: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    securities: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_version_times(self) -> "TopicSummary":
        _require_update_order(self.known_at, self.updated_at)
        _validate_retrieval_metadata(self.topics, self.methods, self.securities, self.aliases)
        return self


class Lesson(ContractModel):
    lesson_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    check_or_method: str = Field(min_length=1)
    applies_when: str = Field(min_length=1)
    source_refs: tuple[Reference, ...]
    counterexamples: tuple[str, ...]
    validity: Literal["candidate", "usable", "superseded"]
    review_condition: str = Field(min_length=1)
    known_at: AwareDateTime
    updated_at: AwareDateTime
    topics: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    securities: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    duplicate_of: str | None = None

    @model_validator(mode="after")
    def validate_version_times(self) -> "Lesson":
        _require_update_order(self.known_at, self.updated_at)
        _validate_retrieval_metadata(self.topics, self.methods, self.securities, self.aliases)
        if self.duplicate_of is not None and (not self.duplicate_of.strip() or self.duplicate_of == self.lesson_id):
            raise ValueError("duplicate_of must name a different non-empty lesson ID")
        return self


class MemoryPacket(ContractModel):
    packet_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    context_mode: MemoryContextMode
    as_of: AwareDateTime
    decision_id: str | None = None
    review_at: AwareDateTime | None = None
    selected_refs: tuple[Reference, ...]
    exclusions: tuple[str, ...]
    budget: dict[str, int]
    content_ref: Reference

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "MemoryPacket":
        if self.context_mode == "review":
            if not self.decision_id:
                raise ValueError("review context requires decision_id")
            if self.review_at is None:
                raise ValueError("review context requires review_at")
            if self.review_at < self.as_of:
                raise ValueError("review_at cannot precede as_of")
        elif self.decision_id is not None or self.review_at is not None:
            raise ValueError("decision_id and review_at are only valid in review context")
        if any(value < 0 for value in self.budget.values()):
            raise ValueError("memory budget values cannot be negative")
        return self


class ArtifactSummary(ContractModel):
    path: Reference
    type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)


class CallError(ContractModel):
    reason: Literal["unauthorized", "unsupported", "rate_limited", "empty", "stale", "conflict", "invalid", "external"]
    message: str = Field(min_length=1)


class CallResult(ContractModel):
    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    request_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    status: Literal["ok", "partial", "error"]
    artifacts: tuple[ArtifactSummary, ...]
    warnings: tuple[str, ...]
    gaps: tuple[Reference, ...]
    error: CallError | None

    @model_validator(mode="after")
    def validate_error_payload(self) -> "CallResult":
        if self.status == "error" and self.error is None:
            raise ValueError("error status requires an error payload")
        if self.status != "error" and self.error is not None:
            raise ValueError("only error status may include an error payload")
        return self


def _require_unknown_reasons(model: BaseModel, fields: tuple[str, ...]) -> None:
    reasons = getattr(model, "unknown_reasons")
    for field in fields:
        if getattr(model, field) is None and not reasons.get(field):
            raise ValueError(f"unknown {field} requires a reason")


def _validate_retrieval_metadata(*groups: tuple[str, ...]) -> None:
    if any(not isinstance(value, str) or not value.strip() for group in groups for value in group):
        raise ValueError("retrieval metadata values must be non-empty strings")


def _require_update_order(known_at: datetime, updated_at: datetime) -> None:
    if updated_at < known_at:
        raise ValueError("updated_at cannot precede known_at")
