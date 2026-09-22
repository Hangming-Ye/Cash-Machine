---
name: research-entry
description: Turn an in-scope investment question into a sufficient standalone research assignment, compose the required methods, and hand off frozen artifacts.
---

# Research Entry

Use this Skill when a new research goal, update request, scheduled invocation, or specialist handoff enters the existing Bot workflow. It runs through native conversation, Routine context, files, terminal, and messages already available. It does not create a dispatcher, workflow state store, scheduler, callback, or new Bot.

## 1. Frame the decision

Restate the user's natural-language question as a decision-relevant research objective. Preserve the requested market, theme, securities, horizon, and attention scope; these are run inputs, not permanent whitelists.

Resolve:

- what the user wants to decide or understand;
- authorized scope and what would be a material scope expansion;
- market and exact security/topic identities, including exchange and currency when known;
- research horizon and timezone-aware knowledge cutoff;
- whether this is current research, historical reconstruction, or review of an archived Decision;
- existing positions/watchlist context when authorized and actually readable;
- the evidence or condition that would change the conclusion.

Ask only when an ambiguity changes the research meaning and cannot be inferred. A common in-scope question must not be rejected merely because no same-name template exists.

## 2. Compose methods

Select and combine only the methods the question needs. The following are guides, not fixed workflows:

- Theme / supply-chain exploration: follow [supply-chain-research](../supply-chain-research/SKILL.md) and [supply-chain.md](../../tasks/supply-chain.md) for demand change → system/process map → bottleneck and substitutes → company exposure → commercial/profit realization → valuation handoff → counterevidence. Do not paste those methods here.
- Company verification (each surviving company): run [company-thesis.md](../../tasks/company-thesis.md) for business exposure, competitive/supply response, realization timing, and whether the name is an early lead or a researchable candidate. Do not invent a parallel thesis checklist.
- Applicable valuation: when the thesis says valuation is applicable, use [valuation.md](../../tasks/valuation.md) and the local `compute valuation` CLI only; never copy formulas or substitute mental arithmetic. Early leads may leave valuation not applicable with an explicit reason.
- Counterevidence review: before archive, use [review.md](../../tasks/review.md) for material claim and counterevidence review.
- Company or holding research: timestamped position/price context → operating and financial drivers → industry/events/sentiment → valuation or explicit conditions → portfolio relevance → risks and invalidators; prefer [portfolio-research](../portfolio-research/SKILL.md) when that pattern fits.
- Single-stock factor research: economic hypothesis → available information and named-operation combination → frozen validation request → deterministic result → incremental value, failure regimes, and current applicability.
- Source follow-up: identify a decision-critical gap → try authorized existing sources → original company/exchange/regulator disclosure → attributable public web material or supported ingest → record attempts, provenance, and remaining impact.
- Review and memory: source/calculation quality review, or historical Decision review with later facts separated; recall before research and consolidate only after frozen supporting records exist.

For a theme that needs the exploration → company verification → applicable valuation → counterevidence chain, compose those four steps in order for each surviving name. An empty candidate list or Decision label `no_opportunity` is a valid research result: set `WorkRecord.outcome` to `complete` (or `limited` only when evidence/coverage is incomplete). Do not treat no-candidate / `no_opportunity` as execution `failed`.

Add in-scope subquestions and candidates when evidence requires them. Do not use a fixed candidate count, source count, follow-up count, or permanent workflow list. Ask the user before a material scope expansion or supplier change.

Consult [the capability table](../../README.md) and the current tool map. A planned method is not a callable operation. New combinations of available factor operations are allowed when the calculation contract is implemented; arbitrary executable code is never allowed. Missing data triggers existing-source/web/ingest attempts and a gap, not an automatic development request.

## 3. Recall memory and assemble context

Follow [research-memory](../research-memory/SKILL.md) before dispatch. Store the returned immutable memory packet reference even when recall succeeds with no history, plus the resolved context mode and cutoff, selected version references, warnings/gaps, and the reason each relevant item is adopted or rejected. Only a recall that was not run or failed has no packet, and that reason must remain explicit.

Match memory use to the research pattern without creating separate workflows:

- For periodic research, compare the recalled baseline with the new increment and carry forward unresolved questions.
- For long-running research, preserve thesis evolution, supporting and opposing evidence, open questions, and the next review trigger.
- For deep analysis, reopen changed inputs and assumptions, identify dependent calculations, and rerun only the affected work.

Before adopting an item, verify its frozen source references, cutoff, `validity`, `applies_when`, `review_condition`, expiry if one is stated, and counterexamples against the present task. Record every adopted or rejected item with its reason. Current user instructions and newly verified evidence govern the work; remembered content cannot override them, expand scope, or turn an expired or inapplicable lesson into an instruction.

During consolidation, classify a materially identical result as `no_change` and do not call `memory apply`; retain the existing immutable version. On a version conflict, recall the latest state, merge the competing evidence and unresolved questions without discarding either writer, then apply with the newly returned `expected_version`. Never rewrite a saved version.

Create one standalone brief from [task-brief.md](../../templates/task-brief.md). Include:

- caller-assigned `request_id` and `task_id`; these correlate work and are not archive IDs;
- original question, objective, scope, identities, horizon, `as_of`, and current/historical/review mode;
- source/input references with original locators and availability limitations;
- immutable memory packet reference and version/context metadata;
- existing calculation references and assumptions; never fabricate missing values;
- selected methods, concrete steps, claim checks, counterevidence checks, and completion standard;
- actual tools/capabilities, owned output path, responsible Bot, and upstream/downstream handoff;
- source fallback, partial-result behavior, retry input, and escalation condition.

The program generates `rec_...` archive IDs and `mem_...` packet IDs. Never invent them in a brief. Refer to a draft only as a draft input; historical citations require the returned archive ID or immutable path.

## 4. Dispatch and adapt

Map each independent question to an existing Bot with the matching responsibility. Send the complete brief and paths through native messaging; never assume parent-chat context. Independent briefs may run concurrently. Dependent work waits for the cited artifact.

During research, a specialist may adjust the plan, add an in-scope candidate, or request targeted source follow-up. Record the reason and keep ownership clear. When a call fails, preserve its reason and retry the same bounded input if useful. Do not create task nodes or poll a hidden completion state.

Use these meanings consistently:

- utility `CallResult.status`: `ok`, `partial`, `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, `failed`;
- Decision label: `buy`, `sell`, `watch`, `no_opportunity`, `no_factor_increment`.

## 5. Handoff and close

The specialist returns its result to the declared output path with evidence and calculation references, limitations, and next check. The coordinator reads actual artifacts, composes dependent work, and uses [review.md](../../tasks/review.md) for material claim review.

Produce the user-facing result with [report.md](../../templates/report.md). Create drafts first. Explicitly run `check artifact --archive` for a Decision, WorkRecord, or historical Review; validation without `--archive` creates no historical ID. After successful archive, hand off the returned immutable path/ID and apply justified memory updates. A failed archive or memory write remains a failure and must not be described as saved.
