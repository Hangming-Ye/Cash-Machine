# Supply-chain discovery and candidate screening v1.0

Use this method when the assignment starts from a theme, system, demand shift, or open-ended industry question and needs demand change, chain stages, bottlenecks, substitutes, company exposure, profit realization, and counterevidence. It may hand off to company-thesis, valuation, source-followup, review, or memory methods. It does not submit, modify, or cancel an order.

## Standalone inputs

The assignment states the theme or question, authorized market and security scope (US/HK/CN as runtime inputs, not a permanent whitelist), research horizon, timezone-aware `as_of`, any initial candidate universe, source packet and prior Decision when available, actual MemoryPacket reference, tool map, owned output path, and completion standard. Do not depend on the parent conversation or a legacy task ID.

A theme may come from program screening or a user question. Do not require a preselected winning company. Do not reject a normal in-scope question merely because no same-name template exists. Ask the user before a material scope expansion or any supplier change.

## Method

There is no fixed candidate count, layer count, source count, or retry cap. Add in-scope stages, substitutes, and companies when evidence requires them. Stop a path when it is unavailable, duplicative, outside the cutoff, or unlikely to change the conclusion.

1. **Demand change.** Identify what changed in end-user demand, technology, regulation, cost, or capacity. Quantify the changed unit demand with sourced period, units, and geography when available. News heat alone is not demand. Plans, guidance, and forecasts remain labeled as such.
2. **System and process map.** Decompose the economically relevant end system into components, materials, processes, capacity nodes, customers, and geographic constraints that the demand change actually touches. Prefer a limited evidenced map over a speculative comprehensive graph. Record every node and relation with evidence references or an explicit unknown.
3. **Bottleneck and substitutes.** Test the proposed constraint with lead time, effective capacity, yield, qualification, inventory, concentration, expansion timing, financing, and competing routes. Unknown capacity is unknown, not automatic scarcity. A short supplier list or hard technology is insufficient by itself. For every bottleneck claim, state how a customer can substitute, dual-source, redesign, inventory-buffer, or wait, and on what timeline.
4. **Company exposure.** Map companies only to specific chain roles with evidence of product, process, qualification, production, order, shipment, or revenue. Development, sampling, and qualification are earlier stages than orders or recognized revenue; do not advance a stage by implication. A parent ticker does not prove a subsidiary exposure is material. Add an adjacent in-scope company when new evidence requires it, and record why. Exclude or keep as leads when the relation is weak, anonymous without corroboration, or outside authorized markets.
5. **Commercial and profit realization.** For each surviving exposure, explain how the company could capture value: exposure size or share of revenue, price/volume, margin, working capital, capex, funding, and dilution. Distinguish a real supply-chain relation from a material profit contribution. Sitting at a bottleneck is not a recommendation.
6. **Valuation handoff.** When a candidate needs a valuation expectation, use `bot-kit/tasks/valuation.md` and the verified `compute valuation` capability. Do not copy valuation formulas into this method. Early leads may leave valuation null with a reason; they are not buy recommendations. Investment-candidate output requires business and valuation follow-up before price-dependent conclusions.
7. **Counterevidence and exclusions.** Build the strongest evidence-backed opposing case: substitution, capacity response, customer delay, financing failure, immaterial exposure, or already-priced expectation. If evidence rejects the original theme framing, keep the rejection reason and continue inside the authorized scope with the revised demand or chain question. Record examined competing routes and rejected companies with reasons. Do not invent a candidate to fill a quota.

## Source fallback

Use only the existing six integrations—Finnhub, Tiingo, FMP stable, AKShare, IBKR Flex, and Longbridge OAuth—then company IR, exchange or regulator filings, and attributable public web material. Treat web search, filings, and user-provided material as evidence channels, not new suppliers. For decision-critical gaps or conflicts, follow the source-followup Skill. Record every attempt, locator, result class, and remaining gap. Do not invent capacity, orders, margins, or prices.

Brokerage access is read-only when portfolio context is authorized. A read failure is not an empty portfolio.

## Status, labels, and outputs

Keep execution and judgment separate:

- utility `CallResult.status`: `ok`, `partial`, or `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, or `failed`;
- research result class: complete research, limited evidence, no qualified opportunity, or execution failure;
- Decision label when this method synthesizes the theme screen: `watch` for an early lead or evidence-limited continue case, or `no_opportunity` when the screen finds no qualified opportunity.

A supported no-candidate or no-opportunity result can be `WorkRecord.outcome: complete`. It is not an execution failure. Missing decision-critical evidence makes only the affected claims `limited`. Failure to execute the method is `failed`. Do not force a positive candidate or attach arbitrary success probabilities.

Return:

- `demand_change`: mechanism, quantified change when supported, period/units/geography, evidence references, and unknowns;
- `system_map`: evidenced nodes and relations with evidence IDs; unknowns remain explicit;
- `bottleneck_hypothesis`: mechanism, supporting and contrary evidence, expected duration, and substitution paths;
- `candidates`: security or entity when known, chain role, maturity stage, exposure evidence, profit hypothesis, status (`lead`, `deepen`, `reject`, `unknown`), valuation status or handoff note, and next proof;
- `exclusions_and_rejects`: examined competing routes or companies with reasons, or an explicit statement that evidence was too thin to examine alternatives;
- `screen_result`: complete research, limited evidence, or no qualified opportunity, with what to watch next;
- Decision fields when applicable: label (`watch` or `no_opportunity`), horizon/expiry, conditions or null with reason, risks, invalidators, gaps, and next check.

## Records and memory

Draft the WorkRecord and any Decision with real evidence and calculation references. Present the user-facing conclusion in Chinese through the shared report template. Run source-based quality review, then archive only through the verified `check artifact --archive` command. Only a returned immutable ID or path may support later historical review or memory updates.

After a real archived record exists, follow the research-memory Skill. Apply a topic or lesson update only for an evidence-backed change; return `no_change` when nothing material changed. Current user instructions and newly verified evidence outrank memory.
