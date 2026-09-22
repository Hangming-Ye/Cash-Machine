<!-- SPECKIT START -->
Active feature: `specs/001-investment-research-framework/`.

Implementation authority is the current task in `tasks.md` together with the exact requirements,
approved decisions, plan sections, contracts, and predecessor results that it cites.
<!-- SPECKIT END -->

# Authority and scope

1. Read `docs/intent.md` before specification or implementation work. It is confirmed intent;
   research reports and `bot-kit/` are design candidates unless adopted by approved feature documents.
2. Follow the project-local Spec Kit flow: intent -> spec -> plan -> tasks -> implementation.
   Keep code, tests, contracts, documentation, and tasks consistent with the latest approved sources.
3. The current task is the unit of implementation authority. Implement its smallest sufficient change;
   do not add nearby features, speculative abstractions, compatibility work, or unrelated cleanup.
4. The constitution records confirmed constraints. It does not approve new plan assumptions.
   If a task conflicts with intent, the constitution, the approved plan, or a requirement, stop and
   obtain the required user decision instead of silently changing the meaning or acceptance standard.
5. Tests, tooling, evidence, research candidates, and convenient implementation choices do not create
   product requirements. Latest explicit user instructions override older project documents.

# Main-agent role

1. At the start of each task, and again after compaction, recovery, or handoff, the main agent must
   personally read this file, the complete current task and dependencies, every cited requirement and
   approved decision, the relevant contracts, and the current source paths affected by the task.
2. The main agent owns task selection, dependency ordering, worker briefs, audit of actual diffs and
   evidence, missing verification, acceptance decisions, and the final user report. Summaries and code
   graphs may aid navigation but cannot replace the main agent's reading of authoritative context.
3. Delegate all development to worker subagents configured exactly with `model=grok-4.7` and
   `reasoning_effort=high`. Development includes production code, tests, documentation, scripts,
   configuration, generated artifacts, integration edits, and conflict repairs.
4. The main agent must not author or patch development changes, including small integration fixes.
   Audit findings and failed checks go back to the responsible worker for repair and re-verification.
5. If the exact model or effort is unavailable, report the blocker; do not silently substitute another.

# Delegation and parallel work

1. Before dispatch, convert the task into a concrete brief containing:
   - the goal, exact task text, FR/SC or other acceptance clauses, and completed dependencies;
   - required context plus exact files, symbols, contracts, and approved decisions;
   - exclusive owned write paths and explicit read-only or out-of-scope paths;
   - the narrowest required tests and evidence, with exact commands where known;
   - a warning that other agents share the repository and must not be reverted or absorbed;
   - a request to inspect the final diff and report changes, commands, results, and remaining risks.
2. Run workers in parallel only for independent, dependency-ready work with non-overlapping owned files,
   generated outputs, and tests. Do not use parallelism to bypass task dependencies.
3. The shared worktree may already be dirty. Workers must preserve every unrelated change and must not
   stage or commit concurrently from a shared dirty tree.
4. Use separate worktrees or checkouts with their own indexes for concurrent Git writes. Shared-tree,
   non-overlapping edits are allowed when safe, but authorized staging and commits must be serialized.
   Do not create a worktree, checkout, or commit for every task by default.
5. Assign integration and conflict resolution to one worker with explicit ownership after prerequisite
   work is ready. The main agent audits the integrated result rather than editing it.

# Worker implementation discipline

1. Read the assigned authority and current file contents before editing. Preserve local style and make
   only the task-backed change; never reset, clean, overwrite, reformat, or revert other agents' work.
2. For behavior or defect work, create the narrowest failing test or measurement first when meaningful.
   For scaffolding or documents, use the smallest applicable schema, import, command, or static check.
3. Run the owning-layer check first, then only the affected contract or integration regressions required
   by the task. Do not weaken assertions, hide failures, or bypass the native production path.
4. Inspect the final diff for scope, secrets, generated noise, and accidental changes. Report exact
   commands, exit status, material results, skipped checks, and the concrete remaining risk.
5. A worker may complete and verify its assigned task but must not declare a phase, Gate, or project done.

# Audit and verification

