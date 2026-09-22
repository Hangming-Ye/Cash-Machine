# Supply-chain discovery and candidate screening v1.1

Use this method when the assignment starts from a theme, system, demand shift, or open-ended industry question and needs a breadth-first manufacturing-process map down to materials, quantified downstream demand, bottleneck test, price-in judgment, profit realization, program valuation handoff, and counterevidence. It may hand off to company-thesis, valuation, source-followup, review, or memory methods. It does not submit, modify, or cancel an order.

## Standalone inputs

The assignment states the theme or question, authorized market and security scope (US/HK/CN as runtime inputs, not a permanent whitelist), research horizon, timezone-aware `as_of`, any initial candidate universe, source packet and prior Decision when available, actual MemoryPacket reference, tool map, owned output path, and completion standard. Do not depend on the parent conversation or a legacy task ID.

A theme may come from program screening or a user question. Do not require a preselected winning company. Do not reject a normal in-scope question merely because no same-name template exists. Ask the user before a material scope expansion or any supplier change.

## Method

There is no fixed candidate count, layer count, source count, or retry cap. Add in-scope stages, substitutes, and companies when evidence requires them. Stop a path when it is unavailable, duplicative, outside the cutoff, or unlikely to change the conclusion. Required stages run in order and leave separate frozen artifacts for the next stage. An early lead file may exist mid-run; it is not the user-facing conclusion. Do not treat a limited evidenced map, a stop at major components, or `valuation_status: not_applicable` as a finished user answer. Skipping the chain is not “no opportunity.”

1. **BFS manufacturing process map (toward materials).** Start from the manufacturing process of the current system. Breadth-first: list the full frontier of process steps, components, and constituting materials at this layer before any recursion—each with the company that handles it, the part or role owned, and same-step competitors. Evidence or explicit unknown on every item. A named component (for example an optical module) is not an opaque leaf when it is itself made from materials, substrates, and process steps. This step writes the map only; it does not fill `shortage_queue`. Listing a few famous names, or depth-first drilling into one famous company and stopping, is not a process map. User illustration only: an inference server uses optical modules; if a later shortage test judges the module short, further decompose that module’s chain—method motive, not a return multiple, and no required ticker.
2. **Quantified downstream demand.** Quantify end demand with sourced units, period, and geography. Plans, guidance, and forecasts remain labeled as such. News heat alone is not demand. Do not enqueue during this step.
3. **Shortage / bottleneck test.** This is the only shortage test. On named frontier nodes, test the proposed constraint with capacity, yield, lead time, qualification, or expansion. Unknown capacity is unknown, not automatic scarcity. A short supplier list or hard technology is insufficient by itself. For every bottleneck claim, state how a customer can substitute, dual-source, redesign, inventory-buffer, or wait, and on what timeline. Do not run an earlier or weaker shortage screen.
4. **Enqueue and recurse after the test.** A frontier node enters `shortage_queue` only after step 3 judged it a shortage or bottleneck. Non-shortage and unknown nodes stay on the map and are not recursed. Each queued node becomes the next system and is decomposed with the same BFS. The queue file is the next stage’s frozen artifact—not a graph database, scheduler, or state machine. Do not invent a shortage to justify another layer. If evidence cannot split a node further, record that stop and its effect. Do not write the queue before step 3 exists.
5. **Company exposure and profit realization.** Map companies only to specific process roles with evidence of product, process, qualification, production, order, shipment, or revenue. Development, sampling, and qualification are earlier stages than orders or recognized revenue; do not advance a stage by implication. A parent ticker does not prove a subsidiary exposure is material. For each surviving exposure, explain how the company could capture value: exposure size or share of revenue, price/volume, margin, working capital, capex, funding, and dilution. Sitting at a bottleneck is not a recommendation.
6. **Price-in.** Compare bottleneck economics with related security prices using program valuation versus a sourced quote. State whether the bottleneck is already priced in. Do not recommend from industry position alone.
7. **Program valuation handoff.** When valuation is applicable, use `bot-kit/tasks/valuation.md` and the verified `compute valuation` capability. Do not copy valuation formulas into this method. Analyst targets and pasted press-release figures are not a calculation. Mid-run early leads may temporarily leave valuation pending with a reason; that pending state does not finish a user-requested study. After recorded follow-up, if a stated input is still missing, record inapplicability and keep only the blocked price conclusion limited—do not mark the whole requested study complete.
8. **Counterevidence and exclusions.** Build the strongest evidence-backed opposing case: substitution, capacity response, customer delay, financing failure, immaterial exposure, or already-priced expectation. If evidence rejects the original theme framing, keep the rejection reason and continue inside the authorized scope only after the process map and the tests evidence can support. Record examined competing routes and rejected companies with reasons. Do not invent a candidate to fill a quota.

