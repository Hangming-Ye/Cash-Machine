from __future__ import annotations

from cash_research.scope import classify_scope


def test_no_template_liquid_cooling_us_still_proceeds() -> None:
    decision = classify_scope(
        authorized={"markets": ["US"]},
        proposal={
            "market": "US",
            "question": "Which US liquid-cooling suppliers benefit from AI data-center buildout?",
        },
    )

    assert decision.action == "proceed"
    assert decision.reason == "no_template_still_in_scope"
    assert "authorized" in decision.follow_up.lower() or "continue" in decision.follow_up.lower()
    assert "fetch" not in decision.follow_up.lower()


def test_market_outside_assignment_asks_user_without_fetch() -> None:
    decision = classify_scope(
        authorized={"markets": ["US"]},
        proposal={
            "market": "CN",
            "question": "Compare A-share liquid-cooling names to the US set",
        },
    )

    assert decision.action == "ask_user"
    assert decision.reason == "market_outside_assignment"
    assert "fetch" not in decision.follow_up.lower()
    assert "decide" in decision.follow_up.lower() or "decision" in decision.follow_up.lower()


def test_supplier_outside_allowlist_asks_user() -> None:
    decision = classify_scope(
        authorized={"markets": ["US", "HK", "CN"]},
        proposal={
            "market": "US",
            "source": "bloomberg",
            "question": "Pull Bloomberg consensus for liquid-cooling names",
        },
    )

    assert decision.action == "ask_user"
    assert decision.reason == "supplier_outside_allowlist"
    assert "fetch" not in decision.follow_up.lower()
    assert "supplier" in decision.follow_up.lower() or "added" in decision.follow_up.lower()


def test_assignment_cannot_authorize_supplier_outside_allowlist() -> None:
    decision = classify_scope(
        authorized={"markets": ["US"], "sources": ["finnhub", "bloomberg"]},
        proposal={
            "market": "US",
            "source": "bloomberg",
            "question": "Use Bloomberg via an assignment that lists it",
        },
    )

    assert decision.action == "ask_user"
    assert decision.reason == "supplier_outside_allowlist"
    assert "fetch" not in decision.follow_up.lower()


def test_authorized_hk_with_finnhub_proceeds() -> None:
    decision = classify_scope(
        authorized={"markets": ["US", "HK", "CN"]},
        proposal={
            "market": "HK",
            "source": "finnhub",
            "question": "HK-listed cooling-related names via Finnhub",
        },
    )

    assert decision.action == "proceed"
