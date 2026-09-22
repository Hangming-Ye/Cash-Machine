# Handoff

2026-09-22. Fresh session continues Spec 001 on `D:/Personal_Project/cash-machine`. Do not treat this note as a new requirement. Authority is `docs/intent.md`, `.specify/memory/constitution.md`, and `specs/001-investment-research-framework/`. Latest user instructions override older wording; the overrides already written down are TD-08 and TD-09 in `specs/001-investment-research-framework/task-decisions.md`.

## Where things stand

Branch `codex/001-investment-research-framework` is clean. Head is `58c60d3` (`feat(research): gate user-facing studies on staged run manifests`). That commit is on GitHub: https://github.com/Hangming-Ye/Cash-Machine/tree/codex/001-investment-research-framework

Push used `git@github.com:Hangming-Ye/Cash-Machine.git`. The saved `origin` is still `https://github.com/Hangming-Ye/Cash-Machine.git` and the branch has no upstream, so a plain `git push` will try HTTPS again. The GitHub SSH key is `C:/Users/thomashmye/.ssh/id_ed25519_github`, referenced from `C:/Users/thomashmye/.ssh/config` under `Host github.com`. Do not read, print, or copy that private key. `ssh -T git@github.com` already authenticated as `Hangming-Ye` (GitHub's exit code 1 with "successfully authenticated" is the success text).

## What the user rejected

A one-step public-web pass on two questions scored 0/100: inference-server supply chain, and Nasdaq TXG (10x Genomics Class A, not TSX TGX and not TSX:TXG Torex Gold). Those drafts are gitignored and must not be repaired or cited as research:

- `data/validation/live-inference-servers.md`
- `data/validation/live-txg.md`

The user then required the process change that is now in the spec, plan, methods, and `src/cash_research/runs.py`. Do not re-derive it from this note. Read:

- `specs/001-investment-research-framework/spec.md` US1, US2, FR-003, FR-004, FR-006, FR-014, A-07, SC-001
- `specs/001-investment-research-framework/plan.md` section 3
- `specs/001-investment-research-framework/research.md` R-04 append
- `bot-kit/tasks/supply-chain.md`
- `bot-kit/prompts/chief.md`
- `bot-kit/skills/research-entry/SKILL.md`
- `specs/001-investment-research-framework/contracts/bot-workflow.md`
- `specs/001-investment-research-framework/contracts/cli.md` (`check run`)

Stage order to preserve: BFS frontier toward materials, quantified demand, one shortage/bottleneck test, then `shortage_queue` and recurse only nodes that passed that test, then price-in, program valuation, review. A component that still has materials is not an opaque leaf. The optical-module / Serenity example is a method motive only: no return multiple and no required ticker. Single-name work needs a driver bridge, `compute valuation`, and a sourced quote comparison. News plus reported figures are not the analysis.

`check artifact` enforces the manifest only when the Decision or WorkRecord sets `run_manifest_ref`. Drafts without that field still archive. New supply-chain and single-name conclusions must set it. `check run` reports `next_stage_id` and does not archive. There is no new scheduler or graph database. Tests: `tests/unit/test_run_manifest.py` (44 passed, 1 skipped in the last run with `tests/unit/test_artifacts.py`).

## Open work

Do not check these from the document edits already in `58c60d3`:

- T062–T064 in `specs/001-investment-research-framework/tasks.md` Phase 10. T062 is a method-alignment record at `data/validation/depth-method-align.md`, not a claim that the prose was edited. T063 is one real supply-chain run with separate stage files. T064 is one real single-name quantitative run. T039 does not satisfy either.
- T061 stays open. SC-001, SC-003, SC-004, and SC-006 were still blocked before this depth change. Historical rows in `acceptance.md` stay historical; they do not meet A-07.
- No real multi-stage study has been run. The next user-facing research has to be many one-stage specialist briefs, resumed from `data/runs/<request_id>/manifest.json`, with workers on `grok-4.7-high`. The main agent does not patch product code. See `AGENTS.md`.

Do not load `sec-analysis.env`. Do not add a data supplier. Do not place orders. Do not commit `data/` or the SSH key. Do not push unless asked. If pushing again, use the SSH URL above or the user must first accept changing the saved `origin`.

## Skills for the next session

- Follow `AGENTS.md` and the bot-kit method files above. No extra Cursor skill is required to resume.
- Use `speckit-implement` only if the user asks to execute `tasks.md`.
- Use the codebase-memory skill only for a structural question about `runs.py`, `artifacts.py`, or `cli.py`.
