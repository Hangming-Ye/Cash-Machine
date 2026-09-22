"""Qualified point-in-time alignment for historical factor inputs."""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Literal, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from cash_research.calculations.operators import EvaluationContext, EvaluationResult, HistoricalHandler, OperatorInputError, OperatorWarning, SeriesData
Basis = Literal['raw_price', 'adjusted_price', 'raw_volume', 'adjusted_volume', 'other']

@dataclass(frozen=True)
class QualificationEvidence:
    evidence_refs: tuple[str, ...]
    coverage_start: date | datetime
    coverage_end: date | datetime
    knowledge_start: datetime
    knowledge_end: datetime
    retrieved_at: datetime
    revision_history: Literal['complete', 'partial', 'unknown']
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        evidence_refs = tuple(self.evidence_refs)
        limitations = tuple(self.limitations)
        if not evidence_refs or any(not isinstance(ref, str) or not ref.strip() for ref in evidence_refs):
            raise OperatorInputError('qualification requires evidence_refs')
        if any(not isinstance(item, str) or not item.strip() for item in limitations):
            raise OperatorInputError('qualification limitations must be non-empty strings')
        object.__setattr__(self, 'evidence_refs', evidence_refs)
        object.__setattr__(self, 'limitations', limitations)
        _aware(self.knowledge_start, 'knowledge start')
        _aware(self.knowledge_end, 'knowledge end')
        _aware(self.retrieved_at, 'qualification retrieval')
        if not _utc(self.knowledge_start) <= _utc(self.knowledge_end) <= _utc(self.retrieved_at):
            raise OperatorInputError('qualification knowledge window is invalid')
        if self.revision_history != 'complete':
            raise OperatorInputError('partial or unknown revision history is not qualified')
        if type(self.coverage_start) is not type(self.coverage_end):
            raise OperatorInputError('qualification coverage is invalid')
        if isinstance(self.coverage_start, datetime):
            _aware(self.coverage_start, 'coverage start')
            _aware(self.coverage_end, 'coverage end')
            coverage_invalid = _utc(self.coverage_end) < _utc(self.coverage_start)
        elif type(self.coverage_start) is date:
            coverage_invalid = self.coverage_end < self.coverage_start
        else:
            coverage_invalid = True
        if coverage_invalid:
            raise OperatorInputError('qualification coverage is invalid')

@dataclass(frozen=True)
class FieldTimeMetadata:
    observed_at_field: str
    available_at_field: str
    revision_field: str | None
    basis: Basis
    market_timezone: str | None = None
    output_basis: Basis | None = None

    def __post_init__(self):
        if not isinstance(self.observed_at_field, str) or not self.observed_at_field.strip():
            raise OperatorInputError('field time metadata is incomplete')
        if not isinstance(self.available_at_field, str) or not self.available_at_field.strip():
            raise OperatorInputError('field time metadata is incomplete')
        if self.revision_field is not None and (
            not isinstance(self.revision_field, str) or not self.revision_field.strip()
        ):
            raise OperatorInputError('revision field must be a non-empty string')
        if self.market_timezone is not None:
            _market_zone(self.market_timezone)
        if self.basis not in {'raw_price', 'adjusted_price', 'raw_volume', 'adjusted_volume', 'other'}:
            raise OperatorInputError('unsupported value basis')
        if self.output_basis is not None and self.output_basis not in {'raw_price', 'adjusted_price', 'raw_volume', 'adjusted_volume', 'other'}:
            raise OperatorInputError('unsupported output basis')

@dataclass(frozen=True)
class HistoricalRecord:
    field: str
    value: float
    observed_at: date | datetime
    available_at: datetime | None
    revision_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.field, str) or not self.field.strip():
            raise OperatorInputError('historical field must be a non-empty string')
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not math.isfinite(self.value)
        ):
            raise OperatorInputError('historical value must be finite numeric')
        if isinstance(self.observed_at, datetime):
            _aware(self.observed_at, 'observation')
        elif type(self.observed_at) is not date:
            raise OperatorInputError('observation must be a date or aware datetime')
        if self.available_at is not None:
            _aware(self.available_at, 'availability')
        if self.revision_id is not None and (
            not isinstance(self.revision_id, str) or not self.revision_id.strip()
        ):
            raise OperatorInputError('revision id must be a non-empty string')

@dataclass(frozen=True)
class CompanyAction:
    effective_at: datetime
    available_at: datetime
    factor: float
    applies_to: Literal['price', 'volume']
    evidence_ref: str

    def __post_init__(self):
        _aware(self.effective_at, 'action effective')
        _aware(self.available_at, 'action availability')
        if (
            self.applies_to not in {'price', 'volume'}
            or not isinstance(self.evidence_ref, str)
            or not self.evidence_ref.strip()
        ):
            raise OperatorInputError('company action metadata is invalid')
        if (
            isinstance(self.factor, bool)
            or not isinstance(self.factor, (int, float))
            or not math.isfinite(self.factor)
            or self.factor <= 0
        ):
            raise OperatorInputError('action factor must be finite positive')

