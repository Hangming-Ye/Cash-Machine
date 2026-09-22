# Event, earnings, preview, and macro impact v1.0

Use this composable method when the assignment needs to determine what changed, what was expected, and how the change reaches a company, industry, or valuation. It may be combined with company, holding, supply-chain, valuation, source-followup, or review methods. The assignment must provide the question, authorized scope, identity, horizon, timezone-aware `as_of`, prior thesis/cutoff when available, source references, actual tools, output path, and completion standard. Do not depend on the parent conversation or a legacy task ID.

## Method

1. Cluster reports that trace to the same original event. Separate a new disclosure, correction, changed expectation, and recycled story. Preserve original locators, authors, publication/event/availability times, access limits, and the cutoff used.
2. Extract reported facts, management statements, analyst or social views, assumptions, and inferences separately. Repeated articles or posts are not independent confirmation. Use the source-followup Skill for a decision-critical missing original or conflict.
3. Compare the correct period and definition with the prior thesis, forecast, guidance, or timestamped pre-event expectation. Preserve units, currency, accounting basis, and source. If a comparable baseline is unavailable, state which comparison cannot be made.
4. Trace transmission through demand, price/mix, revenue, cost/margin, cash flow, balance sheet, funding or capital spending, competitive position, regulation, discount rate, and valuation assumptions as applicable. Identify one-offs and the strongest supported opposing explanation. Do not infer price causality from timing alone.
5. State what changed, what did not, what remains only a lead, which conclusion is affected, and the evidence or future event that can resolve it. The number of questions and checks follows materiality; there is no fixed cap.

## Mode-specific checks

- **Event**: identify factual change, expectation change, affected driver, thesis effect, reaction context, and alternative explanations.
- **Earnings**: compare actuals with the matching prior period, prior guidance, and pre-release consensus only when each is available before release. Cover segment drivers, margin quality, cash conversion, balance-sheet effects, one-offs, guidance, and changes to the forecast. Never use a post-release estimate as the pre-release bar.
- **Preview**: identify decision-relevant KPIs, evidence-backed expectation ranges, proof points, and scenarios. Mark a proposed threshold as a research hypothesis unless already approved or inherited from an archived decision; never invent a missing consensus.
- **Macro/policy**: connect the stated change to actual entity exposure and the transmission path, timing, currency, countervailing forces, and valuation variable. A generic macro summary is insufficient.

For analyst research and social material, retain original-source status, author, time, coverage, access right, and opposing views. An accessible excerpt is an excerpt; without full text do not claim the report or thread was reviewed. Zero retrieved posts is missing coverage, not neutral sentiment. A news API or quote cannot replace the underlying research or social source.

## Output and records

Return the mode, event clusters and evidence references, factual and expectation changes, financial transmission, price/reaction calculation references when available, opposing interpretation, coverage limits, affected conclusion, and material next checks. Earnings output also identifies comparable actual/forecast/prior fields and earnings quality; preview output identifies expectation bars and threshold provenance; macro output identifies entity exposure and transmission.

Keep execution and judgment separate. `WorkRecord.outcome` is `complete`, `limited`, or `failed`; a missing original source or required comparison makes only the affected scope limited. The investment Decision label is produced by the responsible synthesis method, not by this method alone. Nothing changing the thesis can be a complete event-analysis result.

Draft the WorkRecord and related research output with their actual input/output references. Review and archive critical research through `check artifact --archive`; only a returned immutable record ID/path may support later historical review or memory updates. Do not overwrite the prior Decision. After review, use the research-memory Skill to record evidence-backed thesis changes, unresolved questions, or reusable checks while retaining contrary evidence and old versions.
