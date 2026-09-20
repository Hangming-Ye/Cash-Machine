"""Hard-fail guards so this tree never grows order-placement APIs.

Call ``assert_no_order_methods`` from tests (and optionally at import time).
``scan_broker_sources`` greps broker modules for forbidden identifiers.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sec_analysis.core.errors import BrokerReadOnlyError

# Normalized (lowercase, underscores stripped) method names that must never exist.
FORBIDDEN_METHODS = frozenset(
    {
        "placeorder",
        "modifyorder",
        "cancelorder",
        "submitorder",
        "createorder",
        "sendorder",
        "replaceorder",
        "transmitorder",
        "closeorder",
        "updateorder",
    }
)

FORBIDDEN_SOURCE_TOKENS = frozenset(
    {
        "placeOrder",
        "place_order",
        "modifyOrder",
        "modify_order",
        "cancelOrder",
        "cancel_order",
        "submitOrder",
        "submit_order",
        "ib.placeOrder",
        "ib.cancelOrder",
        "readonly=False",
        "readonly = False",
    }
)

_ORDER_VERBS = ("place", "modify", "cancel", "submit", "create", "send", "replace", "transmit")


def _normalize(name: str) -> str:
    return name.replace("_", "").lower()


def public_callables(obj: Any) -> list[str]:
    names: list[str] = []
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            attr = getattr(obj, name)
        except Exception:
            continue
        if callable(attr):
            names.append(name)
    return names


def assert_no_order_methods(obj: Any) -> None:
    """Raise if ``obj`` (class or instance) exposes an order-placement method."""

    class_name = getattr(obj, "__name__", obj.__class__.__name__)
    allowed_plain = {"BrokerReadOnlyClient", "FlexActivityReadOnlyClient"}
    if "readonly" not in class_name.lower() and class_name not in allowed_plain:
        raise BrokerReadOnlyError(
            f"{class_name} must be named *ReadOnly* (or be a *ReadOnlyClient interface)"
        )
    for name in public_callables(obj):
        normalized = _normalize(name)
        if normalized in FORBIDDEN_METHODS:
            raise BrokerReadOnlyError(f"{class_name}.{name} is a forbidden order method")
        lowered = name.lower()
        if "order" in lowered and any(verb in lowered for verb in _ORDER_VERBS):
            raise BrokerReadOnlyError(f"{class_name}.{name} looks like an order-placement method")


def scan_broker_sources(root: Path | None = None) -> list[str]:
    """Return human-readable hits of forbidden tokens under ``brokers/``."""

    brokers_root = root or Path(__file__).resolve().parents[1]
    hits: list[str] = []
    for path in brokers_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        rel = path
        for token in FORBIDDEN_SOURCE_TOKENS:
            if token in text:
                # Allow the token to appear only inside this safety module's sets.
                if path.name == "safety.py":
                    continue
                hits.append(f"{rel}: token {token!r}")
        hits.extend(_ast_function_hits(path, text))
    return hits


def _ast_function_hits(path: Path, text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [f"{path}: unreadable Python"]
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _normalize(node.name) in FORBIDDEN_METHODS:
                found.append(f"{path}:{node.lineno} defines {node.name}")
    return found


def assert_broker_tree_is_read_only(classes: Iterable[type] | None = None) -> None:
    from sec_analysis.brokers.longbridge import LongbridgeReadOnlyClient
    from sec_analysis.core.interfaces import BrokerReadOnlyClient, FlexActivityReadOnlyClient
    from sec_analysis.providers.stub import StubBrokerReadOnlyClient

    from .flex import IbkrFlexReadOnlyClient
    from .readonly_client import IbkrReadOnlyClient

    targets = list(
        classes
        or (
            BrokerReadOnlyClient,
            FlexActivityReadOnlyClient,
            IbkrReadOnlyClient,
            IbkrFlexReadOnlyClient,
            LongbridgeReadOnlyClient,
            StubBrokerReadOnlyClient,
        )
    )
    for cls in targets:
        assert_no_order_methods(cls)
    hits = scan_broker_sources()
    if hits:
        raise BrokerReadOnlyError("Forbidden order tokens in brokers/:\n" + "\n".join(hits))


def enforce_on_subclass(cls: type) -> type:
    """Class decorator for extra implementations."""
    assert_no_order_methods(cls)
    return cls
