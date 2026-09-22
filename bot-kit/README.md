# Bot research method package

This directory contains offline source text for configuring the existing Grok Bots. It is not evidence that any prompt or Skill is installed, loaded, or behaving correctly in the live product. Local packaging has been replayed on this machine; that is not a cloud install. Native loading and behavior remain unverified pending T016 and the private Bot mapping from T001.

## Active load list

Load one shared instruction and the role files matching an existing Bot's mapped responsibilities. One Bot may hold several responsibilities; these names do not require six new Bots.

| File | Version | Purpose | Offline status |
| --- | --- | --- | --- |
| [common.md](prompts/common.md) | v1.0 | Shared evidence, memory, status, archive, privacy, and delivery rules | Migrated source |
| [chief.md](prompts/chief.md) | v1.0 | Framing, method composition, native handoff, synthesis, closure | Migrated source |
| [research.md](prompts/research.md) | v1.0 | Industry, supply chain, company, holding, valuation method | Migrated source |
| [market.md](prompts/market.md) | v1.0 | Events, earnings, expectations, macro, price, sentiment | Migrated source |
| [quant.md](prompts/quant.md) | v1.0 | Factor hypothesis, frozen validation, interpretation | Migrated source |
| [reviewer.md](prompts/reviewer.md) | v1.0 | Evidence, calculation, temporal, boundary, memory review | Migrated source |
| [research-memory/SKILL.md](skills/research-memory/SKILL.md) | current T052 | Query/ID recall, task-specific consolidation, dedupe and version-safe apply | Implemented offline; native loading unverified |
| [research-entry/SKILL.md](skills/research-entry/SKILL.md) | v1.0 | Goal/scope framing, method composition, standalone brief, artifact handoff | Implemented offline; native loading unverified |
| [source-followup/SKILL.md](skills/source-followup/SKILL.md) | v1.0 | Existing-source, original-disclosure, research/social follow-up and gap recording | Implemented offline; native loading unverified |
| [portfolio-research/SKILL.md](skills/portfolio-research/SKILL.md) | v1.0 | Company, holding, and watchlist research with conditions, counterevidence, expiry, and memory | Implemented offline; native loading unverified |
| [supply-chain-research/SKILL.md](skills/supply-chain-research/SKILL.md) | v1.0 | Theme demand, chain stages, bottleneck/substitutes, exposure, profit path, and no-opportunity screen | Implemented offline; native loading unverified |
| [factor-research/SKILL.md](skills/factor-research/SKILL.md) | v1.0 | Single-stock factor hypothesis, approved-operator combinations, frozen validation, and interpretation | Implemented offline; native loading unverified |
| [task-brief.md](templates/task-brief.md) | v1.0 | Sufficient specialist context and ownership template | Implemented offline; native loading unverified |
| [report.md](templates/report.md) | v1.0 | One Chinese user-facing report for mobile and PC | Implemented offline; native loading unverified |
| [review.md](tasks/review.md) | v1.0 | Source-based quality review and historical Review distinction | Implemented offline; native loading unverified |
| [retrospective.md](tasks/retrospective.md) | v1.0 | Due/triggered historical Decision review and lesson handoff | Implemented offline; native loading unverified |
| [templates/review.md](templates/review.md) | v1.0 | Chinese original-versus-later historical Review template | Implemented offline; native loading unverified |
| [event-impact.md](tasks/event-impact.md) | v1.0 | Composable event, earnings, preview, and macro impact method | Implemented offline; native loading unverified |
| [valuation.md](tasks/valuation.md) | v1.0 | Sourced valuation assumptions, T030 request shape, applicability, and interpretation | Implemented offline; native loading unverified |
| [decision-brief.md](tasks/decision-brief.md) | v1.0 | Holding/watchlist synthesis and lower-case Decision semantics | Implemented offline; native loading unverified |
| [supply-chain.md](tasks/supply-chain.md) | v1.0 | Serenity-style demand, bottleneck, exposure, profit, valuation handoff, and counterevidence method | Implemented offline; native loading unverified |
| [company-thesis.md](tasks/company-thesis.md) | v1.0 | Surviving-company exposure, competitive/supply response, realization timing, early lead vs researchable candidate, and valuation applicability | Implemented offline; native loading unverified |
| [factor-study.md](tasks/factor-study.md) | v1.0 | Single-stock factor proposal and interpretation with approved operators, validation readout, and no-increment outcomes | Implemented offline; native loading unverified |

For each Bot load `common.md`, the selected role file(s), and the complete current assignment produced through the research-entry Skill and task-brief template. Do not load every role by default. Use the report template for the same mobile/PC delivery and the review method when material claims need independent checking.

## Capability status

- The local CLI implements `data fetch`, `data ingest`, `check artifact`, and `memory recall/apply` with offline tests. The actual run must still confirm enabled configuration, entitlement, and returned coverage.
- Public `data fetch` routing currently covers Finnhub quote/news, Tiingo bars, FMP stable profile/statements, and AKShare quote/bars/news/profile/statements. Ingest archives already obtained text/PDF/CSV/JSON material within its validated boundary; it is not a browser or network fetch.
- IBKR Flex and Longbridge accounts/positions/executions now route through the local read-only CLI and atomically persist typed portfolio snapshots when the adapters can form one. Tests use mocked transport/SDK only: live entitlement, OAuth, account coverage, and cloud availability remain unverified. IBKR Flex is normally T+1; Longbridge is current-only within returned coverage. A failed read is never an empty portfolio.
- `compute valuation` and `compute factor` both exist in the local CLI. Valuation freezes the complete request, deterministic result, typed Calculation, input bytes/provenance, and manifest. Factor freezes the experiment, calculation table, and interpretation for approved operator combinations. A local receipt proves only the supplied synthetic inputs were calculated.
- The source baseline remains exactly Finnhub, Tiingo, FMP stable, AKShare, IBKR Flex, and Longbridge OAuth. Native web search, company IR, and exchange/regulator filings are evidence channels. No supplier is added here.
- Entry/task-brief, source follow-up, event impact, portfolio research, supply-chain research, factor research, valuation, decision brief, and report/review files are implemented offline. Packaging was replayed locally; that is not a cloud install. Native loading and behavior remain unverified pending T016 and later story acceptance.
- This migration creates no Routine, scheduler, notification rule, service, callback, state machine, or Bot.

## Native boundary

Map these methods to existing Bots after the private mapping is available. Use native Description, Skills, Routine references, shared files, terminal, and messages only as the actual product supports. Verify loaded versions through behavior with a complete isolated assignment; “I remember” is insufficient.

Independent questions may use existing concurrency; dependent work waits for inputs. Retry failed messages with the same bounded context and recorded reason. The program does not prepare ready nodes, dispatch Bots, poll completion, or deliver notifications. Mobile and PC use the same artifact. Never put credentials or non-public account data in shared templates or public outputs.

## Reference-only legacy material

These v0.3 files remain design history and are not active authority or part of the load list:

- `BOT_OPERATING_SPEC.md`
- `bot-kit/contracts.md`
- `bot-kit/result.schema.json`
- `bot-kit/evaluation.md`
- `bot-kit/tasks/` old task cards, except the active migrated `review.md`, `event-impact.md`, `valuation.md`, `decision-brief.md`, `retrospective.md`, `supply-chain.md`, `company-thesis.md`, and `factor-study.md`

Only the migrated task files listed above are active in that directory. Do not load the other legacy fixed workflows, task IDs, candidate/finding caps, one-pass review limits, registered-formula-only restrictions, ready-node scheduler concepts, or notification templates. Later tasks may activate a task file only after reconciling it with current authority and listing it above.
