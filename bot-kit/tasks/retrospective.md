# T08 Historical decision review v0.3

Owner: Chief. Modes: `process` or `outcome`.

Required: frozen original decision, information cutoff, considered alternatives, prior evidence, intended horizon, and user choice if recorded. Outcome mode additionally needs program-produced subsequent returns, benchmark, adverse excursion and known later events. Unknown user execution remains unknown.

Process mode:
The input must exclude subsequent outcomes; if outcomes are already visible, mark unblinded. The program must save this result before making the separate outcome task ready. Do not request or open the outcome file during process mode.
1. Evaluate only the information available then. Was the business mechanism explicit, the price assumption coherent, and the strongest contrary case examined?
2. Identify evidence that was available but missed versus information that could not have been known. Evaluate uncertainty and timing fairly.
3. Save the process assessment before receiving the outcome packet. If later outcomes were already visible, label the assessment unblinded.

Outcome mode:
1. Read the prior process assessment and actual outcome receipt; do not rewrite the original decision.
2. Separate thesis realization, broad market/sector effects, valuation changes, timing and actual execution. Attribution beyond available data remains an interpretation.
3. Compare only pre-registered alternatives with their recorded timing/cost rules. Do not invent a perfect hindsight trade.
4. Propose at most one lesson with supporting cases, applicable conditions, counterexamples and a future validation plan. Keep it a candidate, never an automatic prompt or rule update.

Return `result` keys: `mode`, `decision_id`, `blinding_status`, `process_assessment`, `outcome_assessment`, `error_category`, `lesson_candidate`, `reopen_condition`.

A profitable outcome does not prove a good decision. A loss does not prove the thesis process was bad. If the horizon has not elapsed, record pending and the next review date rather than a final score. Do not imply that a recorded intention is an executed broker trade.
