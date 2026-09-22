"""Shared paths and mappings for synthetic fixture tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_MANIFEST_PATH = PROJECT_ROOT / "fixtures" / "scenarios" / "manifest.json"


def _load_scenario_manifest() -> dict[str, Any]:
    manifest = json.loads(SCENARIO_MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("evidence_level") != "synthetic":
        raise ValueError("fixture manifest must be marked synthetic")
    if len(manifest.get("core_cases", [])) != 9:
        raise ValueError("fixture manifest must map exactly 9 core cases")
    if len(manifest.get("exception_cases", [])) != 8:
        raise ValueError("fixture manifest must map exactly 8 exception cases")
    if len(manifest.get("memory_cases", [])) != 3:
        raise ValueError("fixture manifest must map exactly 3 memory cases")
    return manifest


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def scenario_manifest() -> dict[str, Any]:
    return _load_scenario_manifest()


@pytest.fixture(scope="session")
def synthetic_case_map(scenario_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = (
        scenario_manifest["core_cases"]
        + scenario_manifest["exception_cases"]
        + scenario_manifest["memory_cases"]
    )
    return {case["id"]: case for case in cases}
