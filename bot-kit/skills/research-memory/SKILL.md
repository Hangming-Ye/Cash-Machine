---
name: research-memory
description: Read time-safe research memory before work, then consolidate evidence-backed topic summaries and lessons after work.
---

# Research Memory

Use this method for every periodic update, long-running thesis, and deep re-analysis. The files are a research aid with provenance, not a substitute for source review or current instructions.

Use only the existing `cash-research` CLI and private workspace files. Do not add a memory service, vector database, hidden prompt hook, scheduler, or approval workflow. Memory must never submit, modify, or cancel an order.

Use the exact launcher and verified release directory from the standalone assignment's tool map. For a uv release, run `uv run --project <VERIFIED_APP_DIR> cash-research`; use bare `cash-research` only when that executable was explicitly verified on `PATH`. `<DATA_ROOT>` is the verified persistent research root and may differ from the versioned application directory.

## Before research

1. Define the question and cutoff. Use explicit IDs for exact records; otherwise use the question and optional `query_metadata.topics`, `methods`, and canonical `securities` (`market:exchange:symbol`). Per-version topics, methods, securities, and bilingual aliases support deterministic lexical retrieval, not semantic proof.
2. Run:

   ```text
   uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> memory recall --request <REQUEST.json>
   ```

3. The request is a JSON object with:
   - `request_id`: unique non-empty caller ID.
   - `query`: the research question.
   - `context_mode`: `current`, `historical`, or `review`.
   - `as_of`: timezone-aware ISO-8601 cutoff. `runtime` is allowed only for current work and is resolved once to server UTC; the packet stores the resolved timestamp.
   - `topic_ids` and `lesson_ids`: lists of exact memory IDs.
   - optional `query_metadata`: non-empty string lists for `topics`, `methods`, and `securities`.
   - `budget.max_items` and `budget.max_chars`: explicit non-negative limits for the returned material. Do not invent a budget silently.
   - Review mode also requires the immutable `decision_id` and a timezone-aware `review_at`.
   Supplying either ID list requests those exact records and bypasses relevance/deduplication. For discovery, omit both lists or send both empty; discovery does not automatically combine with explicit-ID mode.
4. Read the returned `memory_packet` and `memory_content` artifacts. Keep the packet path with the research record so later review can recover exactly what was supplied. A `memory_state` artifact gives the real current/expected version for a later update.
   If content points to `full_index_ref`, open relevant complete entries before use. Record each recalled item as adopted or rejected and why.
5. Treat warnings and gaps as part of the input. `no_history` is a valid no-hit result, not a read failure; for a genuinely new requested topic or lesson, `memory_state` reports `expected_version: 0`. Unknown source availability produces an explicit gap and partial result instead of being treated as no history. A read error, corrupt history, or missing original review packet is a limitation, not an empty memory result.

For genuinely new memory, assign one stable safe `topic_id` or `lesson_id` and use it consistently. Do not claim that new ID already has history. Packet, Decision, Review, Evidence/source and record IDs or immutable paths must be actual values returned by the program. Memory version references use returned `data/topics/.../versions/N.json` or `data/lessons/.../versions/N.json` paths. Sources may be returned `rec_...`, `evi_...`, source record IDs, or verified immutable relative paths; never fabricate one or cite mutable drafts/current files.

Mode rules:

- `current`: reads the latest version formed no later than the resolved `as_of`; later versions and later-available sources are excluded.
- `historical`: reconstructs memory at the stated historical cutoff. It uses `known_at`, source `available_at`, and the validity recorded in that selected version. A later `superseded` version never rewrites the past.
- `review`: `as_of` must equal the archived decision cutoff. The original-input partition comes from that decision's frozen non-review memory packet references. The later-facts-and-lessons partition is selected only through `review_at`. Never mix later facts into what was known at the decision time.

If complete items do not fit the declared budget, the content artifact returns a small partition-preserving pointer to an immutable full index. Follow only the required paths. Do not treat an index entry as if the complete conditions, counterexamples, and sources were read.

## During research

