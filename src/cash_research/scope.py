"""Classify whether a research proposal stays inside the assignment scope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from cash_research.config import ALLOWED_SOURCE_OPERATIONS


@dataclass(frozen=True)
class ScopeDecision:
    """Outcome of checking a proposal against an assignment's authorized scope."""

    action: str
    reason: str
    follow_up: str


def classify_scope(
    authorized: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> ScopeDecision:
    """Decide whether a proposal may proceed inside the authorized assignment scope.

    A missing or unknown template does not block an otherwise in-scope question.
    A market outside the assignment's authorized markets, or a supplier outside the
    six existing sources, stops and asks the user without executing the expansion.
    """

    authorized_markets = {str(m) for m in authorized.get("markets", ())}
    assignment_sources = authorized.get("sources", ALLOWED_SOURCE_OPERATIONS.keys())
    allowed_sources = {
        str(s) for s in assignment_sources
    } & set(ALLOWED_SOURCE_OPERATIONS.keys())

    market = proposal.get("market")
    if market is None or str(market) not in authorized_markets:
        return ScopeDecision(
            action="ask_user",
            reason="market_outside_assignment",
            follow_up=(
                "The proposed market is outside this assignment's authorized markets. "
                "The user must decide before the market set changes; do not run the "
                "expanded request."
            ),
        )

    source = proposal.get("source")
    if source is not None and str(source) not in allowed_sources:
        return ScopeDecision(
            action="ask_user",
            reason="supplier_outside_allowlist",
            follow_up=(
                "The proposed supplier is outside the six existing sources. "
                "The user must decide before a supplier is added; do not use it."
            ),
        )

    template_id = proposal.get("template_id")
    if template_id is None or not str(template_id).strip():
        return ScopeDecision(
            action="proceed",
            reason="no_template_still_in_scope",
            follow_up=(
                "No same-name template exists; continue inside the authorized scope."
            ),
        )

    return ScopeDecision(
        action="proceed",
        reason="in_scope",
        follow_up="Proposal is within the authorized scope; continue.",
    )
