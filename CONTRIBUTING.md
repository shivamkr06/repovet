# Contributing

Thanks for helping. The project is small on purpose: standard library only, one check per
function, no network inside checks.

## Setup

```bash
git clone https://github.com/OWNER/repovet.git
cd repovet
pip install -e .
python -m unittest discover -s tests
```

## How the code is laid out

| File | Role |
|---|---|
| `src/repovet/github.py` | GitHub API client, cache, rate-limit handling |
| `src/repovet/checks.py` | Pure checks: data in, `Finding` objects out. No network |
| `src/repovet/vet.py` | Fetches data, runs checks, builds the report |
| `src/repovet/radar.py` | Stack detection and new-repo ranking |
| `src/repovet/render.py` | Terminal output |
| `src/repovet/cli.py` | Argument parsing and exit codes |

## Adding a check

1. Write `check_something(...)` in `checks.py` returning `list[Finding]`. Take already-fetched
   data as arguments; do not call the network.
2. Pick a severity honestly: `high` only for things that are rarely innocent.
3. Wire it into `analyze()` in `vet.py`, and fetch any new data in `collect()`.
4. Add tests in `tests/test_checks.py` with a clean case and a flagged case. Tests run offline.
5. Add a row to the table in the README.

## Reducing false positives

Every flag on a legitimate project is a bug. If `repovet` flags a well-known healthy repo,
open an issue with the repo name and the finding, or send a fix with a test.

## Pull requests

Keep them small, keep tests green, and describe what changed and why.
