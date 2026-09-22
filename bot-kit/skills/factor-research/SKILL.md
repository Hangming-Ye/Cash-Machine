---
name: factor-research
description: Test a single-stock factor hypothesis built from approved operators, freeze validation, interpret program results, and record memory without buy/sell or fake increments.
---

# Factor Research

Use this Skill when the user asks whether an observable signal improves a discretionary decision for one security. It implements proposal and interpretation inside the existing Bot workflow: economic hypothesis → approved-operator expression → frozen validation request → program calculation → validation readout → incremental value, failure regimes, and next test. It supports human decisions and never submits, changes, or cancels an order.

## Start from a standalone assignment

Require the original question, authorized market and security scope, the discretionary decision to improve, horizon, timezone-aware `as_of`, baseline, dataset or protocol references, prior Decision when available, verified application directory and data root, actual tool map, owned draft path, completion checks, and downstream owner. Interpretation mode also needs an actual experiment receipt. Never depend on parent-chat context.

US, HK, and CN markets are runtime inputs for the current assignment. Do not treat them as a permanent whitelist. Ask before a material scope expansion or any supplier change. Do not reject a normal in-scope question merely because no same-name template exists.

## Recall before research

Create the current memory recall request using the research-memory Skill and run it with the exact verified launcher:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> memory recall --request <MEMORY_RECALL.json>
```

Keep the returned immutable MemoryPacket even when it has no hits. Record selected versions, gaps, and adopted or rejected items with reasons. Current research uses `context_mode: current`; historical and review modes keep their own cutoffs and cannot import later knowledge into the earlier view. Current user instructions and newly verified evidence outrank memory. Do not invent `mem_` IDs in the method text; cite only returned packet, topic, lesson, and artifact identifiers.

## Confirm actual capabilities

Read the current capability table in `bot-kit/README.md` and the assignment tool map before issuing a command.

- `data fetch`, `data ingest`, `check artifact`, and memory recall/apply are locally wired. Public fetch currently routes Finnhub quote/news, Tiingo bars, FMP stable profile/statements, and AKShare quote/bars/news/profile/statements, subject to enabled configuration, entitlement, and actual response coverage.
- IBKR Flex and Longbridge accounts/positions/executions route through the local read-only CLI when portfolio context is authorized. A failed read is never an empty portfolio.
- `compute valuation` runs the T030 engine when a candidate needs a valuation expectation.
- Factor calculation runs through the factor engine and the verified `compute factor` CLI when the tool map confirms it. Until that capability is present on the assignment, deliver a frozen protocol and the exact missing capability; do not fabricate statistics or claim execution.

Do not claim a pending operation ran. Do not invent data. Do not paste formulas into improvised Python, spreadsheets, or chat arithmetic as a substitute for the engine. For a wired source operation, copy the shape from the relevant synthetic fixture, replace every synthetic field, save JSON under the private task workspace, then use:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> data fetch --request <REQUEST.json>
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> data ingest --request <REQUEST.json>
```

Never put credentials, non-public holdings, or protected account identifiers in a shared request, report, prompt, or command line.

## Research method

Follow `bot-kit/tasks/factor-study.md`.

### 1. Form the hypothesis

State one falsifiable hypothesis with an economic mechanism and expected failure regimes. Name the discretionary decision, observation time, earliest feasible use time, target, horizon, bar interval, and baseline. A close signal is not an executable same-bar trade.

### 2. Build from approved operators only

Compose the expression and parameter sets only from the approved operator set in `fixtures/factors/expected.json` (`contract.allowed_operations`) and `specs/001-investment-research-framework/contracts/calculations.md`. New windows, thresholds, conditions, and parameter lists built from those operators are research work, not development requests. There is no registered-factor-ID gate and no “at most two registered variables” limit.

Stop clearly when the hypothesis needs a new primitive outside that set, or when the dataset lacks required fields or history. Report a data or primitive gap; do not invent a factor result. Authorized source follow-up and ingest may fill data gaps; they do not authorize new operators.

### 3. Freeze and calculate through the program

Freeze hypothesis, failure regimes, dataset_ref, expression, parameter_sets, target, horizon, bar_interval, baseline, available_time_rule, split, primary_metric, costs, and trial_group. Fit and parameter choice stay on the train partition. Separate exploration, validation, and final holdout. Then run only through the verified launcher when capability exists:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> compute factor --request <REQUEST.json>
```

Read status, warnings, gaps, frozen request references, experiment IDs, metrics, and validation artifacts. The model interprets; it does not recompute.

### 4. Interpret validation output

Confirm coverage, missingness, revisions, corporate actions, leakage controls, sample size, trial count, regime stability, costs, and baseline comparison. If trading simulation is unsupported, say the statistics are not executable returns. If the final holdout has been viewed, later claims about it are exploratory, not unseen. Separate descriptive association, exploratory evidence, out-of-sample support, and prospective confirmation.

### 5. Conclude without trade instructions

State incremental value or `no_factor_increment`, applicable and failure regimes, evidence level, and what would justify reopening. Do not emit buy/sell. `no_factor_increment` can be a complete research result and is not an execution failure.

When a decision-critical source is missing or conflicting, invoke the source-followup Skill. Try another approved existing integration, then company IR, exchange or regulator filings, and attributable public web material. Keep attempts and gaps. Do not add a vendor.

## Decision and result classes

Distinguish:

- utility `CallResult.status`: `ok`, `partial`, or `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, or `failed`;
- research result class: complete research, limited evidence, `no_factor_increment`, or execution failure.

Rules:

- A supported no-increment result can be `WorkRecord.outcome: complete`.
- Missing decision-critical data or a missing primitive makes only the affected claims limited or stopped; do not fabricate performance.
- Failure to run the method or verified compute path when required is `failed`.
- Holding labels `buy` / `sell` belong to company or portfolio synthesis methods, not this factor study.

## Review, archive, and memory

Use the unified phone/PC report template. Include hypothesis and mechanism, expression/parameter summary, protocol and experiment references, validation readout, incremental value or no-increment, failure regimes, gaps, next check, and memory use.

Draft a WorkRecord with real references, then archive only through the verified command:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> check artifact --request <ARCHIVE_REQUEST.json> --archive
```

Only a returned immutable ID or path proves the core record exists. Do not overwrite prior history.

After a real archived record exists, follow the research-memory Skill. Write the judgment summary into a topic update only for an evidence-backed change; propose a lesson only when review identifies a reusable check. Reference the archived record, preserve conditions and counterexamples, use the returned expected version, and retain old versions. If nothing material changed, record `no_change` instead of duplicating it.
