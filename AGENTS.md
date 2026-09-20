# Project Working Rules

- Read `docs/intent.md` before specification or implementation work. It is the confirmed intent; research reports and `bot-kit/` are design candidates.
- Use the project-local Spec Kit workflow. Create a feature spec before implementing product behavior, and keep plan/tasks consistent with that spec.
- Do not treat the placeholder constitution as approved project policy.
- `archive/` is reference-only. Do not execute, evolve, or import the legacy package as the active application unless the current task explicitly chooses to reuse it.
- Legacy code compatibility is not a requirement. Preserve the archived snapshot; implement approved changes outside the archive.
- Keep credentials and runtime data out of Git. The local `sec-analysis.env` is not a source file or a default new-project configuration.
- Preserve the existing Git history, `main` branch name, and remote configuration. Do not push unless requested.
- Put temporary scripts and inspection output in `tmp/` and remove them when finished.
- Distinguish document/static checks, mocked tests, live data access, and actual Grok Bot behavior in completion reports.
