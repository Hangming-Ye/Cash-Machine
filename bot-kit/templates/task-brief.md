# Standalone research task brief

Copy this template for one bounded assignment. Replace every angle-bracket field or mark it `not_applicable` with a reason. Do not insert invented archive IDs, quotations, prices, holdings, or quantitative results.

## Identity and ownership

- Caller-assigned request ID: `<request_id>`
- Caller-assigned task ID: `<task_id>`
- Stage ID for this assignment only: `<stage_id>`
- Run manifest reference: `<data/runs/<request_id>/manifest.json or not_applicable>`
- Parent request ID, if any: `<request_id or not_applicable>`
- Responsible existing Bot / method owner: `<mapped responsibility>`
- Owned output path: `<workspace-relative stage file path for this stage_id only>`
- Upstream artifact(s): `<immutable paths/IDs or none>`
- Downstream recipient and expected handoff: `<recipient, artifact, and location>`

Caller-assigned IDs correlate this assignment. They are not program-generated `rec_...` records, `mem_...` packets, Evidence IDs, calculation IDs, or experiment IDs. This assignment must not perform later stages; write only the owned stage file and leave subsequent `stage_id` values to later briefs.

## Question and decision context

- Original user question: <verbatim question>
- Research objective: <what this work must establish>
- Authorized scope: <markets, themes, securities, accounts, and exclusions>
- Material scope change requiring user choice: <boundary>
- Market/security/topic identity: <resolved identity, exchange, currency, or unresolved reason>
- Horizon: <research/decision horizon>
- Knowledge cutoff (`as_of`, timezone-aware): <timestamp>
- Context mode: `<current | historical | review>`
- Review fields when applicable: <archived decision ID, decision cutoff, review cutoff>
- Decision-changing evidence or condition: <what could alter the result>

## Inputs and provenance

| Input/reference | Kind | Original source and locator | Published/event/available time | Coverage, units, and limitation |
| --- | --- | --- | --- | --- |
| <path or returned ID> | <evidence / record / calculation / request> | <source + locator> | <known times or explicit unknown> | <scope and limitation> |

- Authorized account/position input and reported time: <immutable reference or not_applicable; never copy secrets>
- Prior Decision/WorkRecord/Review: <immutable reference or none>
- Calculation/experiment references: <actual immutable references or pending>
- Assumptions supplied for calculation: <explicit assumptions; no generated numeric result>
- Source conflicts already known: <references and disagreement>

## Memory supplied to this task

- Memory packet reference: <actual `data/memory-packets/.../packet.json`; if recall was not run or failed, state that and the reason>
- Recall hit state: <selected history / `no_history`; a successful no-hit recall still keeps its actual packet reference>
- Packet ID and context mode: <returned values>
- Packet `as_of` / `review_at`: <returned values>
- Selected topic/lesson version references: <immutable references>
- Recall warnings and gaps: <returned values>
- Adopted memory and reason: <items>
- Rejected memory and reason: <items>

## Method composition

- Selected methods: <supply chain / company-holding / event / valuation / factor / source follow-up / quality review / historical review / memory>
- Why these methods answer the question: <rationale>
- Ordered dependencies: <only real prerequisites>
- Independent work that may run concurrently: <separate questions and owners>

### Required analysis

1. <financial/research step with its input>
2. <evidence or calculation check>
3. <counterevidence, invalidator, or failure-regime check>

### Completion checks

- <claim-to-source and time/unit check>
- <method-specific check: commercial chain, valuation receipt, or frozen factor protocol>
- <contrary case and limitations>
- <required output and immutable reference>

Do not impose a default candidate, source, finding, or revision count. Scale the work to the decision-critical evidence and declared budget.

## Actual capability and fallback

- Actual tool map for this run: <available operations, exact verified CLI launcher, and versioned application directory; for uv use `uv run --project <VERIFIED_APP_DIR> cash-research`, and use bare `cash-research` only if verified on PATH>
- Persistent data root passed to `--root`: <verified private data/project root; do not assume it is the application release directory>
- Capability table version checked: <path/version>
- Pending operations that must not be claimed: <operations>
- Preferred source path: <existing authorized source>
- Fallback path: <other existing source → original disclosure → public web/supported ingest>
- If evidence remains unavailable: <gap, affected conclusion, unaffected work>
- Retry input after a call failure: <same bounded request/path>
- Escalate when: <material scope choice, new supplier, permission, or irreducible core evidence>

## Required delivery

- Execution outcome: `<complete | limited | failed>`
- Research result class: `<complete research | evidence-limited | no opportunity | no factor increment | execution failure>`
- Decision label when applicable: `<buy | sell | watch | no_opportunity | no_factor_increment | not_applicable>`
- Required report sections: conclusion, evidence, contrary case, horizon, conditions/price when supportable, risks/invalidators, gaps, next check
- Draft record type: `<Decision | WorkRecord | historical Review | not_applicable>`
- Review requirement: <quality review scope or reason not required>
- Archive requirement and destination: <explicit `check artifact --archive` handoff>
- Post-archive memory update: <topic/lesson IDs and source record, or no change>

## Failure response

If the core question cannot be evaluated, return the exact failed requirement, attempted paths, impact, safe partial work, and bounded retry/escalation input. Do not return an empty result, fabricate a successful call, create a new workflow node, or overwrite prior history.
