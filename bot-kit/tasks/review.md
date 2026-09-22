# Evidence and reasoning review v1.0

Use this method to check a draft before final delivery or after a targeted repair. This is a quality-review workflow. Its verdict (`pass`, `revise`, or `blocked`) is not the historical `Review` entity from `cash_research.models`.

## Inputs

The reviewer receives a standalone brief containing:

- draft report and proposed Decision/WorkRecord fields;
- question, authorized scope, identities, horizon, and timezone-aware cutoff;
- immutable source, calculation, experiment, and memory packet references;
- source locators, availability limits, assumptions, and known conflicts;
- the method-specific completion checks;
- prior review issues and changed claims for a repair pass.

If these inputs are missing, identify the exact item and affected claim. Do not reconstruct evidence from another Bot's confidence or parent-chat context.

## Review procedure

1. Select claims that can change the conclusion, price/conditions, horizon, candidate inclusion, factor evidence level, or research completeness.
2. Open the cited source or calculation artifact. Confirm entity, segment, date, availability time, units, currency, scope, and locator. A mention is not support for the precise claim.
3. Check the reasoning chain and strongest alternative explanation. Look for unsupported jumps from demand to company exposure, qualification to orders, orders to revenue, revenue to cash flow, or event timing to price causality.
4. Check method-specific evidence:
   - company/supply chain: bottleneck durability, substitutes, materiality, commercialization, balance sheet, valuation expectations, and contrary evidence;
   - holding/valuation: timestamped position and price, method suitability, sourced inputs versus assumptions, net debt, dilution, sensitivity, and actual calculation receipt;
   - factor: economic hypothesis, frozen request, available-time rule, leakage, trial history, split/holdout, baseline, costs, uncertainty, and claimed validation level;
   - memory/review: packet actually available at cutoff, adopted/rejected reason, original-decision inputs separate from later facts, and no backfilled lesson.
5. Check boundaries: no orders, no invented or leaked private data, no pending tool described as executed, and utility status/execution outcome/Decision label kept distinct.
6. Preserve valid partial work. Missing optional material is not a universal veto; missing decision-critical evidence limits or blocks only the affected conclusion.

Do not use Bot agreement, majority, confidence language, or a fixed score as proof. Do not silently recalculate, rewrite canonical files, or expand scope.

## Quality-review output

- **Verdict**: `pass`, `revise`, or `blocked`.
- **Accepted scope**: claims and sections that remain supportable.
- **Strongest counter-case**: sourced alternative explanation or explicit evidence limitation.
- **Issues**: for each actionable issue provide exact claim/field, severity (`blocking`, `material`, `minor`), evidence/calculation reference, defect, impact, responsible method, and required result.
- **Recheck scope**: changed claims and any consequential dependent claims that must be checked after repair.

`pass` means no material defect found within the stated scope and available evidence. It does not guarantee completeness, future returns, or correctness beyond that scope. `revise` routes concrete findings to the responsible researcher for targeted evidence or correction. `blocked` identifies the unavailable required evidence/calculation and the exact consequence.

There is no arbitrary one-pass or issue-count limit. Recheck after material repair; stop when issues are resolved, explicitly limited, or unchanged because the required evidence remains unavailable.

## Historical Review entity

Create a historical `Review` only when evaluating an archived Decision against later facts at a real `review_at`. Use the actual model fields: `review_id`, `decision_id`, `decision_as_of`, `review_at`, `observed_outcome`, `process_findings`, `counterevidence`, and `lesson_refs`. Keep the original Decision and its frozen `memory_packet_refs` separate from later facts. Archive the Review before using it as a lesson source.

An ordinary pre-publication quality verdict does not automatically satisfy those fields and must not be serialized or described as a historical Review. Record it as the quality-review artifact referenced by the coordinating WorkRecord/report annex.
