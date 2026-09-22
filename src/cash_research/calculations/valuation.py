"""Pure Decimal valuation calculations with explicit provenance and units."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import re
from typing import Any


_METHODS = {
    "dcf_fcff",
    "dcf_fcfe",
    "equity_multiples",
    "enterprise_multiples",
    "ev_equity_bridge",
    "sum_of_parts",
    "asset_value",
}
_BRIDGE_CONVENTION = "debt_and_minority_subtracted_cash_added_other_adjustments_signed"
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_TOP_REQUIRED = {
    "request_id",
    "method",
    "scope",
    "valuation_date",
    "currency",
    "financial_refs",
    "assumptions",
    "scenarios",
    "share_basis",
    "quote_ref",
    "sensitivity",
    "precision",
}
_TOP_OPTIONAL = {"method_inputs", "evidence_refs", "evidence_use"}


class ValuationError(ValueError):
    """A stable validation error raised for an invalid valuation request."""


def _error(message: str) -> None:
    raise ValuationError(message)


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _error(f"mapping_required:{where}")
    return value


def _sequence(value: object, where: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        _error(f"list_required:{where}")
    return value


def _keys(
    value: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str] | None = None,
    where: str,
) -> None:
    optional = optional or set()
    missing = sorted(required - set(value))
    if missing:
        _error(f"missing_fields:{where}:{','.join(missing)}")
    unknown = sorted(set(value) - required - optional)
    if unknown:
        _error(f"unknown_fields:{where}:{','.join(unknown)}")


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(f"nonempty_string_required:{where}")
    return value


def _decimal(value: object, where: str) -> Decimal:
    if value is None or isinstance(value, bool):
        _error(f"finite_decimal_required:{where}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValuationError(f"finite_decimal_required:{where}") from exc
    if not result.is_finite():
        _error(f"finite_decimal_required:{where}")
    return result


def _date(value: object, where: str) -> date:
    text = _text(value, where)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValuationError(f"iso_date_required:{where}") from exc


def _currency(value: object, where: str) -> str:
    text = _text(value, where)
    if not _CURRENCY_RE.fullmatch(text):
        _error(f"iso_currency_required:{where}")
    return text


def _format(value: Decimal) -> str:
    return format(value, "f")


def _unique_strings(value: object, where: str, *, allow_empty: bool = False) -> list[str]:
    items = _sequence(value, where)
    result = [_text(item, f"{where}[]") for item in items]
    if not allow_empty and not result:
        _error(f"nonempty_list_required:{where}")
    if len(result) != len(set(result)):
        _error(f"duplicate_values:{where}")
    return result


def _money(
    value: object,
    where: str,
    *,
    expected_currency: str | None = None,
) -> tuple[Decimal, str, str, Decimal]:
    quantity = _mapping(value, where)
    _keys(
        quantity,
        required={"value", "unit", "currency"},
        optional={"identity", "unknown_reason"},
        where=where,
    )
    amount = _decimal(quantity["value"], f"{where}.value")
    currency = _currency(quantity["currency"], f"{where}.currency")
    if expected_currency is not None and currency != expected_currency:
        _error(f"currency_mismatch:{where}")
    unit = _text(quantity["unit"], f"{where}.unit")
    if unit == currency:
        scale = Decimal(1)
    elif unit == f"{currency}_million":
        scale = Decimal(1_000_000)
    else:
        _error(f"incompatible_money_unit:{where}")
    if quantity.get("unknown_reason") is not None:
        _error(f"unknown_reason_conflicts_with_value:{where}")
    return amount * scale, currency, unit, scale


def _per_share(value: object, where: str, currency: str) -> Decimal:
    quantity = _mapping(value, where)
    _keys(
        quantity,
        required={"value", "unit", "currency"},
        optional={"identity", "unknown_reason"},
        where=where,
    )
    if quantity["currency"] != currency or quantity["unit"] != f"{currency}_per_share":
        _error(f"incompatible_per_share_unit:{where}")
    if quantity.get("unknown_reason") is not None:
        _error(f"unknown_reason_conflicts_with_value:{where}")
    return _decimal(quantity["value"], f"{where}.value")


def _shares(value: object, valuation_date: date) -> Decimal:
    basis = _mapping(value, "share_basis")
    _keys(
        basis,
        required={"diluted_shares", "as_of", "source_ref", "basis"},
        optional={"alignment_reason"},
        where="share_basis",
    )
    if _text(basis["basis"], "share_basis.basis") != "diluted":
        _error("diluted_share_basis_required")
    share_date = _date(basis["as_of"], "share_basis.as_of")
    if share_date != valuation_date and not basis.get("alignment_reason"):
        _error("share_basis_date_requires_alignment")
    if basis.get("alignment_reason") is not None:
        _text(basis["alignment_reason"], "share_basis.alignment_reason")
    _text(basis["source_ref"], "share_basis.source_ref")
    quantity = _mapping(basis["diluted_shares"], "share_basis.diluted_shares")
    _keys(
        quantity,
        required={"value", "unit", "currency"},
        optional={"identity", "unknown_reason"},
        where="share_basis.diluted_shares",
    )
    if quantity["currency"] is not None:
        _error("share_quantity_currency_must_be_null")
    if quantity.get("unknown_reason") is not None:
        _error("unknown_reason_conflicts_with_value:share_basis.diluted_shares")
    unit = _text(quantity["unit"], "share_basis.diluted_shares.unit")
    scale = {"shares": Decimal(1), "million_shares": Decimal(1_000_000)}.get(unit)
    if scale is None:
        _error("incompatible_share_unit")
    count = _decimal(quantity["value"], "share_basis.diluted_shares.value") * scale
    if count <= 0:
        _error("diluted_shares_must_be_positive")
    return count


def _output_amount(value: Decimal, unit: str, currency: str) -> str:
    if unit == currency:
        scale = Decimal(1)
    elif unit == f"{currency}_million":
        scale = Decimal(1_000_000)
    else:
        _error("invalid_output_unit")
    return _format(value / scale)


def _rate(value: object, where: str) -> Decimal:
    result = _decimal(value, where)
    if result <= -1:
        _error(f"discount_rate_must_exceed_negative_one:{where}")
    return result


def _cash_flows(
    value: object,
    where: str,
    currency: str,
) -> tuple[list[tuple[int, Decimal]], str]:
    rows = _sequence(value, where)
    if not rows:
        _error(f"nonempty_list_required:{where}")
    result: list[tuple[int, Decimal]] = []
    output_unit: str | None = None
    for index, raw in enumerate(rows):
        row = _mapping(raw, f"{where}[{index}]")
        _keys(row, required={"period", "amount"}, where=f"{where}[{index}]")
        period = row["period"]
        if isinstance(period, bool) or not isinstance(period, int) or period < 1:
            _error(f"positive_integer_period_required:{where}[{index}]")
        amount, _, unit, _ = _money(
            row["amount"], f"{where}[{index}].amount", expected_currency=currency
        )
        output_unit = output_unit or unit
        result.append((period, amount))
    periods = [period for period, _ in result]
    if periods != list(range(1, len(periods) + 1)):
        _error(f"contiguous_year_end_periods_required:{where}")
    return result, output_unit or currency


def _dcf_value(cash_flows: list[tuple[int, Decimal]], rate: Decimal, growth: Decimal) -> Decimal:
    if growth >= rate:
        _error("terminal_growth_must_be_below_discount_rate")
    terminal = cash_flows[-1][1] * (Decimal(1) + growth) / (rate - growth)
    return sum(
        (amount / ((Decimal(1) + rate) ** period) for period, amount in cash_flows),
        Decimal(0),
    ) + terminal / ((Decimal(1) + rate) ** cash_flows[-1][0])


def _bridge(
    value: object,
    convention: object,
    currency: str,
    where: str,
) -> tuple[Decimal, str]:
    if convention != _BRIDGE_CONVENTION:
        _error(f"unsupported_bridge_convention:{where}")
    bridge = _mapping(value, where)
    allowed = {"debt", "cash", "net_debt", "minority_interest", "other_adjustments"}
    unknown = sorted(set(bridge) - allowed)
    if unknown:
        _error(f"unknown_fields:{where}:{','.join(unknown)}")
    if "net_debt" in bridge and ({"debt", "cash"} & set(bridge)):
        _error("redundant_bridge_inputs")
    if "net_debt" not in bridge and not {"debt", "cash"} <= set(bridge):
        _error(f"missing_fields:{where}:debt,cash")
    if not {"minority_interest", "other_adjustments"} <= set(bridge):
        _error(f"missing_fields:{where}:minority_interest,other_adjustments")

    output_unit: str | None = None
    if "net_debt" in bridge:
        net_debt, _, output_unit, _ = _money(
            bridge["net_debt"], f"{where}.net_debt", expected_currency=currency
        )
        adjustment = -net_debt
    else:
        debt, _, output_unit, _ = _money(
            bridge["debt"], f"{where}.debt", expected_currency=currency
        )
        cash, _, _, _ = _money(bridge["cash"], f"{where}.cash", expected_currency=currency)
        if debt < 0 or cash < 0:
            _error("debt_and_cash_must_be_nonnegative")
        adjustment = -debt + cash
    minority, _, _, _ = _money(
        bridge["minority_interest"],
        f"{where}.minority_interest",
        expected_currency=currency,
    )
    if minority < 0:
        _error("minority_interest_must_be_nonnegative")
    adjustment -= minority

    adjustments = _sequence(bridge["other_adjustments"], f"{where}.other_adjustments")
    names: set[str] = set()
    for index, raw in enumerate(adjustments):
        item = _mapping(raw, f"{where}.other_adjustments[{index}]")
        _keys(
            item,
            required={"name", "amount"},
            where=f"{where}.other_adjustments[{index}]",
        )
        name = _text(item["name"], f"{where}.other_adjustments[{index}].name")
        if name in names:
            _error(f"duplicate_bridge_adjustment:{name}")
        names.add(name)
        amount, _, _, _ = _money(
            item["amount"],
            f"{where}.other_adjustments[{index}].amount",
            expected_currency=currency,
        )
        adjustment += amount
    return adjustment, output_unit or currency


def _result_values(
    *,
    equity: Decimal,
    shares: Decimal,
    currency: str,
    output_unit: str,
    enterprise: Decimal | None = None,
    value_name: str = "equity_value",
) -> dict[str, object]:
    result: dict[str, object] = {
        "applicable": True,
        value_name: _output_amount(equity, output_unit, currency),
        "per_share_value": _format(equity / shares),
        "currency": currency,
        "units": {value_name: output_unit, "per_share_value": f"{currency}_per_share"},
        "warnings": [],
    }
    if enterprise is not None:
        result["enterprise_value"] = _output_amount(enterprise, output_unit, currency)
        result["units"] = {
            "enterprise_value": output_unit,
            value_name: output_unit,
            "per_share_value": f"{currency}_per_share",
        }
    if equity < 0:
        result["warnings"] = ["negative_calculated_value"]
    return result


def _dcf_scenario(
    method: str,
    scenario: object,
    method_inputs: Mapping[str, object],
    currency: str,
    shares: Decimal,
) -> dict[str, object]:
    values = _mapping(scenario, "scenario")
    if method == "dcf_fcff":
        _keys(values, required={"fcff", "wacc", "terminal_growth"}, where="scenario")
        _keys(
            method_inputs,
            required={"cash_flow_type", "forecast_timing", "bridge", "bridge_convention"},
            where="method_inputs",
        )
        if method_inputs.get("cash_flow_type") != "FCFF" or method_inputs.get("forecast_timing") != "year_end":
            _error("fcff_method_inputs_mismatch")
        flows, output_unit = _cash_flows(values["fcff"], "scenario.fcff", currency)
        rate = _rate(values["wacc"], "scenario.wacc")
        growth = _decimal(values["terminal_growth"], "scenario.terminal_growth")
        enterprise = _dcf_value(flows, rate, growth)
        bridge_adjustment, _ = _bridge(
            method_inputs.get("bridge"),
            method_inputs.get("bridge_convention"),
            currency,
            "method_inputs.bridge",
        )
        return _result_values(
            equity=enterprise + bridge_adjustment,
            enterprise=enterprise,
            shares=shares,
            currency=currency,
            output_unit=output_unit,
        )

    _keys(values, required={"fcfe", "cost_of_equity", "terminal_growth"}, where="scenario")
    if set(method_inputs) != {"cash_flow_type", "forecast_timing", "bridge"}:
        _error("fcfe_method_inputs_fields_invalid")
    if (
        method_inputs.get("cash_flow_type") != "FCFE"
        or method_inputs.get("forecast_timing") != "year_end"
        or method_inputs.get("bridge") is not None
    ):
        _error("fcfe_method_inputs_mismatch")
    flows, output_unit = _cash_flows(values["fcfe"], "scenario.fcfe", currency)
    rate = _rate(values["cost_of_equity"], "scenario.cost_of_equity")
    growth = _decimal(values["terminal_growth"], "scenario.terminal_growth")
    equity = _dcf_value(flows, rate, growth)
    result = _result_values(
        equity=equity,
        shares=shares,
        currency=currency,
        output_unit=output_unit,
    )
    result["bridge_applied"] = False
    result["debt_subtracted_after_fcfe"] = False
    return result


def _inapplicable(reason: str, currency: str, warning: str) -> dict[str, object]:
    return {
        "applicable": False,
        "value": None,
        "reason": reason,
        "currency": currency,
        "warnings": [warning],
    }


def _multiple_scenario(
    method: str,
    scenario: object,
    method_inputs: Mapping[str, object],
    currency: str,
    shares: Decimal,
) -> dict[str, object]:
    values = _mapping(scenario, "scenario")
    _keys(
        values,
        required={"denominator_name", "denominator", "multiple", "multiple_basis"},
        where="scenario",
    )
    multiple = _decimal(values["multiple"], "scenario.multiple")
    if multiple < 0:
        _error("multiple_must_be_nonnegative")
    denominator_name = _text(values["denominator_name"], "scenario.denominator_name")
    multiple_basis = _text(values["multiple_basis"], "scenario.multiple_basis")

    if method == "equity_multiples":
        _keys(
            method_inputs,
            required={"valuation_level", "peer_set_ref", "peer_justification"},
            where="method_inputs",
        )
        if method_inputs["valuation_level"] != "equity":
            _error("equity_multiple_level_required")
        _text(method_inputs["peer_set_ref"], "method_inputs.peer_set_ref")
        _text(method_inputs["peer_justification"], "method_inputs.peer_justification")
        if denominator_name == "net_income" and multiple_basis == "price_to_earnings":
            denominator, _, output_unit, _ = _money(
                values["denominator"], "scenario.denominator", expected_currency=currency
            )
            if denominator <= 0:
                kind = "negative" if denominator < 0 else "zero"
                return _inapplicable(
                    f"{kind} denominator makes P/E not meaningful",
                    currency,
                    f"inappropriate_{kind}_denominator",
                )
            equity = denominator * multiple
        elif denominator_name == "eps" and multiple_basis == "price_to_earnings":
            eps = _per_share(values["denominator"], "scenario.denominator", currency)
            if eps <= 0:
                kind = "negative" if eps < 0 else "zero"
                return _inapplicable(
                    f"{kind} denominator makes P/E not meaningful",
                    currency,
                    f"inappropriate_{kind}_denominator",
                )
            equity = eps * multiple * shares
            output_unit = currency
        else:
            _error("unsupported_equity_multiple_denominator")
        return _result_values(
            equity=equity,
            shares=shares,
            currency=currency,
            output_unit=output_unit,
        )

    _keys(
        method_inputs,
        required={"valuation_level", "peer_set_ref"},
        optional={"peer_justification", "bridge", "bridge_convention"},
        where="method_inputs",
    )
    if method_inputs["valuation_level"] != "enterprise":
        _error("enterprise_multiple_level_required")
    _text(method_inputs["peer_set_ref"], "method_inputs.peer_set_ref")
    if method_inputs.get("peer_justification") is not None:
        _text(method_inputs["peer_justification"], "method_inputs.peer_justification")
    allowed = {
        "ebitda": "enterprise_value_to_ebitda",
        "ebit": "enterprise_value_to_ebit",
        "revenue": "enterprise_value_to_revenue",
    }
    if allowed.get(denominator_name) != multiple_basis:
        _error("unsupported_enterprise_multiple_denominator")
    denominator, _, output_unit, _ = _money(
        values["denominator"], "scenario.denominator", expected_currency=currency
    )
    if denominator <= 0:
        kind = "negative" if denominator < 0 else "zero"
        label = "EV/EBITDA" if multiple_basis == "enterprise_value_to_ebitda" else multiple_basis
        return _inapplicable(
            f"{kind} denominator makes {label} not meaningful",
            currency,
            f"inappropriate_{kind}_denominator",
        )
    _keys(
        method_inputs,
        required={"valuation_level", "peer_set_ref", "peer_justification", "bridge", "bridge_convention"},
        where="method_inputs",
    )
    _text(method_inputs["peer_justification"], "method_inputs.peer_justification")
    enterprise = denominator * multiple
    adjustment, _ = _bridge(
        method_inputs["bridge"],
        method_inputs["bridge_convention"],
        currency,
        "method_inputs.bridge",
    )
    return _result_values(
        equity=enterprise + adjustment,
        enterprise=enterprise,
        shares=shares,
        currency=currency,
        output_unit=output_unit,
    )


def _bridge_scenario(
    scenario: object,
    method_inputs: Mapping[str, object],
    currency: str,
    shares: Decimal,
) -> dict[str, object]:
    values = _mapping(scenario, "scenario")
    _keys(values, required={"enterprise_value"}, where="scenario")
    _keys(
        method_inputs,
        required={"bridge", "bridge_convention"},
        where="method_inputs",
    )
    enterprise, _, output_unit, _ = _money(
        values["enterprise_value"], "scenario.enterprise_value", expected_currency=currency
    )
    adjustment, _ = _bridge(
        method_inputs["bridge"],
        method_inputs["bridge_convention"],
        currency,
        "method_inputs.bridge",
    )
    return _result_values(
        equity=enterprise + adjustment,
        enterprise=enterprise,
        shares=shares,
        currency=currency,
        output_unit=output_unit,
    )


def _named_amounts(value: object, where: str, currency: str) -> tuple[Decimal, str]:
    rows = _sequence(value, where)
    if not rows:
        _error(f"nonempty_list_required:{where}")
    names: set[str] = set()
    total = Decimal(0)
    output_unit: str | None = None
    for index, raw in enumerate(rows):
        row = _mapping(raw, f"{where}[{index}]")
        _keys(
            row,
            required={"amount"},
            optional={"name", "asset_id"},
            where=f"{where}[{index}]",
        )
        identifiers = [row[key] for key in ("name", "asset_id") if key in row]
        if len(identifiers) != 1:
            _error(f"exactly_one_item_identifier_required:{where}[{index}]")
        name = _text(identifiers[0], f"{where}[{index}].identifier")
        if name in names:
            _error(f"duplicate_item_id:{where}:{name}")
        names.add(name)
        amount, _, unit, _ = _money(
            row["amount"], f"{where}[{index}].amount", expected_currency=currency
        )
        output_unit = output_unit or unit
        total += amount
    return total, output_unit or currency


def _asset_scenario(
    scenario: object,
    method_inputs: Mapping[str, object],
    currency: str,
    shares: Decimal,
) -> dict[str, object]:
    values = _mapping(scenario, "scenario")
    _keys(values, required={"assets", "liabilities"}, where="scenario")
    _keys(method_inputs, required={"missing_value_policy"}, where="method_inputs")
    if method_inputs["missing_value_policy"] != "reject_never_fill_zero":
        _error("missing_value_policy_must_reject")
    assets, output_unit = _named_amounts(values["assets"], "scenario.assets", currency)
    liabilities, _ = _named_amounts(values["liabilities"], "scenario.liabilities", currency)
    return _result_values(
        equity=assets - liabilities,
        shares=shares,
        currency=currency,
        output_unit=output_unit,
        value_name="net_asset_value",
    )


def _fx_rate(
    source_currency: str,
    reporting_currency: str,
    method_inputs: Mapping[str, object],
    valuation_date: date,
    fx_ref: object,
) -> tuple[Decimal, list[str]]:
    if source_currency == reporting_currency:
        if fx_ref is not None:
            _error("same_currency_segment_must_not_supply_fx_ref")
        return Decimal(1), []
    ref = _text(fx_ref, "segment.fx_ref")
    fx_table = _mapping(method_inputs.get("fx"), "method_inputs.fx")
    pair = f"{source_currency}{reporting_currency}"
    if pair not in fx_table:
        _error("explicit_dated_fx_required")
    entry = _mapping(fx_table[pair], f"method_inputs.fx.{pair}")
    _keys(
        entry,
        required={"rate", "unit", "as_of", "source_ref"},
        where=f"method_inputs.fx.{pair}",
    )
    if entry["unit"] != f"{reporting_currency}_per_{source_currency}":
        _error("fx_direction_mismatch")
    if entry["source_ref"] != ref:
        _error("segment_fx_ref_mismatch")
    rate = _decimal(entry["rate"], f"method_inputs.fx.{pair}.rate")
    if rate <= 0:
        _error("fx_rate_must_be_positive")
    rate_date = _date(entry["as_of"], f"method_inputs.fx.{pair}.as_of")
    if rate_date > valuation_date:
        _error("fx_rate_cannot_be_from_future")
    warnings = [] if rate_date == valuation_date else [f"stale_fx_rate:{pair}:{rate_date.isoformat()}"]
    return rate, warnings


def _segment_value(
    segment: Mapping[str, object],
    reporting_currency: str,
    method_inputs: Mapping[str, object],
    valuation_date: date,
) -> tuple[str, Decimal | None, str, list[str], str | None]:
    segment_id = _text(segment.get("segment_id"), "segment.segment_id")
    method = _text(segment.get("method"), f"segment.{segment_id}.method")
    level = _text(segment.get("valuation_level"), f"segment.{segment_id}.valuation_level")
    if method in {"ev_to_ebitda", "price_to_earnings"}:
        _keys(
            segment,
            required={"segment_id", "valuation_level", "method", "denominator", "multiple"},
            optional={"fx_ref"},
            where=f"segment.{segment_id}",
        )
        denominator, source_currency, _, _ = _money(
            segment["denominator"], f"segment.{segment_id}.denominator"
        )
        if denominator <= 0:
            kind = "negative" if denominator < 0 else "zero"
            label = "EV/EBITDA" if method == "ev_to_ebitda" else "P/E"
            return (
                segment_id,
                None,
                level,
                [f"inappropriate_{kind}_denominator"],
                f"{kind} denominator makes {label} not meaningful",
            )
        if method == "ev_to_ebitda" and level != "enterprise":
            _error(f"segment_level_mismatch:{segment_id}")
        if method == "price_to_earnings" and level != "equity":
            _error(f"segment_level_mismatch:{segment_id}")
        multiple = _decimal(segment["multiple"], f"segment.{segment_id}.multiple")
        if multiple < 0:
            _error("multiple_must_be_nonnegative")
        value = denominator * multiple
    elif method == "asset_value":
        _keys(
            segment,
            required={"segment_id", "valuation_level", "method", "assets", "liabilities", "currency"},
            optional={"fx_ref"},
            where=f"segment.{segment_id}",
        )
        source_currency = _currency(segment["currency"], f"segment.{segment_id}.currency")
        if level != "equity":
            _error(f"segment_level_mismatch:{segment_id}")
        assets, _ = _named_amounts(segment["assets"], f"segment.{segment_id}.assets", source_currency)
        liabilities, _ = _named_amounts(
            segment["liabilities"], f"segment.{segment_id}.liabilities", source_currency
        )
        value = assets - liabilities
    elif method in {"dcf_fcff", "dcf_fcfe"}:
        required = (
            {"segment_id", "valuation_level", "method", "fcff", "wacc", "terminal_growth"}
            if method == "dcf_fcff"
            else {"segment_id", "valuation_level", "method", "fcfe", "cost_of_equity", "terminal_growth"}
        )
        _keys(segment, required=required, optional={"fx_ref"}, where=f"segment.{segment_id}")
        flow_key = "fcff" if method == "dcf_fcff" else "fcfe"
        rows = _sequence(segment[flow_key], f"segment.{segment_id}.{flow_key}")
        if not rows:
            _error(f"nonempty_list_required:segment.{segment_id}.{flow_key}")
        first_amount = _mapping(_mapping(rows[0], "segment.cash_flow")["amount"], "segment.amount")
        source_currency = _currency(first_amount.get("currency"), "segment.amount.currency")
        flows, _ = _cash_flows(rows, f"segment.{segment_id}.{flow_key}", source_currency)
        rate_key = "wacc" if method == "dcf_fcff" else "cost_of_equity"
        value = _dcf_value(
            flows,
            _rate(segment[rate_key], f"segment.{segment_id}.{rate_key}"),
            _decimal(segment["terminal_growth"], f"segment.{segment_id}.terminal_growth"),
        )
        expected_level = "enterprise" if method == "dcf_fcff" else "equity"
        if level != expected_level:
            _error(f"segment_level_mismatch:{segment_id}")
    else:
        _error(f"unsupported_segment_method:{method}")

    fx, warnings = _fx_rate(
        source_currency,
        reporting_currency,
        method_inputs,
        valuation_date,
        segment.get("fx_ref"),
    )
    return segment_id, value * fx, level, warnings, None


def _sotp_scenario(
    scenario: object,
    method_inputs: Mapping[str, object],
    currency: str,
    shares: Decimal,
    valuation_date: date,
) -> dict[str, object]:
    values = _mapping(scenario, "scenario")
    _keys(values, required={"segments"}, where="scenario")
    _keys(
        method_inputs,
        required={"common_bridge", "bridge_convention", "bridge_applies_to", "fx"},
        where="method_inputs",
    )
    segments = _sequence(values["segments"], "scenario.segments")
    if not segments:
        _error("nonempty_list_required:scenario.segments")
    ids: set[str] = set()
    enterprise_ids: set[str] = set()
    enterprise_total = Decimal(0)
    equity_total = Decimal(0)
    component_values: dict[str, str] = {}
    warnings: list[str] = []
    for raw in segments:
        segment = _mapping(raw, "scenario.segment")
        segment_id, value, level, segment_warnings, inapplicable_reason = _segment_value(
            segment, currency, method_inputs, valuation_date
        )
        if segment_id in ids:
            _error(f"duplicate_segment_id:{segment_id}")
        ids.add(segment_id)
        warnings.extend(segment_warnings)
        if value is None:
            return _inapplicable(
                f"segment {segment_id}: {inapplicable_reason}",
                currency,
                segment_warnings[0],
            )
        component_values[segment_id] = _format(value)
        if level == "enterprise":
            enterprise_ids.add(segment_id)
            enterprise_total += value
        else:
            equity_total += value
    bridge_ids = set(_unique_strings(method_inputs["bridge_applies_to"], "method_inputs.bridge_applies_to", allow_empty=True))
    if bridge_ids != enterprise_ids:
        _error("common_bridge_coverage_mismatch")
    adjustment, output_unit = _bridge(
        method_inputs["common_bridge"],
        method_inputs["bridge_convention"],
        currency,
        "method_inputs.common_bridge",
    )
    total = equity_total + enterprise_total + adjustment
    result = _result_values(
        equity=total,
        shares=shares,
        currency=currency,
        output_unit=output_unit,
    )
    result["component_values_base_currency"] = component_values
    result["warnings"] = list(dict.fromkeys([*result["warnings"], *warnings]))
    return result


def _scenario_result(
    method: str,
    scenario: object,
    method_inputs: Mapping[str, object],
    currency: str,
    shares: Decimal,
    valuation_date: date,
) -> dict[str, object]:
    if method in {"dcf_fcff", "dcf_fcfe"}:
        return _dcf_scenario(method, scenario, method_inputs, currency, shares)
    if method in {"equity_multiples", "enterprise_multiples"}:
        return _multiple_scenario(method, scenario, method_inputs, currency, shares)
    if method == "ev_equity_bridge":
        return _bridge_scenario(scenario, method_inputs, currency, shares)
    if method == "asset_value":
        return _asset_scenario(scenario, method_inputs, currency, shares)
    return _sotp_scenario(scenario, method_inputs, currency, shares, valuation_date)


def _sensitivity(
    method: str,
    value: object,
    scope: str,
    scenarios: Mapping[str, object],
    method_inputs: Mapping[str, object],
    currency: str,
    shares: Decimal,
    valuation_date: date,
) -> Mapping[str, object] | None:
    if value is None:
        if scope == "full":
            _error("full_valuation_requires_sensitivity_or_reason")
        return None
    sensitivity = _mapping(value, "sensitivity")
    if set(sensitivity) == {"not_applicable_reason"}:
        reason = _text(sensitivity["not_applicable_reason"], "sensitivity.not_applicable_reason")
        return {"kind": "not_applicable", "reason": reason}
    scenario_name = _text(sensitivity.get("scenario"), "sensitivity.scenario")
    if scenario_name not in scenarios:
        _error("sensitivity_scenario_not_found")
    if method == "dcf_fcff" and set(sensitivity) == {
        "scenario",
        "wacc_rates",
        "terminal_growth_rates",
    }:
        base = _mapping(scenarios[scenario_name], f"scenarios.{scenario_name}")
        rows: dict[str, object] = {}
        for rate in _decimal_axis(sensitivity["wacc_rates"], "sensitivity.wacc_rates"):
            row: dict[str, object] = {}
            for growth in _decimal_axis(
                sensitivity["terminal_growth_rates"], "sensitivity.terminal_growth_rates"
            ):
                candidate = dict(base)
                candidate["wacc"] = rate
                candidate["terminal_growth"] = growth
                try:
                    result = _scenario_result(
                        method, candidate, method_inputs, currency, shares, valuation_date
                    )
                    row[_format(growth)] = result["per_share_value"]
                except ValuationError as exc:
                    row[_format(growth)] = {"value": None, "error": str(exc)}
            rows[_format(rate)] = row
        return {"kind": "dcf_grid", "scenario": scenario_name, "per_share": rows}

    _keys(sensitivity, required={"scenario", "cases"}, where="sensitivity")
    cases = _sequence(sensitivity["cases"], "sensitivity.cases")
    if not cases:
        _error("nonempty_list_required:sensitivity.cases")
    results: dict[str, object] = {}
    for index, raw in enumerate(cases):
        case = _mapping(raw, f"sensitivity.cases[{index}]")
        _keys(
            case,
            required={"case_id", "scenario"},
            where=f"sensitivity.cases[{index}]",
        )
        case_id = _text(case["case_id"], f"sensitivity.cases[{index}].case_id")
        if case_id in results:
            _error(f"duplicate_sensitivity_case:{case_id}")
        try:
            results[case_id] = _scenario_result(
                method, case["scenario"], method_inputs, currency, shares, valuation_date
            )
        except ValuationError as exc:
            results[case_id] = {"applicable": False, "error": str(exc), "warnings": ["sensitivity_case_failed"]}
    return {"kind": "declared_cases", "scenario": scenario_name, "cases": results}


def _collect_refs(request: Mapping[str, object]) -> list[str]:
    refs: list[str] = []

    def add(value: object, where: str) -> None:
        if value is None:
            return
        ref = _text(value, where)
        if ref not in refs:
            refs.append(ref)

    for ref in _unique_strings(request["financial_refs"], "financial_refs"):
        add(ref, "financial_refs[]")
    for index, raw in enumerate(_sequence(request["assumptions"], "assumptions")):
        assumption = _mapping(raw, f"assumptions[{index}]")
        _keys(
            assumption,
            required={"name", "reason", "source_refs"},
            where=f"assumptions[{index}]",
        )
        _text(assumption["name"], f"assumptions[{index}].name")
        _text(assumption["reason"], f"assumptions[{index}].reason")
        for ref in _unique_strings(
            assumption["source_refs"], f"assumptions[{index}].source_refs"
        ):
            add(ref, f"assumptions[{index}].source_refs[]")
    share_basis = _mapping(request["share_basis"], "share_basis")
    add(share_basis.get("source_ref"), "share_basis.source_ref")
    if request.get("quote_ref") is not None:
        add(request["quote_ref"], "quote_ref")
    for ref in _unique_strings(
        request.get("evidence_refs", []), "evidence_refs", allow_empty=True
    ):
        add(ref, "evidence_refs[]")
    method_inputs = request.get("method_inputs")
    if isinstance(method_inputs, Mapping):
        if method_inputs.get("peer_set_ref") is not None:
            add(method_inputs["peer_set_ref"], "method_inputs.peer_set_ref")
        fx = method_inputs.get("fx")
        if isinstance(fx, Mapping):
            for pair, raw in fx.items():
                entry = _mapping(raw, f"method_inputs.fx.{pair}")
                add(entry.get("source_ref"), f"method_inputs.fx.{pair}.source_ref")
    return refs


def _precision(value: object) -> dict[str, str]:
    precision = _mapping(value, "precision")
    _keys(
        precision,
        required={"absolute_tolerance", "relative_tolerance"},
        where="precision",
    )
    absolute = _decimal(precision["absolute_tolerance"], "precision.absolute_tolerance")
    relative = _decimal(precision["relative_tolerance"], "precision.relative_tolerance")
    if absolute <= 0 or relative <= 0:
        _error("precision_tolerances_must_be_positive")
    return {"absolute_tolerance": _format(absolute), "relative_tolerance": _format(relative)}


def _decimal_axis(value: object, where: str) -> list[Decimal]:
    raw_values = _sequence(value, where)
    if not raw_values:
        _error(f"nonempty_list_required:{where}")
    result = [_decimal(item, f"{where}[]") for item in raw_values]
    if len(set(result)) != len(result):
        _error(f"duplicate_values:{where}")
    return result


def _contains_error(value: object) -> bool:
    if isinstance(value, Mapping):
        if value.get("error") is not None:
            return True
        return any(_contains_error(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_error(item) for item in value)
    return False


def calculate_valuation(request: Mapping[str, object]) -> Mapping[str, object]:
    """Validate and calculate one side-effect-free valuation request.

    Numeric outputs are decimal strings so serialization cannot silently convert them to binary floats.
    Every request, assumption, and source reference is retained for later Calculation publication.
    """

    request = _mapping(request, "request")
    _keys(request, required=_TOP_REQUIRED, optional=_TOP_OPTIONAL, where="request")
    request_id = _text(request["request_id"], "request_id")
    method = _text(request["method"], "method")
    if method not in _METHODS:
        _error("unsupported_valuation_method")
    scope = _text(request["scope"], "scope")
    if scope not in {"full", "component"}:
        _error("scope_must_be_full_or_component")
    valuation_date = _date(request["valuation_date"], "valuation_date")
    currency = _currency(request["currency"], "currency")
    precision = _precision(request["precision"])
    refs = _collect_refs(request)
    if request.get("evidence_use") is not None:
        _text(request["evidence_use"], "evidence_use")

    scenarios = _mapping(request["scenarios"], "scenarios")
    if not scenarios:
        _error("nonempty_scenarios_required")
    if scope == "full" and set(scenarios) != {"bear", "base", "bull"}:
        _error("scenario_scope_incomplete_for_full_valuation")
    for name in scenarios:
        _text(name, "scenarios.name")
    method_inputs = _mapping(request.get("method_inputs", {}), "method_inputs")

    tolerance_digits = max(
        0,
        -Decimal(precision["absolute_tolerance"]).as_tuple().exponent,
        -Decimal(precision["relative_tolerance"]).as_tuple().exponent,
    )
    with localcontext() as context:
        context.prec = max(50, tolerance_digits + 30)
        shares = _shares(request["share_basis"], valuation_date)
        scenario_results = {
            name: _scenario_result(
                method,
                scenario,
                method_inputs,
                currency,
                shares,
                valuation_date,
            )
            for name, scenario in scenarios.items()
        }
        sensitivity = _sensitivity(
            method,
            request["sensitivity"],
            scope,
            scenarios,
            method_inputs,
            currency,
            shares,
            valuation_date,
        )

    warnings = list(
        dict.fromkeys(
            warning
            for result in scenario_results.values()
            for warning in result.get("warnings", [])
        )
    )
    sensitivity_failed = _contains_error(sensitivity)
    sensitivity_not_applicable = (
        isinstance(sensitivity, Mapping) and sensitivity.get("kind") == "not_applicable"
    )
    if sensitivity_failed:
        warnings.append("sensitivity_contains_failed_cells")
    if sensitivity_not_applicable:
        warnings.append("sensitivity_not_applicable")
    status = (
        "complete"
        if all(result.get("applicable", True) for result in scenario_results.values())
        and not sensitivity_failed
        and not sensitivity_not_applicable
        else "limited"
    )
    return {
        "request_id": request_id,
        "method": method,
        "scope": scope,
        "valuation_date": valuation_date.isoformat(),
        "currency": currency,
        "status": status,
        "input_refs": refs,
        "parameters": deepcopy(dict(request)),
        "assumptions": deepcopy(list(request["assumptions"])),
        "scenario_results": scenario_results,
        "sensitivity": sensitivity,
        "precision": precision,
        "warnings": warnings,
    }
