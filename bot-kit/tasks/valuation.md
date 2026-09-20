# T04 Valuation assumptions and interpretation v0.3

Owner: Research. Modes: `assumptions` or `interpretation`.

Required: company thesis, valuation date/horizon, currency, available financial/share/debt inputs, current quote if a current-price conclusion is requested. The packet specifies the permitted calculation methods. Missing quotation blocks current upside/entry conclusions but not a supported valuation-method discussion.

Assumptions mode:
1. Select an appropriate method from permitted methods: earnings/cash-flow multiple, enterprise-value bridge, DCF, asset-based or segment valuation. Explain why and what makes it unsuitable if inputs fail.
2. Define relevant peers and exclusions using business model, growth, margin, balance sheet and fiscal basis. Cheap headline multiples alone do not establish value.
3. Supply bear/base/bull input sets with units, periods, source IDs and assumption labels. Include net debt, diluted shares and financing when material.
4. Name the decisive sensitivities, what the current price may be assuming, and the evidence needed to narrow the range. Send the input set to the program; do not invent computed prices.

Interpretation mode:
1. Read the actual calculation receipt and flags. Check that method and inputs match the intended thesis.
2. Explain fair-value ranges, sensitivity and downside. Distinguish fundamental value, required-return entry ceiling and technical timing.
3. Retain uncertainty, conflicting peer logic and failed scenarios. Do not average analyst targets, DCF outputs and chart support levels.

Return `result` keys: `mode`, `method`, `peer_rationale`, `scenario_inputs`, `calculation_ids`, `valuation_read`, `sensitivities`, `missing_inputs`.

In assumptions mode calculation_ids may be empty and valuation_read must not claim computed values. In interpretation mode use null for unsupported cases, not invented prices. Early unprofitable businesses may require milestones/funding scenarios instead of a spurious precise DCF.
