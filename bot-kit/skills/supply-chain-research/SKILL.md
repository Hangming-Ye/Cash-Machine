---
name: supply-chain-research
description: Explore a theme with a BFS process map toward materials, quantified demand, one bottleneck test, then a shortage-queue recurse, price-in, and program valuation.
---

# Supply-Chain Research

Use this Skill when the user gives a theme, system change, or open-ended industry goal and needs discovery or candidate screening. It implements the Serenity-style sequence inside the existing Bot workflow: BFS process map toward materials → quantified demand → one shortage/bottleneck test → enqueue only nodes that passed that test → company exposure and profit realization → price-in → program valuation → counterevidence. It supports human decisions and never submits, changes, or cancels an order.

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

Follow `bot-kit/tasks/supply-chain.md`. There is no fixed candidate count, layer count, source count, or retry quota. Required stages leave separate frozen artifacts. An early lead file may exist mid-run; it is not the user-facing conclusion. Do not prefer a “limited evidenced map” or a stop at major components as the stopping rule.

1. Breadth-first process map for the current system: full frontier of process steps, components, and constituting materials; company, role, and same-step competitors on each; evidence or explicit unknown. A named component (e.g. optical module) is not an opaque leaf if it still has materials, substrates, and process steps. Map only; do not enqueue. Do not depth-first into one famous company and stop. User illustration (inference server → optical module judged short by the later test → further decompose): method motive only; no return multiple; no required ticker.
2. Quantify downstream demand with sourced units, period, and geography. Plans and forecasts stay labeled. Do not enqueue.
3. One shortage/bottleneck test on named frontier nodes, using capacity, yield, lead time, qualification, or expansion. Unknown capacity is unknown, not scarcity. Do not run an earlier or weaker shortage screen.
4. Enqueue and recurse only nodes that step 3 judged shortage or bottleneck. Non-shortage and unknown nodes stay on the map and are not recursed. Write the queue as a frozen file after the test—not a graph DB, scheduler, or state machine. Do not invent a shortage to justify another layer. If evidence cannot split further, record the stop and its effect.
5. Attach companies only through evidenced product, process, qualification, production, order, shipment, or revenue links. Trace commercial and profit realization separately. Do not recommend a company only because it sits at a bottleneck.
6. Price-in: program valuation versus a sourced quote.
7. Program valuation handoff via `bot-kit/tasks/valuation.md` and `compute valuation`. Analyst targets and pasted press figures are not a calculation. Pending or `not_applicable` after mid-run does not finish a user-requested study; after recorded follow-up, missing inputs limit only the price conclusion.
8. Record the strongest counterevidence, exclusions, and what to watch next. Rejected theme or no opportunity is valid only after the process map and the tests evidence can support.

When a decision-critical source is missing or conflicting, invoke the source-followup Skill. Try another approved existing integration, then company IR, exchange or regulator filings, and attributable public web material. Keep attempts and gaps. Do not add a vendor.

## Decision and result classes

Distinguish:

- utility `CallResult.status`: `ok`, `partial`, or `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, or `failed`;
- research result class: complete research, limited evidence, no qualified opportunity, method defect, or execution failure;
- Decision label for this screen: `watch` or `no_opportunity`.

Rules:

- Mid-run early leads may stay open with unresolved profit or valuation; they are not buy recommendations and do not close a user-requested study.
- When no qualified opportunity exists after the BFS-to-materials map and supported tests, deliver the screen, queue state, exclusions, and what to watch next with Decision label `no_opportunity`. That result can be a complete execution outcome; it is not an execution failure.
- Missing a required stage or stopping at major components is a method defect, not an acceptable limited finish of a requested study.
- Do not invent a candidate to fill a quota. Do not attach arbitrary success probabilities.
- Holding labels `buy` / `sell` belong to company or portfolio synthesis methods, not this theme screen.

## Review, archive, and memory

Use the unified phone/PC report template. Include the BFS process map, quantified demand, the one bottleneck test, the shortage queue written only after that test, candidates or explicit absence, profit path or why it fails, price-in, valuation handoff or recorded inapplicability after follow-up, strongest counterevidence, exclusions, gaps, next check, and memory use.

Draft a Decision and WorkRecord with real references, then archive only through the verified command:

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> check artifact --request <ARCHIVE_REQUEST.json> --archive
```

Only a returned immutable ID or path proves the core record exists. Do not overwrite prior history.

After a real archived record exists, follow the research-memory Skill. Write the judgment summary into a topic update only for an evidence-backed change; propose a lesson only when review identifies a reusable check. Reference the archived record, preserve conditions and counterexamples, use the returned expected version, and retain old versions. If nothing material changed, record `no_change` instead of duplicating it.
