"""Frozen, hand-calculated contracts for the future pure valuation engine."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

import pytest

from cash_research.models import Calculation, Quantity
from cash_research.calculations.valuation import ValuationError, calculate_valuation


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PATH = ROOT / "fixtures" / "valuation" / "expected.json"
REQUEST_PATH = ROOT / "fixtures" / "requests" / "valuation.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return _load(EXPECTED_PATH)


def _decimal(value: object) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("finite_decimal_required")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("finite_decimal_required") from exc
    if not result.is_finite():
        raise ValueError("finite_decimal_required")
    return result


def _quantity_value(quantity: Mapping[str, object], policy: Mapping[str, object]) -> Decimal:
    value = _decimal(quantity.get("value"))
    unit = str(quantity.get("unit", ""))
    if unit not in policy:
        raise ValueError("unsupported_unit")
    unit_currency = policy[unit]["currency"]  # type: ignore[index]
    if quantity.get("currency") != unit_currency:
        raise ValueError("unit_currency_mismatch")
    Quantity.model_validate(quantity)
    return value


def _base_value(quantity: Mapping[str, object], policy: Mapping[str, object]) -> Decimal:
    return _quantity_value(quantity, policy) * _decimal(policy[str(quantity["unit"])]["base_scale"])  # type: ignore[index]


def _assert_close(actual: Decimal, expected: object, precision: Mapping[str, object]) -> None:
    target = _decimal(expected)
    absolute = _decimal(precision["absolute_tolerance"])
    relative = _decimal(precision["relative_tolerance"])
    assert abs(actual - target) <= max(absolute, relative * abs(target))


def _dcf(cash_flows: list[Mapping[str, object]], rate: object, growth: object) -> Decimal:
    r = _decimal(rate)
    g = _decimal(growth)
    if g >= r:
        raise ValueError("terminal_growth_must_be_below_discount_rate")
    periods = [int(item["period"]) for item in cash_flows]
    assert periods == list(range(1, len(periods) + 1)), "fixture uses explicit year-end timing"
    amounts = [_decimal(item["amount"]["value"]) for item in cash_flows]  # type: ignore[index]
    terminal = amounts[-1] * (Decimal(1) + g) / (r - g)
    return sum(
        (amount / ((Decimal(1) + r) ** period) for period, amount in zip(periods, amounts)),
        Decimal(0),
    ) + terminal / ((Decimal(1) + r) ** periods[-1])


def _assert_rejects(error: str, function: object, *args: object) -> None:
    with pytest.raises(ValueError, match=f"^{error}$"):
        function(*args)  # type: ignore[operator]


def test_api_contract_is_bounded_and_all_methods_are_represented(contract: dict[str, Any]) -> None:
    api = contract["api_contract"]
    assert api["future_signature"] == (
        "calculate_valuation(request: Mapping[str, object]) -> Mapping[str, object]"
    )
    assert set(api["methods"]) == {
        "dcf_fcff",
        "dcf_fcfe",
        "equity_multiples",
        "enterprise_multiples",
        "ev_equity_bridge",
        "sum_of_parts",
        "asset_value",
    }
    represented = {case["request"]["method"] for case in contract["cases"].values()}
    assert represented == set(api["methods"])
    assert contract["engine_status"] == "implemented_by_T030"

    for case in contract["cases"].values():
        request = case["request"]
        assert set(api["required_common_fields"]) <= set(request)
        assert not ({"decision", "decision_label", "recommendation"} & set(case["expected"]))
        assert case["expected"]["currency"] == request["currency"]
        for assumption in request["assumptions"]:
            assert assumption["reason"]
            assert assumption["source_refs"]
            for ref in assumption["source_refs"]:
                assert (ROOT / ref).is_file(), ref


def test_fixture_request_uses_workflow_evidence_capture_and_real_fixture_refs(
    contract: dict[str, Any],
) -> None:
    request = _load(REQUEST_PATH)
    canonical = contract["cases"]["dcf_fcff"]["request"]
    assert request["evidence_refs"] == ["{{evidence_id}}"]
    assert "not the source of the numeric assumptions" in request["evidence_use"]
    assert request["request_id"] == "fixture-valuation-fcff"
    for field in contract["api_contract"]["required_common_fields"]:
        if field == "request_id":
            continue
        assert request[field] == canonical[field]

    refs = set(request["financial_refs"])
    refs.update(ref for item in request["assumptions"] for ref in item["source_refs"])
    for ref in refs:
        assert (ROOT / ref).is_file(), ref

    source = _load(ROOT / "fixtures" / "valuation" / "financial-inputs.json")
    source_base_fcff = source["method_inputs"]["fcff"]["base"]
    request_base_fcff = [item["amount"]["value"] for item in request["scenarios"]["base"]["fcff"]]
    assert request_base_fcff == source_base_fcff
    assert request["share_basis"]["diluted_shares"] == source["values"]["diluted_shares"]


def test_quantities_have_explicit_compatible_scales_and_fit_shared_model(
    contract: dict[str, Any],
) -> None:
    policy = contract["api_contract"]["amount_unit_policy"]
    assert policy["USD_million"]["base_scale"] == "1000000"
    assert policy["million_shares"]["base_scale"] == "1000000"
    assert _decimal(policy["USD_million"]["base_scale"]) / _decimal(
        policy["million_shares"]["base_scale"]
    ) == Decimal(1)
    assert contract["api_contract"]["currency_policy"] == {
        "accepted_codes": "runtime ISO 4217 codes",
        "fixture_codes": ["USD", "EUR"],
        "fixture_codes_are_examples_not_engine_whitelist": True,
        "amount_unit_templates": ["{currency}", "{currency}_million"],
    }

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            if {"value", "unit", "currency", "identity"} <= set(value):
                _quantity_value(value, policy)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for case in contract["cases"].values():
        visit(case["request"])

    financials = _load(ROOT / "fixtures" / "valuation" / "financial-inputs.json")
    for quantity in financials["values"].values():
        _quantity_value(quantity, policy)


def test_request_can_be_recorded_as_a_calculation_without_claiming_engine_output(
    contract: dict[str, Any],
) -> None:
    request = contract["cases"]["dcf_fcff"]["request"]
    calculation = Calculation(
        calculation_id="calc_fixture_valuation_contract",
        kind="valuation_dcf_fcff",
        input_refs=tuple(request["financial_refs"]),
        parameters=request,
        assumptions=tuple(item["reason"] for item in request["assumptions"]),
        engine_version="not-implemented-t029",
        result_ref=None,
        result_reason="T029 freezes inputs and expected arithmetic before T030 implements the engine",
        warnings=("synthetic_fixture_only",),
    )
    assert calculation.result_ref is None
    assert calculation.parameters["method"] == "dcf_fcff"


def test_fcff_scenarios_bridge_once_and_representative_sensitivity(
    contract: dict[str, Any],
) -> None:
    case = contract["cases"]["dcf_fcff"]
    request = case["request"]
    precision = request["precision"]
    assert case["fixture_scope"] == "full_scenario_valuation"
    assert set(request["scenarios"]) == {"bear", "base", "bull"}
    assert request["method_inputs"]["forecast_timing"] == "year_end"
    bridge = request["method_inputs"]["bridge"]
    assert request["method_inputs"]["bridge_convention"] == (
        "debt_and_minority_subtracted_cash_added_other_adjustments_signed"
    )
    shares = _decimal(request["share_basis"]["diluted_shares"]["value"])

    for name, scenario in request["scenarios"].items():
        enterprise_value = _dcf(scenario["fcff"], scenario["wacc"], scenario["terminal_growth"])
        equity_value = (
            enterprise_value
            - _decimal(bridge["debt"]["value"])
            + _decimal(bridge["cash"]["value"])
            - _decimal(bridge["minority_interest"]["value"])
        )
        expected = case["expected"]["scenario_results"][name]
        _assert_close(enterprise_value, expected["enterprise_value"], precision)
        _assert_close(equity_value, expected["equity_value"], precision)
        _assert_close(equity_value / shares, expected["per_share_value"], precision)

    base_cash_flows = request["scenarios"]["base"]["fcff"]
    for rate, row in case["expected"]["sensitivity_per_share"].items():
        for growth, expected in row.items():
            equity = (
                _dcf(base_cash_flows, rate, growth)
                - _decimal(bridge["debt"]["value"])
                + _decimal(bridge["cash"]["value"])
                - _decimal(bridge["minority_interest"]["value"])
            )
            _assert_close(equity / shares, expected, precision)


def test_fcfe_is_discounted_to_equity_without_second_debt_subtraction(
    contract: dict[str, Any],
) -> None:
    case = contract["cases"]["dcf_fcfe"]
    request = case["request"]
    scenario = request["scenarios"]["base"]
    equity = _dcf(scenario["fcfe"], scenario["cost_of_equity"], scenario["terminal_growth"])
    shares = _decimal(request["share_basis"]["diluted_shares"]["value"])
    assert request["method_inputs"]["bridge"] is None
    assert case["expected"]["debt_subtracted_after_fcfe"] is False
    _assert_close(equity, case["expected"]["equity_value"], request["precision"])
    _assert_close(equity / shares, case["expected"]["per_share_value"], request["precision"])


def test_equity_and_enterprise_multiples_keep_valuation_levels_distinct(
    contract: dict[str, Any],
) -> None:
    equity_case = contract["cases"]["equity_multiples"]
    enterprise_case = contract["cases"]["enterprise_multiples"]

    eq_request = equity_case["request"]
    eq_scenario = eq_request["scenarios"]["base"]
    equity = _decimal(eq_scenario["denominator"]["value"]) * _decimal(eq_scenario["multiple"])
    assert eq_request["method_inputs"]["valuation_level"] == "equity"
    assert eq_request["method_inputs"]["peer_justification"]
    _assert_close(equity, equity_case["expected"]["equity_value"], eq_request["precision"])

    ev_request = enterprise_case["request"]
    ev_scenario = ev_request["scenarios"]["base"]
    enterprise = _decimal(ev_scenario["denominator"]["value"]) * _decimal(ev_scenario["multiple"])
    bridge = ev_request["method_inputs"]["bridge"]
    assert ev_request["method_inputs"]["bridge_convention"] == (
        "debt_and_minority_subtracted_cash_added_other_adjustments_signed"
    )
    equity_from_ev = (
        enterprise
        - _decimal(bridge["debt"]["value"])
        + _decimal(bridge["cash"]["value"])
        - _decimal(bridge["minority_interest"]["value"])
    )
    assert ev_request["method_inputs"]["valuation_level"] == "enterprise"
    _assert_close(enterprise, enterprise_case["expected"]["enterprise_value"], ev_request["precision"])
    _assert_close(equity_from_ev, enterprise_case["expected"]["equity_value"], ev_request["precision"])

    peers = _load(ROOT / "fixtures" / "valuation" / "peer-set.json")
    assert peers["peer_justification"]
    assert sorted(_decimal(peer["pe"]) for peer in peers["peers"])[1] == Decimal(15)
    assert sorted(_decimal(peer["ev_to_ebitda"]) for peer in peers["peers"])[1] == Decimal(8)


def test_signed_ev_bridge_is_applied_once_and_redundant_net_debt_is_rejected(
    contract: dict[str, Any],
) -> None:
    case = contract["cases"]["ev_equity_bridge"]
    request = case["request"]
    enterprise = _decimal(request["scenarios"]["base"]["enterprise_value"]["value"])
    bridge = request["method_inputs"]["bridge"]
    assert request["method_inputs"]["bridge_convention"] == (
        "debt_and_minority_subtracted_cash_added_other_adjustments_signed"
    )
    equity = (
        enterprise
        - _decimal(bridge["debt"]["value"])
        + _decimal(bridge["cash"]["value"])
        - _decimal(bridge["minority_interest"]["value"])
        + sum(
            (_decimal(item["amount"]["value"]) for item in bridge["other_adjustments"]),
            Decimal(0),
        )
    )
    shares = _decimal(request["share_basis"]["diluted_shares"]["value"])
    _assert_close(equity, case["expected"]["equity_value"], request["precision"])
    _assert_close(equity / shares, case["expected"]["per_share_value"], request["precision"])

    invalid = contract["invalid_cases"]["redundant_net_debt_and_cash"]

    def validate_bridge(value: Mapping[str, object]) -> None:
        if "net_debt" in value and ({"debt", "cash"} & set(value)):
            raise ValueError("redundant_bridge_inputs")

    _assert_rejects(invalid["expected_error"], validate_bridge, invalid["bridge"])


def test_sum_of_parts_uses_dated_fx_and_segment_specific_methods(contract: dict[str, Any]) -> None:
    case = contract["cases"]["sum_of_parts"]
    request = case["request"]
    segments = request["scenarios"]["base"]["segments"]
    segment_a_ev = _decimal(segments[0]["denominator"]["value"]) * _decimal(segments[0]["multiple"])
    common_bridge = request["method_inputs"]["common_bridge"]
    assert request["method_inputs"]["bridge_convention"] == (
        "debt_and_minority_subtracted_cash_added_other_adjustments_signed"
    )
    segment_a_equity = (
        segment_a_ev
        - _decimal(common_bridge["debt"]["value"])
        + _decimal(common_bridge["cash"]["value"])
        - _decimal(common_bridge["minority_interest"]["value"])
        + sum(
            (_decimal(item["amount"]["value"]) for item in common_bridge["other_adjustments"]),
            Decimal(0),
        )
    )
    fx = request["method_inputs"]["fx"]["EURUSD"]
    assert fx["as_of"] == request["valuation_date"]
    assert (ROOT / fx["source_ref"]).is_file()
    segment_b_equity = (
        _decimal(segments[1]["denominator"]["value"])
        * _decimal(segments[1]["multiple"])
        * _decimal(fx["rate"])
    )
    expected = case["expected"]
    _assert_close(segment_a_equity, expected["segment_values_reporting_currency"]["A_equity_USD"], request["precision"])
    _assert_close(segment_b_equity, expected["segment_values_reporting_currency"]["B_equity_USD"], request["precision"])
    _assert_close(segment_a_equity + segment_b_equity, expected["equity_value"], request["precision"])

    invalid = contract["invalid_cases"]["missing_fx"]

    def require_fx(value: Mapping[str, object]) -> None:
        if value["from_currency"] != value["to_currency"] and value["fx"] is None:
            raise ValueError("explicit_dated_fx_required")

    _assert_rejects(invalid["expected_error"], require_fx, invalid)


def test_asset_value_never_fills_missing_amounts_with_zero(contract: dict[str, Any]) -> None:
    case = contract["cases"]["asset_value"]
    request = case["request"]
    scenario = request["scenarios"]["base"]
    assets = sum((_decimal(item["amount"]["value"]) for item in scenario["assets"]), Decimal(0))
    liabilities = sum(
        (_decimal(item["amount"]["value"]) for item in scenario["liabilities"]), Decimal(0)
    )
    net_assets = assets - liabilities
    shares = _decimal(request["share_basis"]["diluted_shares"]["value"])
    assert request["method_inputs"]["missing_value_policy"] == "reject_never_fill_zero"
    _assert_close(net_assets, case["expected"]["net_asset_value"], request["precision"])
    _assert_close(net_assets / shares, case["expected"]["per_share_value"], request["precision"])

    invalid = contract["invalid_cases"]["missing_asset_value"]

    def require_amount(value: Mapping[str, object]) -> None:
        if value["value"] is None:
            raise ValueError("missing_values_not_zero")

    _assert_rejects(invalid["expected_error"], require_amount, invalid)


def test_mixed_base_currency_and_million_share_scales_normalize_before_division(
    contract: dict[str, Any],
) -> None:
    case = contract["scale_normalization_case"]
    policy = contract["api_contract"]["amount_unit_policy"]
    equity_base_units = _base_value(case["equity_value"], policy)
    share_base_units = _base_value(case["diluted_shares"], policy)
    per_share = equity_base_units / share_base_units
    _assert_close(per_share, case["expected_per_share"]["value"], contract["api_contract"]["precision"])
    assert per_share == Decimal("13.3")


def test_nonpositive_multiple_denominator_is_inapplicable_not_a_price(
    contract: dict[str, Any],
) -> None:
    case = contract["cases"]["negative_denominator"]
    denominator = _decimal(case["request"]["scenarios"]["base"]["denominator"]["value"])
    assert denominator < 0
    assert case["expected"] == {
        "applicable": False,
        "value": None,
        "reason": "negative denominator makes EV/EBITDA not meaningful",
        "currency": "USD",
        "warnings": ["inappropriate_negative_denominator"],
    }


def test_invalid_numeric_units_growth_and_shares_are_explicitly_rejected(
    contract: dict[str, Any],
) -> None:
    invalid = contract["invalid_cases"]
    policy = contract["api_contract"]["amount_unit_policy"]
    _assert_rejects(invalid["boolean_amount"]["expected_error"], _decimal, invalid["boolean_amount"]["value"])
    _assert_rejects(invalid["nonfinite_amount"]["expected_error"], _decimal, invalid["nonfinite_amount"]["value"])
    _assert_rejects(
        invalid["currency_unit_mismatch"]["expected_error"],
        _quantity_value,
        invalid["currency_unit_mismatch"],
        policy,
    )
    growth = invalid["terminal_growth_not_below_discount"]
    _assert_rejects(
        growth["expected_error"],
        _dcf,
        [{"period": 1, "amount": {"value": "1"}}],
        growth["wacc"],
        growth["terminal_growth"],
    )

    def validate_multiple_denominator(value: object) -> None:
        if _decimal(value) <= 0:
            raise ValueError("nonpositive_denominator_inapplicable")

    zero_denominator = invalid["zero_multiple_denominator"]
    _assert_rejects(
        zero_denominator["expected_error"],
        validate_multiple_denominator,
        zero_denominator["value"],
    )

    def validate_shares(value: Mapping[str, object]) -> None:
        if _decimal(value["value"]) <= 0:
            raise ValueError("diluted_shares_must_be_positive")

    zero = invalid["zero_diluted_shares"]
    _assert_rejects(zero["expected_error"], validate_shares, zero["share_basis"])


def test_share_date_and_full_scenario_scope_rules_are_unambiguous(contract: dict[str, Any]) -> None:
    invalid = contract["invalid_cases"]
    mismatch = invalid["share_date_mismatch"]

    def validate_share_date(value: Mapping[str, object]) -> None:
        if value["valuation_date"] != value["share_as_of"] and not value["alignment_reason"]:
            raise ValueError("share_basis_date_requires_alignment")

    _assert_rejects(mismatch["expected_error"], validate_share_date, mismatch)
    for case in contract["cases"].values():
        share_basis = case["request"]["share_basis"]
        assert share_basis["as_of"] == case["request"]["valuation_date"]
        assert _decimal(share_basis["diluted_shares"]["value"]) > 0

    scoped = invalid["missing_scenario_scope"]

    def validate_full_scenarios(value: Mapping[str, object]) -> None:
        if value["full_valuation"] and set(value["scenarios"]) != set(value["required"]):
            raise ValueError("scenario_scope_incomplete_for_full_valuation")

    _assert_rejects(scoped["expected_error"], validate_full_scenarios, scoped)
    assert contract["cases"]["dcf_fcff"]["fixture_scope"] == "full_scenario_valuation"
    assert all(
        case["fixture_scope"] != "full_scenario_valuation"
        for name, case in contract["cases"].items()
        if name != "dcf_fcff"
    )


def _engine_request(contract: dict[str, Any], case_name: str) -> dict[str, Any]:
    return deepcopy(contract["cases"][case_name]["request"])


def test_engine_matches_all_frozen_method_expectations(contract: dict[str, Any]) -> None:
    numeric_fields = {
        "enterprise_value",
        "equity_value",
        "net_asset_value",
        "per_share_value",
    }
    for name, case in contract["cases"].items():
        result = calculate_valuation(case["request"])
        assert result["request_id"] == case["request"]["request_id"]
        assert result["method"] == case["request"]["method"]
        assert result["scope"] == case["request"]["scope"]
        assert result["parameters"] == case["request"]
        assert result["assumptions"] == case["request"]["assumptions"]
        assert result["precision"] == case["request"]["precision"]

        if name == "dcf_fcff":
            for scenario_name, expected in case["expected"]["scenario_results"].items():
                actual = result["scenario_results"][scenario_name]
                for field in numeric_fields & set(expected):
                    _assert_close(Decimal(actual[field]), expected[field], case["request"]["precision"])
            actual_grid = result["sensitivity"]["per_share"]
            for rate, row in case["expected"]["sensitivity_per_share"].items():
                for growth, expected in row.items():
                    _assert_close(Decimal(actual_grid[rate][growth]), expected, case["request"]["precision"])
            continue

        actual = result["scenario_results"]["base"]
        expected = case["expected"]
        if expected.get("applicable") is False:
            assert actual["applicable"] is False
            assert actual["value"] is None
            assert actual["reason"] == expected["reason"]
            assert actual["warnings"] == expected["warnings"]
            assert result["status"] == "limited"
            continue
        for field in numeric_fields & set(expected):
            _assert_close(Decimal(actual[field]), expected[field], case["request"]["precision"])
        assert actual["currency"] == expected["currency"]


def test_engine_is_deterministic_and_preserves_every_input_reference(contract: dict[str, Any]) -> None:
    request = _load(REQUEST_PATH)
    first = calculate_valuation(request)
    second = calculate_valuation(deepcopy(request))
    assert first == second
    assert first["parameters"] == request
    assert first["input_refs"] == [
        "fixtures/valuation/financial-inputs.json",
        "fixtures/valuation/expected.json",
        "{{evidence_id}}",
    ]
    serialized = json.dumps(first, default=str)
    assert '"decision"' not in serialized
    assert '"decision_label"' not in serialized
    assert '"recommendation"' not in serialized


def test_engine_normalizes_base_currency_against_million_shares(contract: dict[str, Any]) -> None:
    request = _engine_request(contract, "ev_equity_bridge")
    request["scenarios"]["base"]["enterprise_value"] = {
        "value": "1500000000",
        "unit": "USD",
        "currency": "USD",
        "identity": "enterprise value in base units",
    }
    request["method_inputs"]["bridge"] = {
        "debt": {"value": "200000000", "unit": "USD", "currency": "USD"},
        "cash": {"value": "50000000", "unit": "USD", "currency": "USD"},
        "minority_interest": {"value": "20000000", "unit": "USD", "currency": "USD"},
        "other_adjustments": [
            {"name": "pension", "amount": {"value": "-10000000", "unit": "USD", "currency": "USD"}}
        ],
    }
    actual = calculate_valuation(request)["scenario_results"]["base"]
    assert Decimal(actual["equity_value"]) == Decimal("1320000000")
    assert Decimal(actual["per_share_value"]) == Decimal("13.2")
    assert actual["units"]["equity_value"] == "USD"


def test_engine_supports_runtime_iso_currencies_without_a_fixture_whitelist(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "ev_equity_bridge")
    request["currency"] = "HKD"
    request["scenarios"]["base"]["enterprise_value"].update(
        {"unit": "HKD_million", "currency": "HKD"}
    )
    for key in ("debt", "cash", "minority_interest"):
        request["method_inputs"]["bridge"][key].update(
            {"unit": "HKD_million", "currency": "HKD"}
        )
    request["method_inputs"]["bridge"]["other_adjustments"][0]["amount"].update(
        {"unit": "HKD_million", "currency": "HKD"}
    )
    result = calculate_valuation(request)["scenario_results"]["base"]
    assert result["currency"] == "HKD"
    assert result["units"]["per_share_value"] == "HKD_per_share"


def test_engine_supports_net_debt_alternative_but_rejects_redundant_bridge(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "ev_equity_bridge")
    bridge = request["method_inputs"]["bridge"]
    bridge.pop("debt")
    bridge.pop("cash")
    bridge["net_debt"] = {
        "value": "150",
        "unit": "USD_million",
        "currency": "USD",
        "identity": "net debt",
    }
    actual = calculate_valuation(request)["scenario_results"]["base"]
    assert Decimal(actual["equity_value"]) == Decimal("1320")

    net_cash = _engine_request(contract, "ev_equity_bridge")
    net_cash["method_inputs"]["bridge"] = {
        "net_debt": {
            "value": "-50",
            "unit": "USD_million",
            "currency": "USD",
            "identity": "net cash",
        },
        "minority_interest": {
            "value": "20",
            "unit": "USD_million",
            "currency": "USD",
        },
        "other_adjustments": [
            {
                "name": "pension",
                "amount": {"value": "-10", "unit": "USD_million", "currency": "USD"},
            }
        ],
    }
    net_cash_result = calculate_valuation(net_cash)["scenario_results"]["base"]
    assert Decimal(net_cash_result["equity_value"]) == Decimal("1520")

    bridge["cash"] = {"value": "50", "unit": "USD_million", "currency": "USD"}
    with pytest.raises(ValuationError, match="^redundant_bridge_inputs$"):
        calculate_valuation(request)


@pytest.mark.parametrize(
    ("case_name", "mutate", "error"),
    [
        (
            "dcf_fcff",
            lambda request: request["scenarios"].pop("bear"),
            "scenario_scope_incomplete_for_full_valuation",
        ),
        (
            "dcf_fcff",
            lambda request: request["scenarios"]["base"].update({"unexpected": "1"}),
            "unknown_fields:scenario:unexpected",
        ),
        (
            "dcf_fcff",
            lambda request: request["scenarios"]["base"].update({"wacc": "-1"}),
            "discount_rate_must_exceed_negative_one:scenario.wacc",
        ),
        (
            "dcf_fcff",
            lambda request: request["scenarios"]["base"]["fcff"][0].update({"period": 0}),
            r"positive_integer_period_required:scenario.fcff\[0\]",
        ),
        (
            "dcf_fcff",
            lambda request: request["scenarios"]["base"]["fcff"][0].update({"period": 1.5}),
            r"positive_integer_period_required:scenario.fcff\[0\]",
        ),
        (
            "dcf_fcff",
            lambda request: request["scenarios"]["base"].update({"terminal_growth": "0.10"}),
            "terminal_growth_must_be_below_discount_rate",
        ),
        (
            "dcf_fcff",
            lambda request: request["share_basis"]["diluted_shares"].update({"value": True}),
            "finite_decimal_required:share_basis.diluted_shares.value",
        ),
        (
            "asset_value",
            lambda request: request["scenarios"]["base"]["assets"][0]["amount"].update({"value": None}),
            r"finite_decimal_required:scenario.assets\[0\].amount.value",
        ),
        (
            "asset_value",
            lambda request: request["scenarios"]["base"]["assets"].append(
                deepcopy(request["scenarios"]["base"]["assets"][0])
            ),
            "duplicate_item_id:scenario.assets:cash",
        ),
    ],
)
def test_engine_rejects_invalid_structure_and_numbers(
    contract: dict[str, Any], case_name: str, mutate: object, error: str
) -> None:
    request = _engine_request(contract, case_name)
    mutate(request)  # type: ignore[operator]
    with pytest.raises(ValuationError, match=f"^{error}$"):
        calculate_valuation(request)


def test_engine_enforces_share_date_alignment_and_money_units(contract: dict[str, Any]) -> None:
    request = _engine_request(contract, "equity_multiples")
    request["share_basis"]["as_of"] = "2025-12-31"
    with pytest.raises(ValuationError, match="^share_basis_date_requires_alignment$"):
        calculate_valuation(request)
    request["share_basis"]["alignment_reason"] = "quarter-end diluted basis explicitly aligned"
    calculate_valuation(request)

    request = _engine_request(contract, "equity_multiples")
    request["scenarios"]["base"]["denominator"]["unit"] = "EUR_million"
    with pytest.raises(ValuationError, match="^incompatible_money_unit:scenario.denominator$"):
        calculate_valuation(request)

    request = _engine_request(contract, "equity_multiples")
    request["share_basis"]["diluted_shares"]["unknown_reason"] = "conflicts with supplied value"
    with pytest.raises(
        ValuationError,
        match="^unknown_reason_conflicts_with_value:share_basis.diluted_shares$",
    ):
        calculate_valuation(request)


def test_pe_total_income_and_eps_paths_do_not_mix_units(contract: dict[str, Any]) -> None:
    request = _engine_request(contract, "equity_multiples")
    total_income = calculate_valuation(request)["scenario_results"]["base"]
    assert Decimal(total_income["equity_value"]) == Decimal("1800")
    assert Decimal(total_income["per_share_value"]) == Decimal("18")

    request["scenarios"]["base"].update(
        {
            "denominator_name": "eps",
            "denominator": {
                "value": "1.2",
                "unit": "USD_per_share",
                "currency": "USD",
                "identity": "diluted EPS",
            },
        }
    )
    eps = calculate_valuation(request)["scenario_results"]["base"]
    assert Decimal(eps["per_share_value"]) == Decimal("18")
    assert Decimal(eps["equity_value"]) == Decimal("1800000000")
    assert eps["units"]["equity_value"] == "USD"

    request["scenarios"]["base"]["denominator"]["unknown_reason"] = "conflicts with EPS value"
    with pytest.raises(
        ValuationError,
        match="^unknown_reason_conflicts_with_value:scenario.denominator$",
    ):
        calculate_valuation(request)

    invalid = _engine_request(contract, "equity_multiples")
    invalid["scenarios"]["base"]["denominator_name"] = "free_cash_flow"
    with pytest.raises(ValuationError, match="^unsupported_equity_multiple_denominator$"):
        calculate_valuation(invalid)


def test_zero_multiple_denominator_is_limited_without_a_fake_price(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "enterprise_multiples")
    request["scenarios"]["base"]["denominator"]["value"] = "0"
    result = calculate_valuation(request)
    actual = result["scenario_results"]["base"]
    assert result["status"] == "limited"
    assert actual["applicable"] is False
    assert actual["value"] is None
    assert actual["warnings"] == ["inappropriate_zero_denominator"]
    assert "per_share_value" not in actual

    segment_request = _engine_request(contract, "sum_of_parts")
    segment_request["scenarios"]["base"]["segments"][0]["denominator"]["value"] = "0"
    segment_result = calculate_valuation(segment_request)
    segment_actual = segment_result["scenario_results"]["base"]
    assert segment_result["status"] == "limited"
    assert segment_actual["applicable"] is False
    assert segment_actual["value"] is None
    assert segment_actual["reason"] == "segment A: zero denominator makes EV/EBITDA not meaningful"


def test_negative_calculated_value_remains_a_calculation_warning(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "asset_value")
    request["scenarios"]["base"]["liabilities"][0]["amount"]["value"] = "1000"
    result = calculate_valuation(request)
    actual = result["scenario_results"]["base"]
    assert actual["applicable"] is True
    assert Decimal(actual["net_asset_value"]) < 0
    assert actual["warnings"] == ["negative_calculated_value"]
    assert not ({"decision", "recommendation"} & set(actual))


def test_fx_direction_date_reference_and_segment_coverage_are_enforced(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "sum_of_parts")
    result = calculate_valuation(request)["scenario_results"]["base"]
    assert Decimal(result["equity_value"]) == Decimal("1380")

    missing = _engine_request(contract, "sum_of_parts")
    missing["method_inputs"]["fx"] = {}
    with pytest.raises(ValuationError, match="^explicit_dated_fx_required$"):
        calculate_valuation(missing)

    future = _engine_request(contract, "sum_of_parts")
    future["method_inputs"]["fx"]["EURUSD"]["as_of"] = "2026-01-16"
    with pytest.raises(ValuationError, match="^fx_rate_cannot_be_from_future$"):
        calculate_valuation(future)

    direction = _engine_request(contract, "sum_of_parts")
    direction["method_inputs"]["fx"]["EURUSD"]["unit"] = "EUR_per_USD"
    with pytest.raises(ValuationError, match="^fx_direction_mismatch$"):
        calculate_valuation(direction)

    ref_mismatch = _engine_request(contract, "sum_of_parts")
    ref_mismatch["method_inputs"]["fx"]["EURUSD"]["source_ref"] = "different.json"
    with pytest.raises(ValuationError, match="^segment_fx_ref_mismatch$"):
        calculate_valuation(ref_mismatch)

    coverage = _engine_request(contract, "sum_of_parts")
    coverage["method_inputs"]["bridge_applies_to"] = []
    with pytest.raises(ValuationError, match="^common_bridge_coverage_mismatch$"):
        calculate_valuation(coverage)

    duplicate = _engine_request(contract, "sum_of_parts")
    duplicate["scenarios"]["base"]["segments"].append(
        deepcopy(duplicate["scenarios"]["base"]["segments"][0])
    )
    with pytest.raises(ValuationError, match="^duplicate_segment_id:A$"):
        calculate_valuation(duplicate)

    negative_multiple = _engine_request(contract, "sum_of_parts")
    negative_multiple["scenarios"]["base"]["segments"][0]["multiple"] = "-1"
    with pytest.raises(ValuationError, match="^multiple_must_be_nonnegative$"):
        calculate_valuation(negative_multiple)


def test_applicable_enterprise_multiple_requires_peer_justification(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "enterprise_multiples")
    request["method_inputs"].pop("peer_justification")
    with pytest.raises(
        ValuationError,
        match="^missing_fields:method_inputs:peer_justification$",
    ):
        calculate_valuation(request)


@pytest.mark.parametrize(
    ("case_name", "change", "expected_per_share"),
    [
        ("equity_multiples", {"multiple": "10"}, "12"),
        (
            "asset_value",
            {
                "assets": [
                    {"name": "cash", "amount": {"value": "200", "unit": "USD_million", "currency": "USD"}},
                    {"name": "property", "amount": {"value": "400", "unit": "USD_million", "currency": "USD"}},
                    {"name": "investments", "amount": {"value": "100", "unit": "USD_million", "currency": "USD"}},
                ]
            },
            "4",
        ),
        ("sum_of_parts", {"segment_b_multiple": "10"}, "12.7"),
    ],
)
def test_declared_case_sensitivity_reuses_method_validation(
    contract: dict[str, Any], case_name: str, change: dict[str, Any], expected_per_share: str
) -> None:
    request = _engine_request(contract, case_name)
    scenario = deepcopy(request["scenarios"]["base"])
    if case_name == "equity_multiples":
        scenario["multiple"] = change["multiple"]
    elif case_name == "asset_value":
        scenario["assets"] = change["assets"]
    else:
        scenario["segments"][1]["multiple"] = change["segment_b_multiple"]
    request["sensitivity"] = {
        "scenario": "base",
        "cases": [{"case_id": "declared_change", "scenario": scenario}],
    }
    result = calculate_valuation(request)["sensitivity"]
    actual = result["cases"]["declared_change"]
    assert Decimal(actual["per_share_value"]) == Decimal(expected_per_share)


def test_sensitivity_axes_are_nonempty_and_cannot_silently_overwrite_cells(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "dcf_fcff")
    request["sensitivity"]["wacc_rates"] = ["0.1", "0.10"]
    with pytest.raises(ValuationError, match="^duplicate_values:sensitivity.wacc_rates$"):
        calculate_valuation(request)

    request = _engine_request(contract, "equity_multiples")
    request["sensitivity"] = {"scenario": "base", "cases": []}
    with pytest.raises(ValuationError, match="^nonempty_list_required:sensitivity.cases$"):
        calculate_valuation(request)


def test_failed_sensitivity_cell_makes_the_result_limited_and_visible(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "dcf_fcff")
    request["sensitivity"] = {
        "scenario": "base",
        "wacc_rates": ["0.02"],
        "terminal_growth_rates": ["0.03"],
    }
    result = calculate_valuation(request)
    cell = result["sensitivity"]["per_share"]["0.02"]["0.03"]
    assert cell == {"value": None, "error": "terminal_growth_must_be_below_discount_rate"}
    assert result["status"] == "limited"
    assert "sensitivity_contains_failed_cells" in result["warnings"]


def test_full_valuation_requires_sensitivity_or_explicit_limited_reason(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "dcf_fcff")
    request["sensitivity"] = None
    with pytest.raises(ValuationError, match="^full_valuation_requires_sensitivity_or_reason$"):
        calculate_valuation(request)

    request["sensitivity"] = {
        "not_applicable_reason": "no defensible alternative axis was approved for this model"
    }
    result = calculate_valuation(request)
    assert result["status"] == "limited"
    assert result["sensitivity"] == {
        "kind": "not_applicable",
        "reason": "no defensible alternative axis was approved for this model",
    }
    assert "sensitivity_not_applicable" in result["warnings"]


def test_declared_precision_is_independent_of_callers_decimal_context(
    contract: dict[str, Any],
) -> None:
    request = _engine_request(contract, "ev_equity_bridge")
    exact = "1.23456789012345678901234567890123456789"
    request["precision"] = {
        "absolute_tolerance": "0.0000000000000000000000000000000000000001",
        "relative_tolerance": "0.0000000000000000000000000000000000000001",
    }
    request["scenarios"]["base"]["enterprise_value"]["value"] = exact
    request["method_inputs"]["bridge"] = {
        "debt": {"value": "0", "unit": "USD_million", "currency": "USD"},
        "cash": {"value": "0", "unit": "USD_million", "currency": "USD"},
        "minority_interest": {"value": "0", "unit": "USD_million", "currency": "USD"},
        "other_adjustments": [],
    }
    request["share_basis"]["diluted_shares"]["value"] = exact

    with localcontext() as caller_context:
        caller_context.prec = 6
        low_context_result = calculate_valuation(request)
    with localcontext() as caller_context:
        caller_context.prec = 70
        high_context_result = calculate_valuation(request)
    assert low_context_result == high_context_result
    assert Decimal(low_context_result["scenario_results"]["base"]["per_share_value"]) == 1
