---
name: supply-chain-research
description: Explore a theme through demand, chain stages, bottlenecks, substitutes, company exposure, and profit realization with memory recall, source fallback, and no fixed candidate quota.
---

# Supply-Chain Research

Use this Skill when the user gives a theme, system change, or open-ended industry goal and needs early discovery or candidate screening. It implements the Serenity-style sequence inside the existing Bot workflow: demand change → system/process map → bottleneck and substitutes → company exposure → commercial/profit realization → valuation handoff → counterevidence. It supports human decisions and never submits, changes, or cancels an order.

## Start from a standalone assignment

Require the original question, authorized market and security scope, theme or system identity, horizon, timezone-aware `as_of`, prior Decision when available, verified application directory and data root, actual tool map, owned draft path, completion checks, and downstream owner. Never depend on parent-chat context.

US, HK, and CN markets are runtime inputs for the current assignment. Do not treat them as a permanent whitelist. Ask before a material scope expansion or any supplier change. Do not reject a normal in-scope question merely because no same-name template exists.

## Recall before research

Create the current memory recall request using the research-memory Skill and run it with the exact verified launcher:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> memory recall --request <MEMORY_RECALL.json>
```

Keep the returned immutable MemoryPacket even when it has no hits. Record selected versions, gaps, and adopted or rejected items with reasons. Current research uses `context_mode: current`; historical and review modes keep their own cutoffs and cannot import later knowledge into the earlier view. Current user instructions and newly verified evidence outrank memory.

## Confirm actual capabilities

Read the current capability table in `bot-kit/README.md` and the assignment tool map before issuing a command.

- `data fetch`, `data ingest`, `check artifact`, and memory recall/apply are locally wired. Public fetch currently routes Finnhub quote/news, Tiingo bars, FMP stable profile/statements, and AKShare quote/bars/news/profile/statements, subject to enabled configuration, entitlement, and actual response coverage.
- IBKR Flex and Longbridge accounts/positions/executions route through the local read-only CLI when portfolio context is authorized. A failed read is never an empty portfolio.
- `compute valuation` runs the T030 engine when a candidate needs a valuation expectation. Factor calculation remains pending its integration task.

Do not claim a pending operation ran. Do not invent data. For a wired source operation, copy the shape from the relevant synthetic fixture, replace every synthetic field, save JSON under the private task workspace, then use:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> data fetch --request <REQUEST.json>
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> data ingest --request <REQUEST.json>
```

Never put credentials, non-public holdings, or protected account identifiers in a shared request, report, prompt, or command line.

## Research method

Follow `bot-kit/tasks/supply-chain.md`. There is no fixed candidate count, layer count, source count, or retry quota. Add in-scope candidates, stages, or substitutes when evidence requires them.

1. Restate the demand change with sourced units, period, and geography when available. Plans and forecasts stay labeled.
2. Build an evidenced system and process map for the economically relevant stages. Prefer limited evidenced nodes over a speculative full industry tree.
3. Test the bottleneck with capacity, yield, qualification, lead time, expansion timing, financing, and substitutes. Unknown capacity is unknown, not scarcity.
4. Attach companies only through evidenced product, process, qualification, production, order, shipment, or revenue links. Do not recommend a company only because it sits at a bottleneck.
5. Trace commercial and profit realization separately from the supply relation. Keep early leads distinct from investment candidates.
6. When a candidate needs a valuation expectation, point to `bot-kit/tasks/valuation.md` and call `compute valuation` through the verified CLI. Do not copy valuation formulas into this Skill.
7. Record the strongest counterevidence, exclusions, and what to watch next. If evidence rejects the theme framing, keep the reason and continue inside authorized scope.

When a decision-critical source is missing or conflicting, invoke the source-followup Skill. Try another approved existing integration, then company IR, exchange or regulator filings, and attributable public web material. Keep attempts and gaps. Do not add a vendor.

## Decision and result classes

Distinguish:

- utility `CallResult.status`: `ok`, `partial`, or `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, or `failed`;
- research result class: complete research, limited evidence, no qualified opportunity, or execution failure;
- Decision label for this screen: `watch` or `no_opportunity`.

Rules:

- Early leads with unresolved profit or valuation use `watch`, may mark `evidence_limited`, and remain useful leads, not buy recommendations.
- When no qualified opportunity exists after an evidenced screen, deliver the screen, exclusions, and what to watch next with Decision label `no_opportunity`. That result can be a complete execution outcome; it is not an execution failure.
- Do not invent a candidate to fill a quota. Do not attach arbitrary success probabilities.
- Holding labels `buy` / `sell` belong to company or portfolio synthesis methods, not this theme screen.

## Review, archive, and memory

Use the unified phone/PC report template. Include demand change, system map, bottleneck and substitutes, candidates or explicit absence, profit path or why it fails, valuation handoff or null reason, strongest counterevidence, exclusions, gaps, next check, and memory use.

Draft a Decision and WorkRecord with real references, then archive only through the verified command:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> check artifact --request <ARCHIVE_REQUEST.json> --archive
```

Only a returned immutable ID or path proves the core record exists. Do not overwrite prior history.

After a real archived record exists, follow the research-memory Skill. Write the judgment summary into a topic update only for an evidence-backed change; propose a lesson only when review identifies a reusable check. Reference the archived record, preserve conditions and counterexamples, use the returned expected version, and retain old versions. If nothing material changed, record `no_change` instead of duplicating it.
