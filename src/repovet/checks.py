"""Pure checks: take already-fetched GitHub data, return findings. No network here."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

POINTS = {"high": 25, "medium": 12, "low": 5, "info": 0}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


@dataclass
class Finding:
    severity: str  # high | medium | low | info
    category: str  # stars | maintenance | people | license | install | identity
    title: str
    detail: str = ""

    @property
    def points(self) -> int:
        return POINTS[self.severity]

    def as_dict(self) -> dict:
        return {"severity": self.severity, "category": self.category,
                "title": self.title, "detail": self.detail}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def days_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 86400


# --------------------------------------------------------------------------- stars
def star_burst(star_pages: list[list[str]]) -> float | None:
    """Ratio of the fastest sampled star page to the median one, if it looks like a spike."""
    rates = []
    for page in star_pages:
        if len(page) < 50:
            continue
        stamps = sorted(parse_ts(s) for s in page)
        span = max(days_between(stamps[0], stamps[-1]), 1 / 1440)
        rates.append(len(stamps) / span)
    if len(rates) < 3:
        return None
    ordered = sorted(rates)
    median = ordered[len(ordered) // 2]
    if median <= 0:
        return None
    ratio = ordered[-1] / median
    return ratio if ratio >= 50 else None


def is_ghost(profile: dict) -> bool:
    """Stargazer account that was brand new when it starred, or has no footprint at all."""
    try:
        fresh = days_between(parse_ts(profile["created_at"]),
                             parse_ts(profile["starred_at"])) < 14
    except (KeyError, ValueError, TypeError):
        fresh = False
    empty = profile.get("followers", 1) == 0 and profile.get("public_repos", 1) == 0
    return fresh or empty


def check_stars(repo: dict, issue_total: int | None, star_pages: list[list[str]],
                profiles: list[dict], now: datetime) -> list[Finding]:
    out: list[Finding] = []
    stars = repo.get("stargazers_count", 0)
    forks = repo.get("forks_count", 0)
    watchers = repo.get("subscribers_count")
    age = max(days_between(parse_ts(repo["created_at"]), now), 1)

    if stars >= 500:
        ratio = forks / stars
        detail = (f"{forks:,} forks vs {stars:,} stars ({ratio:.1%}). "
                  "Real projects usually sit around 5-15%.")
        if ratio < 0.01:
            out.append(Finding("medium", "stars", "Almost nobody forks it", detail))
        elif ratio < 0.03:
            out.append(Finding("low", "stars", "Low fork-to-star ratio", detail))

    if stars >= 2000 and watchers is not None and watchers / stars < 0.001:
        out.append(Finding("low", "stars", "Almost nobody watches it",
                           f"{watchers:,} watchers vs {stars:,} stars."))

    if (stars >= 1000 and issue_total is not None and repo.get("has_issues", True)
            and issue_total <= 3):
        out.append(Finding(
            "medium", "stars", "Stars without users",
            f"{stars:,} stars but only {issue_total} issues/PRs ever opened. "
            "Popular code that people really run collects bug reports."))

    if age < 90 and stars / age > 1000:
        out.append(Finding("info", "stars", "Explosive growth",
                           f"~{stars / age:,.0f} stars/day since creation. "
                           "Could be a real viral launch; verify before trusting."))

    burst = star_burst(star_pages)
    if burst:
        out.append(Finding(
            "low", "stars", "Star spike",
            f"One sampled batch of stars arrived ~{burst:,.0f}x faster than the typical "
            "pace. Can be an organic launch spike or a purchased batch."))

    if len(profiles) >= 30:
        share = sum(is_ghost(p) for p in profiles) / len(profiles)
        detail = (f"{share:.0%} of the {len(profiles)} most recent stargazers are "
                  "brand-new or empty accounts (no repos, no followers).")
        if share >= 0.35:
            out.append(Finding("high", "stars", "Stargazers look fake", detail))
        elif share >= 0.18:
            out.append(Finding("medium", "stars", "Many low-quality stargazers", detail))
    return out


# --------------------------------------------------------------------- maintenance
def check_maintenance(repo: dict, commits: list[dict], now: datetime) -> list[Finding]:
    out: list[Finding] = []
    stars = repo.get("stargazers_count", 0)
    if repo.get("disabled"):
        out.append(Finding("high", "maintenance", "Repository is disabled", ""))
    if repo.get("archived"):
        out.append(Finding("high", "maintenance", "Archived (read-only)",
                           "The owner has stopped maintaining it. No fixes will land."))
    else:
        idle = days_between(parse_ts(repo["pushed_at"]), now)
        if idle > 730:
            out.append(Finding("high", "maintenance", "Abandoned",
                               f"No push in {idle / 365:.1f} years."))
        elif idle > 365:
            out.append(Finding("medium", "maintenance", "Stale",
                               f"No push in {idle:.0f} days."))
        elif idle > 180:
            out.append(Finding("low", "maintenance", "Slowing down",
                               f"No push in {idle:.0f} days."))

    age = days_between(parse_ts(repo["created_at"]), now)
    if age < 30:
        out.append(Finding("low", "maintenance", "Very new project",
                           f"Created {age:.0f} days ago. No track record yet."))

    if commits and len(commits) < 5 and stars >= 500:
        out.append(Finding("medium", "maintenance", "Barely any commits",
                           f"Only {len(commits)} commits on the default branch for a "
                           f"repo with {stars:,} stars."))
    return out


# -------------------------------------------------------------------------- people
def top_author_share(commits: list[dict]) -> tuple[str | None, float]:
    counts: dict[str, int] = {}
    for commit in commits:
        author = (commit.get("author") or {}).get("login") or (
            ((commit.get("commit") or {}).get("author") or {}).get("name"))
        if author:
            counts[author] = counts.get(author, 0) + 1
    if not counts:
        return None, 0.0
    name, top = max(counts.items(), key=lambda item: item[1])
    return name, top / sum(counts.values())


def check_people(repo: dict, owner: dict | None, contributors: list[dict],
                 commits: list[dict], now: datetime) -> list[Finding]:
    out: list[Finding] = []
    stars = repo.get("stargazers_count", 0)
    name, share = top_author_share(commits)
    if len(commits) >= 20 and share >= 0.9 and len(contributors) <= 2:
        out.append(Finding("low", "people", "Single maintainer",
                           f"{name} wrote {share:.0%} of the recent commits. "
                           "If they leave, the project stops."))
    if owner and owner.get("type") == "User" and stars >= 1000:
        owner_age = days_between(parse_ts(owner["created_at"]), now)
        if owner_age < 90:
            out.append(Finding("medium", "people", "Owner account is brand new",
                               f"Account created {owner_age:.0f} days ago yet owns a "
                               f"{stars:,}-star repo."))
        elif owner.get("public_repos", 0) <= 2 and owner.get("followers", 0) < 20:
            out.append(Finding("low", "people", "Owner has no track record",
                               f"{owner.get('public_repos', 0)} public repos, "
                               f"{owner.get('followers', 0)} followers."))
    return out


# ------------------------------------------------------------------------- license
RESTRICTIVE = ("AGPL", "GPL", "SSPL", "BUSL", "CC-BY-NC", "Elastic")


def check_license(repo: dict) -> list[Finding]:
    lic = repo.get("license")
    if not lic:
        return [Finding("medium", "license", "No license",
                        "Without a license you have no legal right to reuse or modify "
                        "the code, even though it is public.")]
    spdx = lic.get("spdx_id") or ""
    if spdx in ("", "NOASSERTION"):
        return [Finding("low", "license", "Custom or unrecognized license",
                        "GitHub could not classify the license. Read it before using.")]
    if any(spdx.startswith(prefix) or prefix in spdx for prefix in RESTRICTIVE):
        return [Finding("info", "license", f"Restrictive license ({spdx})",
                        "Copyleft or source-available terms. Check they fit your use.")]
    return []


# ------------------------------------------------------------------------- install
EXEC_EXT = (".exe", ".scr", ".msi", ".lnk")
LIB_EXT = (".dll", ".so", ".dylib", ".jar", ".bin", ".pyc")
INSTALL_NAMES = ("install.sh", "setup.sh", "install.ps1", "setup.ps1", "install.bat",
                 "bootstrap.sh")

SCRIPT_PATTERNS = [
    ("high", r"(eval|exec)\s*\(.{0,80}(b64decode|atob|fromCharCode|decompress)",
     "Runs obfuscated/decoded code"),
    ("high", r"powershell[^\n]{0,60}\s-e(nc|ncodedcommand)?\s+[A-Za-z0-9+/=]{20,}",
     "Runs an encoded PowerShell command"),
    ("high", r"(IEX|Invoke-Expression)[^\n]{0,80}(DownloadString|Invoke-WebRequest|iwr|irm)",
     "Downloads and executes remote PowerShell"),
    ("high", r"discord(app)?\.com/api/webhooks/|api\.telegram\.org/bot",
     "Sends data to a Discord/Telegram webhook"),
    ("medium", r"(curl|wget)[^\n|]{0,200}\|\s*(sudo\s+)?(ba|z)?sh\b",
     "Pipes a remote script straight into a shell"),
    ("medium", r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}[:/]",
     "Talks to a hard-coded IP address"),
    ("medium", r"base64\s+(-d|--decode)[^\n]{0,40}\|\s*(ba|z)?sh",
     "Decodes base64 and runs it"),
]
README_PATTERNS = [
    ("medium", r"(\.zip|\.rar|\.7z|archive)[^\n]{0,200}pass(word)?\s*[:=`* ]+\S+"
               r"|pass(word)?\s*[:=`* ]+\S+[^\n]{0,200}(\.zip|\.rar|\.7z)",
     "README tells you to open a password-protected archive",
     "Classic malware delivery: the password hides the payload from scanners."),
    ("low", r"(curl|wget)[^\n|]{0,200}\|\s*(sudo\s+)?(ba|z)?sh\b",
     "README install pipes a remote script into a shell",
     "Common, but read the script before running it."),
]
SETUP_PY_RISK = re.compile(r"\b(os\.system|subprocess\.|urllib\.request|requests\.(get|post)"
                           r"|socket\.)")
HOOK_RISK = re.compile(r"curl|wget|node\s+-e|powershell|base64|https?://", re.I)


def pick_files(tree_paths: list[str]) -> list[str]:
    """Which files are worth downloading for the install-risk check."""
    wanted: list[str] = []
    for path in tree_paths:
        lower = path.lower()
        base = lower.rsplit("/", 1)[-1]
        depth = lower.count("/")
        if depth == 0 and (base.startswith("readme") or base in ("package.json", "setup.py")):
            wanted.append(path)
        elif depth <= 1 and base in INSTALL_NAMES:
            wanted.append(path)
    return wanted[:8]


def check_install(tree_paths: list[str], files: dict[str, str]) -> list[Finding]:
    out: list[Finding] = []

    executables = [p for p in tree_paths if p.lower().endswith(EXEC_EXT)]
    libraries = [p for p in tree_paths if p.lower().endswith(LIB_EXT)]
    if executables:
        out.append(Finding("medium", "install", "Executables committed to the repo",
                           f"{len(executables)} file(s), e.g. {executables[0]}. "
                           "You cannot review what a binary does."))
    elif libraries:
        out.append(Finding("low", "install", "Prebuilt binaries committed",
                           f"{len(libraries)} file(s), e.g. {libraries[0]}."))

    for path, text in files.items():
        base = path.lower().rsplit("/", 1)[-1]
        if base.startswith("readme"):
            for severity, pattern, title, detail in README_PATTERNS:
                if re.search(pattern, text, re.I):
                    out.append(Finding(severity, "install", title, detail))
            continue

        if base == "package.json":
            try:
                scripts = (json.loads(text).get("scripts") or {})
            except (ValueError, AttributeError):
                scripts = {}
            for hook in ("preinstall", "install", "postinstall"):
                command = scripts.get(hook)
                if isinstance(command, str) and command.strip():
                    risky = HOOK_RISK.search(command)
                    out.append(Finding(
                        "medium" if risky else "low", "install",
                        f"npm {hook} hook runs on install",
                        f"`{command[:140]}`"))
        if base == "setup.py" and SETUP_PY_RISK.search(text):
            out.append(Finding("medium", "install",
                               "setup.py runs commands or network calls",
                               "Code executes on `pip install`, before you ever import it."))
        for severity, pattern, title in SCRIPT_PATTERNS:
            if re.search(pattern, text, re.I):
                out.append(Finding(severity, "install", title, f"in {path}"))
    return out


# ------------------------------------------------------------------------ identity
def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def jaccard(a: str | None, b: str | None) -> float:
    words_a = set(re.findall(r"[a-z0-9]{3,}", (a or "").lower()))
    words_b = set(re.findall(r"[a-z0-9]{3,}", (b or "").lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def check_identity(repo: dict, name_hits: list[dict]) -> list[Finding]:
    out: list[Finding] = []
    if repo.get("fork") and repo.get("parent"):
        out.append(Finding("info", "identity",
                           f"Fork of {repo['parent'].get('full_name')}",
                           "Check whether you want the original instead."))
    name = norm_name(repo["name"])
    if len(name) < 4:
        return out
    me = repo["full_name"].lower()
    stars = repo.get("stargazers_count", 0)
    created = parse_ts(repo["created_at"])
    same = [h for h in name_hits
            if h["full_name"].lower() != me and norm_name(h["name"]) == name]

    originals = [h for h in same
                 if h.get("stargazers_count", 0) > max(2 * stars, 50)
                 and parse_ts(h["created_at"]) < created]
    if originals:
        top = max(originals, key=lambda h: h.get("stargazers_count", 0))
        similar = jaccard(repo.get("description"), top.get("description")) >= 0.4
        out.append(Finding(
            "medium" if similar else "low", "identity",
            "Same name as a bigger, older repo",
            f"{top['full_name']} ({top.get('stargazers_count', 0):,} stars) predates "
            "this one" + (" and has a near-identical description." if similar else ".")
            + " Make sure this is the project you meant."))
    else:
        copies = [h for h in same if parse_ts(h["created_at"]) > created
                  and jaccard(repo.get("description"), h.get("description")) >= 0.4]
        if copies:
            out.append(Finding("info", "identity", f"{len(copies)} lookalike repo(s) exist",
                               "Others copy this name and description, e.g. "
                               f"{copies[0]['full_name']}. This one is the older repo."))
    return out


def alternatives(repo: dict, topic_hits: list[dict], limit: int = 5) -> list[dict]:
    me = repo["full_name"].lower()
    # Tiny repos that merely share a topic are noise, not alternatives.
    floor = max(50, repo.get("stargazers_count", 0) // 100)
    picked = [h for h in topic_hits if h["full_name"].lower() != me and not h.get("archived")
              and h.get("stargazers_count", 0) >= floor]
    picked.sort(key=lambda h: h.get("stargazers_count", 0), reverse=True)
    return [{"full_name": h["full_name"], "stars": h.get("stargazers_count", 0),
             "description": (h.get("description") or "")[:90]} for h in picked[:limit]]


# ------------------------------------------------------------------------- scoring
def score(findings: list[Finding]) -> tuple[int, str]:
    value = max(0, 100 - sum(f.points for f in findings))
    has_high = any(f.severity == "high" for f in findings)
    if value >= 80 and not has_high:
        return value, "LOOKS OK"
    if value >= 55:
        return value, "CAUTION"
    return value, "HIGH RISK"
