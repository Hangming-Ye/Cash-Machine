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

Select and combine only the methods the question needs. The following are guides, not fixed workflows. Composing methods is not permission to collapse them into one specialist essay. One brief covers one stage; the specialist's owned output is that stage file only. Dependent stages wait for the prior artifact path. After each specialist returns, the coordinator checks the stage file and updates the run manifest status at `data/runs/<request_id>/manifest.json`. The coordinator must not deliver a user conclusion while `next_stage_id` is set, or until required stage files exist or a stage records a real blocker. Do not create a dispatcher, workflow database, or scheduler.

- Theme / supply-chain exploration: follow [supply-chain-research](../supply-chain-research/SKILL.md) and [supply-chain.md](../../tasks/supply-chain.md) for BFS process map toward materials → quantified demand → one shortage/bottleneck test → enqueue only nodes that passed that test → recurse ready nodes → price-in → program valuation → counterevidence. Do not paste those methods here. Do not stop at an opaque component; do not fill the frozen queue before the test.
- Company verification (each surviving company): run [company-thesis.md](../../tasks/company-thesis.md) for business exposure, competitive/supply response, realization timing, and quantitative valuation when economics can be expressed with sourced inputs. Do not invent a parallel thesis checklist.
- Applicable valuation: when economics support sourced inputs, use [valuation.md](../../tasks/valuation.md) and the local `compute valuation` CLI only; never copy formulas or substitute mental arithmetic. `not_applicable` only after recorded follow-up shows a stated input is still missing, and that blocks the price conclusion only—not a finished user answer for a requested study.
- Counterevidence review: before archive, use [review.md](../../tasks/review.md) for material claim and counterevidence review.
- Company or holding research: timestamped position/price context → operating and financial drivers → industry/events/sentiment → program valuation versus sourced quote → portfolio relevance → risks and invalidators; prefer [portfolio-research](../portfolio-research/SKILL.md) when that pattern fits. News, guidance, and a quote alone are not the quantitative path. Single-name Decision drafts that close a study include `run_manifest_ref`.
- Single-stock factor research: economic hypothesis → available information and named-operation combination → frozen validation request → deterministic result → incremental value, failure regimes, and current applicability.
- Source follow-up: identify a decision-critical gap → try authorized existing sources → original company/exchange/regulator disclosure → attributable public web material or supported ingest → record attempts, provenance, and remaining impact.
- Review and memory: source/calculation quality review, or historical Decision review with later facts separated; recall before research and consolidate only after frozen supporting records exist.

For a theme that needs the exploration → company verification → applicable valuation → counterevidence chain, compose those steps in order for each surviving name, waiting on prior artifact paths (including `shortage_queue` when further BFS layers are required). An empty candidate list or Decision label `no_opportunity` is a valid research result only after the process map and the tests evidence can support: set `WorkRecord.outcome` to `complete` (or `limited` only when evidence/coverage is incomplete after follow-up). Missing a required stage is a method defect, not an acceptable limited finish. Do not treat no-candidate / `no_opportunity` as execution `failed`.

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

Map each independent stage to an existing Bot with the matching responsibility. Send one complete brief for that `stage_id` only, with paths through native messaging; never assume parent-chat context. The owned output is the stage file named in the brief—not later stages. Independent briefs may run concurrently. Dependent work waits for the cited artifact. After the specialist returns, check the stage file and update the run manifest status; continue at `next_stage_id`.

A Routine may reopen the same `request_id`, read `data/runs/<request_id>/manifest.json`, and continue at `next_stage_id`. That reopen uses research files, not a dispatcher or state machine.

During research, a specialist may adjust the plan, add an in-scope candidate, or request targeted source follow-up. Record the reason and keep ownership clear. When a call fails, preserve its reason and retry the same bounded input if useful. Do not create task nodes or poll a hidden completion state.

Use these meanings consistently:

- utility `CallResult.status`: `ok`, `partial`, `error`;
- execution `WorkRecord.outcome`: `complete`, `limited`, `failed`;
- Decision label: `buy`, `sell`, `watch`, `no_opportunity`, `no_factor_increment`.

## 5. Handoff and close

The specialist returns its result to the declared stage-file path with evidence and calculation references, limitations, and next check. The coordinator reads the run manifest and actual stage files, updates manifest status, composes the next missing stage only, and uses [review.md](../../tasks/review.md) for material claim review. Do not deliver a user-facing conclusion while `next_stage_id` is set or required stage files are missing, unless a may-block stage records a real blocker.

Produce the user-facing result with [report.md](../../templates/report.md). Create drafts first. User-facing supply-chain and single-name Decision drafts include `run_manifest_ref` pointing at the private run manifest. Explicitly run `check artifact --archive` for a Decision, WorkRecord, or historical Review; validation without `--archive` creates no historical ID. After successful archive, hand off the returned immutable path/ID and apply justified memory updates. A failed archive or memory write remains a failure and must not be described as saved.
