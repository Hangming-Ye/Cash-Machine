# T02 Company thesis v0.3

Owner: Research.

Required: security/entity, horizon, question, company filings or primary operating material. Optional: supplied segment tables, peers, consensus, prior thesis and industry evidence. Missing primary business material makes a full company thesis blocked; a clearly labeled narrower source summary may be partial.

Do:
1. Explain the revenue engine by relevant segment: customer, product, volume/price, recurring/project nature and exposure to the researched theme.
2. Identify at most three important operating drivers and their evidence. Link growth to margins, reinvestment, working capital and cash conversion using supplied calculations.
3. Examine competition, customer concentration, switching/qualification, capacity and funding. Distinguish claimed moat from measured economics.
4. Separate what management expects, what analysts expect and what our thesis assumes. Inspect the strongest disconfirming evidence and an alternative outcome.
5. Define measurable proof points and failure conditions. Recommend the next research question, not an unsupported target price.

Return `result` keys:
- `business_engine`: segment/customer/product/economic mechanism.
- `drivers`: driver, baseline and source IDs, assumed change, profit/cash-flow transmission.
- `thesis`: status (`early`, `supported`, `mixed`, `rejected`, `unknown`) and concise rationale.
- `counter_case`: strongest contrary evidence and implication.
- `proof_points`: metric/event, source, due window, what would confirm or disconfirm.

Every material numeric driver uses a source or calculation ID. A company may be good while its stock is unattractive; T04/T06 owns the price/action judgment. Do not filter out an early-stage company merely because revenue has not yet been recognized; state the stage and uncertainty.
