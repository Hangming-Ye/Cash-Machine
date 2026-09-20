# T03 Supply-chain discovery v0.3

Owner: Research. Output mode: `early_leads` or `investment_candidates`.

Required: theme/system, demand change, research horizon, source packet and any initial candidate universe. The theme may originate from program screening or a user question; do not require a preselected winning company.

Do:
1. Decompose the end system into the economically relevant components, materials, processes and capacity. Identify the changed unit demand rather than listing an entire industry.
2. Test the proposed bottleneck using lead time, capacity, yield, qualification, substitution and expansion timing. Unknown capacity is unknown, not automatically scarcity.
3. Map up to three candidate companies to specific roles. Record evidence for development, sampling, qualification, production, order, shipment or revenue; do not advance a stage by implication.
4. Explain how each could capture value: exposure size, price/volume, margin, capex and financing. Distinguish a real relation from a material profit contribution.
5. State what could eliminate the bottleneck and what is already reflected in market expectations, where evidence permits. Route one best next question per candidate.

Return `result` keys:
- `system_map`: limited nodes/relations with evidence IDs, not a speculative comprehensive graph.
- `bottleneck_hypothesis`: mechanism, supporting/contrary evidence, duration and substitution.
- `candidates`: security/entity, chain_role, maturity_stage, exposure_evidence, profit_hypothesis, status (`lead`, `deepen`, `reject`, `unknown`), next_proof.
- `rejected_alternative`: an examined competing route/company or an explicit absence of enough evidence.

Early leads may have unknown revenue or valuation. They remain useful leads, not BUY recommendations. Investment-candidate output requires the business and valuation follow-up before price-dependent conclusions. Never force a positive candidate or attach arbitrary success probabilities.
