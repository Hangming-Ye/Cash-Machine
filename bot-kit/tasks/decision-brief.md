# T06 Position/watchlist decision brief v0.3

Owner: Chief.

Required: security, question/horizon, prior thesis if any, available research/event results, data-quality receipt. Current-price claims additionally require a fresh quote under the configured freshness policy and an applicable valuation calculation. Portfolio-specific actions require a sufficiently current position/policy snapshot; security-level views can still be labeled separately.

Do:
1. State changes since the prior decision in three separate categories: facts, expectations and price. Avoid reprinting an unchanged company report.
2. Assess company thesis separately from price attractiveness. Incorporate factor evidence only at its supported evidence level and horizon.
3. Choose a supported research stance: BUY, SELL or WATCH, and a readiness of ready, conditional or insufficient. Missing optional sources do not automatically force WATCH. If critical inputs are absent, use null for the unsupported stance or price fields and explain the exact limit.
4. Distinguish new/add, trim/exit and wait only when position context permits. A negative view on a watchlist stock means avoid/reject candidate, not selling a position that does not exist.
5. Show fair-value range, entry ceiling and reduction/exit conditions from program calculations or clearly attributable assumptions, each with horizon. State the strongest contrary case and the next test that would change the view.

Return `result` keys: `changes`, `company_thesis`, `research_stance`, `readiness`, `position_action`, `price_conditions`, `factor_relevance`, `counter_case`, `next_review`.

Do not decide by averaging analyst scores or counting agreeing Bots. Optional low social coverage must remain visible but does not veto a filing-based argument. Missing fresh holdings limits sizing/actions, not all company research. This is a research proposal awaiting workflow review, not a trade instruction or proof of investment correctness.
