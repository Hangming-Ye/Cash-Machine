# Synthetic validation fixtures

Everything under `fixtures/` is synthetic or explicitly sanitized validation material. It must not contain credentials, private holdings, production Bot mappings, or live account responses.

`scenarios/manifest.json` maps the approved acceptance baseline:

- 9 core cases: three markets (`us`, `hk`, `cn`) by three research types (`supply_chain`, `portfolio`, `factor`);
- 8 exception cases from SC-002;
- 3 memory patterns for periodic delta, long-term thesis continuation, and deep-analysis revision.

The mapping is an inventory, not evidence that a case ran. New entries start as `not_run`; only the acceptance record may link later execution evidence. Each entry names the task that owns its future fixtures.

## Request ownership

The six workflow templates are intentionally absent until their assigned tasks create the schema-valid request and its expected data:

| Template | Owner |
| --- | --- |
| `fixtures/requests/evidence-ingest.json` | T022 |
| `fixtures/requests/memory-recall.json` | T011 |
| `fixtures/requests/valuation.json` | T029 |
| `fixtures/requests/factor-new-combination.json` | T048 |
| `fixtures/requests/report-check.json` | T032 |
| `fixtures/requests/memory-update.json` | T011 |

Do not add placeholder IDs or manufactured financial results. Templates may use `{{field_name}}` tokens for values declared in the manifest step's `captures`. IDs come from the matching `CallResult.artifacts[].artifact_id`. Version values are read only from a matching JSON artifact whose relative path resolves inside the unique run directory. The T011 template/CLI work must expose `expected_version` (or its declared equivalent) in that artifact; the runner fails rather than inventing one. The validation runner copies and renders templates inside the unique run directory and never overwrites repository templates.

## Runner

After all six templates and the T009 CLI exist:

```sh
uv run python scripts/run_fixtures.py --root /workspace/cash-machine-test --case all
```

The runner first checks all templates and the `cash-research` executable. If either is unavailable, it writes `step-results.json`, reports the workflow as `not_run`, and exits with code 2 without invoking a partial chain. During execution it stops on the first failed step, records stdout/stderr and the parsed JSON envelope, and leaves later steps `not_run`. It preserves an aggregate `partial` result if any CLI step is partial. Exit code 0 means only that the synthetic workflow command chain completed; expected numerical comparisons remain assigned to T060, and this is not live-data or native Grok evidence.
