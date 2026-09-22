# Valuation assumptions and interpretation v1.0

Use this method to turn sourced operating assumptions into a reviewable valuation calculation and to interpret returned scenarios. It does not choose an investment label. The model researches assumptions; the program performs arithmetic and validation.

## Standalone inputs

The assignment states the security identity, question, horizon, timezone-aware cutoff, valuation date, reporting currency, actual tool map, output location, and whether this is a `full` valuation or a `component` calculation. Include actual Evidence/source references, the current MemoryPacket, prior Decision when relevant, financial period and accounting basis, diluted-share date/basis, debt/cash/minority items, current quote reference when price comparison is requested, and every assumption with a reason and source references.

Unknown values remain unknown with their effect on method applicability. Do not enter zero, a stale quote, an analyst target, or a model guess to make a request run.

## Select and specify the method

Choose the method that matches the economics and available inputs; do not average incompatible outputs.

- **FCFF DCF**: define year-end FCFF periods and WACC. It produces enterprise value, then applies one equity bridge.
- **FCFE DCF**: define FCFE periods and cost of equity. It produces equity value directly; do not subtract debt again.
- **Equity multiple**: match total net income with P/E or per-share EPS with P/E. Do not multiply EPS as though it were total income.
- **Enterprise multiple**: match EV/EBITDA, EV/EBIT, or EV/revenue with the same denominator definition, then apply one bridge.
- **EV-to-equity bridge**: positive debt and minority balances subtract; positive cash adds; other adjustments are explicitly signed. `net_debt` is an alternative to debt plus cash and may be negative for net cash. Never provide both forms.
- **Sum of parts**: identify each segment once, give its method and valuation level, convert currencies with a dated directional rate and source, and apply common debt only once to the declared enterprise-valued segments.
- **Asset value**: list every included asset and liability explicitly. Missing parts are not zero.

Explain peer selection and exclusions by business model, growth, margin, balance sheet, geography, accounting period, and currency. A negative or zero denominator makes that multiple inapplicable; it is not a negative price.

## Build the program request

Use [the shipped valuation request](../../fixtures/requests/valuation.json) only as a shape reference. Replace its synthetic identity, dates, sources, values, and assumptions. Do not cite fixture values as evidence.

The runtime request contains:

- `request_id`, `scope`, `method`, `valuation_date`, `currency`;
- `financial_refs`, optional `evidence_refs`, and sourced `assumptions` with `name`, `reason`, and `source_refs`;
- `scenarios`, `share_basis`, method-specific `method_inputs`, optional `quote_ref`, `sensitivity`, and declared `precision`.

`scope: full` requires bear/base/bull and a declared main sensitivity. When no defensible sensitivity axis exists, give an explicit not-applicable reason and treat the result as limited. `scope: component` is for a bounded method calculation and must not be presented as a complete valuation.

Amounts use explicit ISO currency and scale, such as base currency or currency millions; diluted shares use shares or million shares. The program normalizes scales. The diluted-share basis is positive and aligned to the valuation date or carries a specific alignment reason. FX gives direction, observation date, and source. Probabilities are omitted unless independently justified.

The local `compute valuation` CLI is implemented and freezes the request, result, typed Calculation, and input provenance. Check the assignment's actual tool map before invocation because native installation and release selection still require verification. Do not run improvised Python, spreadsheet arithmetic, or mental arithmetic as a substitute. Use the exact release launcher and a request file:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> compute valuation --request <REQUEST.json>
```

Read the returned `CallResult.status`, warnings, gaps, calculation reference, scenario applicability, and sensitivity cells. A parsed result is not proof that its research assumptions are true.

## Interpret without collapsing unlike concepts

Compare program results with the current quote only when both share a valid time, currency, and security basis. Separate:

- the fundamental value range from program scenarios;
- price or entry conditions that follow from the user's horizon and cited assumptions;
- technical levels derived from sourced price data;
- market-implied assumptions inferred from a declared comparison, clearly labeled as inference;
- milestones or evidence needed before an inapplicable method becomes usable.

Explain what current price would require operationally, how that differs from the research thesis, which input drives downside, and which evidence would narrow the range. Do not average DCF, peer multiples, analyst targets, and chart levels into one unsupported price.

## Handoff

Return method rationale, source and assumption references, full/component scope, reviewed request path, actual calculation ID/path or pending reason, applicable scenario values, sensitivities and failed cells, market-implied assumptions, warnings, missing inputs, and the valuation conditions the decision method may use. Keep `CallResult.status`, `WorkRecord.outcome`, and any later Decision label separate.

Archive only through the verified artifact command. Until T032 completes report-body and attachment freezing, a returned core record ID does not prove the full report and attachments were frozen. After a real archived record exists, use it as the source for a memory update; never overwrite a prior Decision or canonical calculation.
