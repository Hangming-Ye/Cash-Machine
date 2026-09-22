---
name: portfolio-research
description: Produce evidence-backed company, holding, or watchlist research with price conditions, counterevidence, expiry, valuation handoff, and time-safe memory use.
---

# Portfolio Research

Use this Skill for an owned position, watchlist security, or company-level investment question. It combines business, industry, event, sentiment, price, valuation, portfolio, review, and memory methods as the question requires. It supports human decisions and never submits, changes, or cancels an order.

## Start from a standalone assignment

Require the original question, authorized market/security/account scope, resolved identity and currency, horizon, timezone-aware `as_of`, prior Decision when available, verified application directory and data root, actual tool map, owned draft path, completion checks, and downstream owner. Never depend on parent-chat context.

Resolve whether the security is an owned position, watchlist/candidate, or company-only subject. If identity, cutoff, or requested portfolio scope is ambiguous enough to change the result, resolve it before using data. Do not infer ownership, account coverage, portfolio policy, risk budget, or position size.

## Recall before research

Create the current memory recall request using the research-memory Skill and run it with the exact verified launcher:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> memory recall --request <MEMORY_RECALL.json>
```

Keep the returned immutable MemoryPacket even when it has no hits. Record selected versions, gaps, and adopted/rejected items with reasons. Current research uses `context_mode: current`; historical and review modes keep their own cutoffs and cannot import later knowledge into the earlier view.

## Confirm actual capabilities

Read the current capability table in `bot-kit/README.md` and the assignment tool map before issuing a command.

- `data fetch`, `data ingest`, `check artifact`, and memory recall/apply are locally wired. Public fetch currently routes Finnhub quote/news, Tiingo bars, FMP stable profile/statements, and AKShare quote/bars/news/profile/statements, subject to enabled configuration, entitlement, and actual response coverage.
- IBKR Flex and Longbridge accounts/positions/executions route through the local read-only CLI and publish a typed snapshot only when adapter coverage supports one. The tests use mock transport/SDK; live entitlement, OAuth, account coverage, and cloud availability remain unverified. IBKR Flex is normally T+1; Longbridge is current-only within returned coverage and can have unknown provider snapshot time.
- `compute valuation` runs the T030 engine and freezes its request, result, typed Calculation, and input provenance. Factor calculation remains pending its integration task.

Do not claim a pending operation ran. Do not execute the pure engine through an improvised Python snippet as a fallback. Prepare a reviewed request and leave the corresponding output null with a reason until the verified capability exists.

For a wired source operation, copy the shape from the relevant synthetic fixture, replace every synthetic field, save JSON under the private task workspace, then use:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> data fetch --request <REQUEST.json>
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> data ingest --request <REQUEST.json>
```

Never put credentials, non-public holdings, or protected account identifiers in a shared request, report, prompt, or command line.

## Research method

### 1. Position and price context

When portfolio context is authorized and actually available, record broker, account coverage, reported/retrieved times, currency, quantity basis, market value/cost basis availability, partial subreads, and limitations. A read error is not an empty account. A confirmed empty result requires a complete read and explicit empty indication.

Independently obtain price/bars appropriate to the market and horizon. Preserve observation/availability time, interval, adjustment status, currency, missing sessions, and current-versus-historical limitation. Do not invent a universal freshness threshold. Describe trend, volatility, drawdown, volume/liquidity, and technical levels only when the series supports them.

### 2. Business and financial drivers

Explain how the company makes money and which volumes, prices, mix, margins, working capital, capital intensity, funding, dilution, and segment exposures drive value. Compare like periods and definitions. Distinguish reported fact, management statement, third-party view, research hypothesis, and inference.

Check earnings quality, cash conversion, balance-sheet resilience, capital allocation, financing needs, and share-count changes as material to the horizon. A provider field or current profile does not prove historical point-in-time availability.

### 3. Industry, competition, and events

Connect industry demand/supply, capacity, substitutes, customer concentration, pricing power, regulation, macro/currency exposure, and competitive response to company economics. For events or earnings, use the event-impact method: compare with the correct prior expectation and trace the effect through operating and valuation drivers. Timing alone does not prove price causality.

### 4. Sentiment and external views

Use news, analyst research, and social material only to the degree actually accessible. Preserve author, publication/availability time, original locator, access scope, and whether content is full text, excerpt, abstract, or quotation. Repetition is not independent confirmation. Zero retrieved posts is missing coverage, not neutral sentiment.

When a decision-critical source is missing or conflicting, invoke the source-followup Skill. Try another approved existing integration, company IR, exchange/regulator filing, native web/document access, or authorized user material. Keep attempts and gaps; do not add a vendor or turn an excerpt into a reviewed report.

### 5. Valuation and price conditions

Use `bot-kit/tasks/valuation.md`. For a requested company or holding conclusion, quantitative valuation is required when the economics can be expressed with sourced inputs. Research every input and reason, then prepare the T030 request shape. Call `compute valuation` only through the verified CLI and read status, applicability, scenarios, failed sensitivity cells, units, references, and warnings. The program computes; the model does not replace it. Compare with a sourced quote to state which operating assumptions the price already implies. Analyst targets and pasted press-release figures are not a calculation. Do not stop at news, guidance, and a quote.

Separate fundamental range, market-implied assumptions, price/entry or exit conditions, and technical levels. State the horizon and evidence behind each. Do not average incompatible outputs or turn an inapplicable method into a price. `not_applicable` only after recorded follow-up shows a stated input is still missing, and that blocks the price conclusion only—not a finished user answer for a requested study.

### 6. Counter-case and expiry

Build the strongest evidence-backed opposing explanation. Identify conflicts, conditions that invalidate the thesis or valuation, and what would distinguish the cases. Define expiry as a horizon, named disclosure/event, operating threshold, price condition, or evidence change that requires review. Do not invent fixed freshness or review intervals.

## Decision and insufficient evidence

Hand the synthesis to `bot-kit/tasks/decision-brief.md`. Decision labels are lower-case `buy`, `sell`, or `watch` and remain separate from `CallResult.status` and `WorkRecord.outcome`.

If decision-critical evidence is missing after reasonable authorized follow-up, return `watch`, research result `evidence_limited`, `WorkRecord.outcome: limited`, exact limitations, and null unsupported price fields with a reason. Continue and deliver independently supported company research. A security-level `sell` assessment may apply to an unowned/watchlist security; describe its practical meaning as avoid/reject and keep position reduction, exit, and sizing not applicable unless a verified owned position exists.

Do not fabricate sizing, risk limits, probabilities, prices, calculations, or a complete result. `no_opportunity` and `no_factor_increment` belong to different research methods.

## Review, archive, and memory

Use the unified phone/PC report template. Include conclusion, horizon/expiry, price or operating conditions when supported, evidence, company/industry/price/sentiment/valuation reasoning, portfolio relevance, strongest counterevidence, invalidators, gaps, next check, and memory use. Keep detailed private account data in the private annex, never a public report.

Run source-based quality review. Draft a Decision and WorkRecord with real references, then archive only through the verified command:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> check artifact --request <ARCHIVE_REQUEST.json> --archive
```

Only a returned immutable ID/path proves the core record exists. T032 report-body and attachment freezing remains pending until an actual result proves it; do not claim the full report is frozen. Do not overwrite prior history.

After a real archived record exists, follow the research-memory Skill. Apply a topic/lesson update only for an evidence-backed change, reference the archived record, preserve conditions and counterexamples, use the returned expected version, and retain old versions. If no lesson changed, record no change instead of duplicating it.
