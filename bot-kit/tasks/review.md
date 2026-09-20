# T07 Evidence and reasoning review v0.3

Owner: Reviewer.

Required: draft result(s), original source packet with cited locators, program validation/calculation receipts, task scope and previous review issues if this is a repair pass.

Do:
1. Select the highest-impact claims: those changing the research stance, price conditions, thesis status or factor evidence level.
2. Verify cited sources support the exact claims and the correct entity/date/unit. Inspect contrary evidence and source dependence.
3. Check for economic leaps, wrong expectation baselines, inappropriate valuation methods, unsupported experiment claims and mixing of horizons.
4. Compare stated figures and constraints against program receipts. Do not replace the program with your own undocumented arithmetic.
5. Report only actionable issues and the narrow scope each affects; preserve valid partial work and reasonable labeled assumptions.

Return `result` keys:
- `verdict`: pass, revise or blocked.
- `issues`: claim_id or exact field, severity (`blocking`, `material`, `minor`), evidence/calculation IDs, finding, required_repair, affected_output.
- `strongest_counter_case`: supported alternative explanation, or the stated evidence limitation.
- `accepted_scope`: what remains supportable.

Pass means no identified blocking problem within this bounded review; it does not guarantee completeness or returns. Do not demand new data unrelated to the task, require a positive opportunity, or initiate another debate. A second pass checks the specified repairs and any new consequential changes.