@dataclass(frozen=True)
class Session:
    start: datetime
    end: datetime
    trading_day: date | None = None

    def __post_init__(self):
        _aware(self.start, 'session start')
        _aware(self.end, 'session end')
        if self.trading_day is not None and type(self.trading_day) is not date:
            raise OperatorInputError('session trading_day must be a date')
        if self.end <= self.start:
            raise OperatorInputError('session bounds are invalid')

@dataclass(frozen=True)
class Bar:
    start: datetime
    end: datetime
    label: datetime
    trading_day: date | None

@dataclass(frozen=True)
class BarCoverage:
    expected_index: tuple[datetime, ...]
    interval: timedelta
    sessions: tuple[Session, ...]
    label_convention: Literal['bar_start', 'bar_end']
    evidence_refs: tuple[str, ...]
    bars: tuple[Bar, ...] = ()

    def __post_init__(self):
        if self.interval <= timedelta(0):
            raise OperatorInputError('bar interval must be positive')
        if self.label_convention not in {'bar_start', 'bar_end'}:
            raise OperatorInputError('bar label convention is invalid')
        if not self.evidence_refs or any(not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs):
            raise OperatorInputError('bar coverage metadata is incomplete')
        expected_index = tuple(self.expected_index)
        sessions = tuple(self.sessions)
        evidence_refs = tuple(self.evidence_refs)
        object.__setattr__(self, 'expected_index', expected_index)
        object.__setattr__(self, 'sessions', sessions)
        object.__setattr__(self, 'evidence_refs', evidence_refs)
        if not sessions:
            raise OperatorInputError('bar coverage requires sessions')
        for value in expected_index:
            _aware(value, 'bar timestamp')
        if len(set(expected_index)) != len(expected_index) or tuple(sorted(expected_index)) != expected_index:
            raise OperatorInputError('bar timestamps must be unique and ordered')
        ordered = tuple(sorted(sessions, key=lambda s: s.start))
        if any(left.end > right.start for left, right in zip(ordered, ordered[1:])):
            raise OperatorInputError('sessions overlap')
        generated: list[Bar] = []
        if self.interval == timedelta(days=1):
            days = [session.trading_day for session in ordered]
            if any(day is None for day in days) or len(set(days)) != len(days):
                raise OperatorInputError('daily coverage requires one full session per explicit trading day')
        for session in ordered:
            if self.interval == timedelta(days=1):
                label = session.start if self.label_convention == 'bar_start' else session.end
                generated.append(Bar(session.start, session.end, label, session.trading_day))
                continue
            duration = session.end - session.start
            if duration % self.interval:
                raise OperatorInputError('session duration must be an exact interval multiple')
            cursor = session.start
            while cursor < session.end:
                bar_end = cursor + self.interval
                label = cursor if self.label_convention == 'bar_start' else bar_end
                generated.append(Bar(cursor, bar_end, label, session.trading_day))
                cursor = bar_end
        labels = tuple(bar.label for bar in generated)
        if expected_index != labels:
            raise OperatorInputError('expected bar index must exactly match complete generated bars')
        object.__setattr__(self, 'sessions', ordered)
        object.__setattr__(self, 'bars', tuple(generated))

