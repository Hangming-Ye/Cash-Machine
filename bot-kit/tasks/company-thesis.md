# Company thesis evaluation v1.0

Use this method to evaluate whether a company sitting on a stated industry change is a researchable candidate, an early lead, or not an opportunity. It does not issue a buy/sell label. Bottleneck position alone is never a recommendation.

## Standalone inputs

The assignment states the security or entity identity, the researched industry change or theme, the research question, horizon, timezone-aware cutoff, and actual tool map. Include company filings or primary operating material, any supply-chain or industry evidence already collected, prior thesis when relevant, and the current MemoryPacket from a pre-work memory recall (follow `bot-kit/skills/research-memory/SKILL.md`). Optional: segment tables, peers, consensus, capacity or order evidence, and a prior valuation calculation reference.

Missing primary business material that would establish exposure to the stated change blocks a full company thesis; a clearly labeled narrower source summary may be `partial`. Unknown values remain unknown. Do not invent revenue, capacity, timing, or implied expectations to complete the method.

## Before work

1. Recall research memory for this question, security, and theme using the verified `memory recall` path in the research-memory skill. Record which recalled items are adopted or rejected and why. `no_history` is a valid input state, not a failure.
2. Confirm the industry change under study and the company's claimed chain role. Do not treat a generic attractive business as exposure to this change.

## Evaluate exposure, response, timing, and counterevidence

Work the checks in order. Keep every material numeric claim tied to a source or calculation ID.

1. **Business exposure to the stated change**  
   State how the company participates in the researched industry change: relevant segment, customer, product, volume/price mechanism, recurring versus project nature, and the path from the change to revenue, margin, or cash. Separate theme adjacency from economically material exposure. A company may have a strong revenue engine that is unrelated to this change; say so and do not promote it as a candidate for this theme.

2. **Competitive and capacity / supply response**  
   Examine competitors, substitutes, customer concentration, switching or qualification barriers, existing and announced capacity, funding for expansion, and how fast supply can respond. Distinguish claimed moat from measured economics. Capacity that is unknown stays unknown; do not equate bottleneck rhetoric with durable scarcity.

3. **Commercial realization timing**  
   Place the company on a commercialization path with dated or windowed evidence: development, sampling, qualification, production, order, shipment, or revenue. State when commercial realization would show up in reported or observable metrics under the research horizon. Do not advance a stage by implication. Missing current revenue is a stage fact, not automatic rejection.

4. **Valuation expectations**  
   Hand off to `bot-kit/tasks/valuation.md` and the existing `compute valuation` CLI when the economics can be expressed with sourced inputs. The program calculates; do not paste DCF, multiple, SOTP, or other formulas into this task, and do not improvise arithmetic. Analyst targets and pasted press-release figures are not a calculation. News, guidance, and a quote alone are not the quantitative path.  
   - Build or refresh the valuation request per the valuation task, invoke the verified launcher, and interpret returned scenarios against cited operating assumptions and a sourced quote (which operating assumptions the price already implies). Separate fundamental range, market-implied expectations, and catalysts that would change either.  
   - `valuation_status: not_applicable` only after a recorded follow-up shows a stated input is still missing; that blocks the price conclusion only. It does not finish a user-requested company or holding judgment, and does not turn a mid-run early lead into a complete user answer.  
   Check the assignment's actual tool map before invocation:

   ```text
   uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> compute valuation --request <REQUEST.json>
   ```

5. **Catalysts and strongest counterevidence**  
   List measurable proof points and catalysts with source, due window, and what would confirm or disconfirm. Inspect the strongest contrary evidence and state what would kill the thesis (exposure fails, supply floods, timing slips beyond the horizon, implied expectations already price in the bull case, or a competing outcome dominates). Preserve unresolved conflict rather than compressing it away.

## Early lead versus researchable candidate

| Label | Meaning |
| --- | --- |
| `early_lead` | Theme-linked exposure hypothesis exists, but commercialization stage, competitive/supply response, timing, or valuation inputs remain incomplete mid-run. Useful for follow-up; not a recommendation and not a finished user-facing conclusion for a requested study. |
| `researchable_candidate` | Exposure to the stated change, competitive and supply response, realization timing, program valuation (or recorded inapplicability after follow-up that only limits the price conclusion), catalysts, and kill conditions have all been checked with cited evidence. Still not a buy/sell decision. |
| `no_opportunity` | After the checks above, the company is not a qualified opportunity for this theme and horizon. Valid research result, not an execution failure. |
| `rejected` | Evidence affirmatively overturns the thesis for this company and theme. |
| `blocked` / `partial` | Required inputs missing or only a narrower source summary is possible. Method defect or evidence limit is labeled separately from `no_opportunity`. |

Do not force a positive candidate, attach arbitrary success probabilities, or apply a numeric cap on drivers or candidates. Do not add a supplier, submit or modify an order, or introduce a scheduler.

## Handoff outputs

Return:

- `industry_change`: the researched change and the company's claimed role.
- `business_exposure`: segment/customer/product/economic link to that change, or explicit non-exposure.
- `competitive_and_supply_response`: competition, substitution, capacity/expansion, and evidence IDs.
- `realization_timing`: commercialization stage, expected proof window, and horizon fit.
- `valuation_handoff`: method chosen via the valuation task, request/calculation reference or `not_applicable` reason, and implied expectations versus thesis (no pasted formulas).
- `catalysts_and_counterevidence`: proof points, strongest contrary case, and kill conditions.
- `thesis_status`: one of `early_lead`, `researchable_candidate`, `no_opportunity`, `rejected`, `partial`, `blocked`, or `unknown`, with concise rationale.
- `next_research_question`: the single best next check, not an unsupported target price.

A company may be a good business while its stock is unattractive; price/action judgment belongs to the decision method after valuation and thesis checks. `no_opportunity` delivers screening basis, exclusion reasons, and watch conditions without inventing a candidate to fill a quota.

## After work

Archive the underlying Decision, WorkRecord, or Review through the verified artifact command before citing it as a memory source. After a real archived record exists, update memory only for an evidence-backed change to thesis, support, opposition, open questions, or next checks; otherwise return `no_change` with the existing version and reason. Follow the research-memory skill for recall, apply, and version conflict handling. Never overwrite a prior Decision or canonical calculation.