- Periodic work compares the recalled baseline, unresolved questions, and next checks with the new period. Record what changed and what did not.
- Long-running work carries the thesis, supporting and opposing evidence, contradictions, open questions, and next checks across sessions. Preserve unresolved conflict instead of compressing it away.
- Deep re-analysis reopens the cited evidence and calculations for each sub-question. If an assumption changes, identify affected conclusions and rerun the relevant calculation or evaluation.
- Current user instructions and newly verified evidence take precedence over stored memory. Record whether recalled material was used or rejected and why.
- A candidate lesson is a prompt to check, not a certified statistical rule. One success or failure does not make it universally usable.
- Present research conclusions and memory limitations to the user in Chinese. Keep CLI field names, IDs, and paths in English only where they are needed for traceability or the next operation.

## After research

1. Archive the underlying Decision, WorkRecord, or Review through `check artifact --archive` before citing it as a memory source. `check artifact` without `--archive` only validates and does not create historical evidence. A reusable lesson derived from a judgment or review must cite the archived Decision or Review, not a draft. Do not point canonical memory at mutable drafts or `current.json` files.
2. Consolidate rather than append blindly:
   - Update a topic when its thesis, support, opposition, open questions, or next checks changed.
   - Propose a lesson only after review identifies a reusable check or method. Preserve its source, application conditions, counterexamples, validity, and review condition.
   - Keep contradictory evidence. Do not create a duplicate lesson for wording changes alone.
   - Mark an obsolete lesson `superseded` in a new version; never rewrite or delete its prior version.
   - Compare existing lessons first. With no material change, return `no_change` with the existing version and reason. Merge a confirmed duplicate into the stable canonical ID by a new version preserving both provenance sets, conditions, and counterexamples. `duplicate_of` is only a versioned hint; dangling/cyclic relations are gaps, not permission to hide records.
   - One outcome cannot establish a universal rule. Keep unverified synthesis `candidate`.
   - Periodic compression preserves baseline, increment/no-change, and unresolved questions; long-theme compression preserves thesis evolution, support/opposition, and next test; re-analysis preserves evidence/calculation paths, changed assumptions, dependencies, and reruns. These characteristics may combine.
   - Never drop source paths, evidence type/confidence, conditions, counterevidence, expiry, or the distinction between old evidence and a current price.
3. Use the `expected_version` read from `memory_state`, then run:

   ```text
   uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> memory apply --proposal <PROPOSAL.json>
   ```

4. An apply proposal contains `request_id`, `memory_type` (`topic` or `lesson`), `expected_version`, and the exact shared model fields:
   - Topic fields: `topic_id`, `current_thesis`, `support_refs`, `opposing_refs`, `changes`, `open_questions`, `next_checks`; optional `topics`, `methods`, `securities`, `aliases`.
   - Lesson fields: `lesson_id`, `check_or_method`, `applies_when`, `source_refs`, `counterexamples`, `validity`, `review_condition`; optional retrieval metadata and `duplicate_of`. `validity` is `candidate`, `usable`, or `superseded`.
   Example lesson payload inside the proposal: `{"lesson_id":"qualification-check","check_or_method":"verify acceptance before revenue","applies_when":"orders precede acceptance","source_refs":["<RETURNED_REVIEW_ID>"],"counterexamples":["cancelable booking"],"validity":"candidate","review_condition":"review after shipment","topics":["commercialization"],"methods":["order-to-revenue"],"securities":[],"aliases":["订单兑现"]}`.
5. Do not send `version`, `known_at`, or `updated_at`. The program assigns the next version and current UTC times. It cannot backdate memory formation to a source publication date.
6. Read the immutable `topic_summary` or `lesson` version returned by apply, then run an explicit-ID current recall to obtain `memory_state`. For an active topic/lesson, recall should return that version and matching state. A newly `superseded` Lesson is excluded from content, but the recall state must still report its current version; verify the apply artifact and state without forcing it back into content. This write-read check does not prove semantic correctness.
7. On a version conflict, recall again, compare the winning version with the proposal, merge both evidence sets without dropping either writer's work, and apply using the new expected version. Do not edit `data/topics`, `data/lessons`, version files, current files, packets, or indexes directly.

Return the applied immutable version, or `no_change` and why. Use the actual state `expected_version`; the program assigns formation time and cannot backdate it.

The command validates shape, frozen references, secret fields, optimistic version, and atomic storage. It does not certify the truth or usefulness of the model's synthesis; that remains part of evidence review.
