# sec-analysis reference archive

Archived on 2026-09-20 from the original `main` commit recorded in [ARCHIVE_MANIFEST.json](ARCHIVE_MANIFEST.json).

This directory preserves the legacy data-fetching framework as reference material. It is not the active application or a compatibility constraint for Cash Machine. Reuse is optional and lower priority than the new framework's requirements and simplicity.

All 70 previously tracked files were preserved byte-for-byte and verified with SHA-256. Their original relative paths, dependency lock, tests, README, calling guide, and configuration example remain inside this directory. The parent Git repository retains the original commit history; no nested Git repository was created.

Live credentials, including the untracked `sec-analysis.env`, were not included. Do not run the archive with real accounts just to inspect its behavior.

Read [the original README](README.md) and [calling guide](docs/calling-guide.md) for the old implementation, or [the source-reading summary](../../research/13-current-data-implementation.md) for its known boundaries. Treat original installation and execution instructions as historical reference, not setup instructions for the new project.
