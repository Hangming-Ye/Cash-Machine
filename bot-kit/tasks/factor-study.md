# T05 Single-stock factor study v0.3

Owner: Quant. Modes: `proposal` or `interpretation`.

Required: security, the discretionary decision to improve, horizon, available dataset/protocol registry, and baseline. Interpretation additionally requires an actual experiment receipt. Examples of decisions: trend confirmation, downside exposure during a pullback, or waiting after an earnings gap.

Proposal mode:
1. State one falsifiable hypothesis with an economic mechanism and an expected failure regime.
2. Select at most two registered variables and one protocol template. Specify observation time, earliest feasible decision/execution, target horizon and baseline.
3. Define the primary utility measure: entry improvement, excess return distribution, adverse excursion, turnover or another registered measure. Preserve costs and coverage/abstention.
4. Request protocol locking and program execution. If unsupported, return a development request, not an improvised formula implementation.

A novel hypothesis is allowed. If it needs a new registered formula, describe its inputs, lags/windows, economic mechanism and failure regime in `hypothesis` and `next_test`, leave registered_factor_ids empty, and return partial. The engineering path may implement/register it for a later run. Do not confuse a fixed validation workflow with a permanent ban on new factors.

Interpretation mode:
1. Confirm actual data vintage, timing, adjustments, validation windows, overlapping-label handling, tried candidates and execution/cost conventions.
2. Compare out-of-sample results with the registered baseline; describe uncertainty and effective evidence, not just the best window.
3. Inspect regime stability, drawdown, turnover and coverage. Identify when the current signal is unsupported or outside the historical range.
4. Conclude whether to use as description, continue exploration, retain as supporting evidence, or reject. State what future data would justify reopening.

Return `result` keys: `mode`, `decision_use`, `hypothesis`, `registered_factor_ids`, `protocol_id`, `experiment_ids`, `incremental_value`, `evidence_level`, `failure_regimes`, `next_test`.

No experiment means no performance conclusion. Negative/no-increment findings can be done. No unregistered search, holdout changes, success-probability invention, cross-sectional IC on one asset, or direct trade instruction.