@dataclass(frozen=True)
class EventRevisionTable:
    records: Mapping[str, tuple[HistoricalRecord, ...]]
    metadata: Mapping[str, FieldTimeMetadata]
    qualification: QualificationEvidence
    actions: tuple[CompanyAction, ...] = ()
    action_coverage: QualificationEvidence | None = None

    def __post_init__(self):
        if not isinstance(self.records, Mapping) or not isinstance(self.metadata, Mapping):
            raise OperatorInputError('records and metadata must be mappings')
        try:
            records = {key: tuple(value) for key, value in self.records.items()}
        except TypeError as exc:
            raise OperatorInputError('record collections must be iterable') from exc
        metadata = dict(self.metadata)
        actions = tuple(self.actions)
        conversion_requested = any(
            item.output_basis is not None and item.output_basis != item.basis
            for item in metadata.values()
            if isinstance(item, FieldTimeMetadata)
        )
        if conversion_requested and self.action_coverage is None:
            raise OperatorInputError('basis conversion requires qualified action coverage')
        if self.action_coverage is not None and not isinstance(
            self.action_coverage, QualificationEvidence
        ):
            raise OperatorInputError('action coverage has an invalid type')
        if set(records) != set(metadata):
            raise OperatorInputError('field metadata must match record fields')
        for field, rows in records.items():
            if not isinstance(field, str) or not field.strip():
                raise OperatorInputError('record field names must be non-empty strings')
            meta = metadata[field]
            if not isinstance(meta, FieldTimeMetadata):
                raise OperatorInputError('field metadata has an invalid type')
            if any(not isinstance(row, HistoricalRecord) for row in rows):
                raise OperatorInputError('historical rows have an invalid type')
            if any(row.field != field for row in rows):
                raise OperatorInputError('record field identity mismatch')
            if any(row.available_at is None for row in rows):
                raise OperatorInputError('complete revision history cannot contain unknown availability')
            if meta.revision_field is not None and any(row.revision_id is None for row in rows):
                raise OperatorInputError('declared revision field requires revision ids')
            kinds = {datetime if isinstance(row.observed_at, datetime) else date for row in rows}
            if len(kinds) > 1:
                raise OperatorInputError('one field cannot mix period dates and event instants')
            if kinds == {date}:
                _market_zone(meta.market_timezone)
            _validate_conflicts(rows)
            _validate_coverage(rows, self.qualification)
        for action in actions:
            if not isinstance(action, CompanyAction):
                raise OperatorInputError('company actions have an invalid type')
        identity_keys = [
            (action.evidence_ref, action.applies_to, _utc(action.effective_at))
            for action in actions
        ]
        effective_keys = [
            (_utc(action.effective_at), action.applies_to)
            for action in actions
        ]
        if (
            len(set(identity_keys)) != len(identity_keys)
            or len(set(effective_keys)) != len(effective_keys)
        ):
            raise OperatorInputError('duplicate company action identity')
        object.__setattr__(self, 'records', MappingProxyType(records))
        object.__setattr__(self, 'metadata', MappingProxyType(metadata))
        object.__setattr__(self, 'actions', actions)

    @property
    def evidence_refs(self):
        refs = self.qualification.evidence_refs
        if self.action_coverage is not None:
            refs += self.action_coverage.evidence_refs
        refs += tuple(action.evidence_ref for action in self.actions)
        return tuple(dict.fromkeys(refs))

def historical_handlers(table: EventRevisionTable, bar_coverage: BarCoverage | None=None) -> dict[str, HistoricalHandler]:

    def handler(node, children, params, context):
        _validate_decision_index(context.index)
        child = node.args[0]
        field = child.parameter('name')
        if not isinstance(field, str) or field not in table.records:
            raise OperatorInputError('historical source field unavailable')
        meta = table.metadata[field]
        if params.get('observed_at_field') != meta.observed_at_field or params.get('available_at_field') != meta.available_at_field or params.get('revision_field') != meta.revision_field:
            raise OperatorInputError('node time metadata does not match qualified field metadata')
        values = []
        times = []
        warnings = []
        for decision in context.index:
            _validate_knowledge_decision(decision, table.qualification)
            eligible = [
                record
                for record in table.records[field]
                if _utc(record.available_at) <= _utc(decision)
                and _not_future(record.observed_at, decision, meta.market_timezone)
            ]
            if not eligible:
                if params.get('no_eligible') == 'reject':
                    raise OperatorInputError('no eligible historical value')
                values.append(None)
                times.append(None)
                warnings.append(OperatorWarning(node.op, decision, 'no_eligible_history'))
                continue
            record = _latest(eligible)
            if node.op == 'asof_value':
                value, available = _value(
                    record,
                    meta,
                    table.actions,
                    table.action_coverage,
                    decision,
                )
            else:
                value, available = _age(record, decision, params.get('output_unit'), bar_coverage)
            values.append(value)
            times.append(available)
        return EvaluationResult(SeriesData(context.index, tuple(values), tuple(times), False), tuple(warnings))
    return {'asof_value': handler, 'event_age': handler}

def _validate_conflicts(rows):
    seen = {}
    for r in rows:
        key = (r.observed_at, r.available_at)
        if key in seen and seen[key] != r.value:
            raise OperatorInputError('conflicting revisions share observation and availability')
        seen[key] = r.value

def _validate_coverage(rows, q):
    for r in rows:
        key = r.observed_at
        if isinstance(key, datetime) and isinstance(q.coverage_start, datetime):
            inside = _utc(q.coverage_start) <= _utc(key) <= _utc(q.coverage_end)
        elif isinstance(key, date) and (not isinstance(key, datetime)) and (type(q.coverage_start) is date):
            inside = q.coverage_start <= key <= q.coverage_end
        else:
            raise OperatorInputError('coverage type does not match observation type')
        if not inside:
            raise OperatorInputError('record falls outside qualified coverage')

