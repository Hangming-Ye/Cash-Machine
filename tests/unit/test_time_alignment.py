from datetime import date, datetime, timedelta, timezone
import pytest
from cash_research.calculations.expression import validate_expression
from cash_research.calculations.operators import EvaluationContext, OperatorInputError, SeriesData, evaluate_expression
from cash_research.calculations.time_alignment import BarCoverage, CompanyAction, EventRevisionTable, FieldTimeMetadata, HistoricalRecord, QualificationEvidence, Session, historical_handlers
UTC = timezone.utc
IDX = tuple((datetime(2026, 1, 5, 14, 30, tzinfo=UTC) + timedelta(minutes=30 * i) for i in range(4)))

def coverage(index=IDX, sessions=None, label='bar_start'):
    interval = timedelta(minutes=30)
    if sessions is None:
        start = index[0] if label == 'bar_start' else index[0] - interval
        end = index[-1] + interval if label == 'bar_start' else index[-1]
        sessions = (Session(start, end),)
    return BarCoverage(index, interval, sessions, label, ('coverage.json',))

def table(rows, basis='other', output=None, actions=(), history='complete'):
    observed = [r.observed_at for r in rows] or [date(2026, 1, 1)]
    start, end = (min(observed), max(observed))
    q = QualificationEvidence(
        ('source.json',),
        start,
        end,
        IDX[0],
        IDX[-1],
        IDX[-1],
        history,
    )
    market_timezone = 'UTC' if type(start) is date else None
    m = FieldTimeMetadata(
        'observed',
        'available',
        'revision',
        basis,
        market_timezone,
        output,
    )
    action_coverage = None
    if output is not None and output != basis:
        action_coverage = QualificationEvidence(
            ('actions.json',),
            IDX[0],
            IDX[-1],
            IDX[0],
            IDX[-1],
            IDX[-1],
            'complete',
        )
    return EventRevisionTable(
        {'x': tuple(rows)},
        {'x': m},
        q,
        tuple(actions),
        action_coverage,
    )

def run(op, t, *, bars=None, index=IDX, field='x', **params):
    expr = {'op': op, 'args': [{'op': 'field', 'args': [], 'params': {'name': field}}], 'params': {'observed_at_field': 'observed', 'available_at_field': 'available', 'revision_field': 'revision', 'no_eligible': 'missing', **params}}
    ds = {'bar_interval': '30m', 'point_in_time_status': 'proven', 'fields': {field: {'unit': 'dimensionless', 'observed_at': 'observed', 'available_at': 'available', 'revision': 'revision'}}, 'rows': [{'timestamp': v.isoformat(), field: 0, 'observed': v.isoformat(), 'available': v.isoformat(), 'revision': 'r'} for v in index]}
    c = validate_expression(expr, dataset=ds, parameter_schema={}, parameter_sets=[{'parameter_set_id': 'p', 'bindings': {}}])
    ctx = EvaluationContext(index=index, fields={field: SeriesData(index, tuple((0 for _ in index)), index)})
    return evaluate_expression(c.root, context=ctx, parameter_set=c.parameter_sets[0], historical_handlers=historical_handlers(t, bars))

