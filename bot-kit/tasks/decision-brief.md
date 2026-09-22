# Position and watchlist decision brief v1.0

Use this method to synthesize company, industry, event, sentiment, price, valuation, factor, portfolio, and memory work into one Decision proposal. It is research support, never an order instruction.

## Required context

Receive a standalone brief with security identity, authorized account/watchlist scope, question, horizon, timezone-aware `as_of`, prior Decision and thesis when available, actual MemoryPacket, evidence and calculation references, data gaps, actual tool map, and output path. A successful memory recall with no hits still supplies and preserves its real packet reference.

For a portfolio-specific action, use a successfully read, timestamped, private snapshot and state its coverage. IBKR Flex is normally T+1 through the prior business day; Longbridge reads are current-only within returned coverage and may omit provider snapshot time. The adapters have offline tests, but broker CLI routing is pending T033. A failed, partial, unauthorized, or unverified read is not an empty portfolio. Missing holdings limits position-specific action; it does not block an independently supported company view.

## Synthesis

1. Resolve whether this is an owned position, watchlist/candidate, or company-only question. Do not infer ownership from a ticker mention.
2. State changes since the prior Decision under separate headings: **facts**, **expectations**, **price**, and **reasoning**. Link each material change to evidence available by the cutoff. Preserve an unchanged prior premise without copying the whole old report.
3. Assess the business and industry: revenue and margin drivers, unit economics/cash conversion, balance-sheet and dilution path, competitive response, industry supply/demand, regulation, catalysts, and event transmission. Mark facts, third-party views, hypotheses, and inferences distinctly.
4. Assess price behavior and sentiment at the declared horizon from sourced bars/events/views. Describe trend, volatility, liquidity, or technical levels only when inputs support them. No retrieved social material means missing sentiment coverage, not neutral sentiment. Timing alone does not prove event causality.
5. Read the actual valuation receipt. Keep fundamental range, market-implied assumptions, entry/exit conditions, and technical levels separate. Do not replace a failed or pending program calculation with model arithmetic.
6. Test the strongest counter-case, source conflicts, and invalidators. State the evidence or price/operating condition that would change the label and the expiry or next review trigger.

## Decision semantics

Use the lower-case Decision label contract: `buy`, `sell`, or `watch`.

- `buy`: supported company thesis and price/condition are attractive for the stated horizon; this is not an order or position size.
- `sell`: a security-level research assessment supported by deterioration, invalidation, or unattractive price/conditions for the stated horizon. For a verified owned position, a separate position action may describe reduction/exit conditions. For an unowned or watchlist security, explain avoid/reject and set position reduction or sizing fields to not applicable; do not pretend a holding was sold.
- `watch`: wait for stated evidence, price, or operating conditions. When decision-critical inputs are unavailable, use `watch`, mark the research result `evidence_limited`, list limitations, and set unsupported price fields to null with a reason.

Do not invent sizing, risk budgets, portfolio policy, confidence probabilities, freshness thresholds, or fixed review dates. Use user-supplied policy when actually available. `no_opportunity` belongs to candidate exploration and `no_factor_increment` belongs to factor validation; neither substitutes for a holding Decision label.

Keep these meanings distinct:

- utility `CallResult.status`: `ok`, `partial`, or `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, or `failed`;
- research result class: complete research, `evidence_limited`, no opportunity, no factor increment, or execution failure;
- Decision label: `buy`, `sell`, or `watch`.

## Output and records

Use the same report body for phone and PC. Lead with label, result class, horizon/expiry, price or operating conditions, and the strongest reason. Then show the evidence chain, company and industry view, price/sentiment, valuation, portfolio relevance, strongest counterevidence, invalidators, gaps, and next check. Preserve adopted and rejected memory with reasons and the actual MemoryPacket reference.

Draft the Decision and coordinating WorkRecord with real input references. Run quality review against sources and calculations, then use the verified `check artifact --archive` command. Only a returned ID/path proves a core record was archived; full report-body and attachment freezing remains pending T032 until an actual return proves otherwise. Do not overwrite the prior Decision.

After a real archive exists, apply a topic or lesson update only when evidence or method changed. Reference the archived record, use the current expected version, retain counterexamples and validity conditions, and do not create a repeated lesson when nothing changed.
