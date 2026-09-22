from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[2]
PACKAGER = PROJECT_ROOT / "scripts/install.ps1"
PWSH = Path(r"C:\Users\Public\PowerShell\7\pwsh.exe")
pytestmark = pytest.mark.skipif(
    os.name != "nt" or not PWSH.is_file(),
    reason="the Windows PowerShell release packager requires the stable pwsh executable",
)

ACTIVE_BOT_FILES = (
    "bot-kit/README.md",
    "bot-kit/prompts/common.md",
    "bot-kit/prompts/chief.md",
    "bot-kit/prompts/research.md",
    "bot-kit/prompts/market.md",
    "bot-kit/prompts/quant.md",
    "bot-kit/prompts/reviewer.md",
    "bot-kit/skills/research-memory/SKILL.md",
    "bot-kit/skills/research-entry/SKILL.md",
    "bot-kit/skills/source-followup/SKILL.md",
    "bot-kit/skills/portfolio-research/SKILL.md",
    "bot-kit/skills/supply-chain-research/SKILL.md",
    "bot-kit/skills/factor-research/SKILL.md",
    "bot-kit/templates/task-brief.md",
    "bot-kit/templates/report.md",
    "bot-kit/templates/review.md",
    "bot-kit/tasks/review.md",
    "bot-kit/tasks/retrospective.md",
    "bot-kit/tasks/event-impact.md",
    "bot-kit/tasks/valuation.md",
    "bot-kit/tasks/decision-brief.md",
    "bot-kit/tasks/supply-chain.md",
    "bot-kit/tasks/company-thesis.md",
    "bot-kit/tasks/factor-study.md",
)


def _write(root: Path, relative: str, contents: str = "fixture\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _synthetic_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    _write(
        root,
        "pyproject.toml",
        '[project]\nname = "cash-research"\nversion = "9.8.7"\nrequires-python = ">=3.12"\n',
    )
    _write(root, "uv.lock", "version = 1\n")
    _write(root, "src/cash_research/__init__.py", "__version__ = '9.8.7'\n")
    _write(root, "src/cash_research/module.py", "VALUE = 1\n")
    _write(root, "config/settings.example.json", "{}\n")
    for relative in ACTIVE_BOT_FILES:
        _write(root, relative)
    _write(root, "docs/deployment.md")
    _write(root, "scripts/run_fixtures.py", "print('synthetic')\n")
    (root / "scripts").mkdir(exist_ok=True)
    shutil.copy2(PACKAGER, root / "scripts/install.ps1")
    _write(root, "fixtures/README.md")
    _write(root, "fixtures/requests/example.json", "{}\n")
    _write(root, "fixtures/scenarios/manifest.json", "{}\n")
    _write(root, "fixtures/memory/evidence.json", "{}\n")
    _write(root, "fixtures/sources/expected.json", "{}\n")
    _write(root, "fixtures/brokers/expected.json", "{}\n")
    _write(root, "fixtures/ingest/document.md")
    _write(root, "fixtures/ingest/excerpt.txt")
    _write(root, "fixtures/ingest/metadata.json", "{}\n")
    _write(root, "fixtures/ingest/series.csv", "date,value\n")
    _write(root, "fixtures/valuation/expected.json", "{}\n")
    _write(root, "fixtures/factors/expected.json", "{}\n")
    _write(root, "fixtures/factors/series.csv", "timestamp,value\n")
    _write(root, "fixtures/reports/decision-draft.json", "{}\n")
    _write(root, "fixtures/reports/decision-report.md", "synthetic report\n")
    _write(root, "fixtures/ingest/excluded.bin", "SYNTHETIC_SECRET_CANARY\n")

    for excluded in (
        ".env",
        "sec-analysis.env",
        ".git/config",
        ".venv/secret.txt",
        "archive/legacy-secret.json",
        "data/private-account.json",
        "tmp/old-output.json",
        "private/bot-mapping.json",
        "tests/private-fixture.txt",
        "bot-kit/contracts.md",
        "bot-kit/evaluation.md",
    ):
        _write(root, excluded, "SYNTHETIC_SECRET_CANARY\n")
    return root