def test_backward_revision_future_and_offsets():
    rows = [HistoricalRecord('x', 10, date(2025, 12, 31), IDX[1], 'r1'), HistoricalRecord('x', 12, date(2025, 12, 31), IDX[3], 'r2')]
    assert run('asof_value', table(rows)).series.values == (None, 10, 10, 12)
    future = HistoricalRecord('x', 99, IDX[3], IDX[0], 'future')
    q = QualificationEvidence(('s',), IDX[3], IDX[3], IDX[0], IDX[-1], IDX[-1], 'complete')
    t = EventRevisionTable({'x': (future,)}, {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')}, q)
    future_result = run('asof_value', t)
    assert future_result.series.values[:3] == (None, None, None)
    assert future_result.series.available_at[-1] == IDX[3]
    a = datetime(2026, 1, 5, 23, tzinfo=timezone(timedelta(hours=8)))
    b = datetime(2026, 1, 5, 16, tzinfo=UTC)
    t = EventRevisionTable({'x': (HistoricalRecord('x', 1, a, IDX[0], 'r1'), HistoricalRecord('x', 2, b, IDX[1], 'r2'))}, {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')}, QualificationEvidence(('s',), a, b, IDX[0], IDX[-1], IDX[-1], 'complete'))
    assert run('asof_value', t).series.values[-1] == 2


def test_future_observation_does_not_change_earlier_prefix():
    base = HistoricalRecord('x', 10, IDX[0], IDX[0], 'r1')
    future = HistoricalRecord('x', 99, IDX[3], IDX[0], 'future')
    qualification = QualificationEvidence(
        ('s',),
        IDX[0],
        IDX[3],
        IDX[0],
        IDX[-1],
        IDX[-1],
        'complete',
    )
    metadata = {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')}
    baseline = EventRevisionTable({'x': (base,)}, metadata, qualification)
    extended = EventRevisionTable({'x': (base, future)}, metadata, qualification)
    assert run('asof_value', baseline).series.values[:3] == run(
        'asof_value', extended
    ).series.values[:3]

def test_conflicts_unknown_availability_and_mixed_periods_reject():
    with pytest.raises(OperatorInputError, match='conflicting'):
        table([HistoricalRecord('x', 1, date(2026, 1, 1), IDX[0], 'r1'), HistoricalRecord('x', 2, date(2026, 1, 1), IDX[0], 'r2')])
    with pytest.raises(OperatorInputError, match='unknown availability'):
        table([HistoricalRecord('x', 1, date(2026, 1, 1), None, 'r1')])
    mixed = [HistoricalRecord('x', 1, date(2026, 1, 1), IDX[0], 'r1'), HistoricalRecord('x', 2, IDX[0], IDX[1], 'r2')]
    with pytest.raises(OperatorInputError, match='mix'):
        EventRevisionTable({'x': tuple(mixed)}, {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other', 'UTC')}, QualificationEvidence(('s',), date(2026, 1, 1), date(2026, 1, 5), IDX[0], IDX[-1], IDX[-1], 'complete'))
    with pytest.raises(OperatorInputError, match='partial'):
        table([], history='partial')
    with pytest.raises(OperatorInputError, match='revision ids'):
        table([HistoricalRecord('x', 1, date(2026, 1, 1), IDX[0])])


def test_qualification_knowledge_window_is_explicit_and_enforced():
    record = HistoricalRecord('x', 1, IDX[0], IDX[0], 'r1')
    qualification = QualificationEvidence(
        ['source'],
        IDX[0],
        IDX[0],
        IDX[1],
        IDX[2],
        IDX[3],
        'complete',
        ['known finite window'],
    )
    table_value = EventRevisionTable(
        {'x': [record]},
        {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')},
        qualification,
        [],
    )
    assert isinstance(qualification.evidence_refs, tuple)
    assert isinstance(qualification.limitations, tuple)
    assert isinstance(table_value.actions, tuple)
    with pytest.raises(OperatorInputError, match='knowledge window'):
        run('asof_value', table_value, index=(IDX[0],))
    with pytest.raises(OperatorInputError, match='knowledge window'):
        run('asof_value', table_value, index=(IDX[3],))
    with pytest.raises(OperatorInputError, match='knowledge window'):
        QualificationEvidence(
            ('s',),
            IDX[0],
            IDX[0],
            IDX[1],
            IDX[3],
            IDX[2],
            'complete',
        )

def test_metadata_field_identity_is_checked():
    rows = (HistoricalRecord('x', 1, date(2026, 1, 1), IDX[0], 'r1'),)
    t = EventRevisionTable({'x': rows}, {'x': FieldTimeMetadata('different_observed', 'different_available', 'revision', 'other', 'UTC')}, QualificationEvidence(('s',), date(2026, 1, 1), date(2026, 1, 1), IDX[0], IDX[-1], IDX[-1], 'complete'))
    with pytest.raises(OperatorInputError, match='metadata'):
        run('asof_value', t)

def test_actions_apply_once_after_observation_and_raise_dependency_time():
    action = CompanyAction(IDX[2], IDX[2], 2, 'price', 'action.json')
    pre = HistoricalRecord('x', 10, IDX[0], IDX[0], 'r1')
    out = run('asof_value', table([pre], 'raw_price', 'adjusted_price', (action,)))
    assert out.series.values == (10, 10, 5, 5) and out.series.available_at[2] == IDX[2]
    post = HistoricalRecord('x', 8, IDX[3], IDX[3], 'r2')
    assert run('asof_value', table([post], 'raw_price', 'adjusted_price', (action,))).series.values[-1] == 8
    adjusted = run('asof_value', table([pre], 'adjusted_price', 'adjusted_price', (action,)))
    assert adjusted.series.values[-1] == 10
    with pytest.raises(OperatorInputError):
        CompanyAction(IDX[0], IDX[0], float('nan'), 'price', 'a')


def test_actions_respect_effective_and_known_times_volume_direction_and_identity():
    preannounced = CompanyAction(IDX[2], IDX[0], 2, 'price', 'split-preannounced')
    late_known = CompanyAction(IDX[1], IDX[2], 2, 'price', 'split-late')
    record = HistoricalRecord('x', 10, IDX[0], IDX[0], 'r1')
    result = run(
        'asof_value',
        table(
            [record],
            'raw_price',
            'adjusted_price',
            (preannounced, late_known),
        ),
    )
    assert result.series.values == (10, 10, 2.5, 2.5)
    assert result.series.available_at[1] == IDX[0]
    assert result.series.available_at[2] == IDX[2]

    volume_action = CompanyAction(IDX[1], IDX[1], 2, 'volume', 'split-volume')
    volume = run(
        'asof_value',
        table([record], 'raw_volume', 'adjusted_volume', (volume_action,)),
    )
    assert volume.series.values == (10, 20, 20, 20)
    with pytest.raises(OperatorInputError, match='duplicate'):
        table(
            [record],
            'raw_price',
            'adjusted_price',
            (preannounced, preannounced),
        )


def test_action_coverage_distinguishes_unknown_from_confirmed_empty():
    record = HistoricalRecord('x', 10, IDX[0], IDX[0], 'r1')
    metadata = FieldTimeMetadata(
        'observed',
        'available',
        'revision',
        'raw_price',
        None,
        'adjusted_price',
    )
    qualification = QualificationEvidence(
        ('events',),
        IDX[0],
        IDX[0],
        IDX[0],
        IDX[-1],
        IDX[-1],
        'complete',
    )
    with pytest.raises(OperatorInputError, match='action coverage'):
        EventRevisionTable({'x': (record,)}, {'x': metadata}, qualification)

    confirmed_empty = table([record], 'raw_price', 'adjusted_price')
    result = run('asof_value', confirmed_empty)
    assert result.series.values == (10, 10, 10, 10)
    assert confirmed_empty.evidence_refs == ('source.json', 'actions.json')


def test_same_action_evidence_can_cover_price_and_volume_without_double_apply():
    evidence_ref = 'split.json'
    actions = (
        CompanyAction(IDX[1], IDX[1], 2, 'price', evidence_ref),
        CompanyAction(IDX[1], IDX[1], 2, 'volume', evidence_ref),
    )
    qualification = QualificationEvidence(
        ('events',),
        IDX[0],
        IDX[0],
        IDX[0],
        IDX[-1],
        IDX[-1],
        'complete',
    )
    action_coverage = QualificationEvidence(
        ('actions',),
        IDX[0],
        IDX[-1],
        IDX[0],
        IDX[-1],
        IDX[-1],
        'complete',
    )
    values = EventRevisionTable(
        {
            'price': (HistoricalRecord('price', 10, IDX[0], IDX[0], 'p1'),),
            'volume': (HistoricalRecord('volume', 10, IDX[0], IDX[0], 'v1'),),
        },
        {
            'price': FieldTimeMetadata(
                'observed',
                'available',
                'revision',
                'raw_price',
                None,
                'adjusted_price',
            ),
            'volume': FieldTimeMetadata(
                'observed',
                'available',
                'revision',
                'raw_volume',
                None,
                'adjusted_volume',
            ),
        },
        qualification,
        actions,
        action_coverage,
    )
    assert run('asof_value', values, field='price').series.values[-1] == 5
    assert run('asof_value', values, field='volume').series.values[-1] == 20
    assert values.evidence_refs == ('events', 'actions', evidence_ref)
    with pytest.raises(OperatorInputError, match='duplicate'):
        EventRevisionTable(
            values.records,
            values.metadata,
            qualification,
            (actions[0], actions[0]),
            action_coverage,
        )


def test_date_period_uses_declared_market_timezone_and_cannot_be_adjusted():
    period = date(2026, 1, 5)
    available = datetime(2026, 1, 4, 16, 15, tzinfo=UTC)
    decision = datetime(2026, 1, 4, 16, 30, tzinfo=UTC)
    record = HistoricalRecord('x', 10, period, available, 'r1')
    qualification = QualificationEvidence(
        ('s',),
        period,
        period,
        available,
        decision,
        decision,
        'complete',
    )
    metadata = FieldTimeMetadata(
        'observed',
        'available',
        'revision',
        'raw_price',
        'Asia/Shanghai',
    )
    period_table = EventRevisionTable({'x': (record,)}, {'x': metadata}, qualification)
    assert run('asof_value', period_table, index=(decision,)).series.values == (10,)

    with pytest.raises(OperatorInputError, match='market timezone'):
        EventRevisionTable(
            {'x': (record,)},
            {'x': FieldTimeMetadata('observed', 'available', 'revision', 'raw_price')},
            qualification,
        )
    action = CompanyAction(decision, decision, 2, 'price', 'split')
    adjusted = EventRevisionTable(
        {'x': (record,)},
        {
            'x': FieldTimeMetadata(
                'observed',
                'available',
                'revision',
                'raw_price',
                'Asia/Shanghai',
                'adjusted_price',
            )
        },
        qualification,
        (action,),
        QualificationEvidence(
            ('actions',),
            available,
            decision,
            available,
            decision,
            decision,
            'complete',
        ),
    )
    with pytest.raises(OperatorInputError, match='date-only'):
        run('asof_value', adjusted, index=(decision,))


def test_two_fields_sharing_time_columns_select_their_own_values():
    qualification = QualificationEvidence(
        ('s',),
        IDX[0],
        IDX[0],
        IDX[0],
        IDX[-1],
        IDX[-1],
        'complete',
    )
    metadata = FieldTimeMetadata('observed', 'available', 'revision', 'other')
    values = EventRevisionTable(
        {
            'x': (HistoricalRecord('x', 10, IDX[0], IDX[0], 'x-r1'),),
            'y': (HistoricalRecord('y', 20, IDX[0], IDX[0], 'y-r1'),),
        },
        {'x': metadata, 'y': metadata},
        qualification,
    )
    assert run('asof_value', values, field='x').series.values[-1] == 10
    assert run('asof_value', values, field='y').series.values[-1] == 20

def test_bar_coverage_gaps_lunch_afterhours_and_labels():
    gap = (IDX[0], IDX[1], IDX[3])
    with pytest.raises(OperatorInputError, match='exactly match'):
        coverage(gap)
    lunch = (IDX[0], IDX[1], IDX[3])
    lunch_sessions = (Session(IDX[0], IDX[1] + timedelta(minutes=30)), Session(IDX[3], IDX[3] + timedelta(minutes=30)))
    assert coverage(lunch, lunch_sessions).expected_index == lunch
    with pytest.raises(OperatorInputError, match='exactly match'):
        coverage(IDX + (IDX[-1] + timedelta(hours=2),), (Session(IDX[0], IDX[-1] + timedelta(minutes=30)),))
    day1, day2 = date(2026, 1, 5), date(2026, 1, 6)
    sessions = (Session(datetime(2026, 1, 5, 14, 30, tzinfo=UTC), datetime(2026, 1, 5, 21, tzinfo=UTC), day1), Session(datetime(2026, 1, 6, 14, 30, tzinfo=UTC), datetime(2026, 1, 6, 21, tzinfo=UTC), day2))
    daily = (sessions[0].end, sessions[1].end)
    assert len(BarCoverage(daily, timedelta(days=1), sessions, 'bar_end', ('daily',)).bars) == 2

def test_bar_coverage_exact_labels_omissions_extras_and_session_rules():
    session = Session(datetime(2026, 1, 5, 9, 30, tzinfo=UTC), datetime(2026, 1, 5, 11, 30, tzinfo=UTC))
    starts = tuple(session.start + timedelta(minutes=30 * i) for i in range(4))
    ends = tuple(session.start + timedelta(minutes=30 * i) for i in range(1, 5))
    assert tuple(bar.label for bar in BarCoverage(starts, timedelta(minutes=30), (session,), 'bar_start', ('e',)).bars) == starts
    assert tuple(bar.label for bar in BarCoverage(ends, timedelta(minutes=30), (session,), 'bar_end', ('e',)).bars) == ends
    cases = ((starts[1:], 'bar_start'), (starts[:-1], 'bar_start'), (starts + (session.end,), 'bar_start'), (ends[1:], 'bar_end'), (ends[:-1], 'bar_end'), ((session.start,) + ends, 'bar_end'))
    for bad, label in cases:
        with pytest.raises(OperatorInputError, match='exactly match'):
            BarCoverage(tuple(bad), timedelta(minutes=30), (session,), label, ('e',))
    with pytest.raises(OperatorInputError):
        Session(IDX[0], IDX[0])
    with pytest.raises(OperatorInputError, match='trading_day'):
        Session(IDX[0], IDX[1], datetime(2026, 1, 5, tzinfo=UTC))
    with pytest.raises(OperatorInputError, match='trading_day'):
        Session(IDX[0], IDX[1], '2026-01-05')
    with pytest.raises(OperatorInputError, match='overlap'):
        coverage((IDX[0], IDX[1]), (Session(IDX[0], IDX[1] + timedelta(minutes=30)), Session(IDX[1], IDX[2])))
    day = date(2026, 1, 5)
    split = (Session(IDX[0], IDX[1], day), Session(IDX[2], IDX[3], day))
    with pytest.raises(OperatorInputError, match='one full session'):
        BarCoverage((IDX[0], IDX[2]), timedelta(days=1), split, 'bar_start', ('d',))
    weekly_start = datetime(2026, 1, 5, tzinfo=UTC)
    weekly_end = weekly_start + timedelta(days=14)
    weekly = BarCoverage([weekly_start, weekly_start + timedelta(days=7)], timedelta(days=7), [Session(weekly_start, weekly_end)], 'bar_start', ['weekly-source'])
    assert isinstance(weekly.expected_index, tuple) and len(weekly.bars) == 2

def test_event_age_counts_only_complete_retained_bars():
    event = datetime(2026, 1, 5, 14, 45, tzinfo=UTC)
    retained = tuple(datetime(2026, 1, 5, hour, minute, tzinfo=UTC) for hour, minute in ((14, 30), (15, 0), (15, 30), (16, 0)))
    bars = coverage(retained, (Session(retained[0], datetime(2026, 1, 5, 16, 30, tzinfo=UTC)),))
    decisions = (
        datetime(2026, 1, 5, 14, 50, tzinfo=UTC),
        retained[1],
        retained[2],
    )
    record = HistoricalRecord('x', 1, event, retained[0], 'r1')
    q = QualificationEvidence(('s',), event, event, retained[0], IDX[-1], IDX[-1], 'complete')
    t = EventRevisionTable({'x': (record,)}, {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')}, q)
    assert run('event_age', t, bars=bars, index=decisions, output_unit='bars').series.values == (None, 0.0, 1.0)


def test_event_age_does_not_count_lunch_or_overnight_gaps():
    lunch_event = datetime(2026, 1, 5, 11, 45, tzinfo=UTC)
    lunch_sessions = (
        Session(datetime(2026, 1, 5, 11, 30, tzinfo=UTC), datetime(2026, 1, 5, 12, 0, tzinfo=UTC)),
        Session(datetime(2026, 1, 5, 13, 0, tzinfo=UTC), datetime(2026, 1, 5, 13, 30, tzinfo=UTC)),
    )
    lunch_bars = BarCoverage(
        (lunch_sessions[0].start, lunch_sessions[1].start),
        timedelta(minutes=30),
        lunch_sessions,
        'bar_start',
        ('lunch',),
    )
    lunch_decisions = (
        lunch_sessions[0].end,
        lunch_sessions[1].start,
        lunch_sessions[1].end,
    )
    lunch_record = HistoricalRecord('x', 1, lunch_event, lunch_sessions[0].start, 'r1')
    lunch_table = EventRevisionTable(
        {'x': (lunch_record,)},
        {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')},
        QualificationEvidence(('s',), lunch_event, lunch_event, lunch_sessions[0].start, lunch_sessions[1].end, lunch_sessions[1].end, 'complete'),
    )
    assert run(
        'event_age',
        lunch_table,
        bars=lunch_bars,
        index=lunch_decisions,
        output_unit='bars',
    ).series.values == (0.0, 0.0, 1.0)
    lunch_result = run(
        'event_age',
        lunch_table,
        bars=lunch_bars,
        index=lunch_decisions,
        output_unit='bars',
    )
    assert lunch_result.series.available_at == lunch_decisions

    monday = Session(
        datetime(2026, 1, 5, 9, 30, tzinfo=UTC),
        datetime(2026, 1, 5, 16, 0, tzinfo=UTC),
        date(2026, 1, 5),
    )
    tuesday = Session(
        datetime(2026, 1, 6, 9, 30, tzinfo=UTC),
        datetime(2026, 1, 6, 16, 0, tzinfo=UTC),
        date(2026, 1, 6),
    )
    daily = BarCoverage(
        (monday.end, tuesday.end),
        timedelta(days=1),
        (monday, tuesday),
        'bar_end',
        ('daily',),
    )
    for observed in (monday.end, datetime(2026, 1, 5, 12, 0, tzinfo=UTC)):
        record = HistoricalRecord('x', 1, observed, monday.start, 'r1')
        event_table = EventRevisionTable(
            {'x': (record,)},
            {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')},
            QualificationEvidence(('s',), observed, observed, monday.start, tuesday.end, tuesday.end, 'complete'),
        )
        assert run(
            'event_age',
            event_table,
            bars=daily,
            index=(monday.end, tuesday.end),
            output_unit='bars',
        ).series.values == (0.0, 1.0)


def test_event_age_rejects_clipped_prefix_and_outside_decisions():
    event = datetime(2026, 1, 5, 14, 45, tzinfo=UTC)
    retained_start = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    retained_end = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)
    bars = coverage(
        (retained_start, retained_start + timedelta(minutes=30)),
        (Session(retained_start, retained_end),),
    )
    record = HistoricalRecord('x', 1, event, event, 'r1')
    event_table = EventRevisionTable(
        {'x': (record,)},
        {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')},
        QualificationEvidence(('s',), event, event, event, retained_end, retained_end, 'complete'),
    )
    with pytest.raises(OperatorInputError, match='predates'):
        run(
            'event_age',
            event_table,
            bars=bars,
            index=(retained_start,),
            output_unit='bars',
        )

    covered_record = HistoricalRecord('x', 1, retained_start, retained_start, 'r1')
    covered_table = EventRevisionTable(
        {'x': (covered_record,)},
        {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')},
        QualificationEvidence(('s',), retained_start, retained_start, retained_start, retained_end + timedelta(seconds=1), retained_end + timedelta(seconds=1), 'complete'),
    )
    with pytest.raises(OperatorInputError, match='outside retained'):
        run(
            'event_age',
            covered_table,
            bars=bars,
            index=(retained_end + timedelta(seconds=1),),
            output_unit='bars',
        )


def test_event_age_seconds_days_and_date_period():
    event = datetime(2026, 1, 5, 14, 45, tzinfo=UTC)
    record = HistoricalRecord('x', 1, event, IDX[1], 'r1')
    q = QualificationEvidence(('s',), event, event, IDX[0], IDX[-1], IDX[-1], 'complete')
    t = EventRevisionTable({'x': (record,)}, {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')}, q)
    seconds = run('event_age', t, index=IDX, output_unit='seconds')
    assert seconds.series.values[1] == 900
    days = run('event_age', t, index=(IDX[-1],), output_unit='days')
    assert days.series.values == (pytest.approx(0.052083333333333336),)
    before_dst = datetime.fromisoformat('2026-03-08T01:30:00-05:00')
    after_dst = datetime.fromisoformat('2026-03-08T03:30:00-04:00')
    dst_record = HistoricalRecord('x', 1, before_dst, before_dst, 'dst')
    dst_table = EventRevisionTable(
        {'x': (dst_record,)},
        {'x': FieldTimeMetadata('observed', 'available', 'revision', 'other')},
        QualificationEvidence(
            ('s',),
            before_dst,
            before_dst,
            before_dst,
            after_dst,
            after_dst,
            'complete',
        ),
    )
    dst = run('event_age', dst_table, index=(after_dst,), output_unit='seconds')
    assert dst.series.values == (3600.0,)
    assert dst.series.available_at == (after_dst,)
    dated = table([HistoricalRecord('x', 1, date(2026, 1, 5), IDX[0], 'r1')])
    with pytest.raises(OperatorInputError, match='date-only'):
        run('event_age', dated, output_unit='seconds')


def test_decision_index_must_be_chronologically_ordered():
    record = HistoricalRecord('x', 1, IDX[0], IDX[0], 'r1')
    with pytest.raises(OperatorInputError, match='unique and ordered'):
        run('asof_value', table([record]), index=(IDX[1], IDX[0]))