1. The main agent audits actual file diffs and artifacts against the task, controlling requirements,
   path ownership, and evidence. Reject missing behavior, mock-only claims about production, out-of-scope
   edits, or material correctness, privacy, licensing, security, data-loss, and architecture hazards.
2. Each finding must name the violated requirement, concrete path or symbol, impact, and required result.
   Return it to the responsible worker; after repair, re-audit the actual diff and evidence.
3. Reuse valid, explicit verification evidence for unchanged code and the same revision. A different
   executor or model alone does not justify rerunning it. Run only missing, invalidated, or task-required
   checks, broadening scope when a shared boundary or unexplained failure makes that necessary.
4. The main agent accepts a task only from actual artifacts and check results. A worker statement, passing
   static check, successful API call, or generated report is not evidence of a later integration or live
   Gate. After acceptance, delegate checkbox and evidence-document edits to a worker; the main agent audits them.
5. A data or access failure blocks only the related live case and conclusions. Continue independent work,
   record the limitation, and never lower the acceptance standard or mark the affected case complete.

# Cash Machine product boundaries

1. Build for the existing native Grok Bot: its resident, scheduled, concurrent, mobile, PC, Skill, and
   terminal capabilities. Do not substitute an arbitrary harness for proof of actual Grok Bot behavior,
   or build a second agent platform, scheduler, recovery service, notification system, or trading engine.
   The required subagent development model is separate from Grok Bot's platform-managed runtime model.
2. The existing source baseline has exactly six integrations: Finnhub, Tiingo, FMP stable, AKShare,
   IBKR Flex, and Longbridge OAuth. Web search, company IR, exchange/regulator filings, and user-provided
   material are evidence channels, not new suppliers. Do not select, purchase, or add another supplier
   without an explicit user choice; record gaps and continue unaffected work.
3. Brokerage access is read-only. Never submit, modify, or cancel orders. Never treat a read failure as
   an empty portfolio or fill missing values with invented defaults. Authorized private user research may
   use account data; never disclose secrets or non-public account data in public or unauthorized outputs.
4. Memory must support periodic, long-running, and analysis-heavy research: preserve incremental baselines,
   evolving hypotheses, unresolved questions, evidence and calculation provenance, validity conditions,
   review outcomes, deduplicated lessons, relevant recall, reinjection, updates, and invalidation.
5. Distinguish paper or external research, document/static checks, synthetic or mocked tests, live data
   access, and native Grok Bot behavior in every completion claim. Evidence at one level proves only that level.
6. `archive/` is reference-only. Preserve the snapshot and do not execute, evolve, import, or treat it as
   the active application unless a current approved task explicitly authorizes bounded reuse elsewhere.
   Legacy compatibility is not a requirement.

# Code discovery and tools

1. For structural code questions, prefer the repository code graph when its MCP tools are actually
   available: identify the project/generation, search and trace relevant symbols, obtain exact snippets,
   then call `check_index_coverage` for material paths.
2. Treat the graph as a locator. Read current source for reported partial, skipped, excluded, stale, or
   unknown ranges; use `rg` or direct reads for literals, configuration, documents, and coverage gaps.
3. Never claim unavailable graph tools were used. Do not install a graph service or add graph tooling code
   as part of product work.

# Workspace, privacy, and Git

1. Keep credentials, non-public holdings, Bot mappings, and runtime data out of Git and shared reports.
   `sec-analysis.env` is neither source nor a default configuration file and must not be loaded implicitly.
2. Put temporary scripts and inspection output under `tmp/`; remove them when finished. Do not turn scratch
   notes into persistent project documents unless the current task requires that document.
3. Preserve the existing Git history, `main` branch name, and remote configuration. Do not initialize or
   replace version control, rewrite history, or push unless the user explicitly requests it.
4. Respect file ownership and inspect status before and after work. Never stage, commit, or discard changes
   outside the assigned task, and never use destructive Git or filesystem operations without authority.

# Completion report

Report the task and requirement satisfied, files changed, exact verification and evidence level achieved,
and remaining blockers or skipped checks. Do not claim completion while an applicable acceptance condition
is failing, unverified, or supported only by a weaker evidence class.
