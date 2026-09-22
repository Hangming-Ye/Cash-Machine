# Historical decision retrospective v1.0

Use this method only for an archived Decision. First read its frozen `memory_packet_refs`, evidence/calculation references, cutoff, horizon, conditions, assumptions, price references, risks, and invalidators.

Also read `bot-kit/prompts/common.md` and `bot-kit/skills/research-memory/SKILL.md`, plus the standalone assignment's actual launcher, output path, and downstream owner. Return the Review draft path, evidence/calculation references, limitations, archive result, and—only after archive—the Review ID/path for a lesson handoff.

Check whether the horizon elapsed or an archived invalidator/review condition triggered. Return `not_due`, `not_triggered`, or `inconclusive` with the next check when appropriate. If later facts are already visible, label process assessment unblinded.

Keep **original inputs** exactly as frozen at `decision_as_of`; keep **later facts and lessons** separately through aware `review_at`. Never reconstruct original inputs from a current summary.

Assess thesis realization and supported causes among evidence quality, prediction, reasoning, execution, and market path. Unknown execution remains unknown. Use return, benchmark, or adverse-excursion calculations only when immutable program receipts exist; a question-specific calculation gap does not fail every review. Do not invent a hindsight-perfect trade.

A gain does not prove process quality and a loss does not disprove it. One outcome cannot establish a universal lesson. State counterevidence, attribution uncertainty, affected assumptions/dependencies, and the next discriminating test.

Draft the shared Review through [the review template](../templates/review.md). Existing `lesson_refs` may cite prior lessons. New lessons derived here wait until the Review is archived with the exact verified launcher and returned immutable Review ID/path. A failed archive creates no ID. This method creates no Routine, scheduler, state machine, notification, or order.

Recall review memory with `{"request_id":"<CALLER_ID>","query":"<REVIEW_QUESTION>","context_mode":"review","as_of":"<DECISION_AS_OF>","review_at":"<REVIEW_AT>","decision_id":"<RETURNED_DECISION_ID>","topic_ids":[],"lesson_ids":[],"budget":{"max_items":<N>,"max_chars":<N>}}`. Use actual IDs and aware times; placeholders are shapes only.
