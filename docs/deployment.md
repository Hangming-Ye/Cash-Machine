# Cash Research manual packaging, deployment, and rollback

This procedure packages code on the Windows development workspace and installs it manually in a versioned application directory on the private Grok cloud computer. It does not deploy by itself, change a Routine, install a background service, monitor health, send notifications, or alter persistent research data.

The target cloud OS, Python inventory, permissions, private project root, and Bot/Routine mapping are still unavailable because T001 is blocked. Replace every angle-bracket path only after it is verified on the target. Do not treat the example `/workspace/cash-machine` path or any Bot name as confirmed live configuration.

## 1. Build a reviewable bundle on Windows

Before packaging, choose a unique release ID. Use the project version plus an explicit candidate/build suffix; the script refuses overwrite, so rerunning requires a new filename. A bundle made while other implementation tasks are changing is a frozen candidate snapshot, not proof that the whole feature is final.

From the verified repository root:

```powershell
$ProjectRoot = (Resolve-Path 'D:\Personal_Project\cash-machine').Path
$ReleaseId = 'cash-research-0.1.0-candidate-001'
$OutputPath = Join-Path $ProjectRoot "tmp\releases\$ReleaseId.zip"

& 'C:\Users\Public\PowerShell\7\pwsh.exe' -NoProfile -File `
  (Join-Path $ProjectRoot 'scripts\install.ps1') `
  -Root $ProjectRoot `
  -OutputPath $OutputPath
```

The command prints JSON containing the absolute ZIP path, package version, file count, and ZIP SHA-256. Save that output with the deployment record. The output must be under the repository's `tmp/releases/`; an existing target, relative output, path escape, non-ZIP name, or symlink/reparse escape is rejected.

The ZIP is deterministic for the same input bytes: entries are ordinal-sorted, use a fixed timestamp, and include `release-manifest.json` with the project version, Python requirement, file sizes, and SHA-256 for every payload file.

### Allowlisted contents

- `pyproject.toml` and `uv.lock`;
- Python files under `src/cash_research/`;
- `config/settings.example.json` only;
- `scripts/install.ps1`, `scripts/run_fixtures.py`, and this deployment guide;
- the active Bot files listed by `bot-kit/README.md`: six prompts, research-entry, research-memory, source-followup, and portfolio-research Skills, task brief, report, and the migrated review, event-impact, valuation, and decision-brief methods;
- synthetic/contract fixtures from the explicit requests, scenarios, memory, sources, brokers, ingest, valuation, and factors fixture directories.

The bundle excludes `.git`, `.venv`, all `.env` files including `sec-analysis.env`, credentials, `data/`, `tmp/` prior outputs, `archive/`, private Bot mappings, test output, account/holding data, and inactive legacy Bot contracts/task cards. Tests inspect synthetic secret canaries; packaging does not read a real credential file.

Review the ZIP before transfer:

```powershell
& (Join-Path $ProjectRoot '.venv\Scripts\python.exe') -m zipfile -l $OutputPath
```

Run the focused packaging test and the relevant project suite before designating a candidate:

```powershell
& (Join-Path $ProjectRoot '.venv\Scripts\python.exe') -m pytest tests/integration/test_packaging.py -q
```

## 2. Transfer without mixing runtime data

Transfer the reviewed ZIP through the user's approved private channel to a staging location inside the verified private project root. Record the transferred path and compare its SHA-256 with the build JSON. Do not place credentials in the ZIP or chat.

The intended layout is:

```text
<PRIVATE_PROJECT_ROOT>/
  app/
    releases/
      <RELEASE_ID>/       # immutable extracted program candidate
  config/                 # private runtime configuration, outside release
  data/                   # persistent records and memory, outside release
  incoming/               # manually transferred ZIPs
```

On a POSIX-like cloud shell, after verifying the actual root and tools:

```sh
set -eu
PROJECT_ROOT='<PRIVATE_PROJECT_ROOT>'
RELEASE_ID='cash-research-0.1.0-candidate-001'
ZIP_PATH="$PROJECT_ROOT/incoming/$RELEASE_ID.zip"
RELEASE_DIR="$PROJECT_ROOT/app/releases/$RELEASE_ID"

test -d "$PROJECT_ROOT"
test -f "$ZIP_PATH"
test ! -e "$RELEASE_DIR"
mkdir -p "$PROJECT_ROOT/app/releases"
mkdir "$RELEASE_DIR"
python3 -m zipfile -e "$ZIP_PATH" "$RELEASE_DIR"
```

Use the target's actual extraction command if `python3` is unavailable. Never extract over an existing release. Do not require PowerShell on a Linux cloud machine.

## 3. Verify the extracted manifest

From the new release directory, verify every payload before installation:

```sh
set -eu
: "${RELEASE_DIR:?set RELEASE_DIR in the same verified deployment shell}"
cd "$RELEASE_DIR"
python3 - <<'PY'
import hashlib, json
from pathlib import Path

root = Path.cwd().resolve()
manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
for item in manifest["files"]:
    path = (root / item["path"]).resolve()
    path.relative_to(root)
    data = path.read_bytes()
    assert len(data) == item["size"], item["path"]
    assert hashlib.sha256(data).hexdigest() == item["sha256"], item["path"]
