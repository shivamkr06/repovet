# repovet

**Check a GitHub repo for fake stars, abandonment, malware-style install scripts and typosquatting before you clone, install or depend on it. Also finds new repos that match your stack.**

[![CI](https://github.com/shivamkr06/repovet/actions/workflows/ci.yml/badge.svg)](https://github.com/shivamkr06/repovet/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)

Hundreds of new repos trend on GitHub every week. Some are great, some are abandoned, some
have bought their stars, and a few are malware with a nice README. `repovet` is a small
command-line **GitHub repository trust scorer** that tells you which is which in a few
seconds.

- **`repovet vet owner/repo`** gives a 0-100 trust score, a verdict, and the reasons.
- **`repovet radar`** lists recently created repos for the languages and topics your project uses.
- Pure Python standard library. No dependencies. Works on Windows, macOS and Linux.
- Output as text or `--json`. Exit code for CI gating with `--fail-under`.

## Quick start

```bash
pip install git+https://github.com/shivamkr06/repovet.git
```

```bash
repovet vet psf/requests
```

Without installing, from a clone:

```bash
PYTHONPATH=src python -m repovet vet psf/requests
```

## Example

```text
$ repovet vet psf/requests

psf/requests  https://github.com/psf/requests
A simple, yet elegant, HTTP library.

LOOKS OK  100/100  [####################]

No red flags found.

Facts
  stars / forks / watchers   55k / 11k / 1.3k
  issues + PRs ever          7.6k
  age / last push            5749d / 8d ago
  license                    Apache-2.0
  contributors               100+
  top author                 nateprewitt (46% of recent commits)
  latest release             v2.34.2
```

A repo with problems looks like this:

```text
CAUTION  78/100  [################----]

[MEDIUM] Stale
         No push in 514 days.
[LOW   ] Low fork-to-star ratio
         9 forks vs 503 stars (1.8%). Real projects usually sit around 5-15%.
[LOW   ] Single maintainer
         m-ahmed-elbeskeri wrote 100% of the recent commits. If they leave, the project stops.
```

## What `vet` checks

| Area | Signals |
|---|---|
| **Fake stars** | fork-to-star and watcher-to-star ratios, stars with almost no issues or PRs, sudden star spikes, share of brand-new or empty stargazer accounts (needs a token) |
| **Maintenance** | archived or disabled, time since last push, commit count, project age |
| **People** | single-maintainer risk, owner account age and track record |
| **License** | missing, unrecognized, or restrictive (AGPL, SSPL, BUSL, non-commercial) |
| **Install risk** | `preinstall`/`postinstall` hooks, `setup.py` that runs commands, `curl \| sh`, encoded PowerShell, obfuscated `exec`, Discord/Telegram webhooks, hard-coded IPs, committed executables, password-protected archives mentioned in the README |
| **Identity** | same name as a bigger, older repo (typosquat or copy), forks, lookalike repos |

It also lists similar repos with the same topics so you can compare before choosing.

Scoring: start at 100, subtract 25 per high, 12 per medium, 5 per low finding. 80+ with no
high findings is `LOOKS OK`, 55+ is `CAUTION`, below that is `HIGH RISK`.

## Use it in CI

Block a risky dependency before it lands:

```bash
repovet vet owner/repo --fail-under 60
```

Exit code is `2` when the score is below the threshold, `1` on errors, `0` otherwise.
`--json` prints the full report for scripts.

## Radar: new repos for your stack

```bash
repovet radar
```

Reads `package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml` and others
in the current folder, then lists recently created repos in those languages and topics.
Same-name clones are collapsed into one entry, and repos are ranked by stars per day with a
penalty for hollow-looking traction (many stars, almost no forks).

```bash
repovet radar --lang Rust --topic cli --days 30 --min-stars 200
```

## GitHub token

Works without a token, but the anonymous API allows about 6 vets per hour and the
stargazer checks (fake accounts, star spikes) are skipped, because GitHub does not list
stargazers anonymously. To lift both limits, set `GITHUB_TOKEN` (or `GH_TOKEN`) to a token
with no scopes. Some tokens (seen on new GitHub accounts) get no stargazer data back from
GitHub; `repovet` then skips those two checks and says so in a note. If the `gh` CLI is installed and logged in, its token is used automatically.

Responses are cached for one hour in `~/.cache/repovet` (`--no-cache` to bypass,
`REPOVET_CACHE` to move it). The token is only ever sent to `api.github.com`.

## Limits

These are heuristics. A flag is a reason to look closer, not proof of fraud, and a clean
score is not a security audit. The install check reads a handful of entry-point files, not
the whole codebase. Popular, legitimate projects can trip individual checks (a fast viral
launch looks like a star spike). Treat the verdict as triage.

## Development

```bash
python -m unittest discover -s tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add a check. Report security issues as
described in [SECURITY.md](SECURITY.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)

<sub>Keywords: github repository analyzer, fake github stars detector, repo trust score,
supply chain security, typosquatting detection, malicious repository checker, dependency
vetting, trending repositories, open source discovery.</sub>
