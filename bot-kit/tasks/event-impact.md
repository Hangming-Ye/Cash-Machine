# T01 Event impact v0.3

Owner: Market. Modes: `event`, `earnings`, `preview`, `macro`.

Required: resolved security/theme, question, decision_at, prior cutoff, source documents with IDs and timestamps. Supply prior thesis, price-reaction calculations and pre-event estimates if available. Their absence limits the respective claims, not every part of the analysis.

Do:
1. Identify new disclosures, corrections and recycled stories. Group copies of the same original event; retain the original IDs.
2. Extract material facts and attributable opinions. In earnings mode inspect segment growth, margin quality, cash flow, one-offs and guidance. In preview mode identify upcoming proof points and available expectation baselines.
3. Compare with prior thesis/guidance/consensus only when periods and knowledge times match. Explain the gap if a comparison is unavailable.
4. Map each event to a specific business or valuation channel. Offer a plausible competing explanation for market reaction where relevant.
5. State what changes now, what remains a lead, and the next source/event that could resolve uncertainty.

Return `result` keys:
- `mode`: copy the selected event/earnings/preview/macro mode.
- `events`: event, original_source_ids, event_time, category, factual_change, expectation_change, affected_driver, thesis_effect, evidence_ids.
- `price_context`: calculation IDs and a descriptive interpretation, or null.
- `social_context`: coverage, main narratives, opposing narrative, independent_origins, or null.
- `next_checks`: at most two specific questions with source type/date.

In earnings mode also return `actual_vs_expectations` (metric, period, unit, actual, prior_guidance, pre_release_consensus, evidence_ids, calculation_ids; missing numbers null), `earnings_quality`, and `guidance_change`.
In preview mode also return `expectation_bar` and `kpi_thresholds` (metric, condition, origin: inherited/draft, evidence_ids). No available bar or threshold must be marked unknown, not invented.
In macro mode also return `exposures` (entity, exposure, transmission, valuation_variable, evidence_ids). These fields make the chosen financial analysis observable; do not substitute a generic news summary.

Done means the supplied event scope is analyzed, even if nothing changes the thesis. Partial when a necessary original source or comparison is missing. Never interpret zero retrieved posts as neutral sentiment, use a post-release estimate as pre-release consensus, or generate a buy/sell label instead of event analysis.