print(manifest["package_name"], manifest["package_version"], "manifest verified")
PY
```

If the ZIP hash, manifest, or containment check fails, do not install or activate that directory. Keep the previous release selected. Record the failed candidate and reason.

## 4. Rebuild the locked environment manually

The release is self-contained code and lock metadata, not a copied virtual environment. From the versioned release directory:

```sh
set -eu
: "${RELEASE_DIR:?set RELEASE_DIR in the same verified deployment shell}"
cd "$RELEASE_DIR"
uv sync --locked --python 3.12
uv run --project "$RELEASE_DIR" cash-research --help
```

`uv sync --locked` must use the packaged lock file. Do not hand-edit versions on the target to make an install pass. If Python 3.12, `uv`, network access, or permissions are unavailable, record the exact failure and leave the candidate inactive; this procedure does not add a self-healing process.

The locked project declares two optional SDK extras: `akshare` and `longbridge`. Install only the extras required by the mapped responsibilities of this exact release, after confirming both `pyproject.toml` and `uv.lock` in `$RELEASE_DIR` declare them. Run from the verified versioned application directory:

```sh
set -eu
: "${RELEASE_DIR:?set RELEASE_DIR to the verified versioned application directory}"
cd "$RELEASE_DIR"
uv sync --locked --python 3.12 --extra akshare
# Or, when only Longbridge read-only access is mapped:
uv sync --locked --python 3.12 --extra longbridge
# Or, only when the mapped Bot needs both:
uv sync --locked --python 3.12 --extra akshare --extra longbridge
```

Do not install a machine-global or unrecorded SDK, edit locked versions, start OAuth authorization automatically, or treat package installation as proof that credentials, entitlement, source access, or broker routing work. Longbridge OAuth uses the existing protected account setup only when the verified runtime mapping enables it.

Private settings and credentials stay outside the release. Pass only an explicitly verified configuration or environment file when invoking the CLI:

Record the exact launcher and versioned release directory in every standalone Bot brief. The release-safe form is `uv run --project <VERIFIED_APP_DIR> cash-research`; bare `cash-research` is allowed only after that executable is verified on `PATH`. The CLI `--root` points to the persistent data root, not implicitly to the versioned application directory.

```sh
set -eu
: "${PROJECT_ROOT:?set PROJECT_ROOT in the same verified deployment shell}"
: "${RELEASE_DIR:?set RELEASE_DIR to the verified versioned application directory}"
uv run --project "$RELEASE_DIR" cash-research \
  --root "$PROJECT_ROOT" \
  --config "$PROJECT_ROOT/config/settings.json" \
  --env-file '<PROTECTED_ENV_FILE>' \
  memory recall --request '<PRIVATE_REQUEST_JSON>'
```

Do not copy `sec-analysis.env` into the release and do not make it a default configuration file.

## 5. Activate and verify manually

Activation means updating the existing, privately mapped Bot/Skill or test invocation to use the new versioned release path. T001 must first supply that mapping. Record the previous release directory before changing anything.

For T016, install only the current offline slice, keep any temporary test Routine disabled except for its explicit test run, point it at the private test root and synthetic inputs, then record the program/Skill versions and actual outputs. Do not change unrelated production Routines, create a new scheduler, or claim a successful native invocation from `--help` alone.

Use the active files in `bot-kit/README.md`. Do not load inactive legacy task cards or contracts from an older checkout. The same report artifact is used for mobile and PC.

## 6. Roll back by selecting an existing release

Rollback does not rebuild, overwrite, or delete data:

1. Identify the previously recorded release directory and verify it still contains its manifest and locked environment.
2. Run that release's `uv run --project <PREVIOUS_RELEASE_DIR> cash-research --help` and any bounded offline smoke input appropriate to its version.
3. Update the same private Bot/Skill/test invocation path back to that release directory.
4. Confirm the selected path and behavior, then record the failed/new and restored release IDs.
5. Leave persistent `config/` and `data/` untouched. If the older release cannot read data written by the newer format, stop and record the incompatibility; do not delete or rewrite records to force rollback.

Run the smoke command from the exact recorded previous directory, never from whichever release the shell last used:

```sh
set -eu
PREVIOUS_RELEASE_DIR='<PRIVATE_PROJECT_ROOT>/app/releases/<PREVIOUS_RELEASE_ID>'
test -d "$PREVIOUS_RELEASE_DIR"
uv run --project "$PREVIOUS_RELEASE_DIR" cash-research --help
```

No automatic rollback, symlink switcher, health monitor, daemon, scheduled cleanup, or recovery service is introduced. Candidate and old release removal, if ever needed, is a separate deliberate maintenance action against an exact verified path.

## Evidence boundary

Successful local packaging, manifest verification, `uv sync`, or `--help` proves only the corresponding offline/code-install layer. It does not prove target-cloud compatibility, source access, private Bot mapping, native Skill loading, Routine behavior, mobile/PC display, or final acceptance. Record each level separately.
