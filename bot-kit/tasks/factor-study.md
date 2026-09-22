# Single-stock factor study v1.0

Use this method to test whether an observable combination improves a stated discretionary decision for one security. Modes: `proposal` or `interpretation`. It supports human decisions and never submits, modifies, or cancels an order. The program calculates through the factor engine; the model does not paste executable formulas, invent statistics, or emit buy/sell labels.

## Standalone inputs

Required: security identity, the discretionary decision to improve, horizon, timezone-aware cutoff, available dataset or protocol registry, baseline, verified tool map, owned draft path, and the current MemoryPacket from a pre-work memory recall (follow `bot-kit/skills/research-memory/SKILL.md`). Interpretation additionally requires an actual experiment receipt. Examples of decisions: trend confirmation, downside exposure during a pullback, or waiting after an earnings gap.

Do not invent `mem_` IDs, experiment IDs, or archive paths in the method text. Use only returned packet, topic, lesson, experiment, and artifact identifiers.

## Approved operators and new combinations

Build formulas and parameters only from the approved operator set in `fixtures/factors/expected.json` (`contract.allowed_operations`) and `specs/001-investment-research-framework/contracts/calculations.md`:

`field`, `constant`, `add`, `subtract`, `multiply`, `safe_divide`, `abs`, `sign`, `log`, `clip`, `gt`, `gte`, `lt`, `lte`, `and`, `or`, `where`, `weighted_sum`, `lag`, `delta`, `pct_return`, `log_return`, `rolling_sum`, `rolling_mean`, `rolling_median`, `rolling_min`, `rolling_max`, `rolling_std`, `rolling_quantile`, `rolling_rank`, `rolling_corr`, `rolling_cov`, `ewm_mean`, `ewm_std`, `asof_value`, `event_age`.

A novel hypothesis that reuses these operators with new windows, thresholds, conditions, or parameter sets is normal research work. There is no “at most two registered variables” limit and no requirement that a missing registered factor ID send the work to engineering. Convenience names expand to the same expression tree; they do not add execution rights. Never run arbitrary Python, `eval`, SQL, shell, or free-text formula execution.

## Stop for primitive or data gaps

Stop and report a gap—not a fake factor result—when:

- the hypothesis needs a new primitive outside the approved operator set; or
- the dataset lacks required fields, available-time history, adjustment/corporate-action coverage, or bar interval needed for the claim.

Record the exact missing primitive or field, what was attempted through authorized sources or ingest, and which independently supported claims remain. A bounded engineering request is appropriate only for a genuine new primitive or data capability, never for a legal combination of existing operators.

## Proposal mode

1. State one falsifiable hypothesis with an economic mechanism (why the signal should relate to the decision) and expected failure regimes (when it should break, abstain, or reverse).
2. Define the expression from approved operators and the parameter sets to try. Specify observation time, earliest feasible decision or execution time, target, horizon, bar interval, baseline, available-time rule, split, primary metric, costs, and trial group. A close-generated signal is not an executable same-bar trade; state the earliest usable time from data and market rules.
3. Define the primary utility measure: entry improvement, excess-return distribution, adverse excursion, turnover, coverage/abstention, or another declared measure. Preserve costs and coverage.
4. Freeze the complete request shape, then ask the program to lock and execute through the verified factor capability. Do not improvise local arithmetic as a substitute.

## Interpretation mode

1. Confirm actual data vintage, timing, adjustments, validation windows, overlapping-label handling, tried candidates, costs, and execution conventions from the experiment receipt and warnings.
2. Compare out-of-sample results with the registered baseline. Describe uncertainty, sample size, trial multiplicity, and effective evidence—not only the best window.
3. Inspect regime stability, drawdown, turnover, and coverage. Identify when the current signal is unsupported or outside the historical range.
4. Read validation output explicitly:
   - coverage, missingness, revision, and corporate-action warnings;
   - train / validation / final-holdout partitions and whether labels overlapped;
   - that fit and parameter choice stayed on the train partition;
   - whether trading simulation was supported; if not, treat reported next-period statistics as research distributions, not executable returns;
   - whether the final holdout was viewed—if so, label later use exploratory, not unseen.
5. Conclude whether to use as description, continue exploration, retain as supporting evidence, or reject. State what future data would justify reopening. `no_factor_increment` is a valid complete research result, not an execution failure.

## Status, labels, and outputs

Keep execution and judgment separate:

- utility `CallResult.status`: `ok`, `partial`, or `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, or `failed`;
- research result class: complete research, limited evidence, `no_factor_increment`, or execution failure.

Rules:

- No experiment receipt means no performance conclusion.
- Negative or no-increment findings can be complete.
- Do not emit buy/sell. Factor output informs a discretionary decision; holding labels belong to synthesis methods.
- No unregistered operator search, holdout feedback into the same-round fit, success-probability invention, cross-sectional IC as the default single-asset validity claim, or direct trade instruction.

Return `result` keys: `mode`, `decision_use`, `hypothesis`, `expression_or_factor_refs`, `protocol_id`, `experiment_ids`, `incremental_value`, `evidence_level`, `failure_regimes`, `validation_readout`, `next_test`.

## Records and memory

Draft the WorkRecord with real experiment, evidence, and calculation references. Present the user-facing conclusion in Chinese through the shared report template. Archive only through the verified `check artifact --archive` command. Only a returned immutable ID or path may support later review or memory updates.

After a real archived record exists, follow the research-memory Skill. Apply a topic or lesson update only for an evidence-backed change; return `no_change` when nothing material changed. Current user instructions and newly verified evidence outrank memory.