def _run_packager(root: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(PWSH),
            "-NoProfile",
            "-File",
            str(root / "scripts/install.ps1"),
            "-Root",
            str(root),
            "-OutputPath",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_release_bundle_is_deterministic_allowlisted_and_manifest_verified(
    tmp_path: Path,
) -> None:
    root = _synthetic_project(tmp_path)
    first = root / "tmp/releases/cash-research-9.8.7-a.zip"
    second = root / "tmp/releases/cash-research-9.8.7-b.zip"

    first_run = _run_packager(root, first)
    second_run = _run_packager(root, second)
    assert first_run.returncode == 0, first_run.stderr
    assert second_run.returncode == 0, second_run.stderr
    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names[:-1]) + ["release-manifest.json"]
        assert "src/cash_research/module.py" in names
        assert "bot-kit/tasks/review.md" in names
        assert "bot-kit/tasks/event-impact.md" in names
        assert "bot-kit/skills/source-followup/SKILL.md" in names
        assert "bot-kit/skills/portfolio-research/SKILL.md" in names
        assert "bot-kit/skills/supply-chain-research/SKILL.md" in names
        assert "bot-kit/skills/factor-research/SKILL.md" in names
        assert "bot-kit/tasks/valuation.md" in names
        assert "bot-kit/tasks/decision-brief.md" in names
        assert "bot-kit/tasks/supply-chain.md" in names
        assert "bot-kit/tasks/company-thesis.md" in names
        assert "bot-kit/tasks/factor-study.md" in names
        assert "fixtures/requests/example.json" in names
        assert "fixtures/ingest/document.md" in names
        assert "fixtures/ingest/excerpt.txt" in names
        assert "fixtures/ingest/metadata.json" in names
        assert "fixtures/ingest/series.csv" in names
        assert "fixtures/valuation/expected.json" in names
        assert "fixtures/factors/expected.json" in names
        assert "fixtures/factors/series.csv" in names
        assert "fixtures/reports/decision-draft.json" in names
        assert "fixtures/reports/decision-report.md" in names
        assert "fixtures/ingest/excluded.bin" not in names
        assert "release-manifest.json" in names
        assert not any(
            name.startswith((".git/", ".venv/", "archive/", "data/", "tmp/", "tests/", "private/"))
            for name in names
        )
        assert "bot-kit/contracts.md" not in names
        assert "bot-kit/evaluation.md" not in names
        assert b"SYNTHETIC_SECRET_CANARY" not in b"".join(
            archive.read(name) for name in names
        )

        manifest = json.loads(archive.read("release-manifest.json"))
        assert manifest["package_version"] == "9.8.7"
        assert manifest["python_requirement"] == ">=3.12"
        for item in manifest["files"]:
            payload = archive.read(item["path"])
            assert len(payload) == item["size"]
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]


def test_packager_rejects_escape_and_existing_output_without_modifying_it(
    tmp_path: Path,
) -> None:
    root = _synthetic_project(tmp_path)
    outside = tmp_path / "outside.zip"
    escaped = _run_packager(root, outside)
    assert escaped.returncode != 0
    assert not outside.exists()

    output = root / "tmp/releases/release.zip"
    assert _run_packager(root, output).returncode == 0
    before = output.read_bytes()
    repeated = _run_packager(root, output)
    assert repeated.returncode != 0
    assert output.read_bytes() == before


def test_packager_rejects_fixture_parent_symlink_before_reading_outside(
    tmp_path: Path,
) -> None:
    root = _synthetic_project(tmp_path)
    outside = tmp_path / "outside-fixtures"
    _write(outside, "canary.json", "SYNTHETIC_OUTSIDE_CANARY\n")
    link = root / "fixtures/requests/external"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink is unavailable: {exc}")

    output = root / "tmp/releases/reparse.zip"
    completed = _run_packager(root, output)
    assert completed.returncode != 0
    assert not output.exists()
    assert (outside / "canary.json").read_text(encoding="utf-8") == "SYNTHETIC_OUTSIDE_CANARY\n"


def test_packager_help_does_not_create_output(tmp_path: Path) -> None:
    completed = subprocess.run(
        [str(PWSH), "-NoProfile", "-File", str(PACKAGER), "-Help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0
    assert "OutputPath" in completed.stdout
    assert not list(tmp_path.iterdir())
