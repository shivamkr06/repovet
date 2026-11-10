# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's "Report a vulnerability" button
on the Security tab of this repository, not in a public issue.

## What repovet does with your data

- It sends requests only to `api.github.com` and `raw.githubusercontent.com`.
- Your GitHub token, if you provide one, is sent only to `api.github.com`.
- It never runs code from the repos it inspects. It downloads a few text files
  (README, `package.json`, `setup.py`, install scripts) and reads them as text.
- Cached responses are stored in `~/.cache/repovet`. They contain public GitHub data only.

## Scope

`repovet` reports heuristics. A clean result is not a guarantee that a repo is safe.