def _latest(rows):

    def key(r):
        observed = _utc(r.observed_at) if isinstance(r.observed_at, datetime) else r.observed_at
        return (observed, r.available_at)
    return max(rows, key=key)

def _value(record, meta, actions, action_coverage, decision):
    target = meta.output_basis or meta.basis
    if target == meta.basis:
        return (record.value, _record_usable_at(record))
    pair = (meta.basis, target)
    if pair not in {('raw_price', 'adjusted_price'), ('raw_volume', 'adjusted_volume')}:
        raise OperatorInputError('unsupported basis conversion')
    if not isinstance(record.observed_at, datetime):
        raise OperatorInputError('date-only observation cannot be action-adjusted')
    _validate_action_coverage(record.observed_at, decision, action_coverage)
    observation = _utc(record.observed_at)
    decision_utc = _utc(decision)
    action_kind = 'price' if 'price' in meta.basis else 'volume'
    used = [
        action
        for action in actions
        if action.applies_to == action_kind
        and observation < _utc(action.effective_at) <= decision_utc
        and _utc(action.available_at) <= decision_utc
    ]
    result = record.value
    for action in used:
        result = result / action.factor if 'price' in meta.basis else result * action.factor
    if not math.isfinite(result):
        raise OperatorInputError('action adjustment produced nonfinite output')
    dependency_times = [_record_usable_at(record)]
    for action in used:
        dependency_times.extend((action.effective_at, action.available_at))
    return (result, max(dependency_times, key=_utc))

def _age(record, decision, unit, bars):
    if not isinstance(record.observed_at, datetime):
        raise OperatorInputError('date-only period cannot produce elapsed event age')
    if unit == 'seconds':
        return ((_utc(decision) - _utc(record.observed_at)).total_seconds(), decision)
    if unit == 'days':
        elapsed = (_utc(decision) - _utc(record.observed_at)).total_seconds()
        return (elapsed / 86400, decision)
    if bars is None:
        raise OperatorInputError('bar age requires explicit bar coverage')
    first_start = bars.bars[0].start
    last_end = bars.bars[-1].end
    if record.observed_at < first_start:
        raise OperatorInputError('event predates retained bar history')
    if decision < first_start or decision > last_end:
        raise OperatorInputError('decision falls outside retained bar coverage')
    boundaries = tuple(sorted({bar.start for bar in bars.bars} | {bar.end for bar in bars.bars}))
    anchor = next((boundary for boundary in boundaries if boundary >= record.observed_at), None)
    if anchor is None:
        raise OperatorInputError('event falls outside retained bar coverage')
    if decision < anchor:
        return (None, decision)
    complete_bars = sum(
        1
        for bar in bars.bars
        if bar.start >= anchor and bar.end <= decision
    )
    return (float(complete_bars), decision)

def _not_future(value, decision, market_timezone):
    if isinstance(value, datetime):
        return _utc(value) <= _utc(decision)
    zone = _market_zone(market_timezone)
    return value <= decision.astimezone(zone).date()


def _record_usable_at(record):
    if isinstance(record.observed_at, datetime):
        return max((record.observed_at, record.available_at), key=_utc)
    return record.available_at


def _market_zone(name):
    if not isinstance(name, str) or not name.strip():
        raise OperatorInputError('date-period fields require a market timezone')
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise OperatorInputError('market timezone is invalid') from exc


def _validate_knowledge_decision(decision, qualification):
    decision_utc = _utc(decision)
    if not _utc(qualification.knowledge_start) <= decision_utc <= _utc(qualification.knowledge_end):
        raise OperatorInputError('decision falls outside qualified knowledge window')


def _validate_action_coverage(observed_at, decision, coverage):
    if coverage is None:
        raise OperatorInputError('basis conversion requires qualified action coverage')
    if not isinstance(coverage.coverage_start, datetime):
        raise OperatorInputError('action coverage must use aware instant bounds')
    observed_utc = _utc(observed_at)
    decision_utc = _utc(decision)
    if not (
        _utc(coverage.coverage_start) <= observed_utc
        and _utc(coverage.coverage_end) >= decision_utc
        and _utc(coverage.knowledge_start) <= observed_utc
        and _utc(coverage.knowledge_end) >= decision_utc
    ):
        raise OperatorInputError('action coverage does not span observation through decision')


def _validate_decision_index(index):
    previous = None
    for decision in index:
        _aware(decision, 'decision')
        current = _utc(decision)
        if previous is not None and current <= previous:
            raise OperatorInputError('decision index must be unique and ordered')
        previous = current

def _utc(value):
    return value.astimezone(timezone.utc)

def _aware(value, label):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperatorInputError(f'{label} must be timezone-aware')