## Source fallback

Use only the existing six integrations—Finnhub, Tiingo, FMP stable, AKShare, IBKR Flex, and Longbridge OAuth—then company IR, exchange or regulator filings, and attributable public web material. Treat web search, filings, and user-provided material as evidence channels, not new suppliers. For decision-critical gaps or conflicts, follow the source-followup Skill. Record every attempt, locator, result class, and remaining gap. Do not invent capacity, orders, margins, or prices.

Brokerage access is read-only when portfolio context is authorized. A read failure is not an empty portfolio.

## Status, labels, and outputs

Keep execution and judgment separate:

- utility `CallResult.status`: `ok`, `partial`, or `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, or `failed`;
- research result class: complete research, limited evidence, no qualified opportunity, method defect, or execution failure;
- Decision label when this method synthesizes the theme screen: `watch` for an evidence-supported continue case after required stages, or `no_opportunity` when the screen finds no qualified opportunity after the process map and supported tests.

A supported no-candidate or no-opportunity result can be `WorkRecord.outcome: complete` only after the process map and the tests evidence can support. It is not an execution failure. Missing a required stage, stopping at major components, or skipping BFS-to-materials is a method defect under FR-014, not complete research and not an acceptable “limited” finish of a study the user asked to complete. Missing decision-critical evidence after follow-up makes only the affected claims `limited`. Failure to execute the method is `failed`. Do not force a positive candidate or attach arbitrary success probabilities.

Return separate stage artifacts (paths), not one combined essay:

- `process_map`: current-layer BFS frontier—process steps, components, and materials to the materials leaf rule; companies, roles/parts owned, same-step competitors; evidence IDs or unknowns;
- `shortage_queue`: frozen list of nodes that the completed bottleneck test judged shortage or bottleneck, awaiting their own process map (empty with reason when none). Do not write this file before `bottleneck_test`.
- `company_competitor_table`: companies by step with role and competitors;
- `downstream_demand`: quantified change with period/units/geography, forecast labels, evidence, unknowns;
- `bottleneck_test`: named stage, mechanism, capacity/yield/lead-time/qualification/expansion evidence, substitution paths;
- `price_in`: program valuation versus sourced quote, whether bottleneck economics are priced in;
- `profit_realization`: exposure and capture path, or why it fails;
- `valuation_handoff`: calculation reference, or recorded inapplicability after follow-up;
- `exclusions_and_rejects`: examined competing routes or companies with reasons;
- `screen_result`: complete research, limited evidence, no qualified opportunity, or method defect, with what to watch next;
- Decision fields when applicable: label (`watch` or `no_opportunity`), horizon/expiry, conditions or null with reason, risks, invalidators, gaps, and next check.

## Records and memory

Draft the WorkRecord and any Decision with real evidence and calculation references. Present the user-facing conclusion in Chinese through the shared report template only when required stage files exist or a stage records a real blocker. Run source-based quality review, then archive only through the verified `check artifact --archive` command. Only a returned immutable ID or path may support later historical review or memory updates.

After a real archived record exists, follow the research-memory Skill. Apply a topic or lesson update only for an evidence-backed change; return `no_change` when nothing material changed. Current user instructions and newly verified evidence outrank memory.
