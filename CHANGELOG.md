# Changelog

## 0.1.0

First release.

- `vet`: trust score with checks for fake stars, maintenance, people, license, install risk
  and identity (typosquats, lookalikes). Text and `--json` output, `--fail-under` for CI.
- `radar`: recently created repos for your detected stack, clones collapsed, ranked by
  stars per day with a penalty for hollow traction.
- One-hour on-disk cache, token from `GITHUB_TOKEN`, `GH_TOKEN` or the `gh` CLI.
