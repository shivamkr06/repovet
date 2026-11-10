# Launch drafts

Post these yourself. Change the wording to sound like you.

## Show HN

**Title:** Show HN: repovet – check a GitHub repo for fake stars and risky install scripts

I kept finding trending repos with thousands of stars and no real users. repovet is a
small Python CLI (standard library only) that scores a repo 0-100 before you clone or
depend on it: fork/star ratios, star spikes, brand-new stargazer accounts, stale or
single-maintainer projects, license problems, install hooks that run commands, and
same-name lookalikes. `repovet radar` also lists new repos matching your stack.

    pip install git+https://github.com/shivamkr06/repovet.git
    repovet vet psf/requests

Heuristics, not proof. False positives are bugs, so please file them:
https://github.com/shivamkr06/repovet

## Reddit (r/Python, r/opensource, r/netsec)

**Title:** I built a CLI that scores GitHub repos for fake stars, abandonment and sketchy install scripts

Same body as above, shorter. Lead with one real example output.

## X / Bluesky

Built repovet: `repovet vet owner/repo` gives a trust score for any GitHub repo (fake-star
signals, abandonment, malware-style install scripts, typosquats). Zero dependencies, MIT.
https://github.com/shivamkr06/repovet

## Other places

- dev.to / Hashnode post: "How I detect fake GitHub stars" with the check table.
- Add it to awesome lists for supply-chain security and Python CLI tools (open a PR).
- After PyPI: update the install line in the README to `pip install repovet`.
