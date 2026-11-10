"""Fetch everything needed to vet one repo, then run the checks."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from . import checks
from .github import GitHub, GitHubError, RateLimited

STAR_JSON = "application/vnd.github.star+json"
STARGAZER_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    stargazers(last: 100) {
      edges {
        starredAt
        node { createdAt followers { totalCount } repositories(privacy: PUBLIC) { totalCount } }
      }
    }
  }
}
"""


def _star_page_numbers(stars: int, samples: int) -> list[int]:
    pages = min(math.ceil(stars / 100), 400)  # GitHub caps stargazer pagination
    if pages <= 0:
        return []
    if pages <= samples:
        return list(range(1, pages + 1))
    step = (pages - 1) / (samples - 1)
    return sorted({round(1 + i * step) for i in range(samples)})


def collect(gh: GitHub, owner: str, name: str) -> dict:
    """Download all inputs. Only the first call may raise; the rest degrade gracefully."""
    data: dict = {"errors": []}
    repo = gh.get(f"/repos/{owner}/{name}")
    data["repo"] = repo
    full = repo["full_name"]
    limited = False

    def safe(key: str, default, fetch):
        nonlocal limited
        if limited:
            data[key] = default
            return
        try:
            value = fetch()
            data[key] = default if value is None else value
        except RateLimited as err:
            limited = True
            data[key] = default
            data["errors"].append(str(err) + "; later checks skipped")
        except GitHubError as err:
            data[key] = default
            data["errors"].append(f"{key}: {err}")

    safe("owner", None, lambda: gh.get(f"/users/{repo['owner']['login']}"))
    safe("commits", [], lambda: gh.get(f"/repos/{full}/commits", {"per_page": 100}))
    safe("contributors", [], lambda: gh.get(f"/repos/{full}/contributors", {"per_page": 100}))
    safe("releases", [], lambda: gh.get(f"/repos/{full}/releases", {"per_page": 3}))
    safe("last_issue", [], lambda: gh.get(f"/repos/{full}/issues",
                                          {"state": "all", "per_page": 1}))
    safe("tree", {}, lambda: gh.get(f"/repos/{full}/git/trees/{repo['default_branch']}",
                                    {"recursive": 1}))

    def star_pages():
        if not gh.token:  # GitHub refuses anonymous stargazer listing
            return []
        pages = []
        for number in _star_page_numbers(repo.get("stargazers_count", 0), 5):
            page = gh.get(f"/repos/{full}/stargazers",
                          {"per_page": 100, "page": number}, accept=STAR_JSON) or []
            pages.append([s["starred_at"] for s in page if s.get("starred_at")])
        return pages
    safe("star_pages", [], star_pages)

    def profiles():
        if not gh.token:
            return []
        result = gh.graphql(STARGAZER_QUERY, {"owner": owner, "name": name})
        edges = ((result.get("repository") or {}).get("stargazers") or {}).get("edges") or []
        return [{"starred_at": e["starredAt"], "created_at": e["node"]["createdAt"],
                 "followers": e["node"]["followers"]["totalCount"],
                 "public_repos": e["node"]["repositories"]["totalCount"]}
                for e in edges if e.get("node")]
    safe("profiles", [], profiles)

    safe("name_hits", [], lambda: (gh.get("/search/repositories", {
        "q": f"{repo['name']} in:name", "sort": "stars", "per_page": 30}) or {}).get("items", []))

    topics = repo.get("topics") or []
    if topics:
        query = " ".join(f"topic:{t}" for t in topics[:2])
        safe("topic_hits", [], lambda: (gh.get("/search/repositories", {
            "q": query, "sort": "stars", "per_page": 10}) or {}).get("items", []))
    else:
        data["topic_hits"] = []

    tree_paths = [item["path"] for item in (data["tree"].get("tree") or [])
                  if item.get("type") == "blob"]
    data["tree_paths"] = tree_paths
    data["files"] = {}
    for path in checks.pick_files(tree_paths):
        text = gh.raw(full, repo["default_branch"], path)
        if text:
            data["files"][path] = text
    return data


def analyze(data: dict, authenticated: bool, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    repo = data["repo"]
    last_issue = data.get("last_issue") or []
    issue_total = last_issue[0].get("number") if last_issue else (
        0 if "last_issue" in data and not data["errors"] else None)

    findings = (
        checks.check_stars(repo, issue_total, data.get("star_pages", []),
                           data.get("profiles", []), now)
        + checks.check_maintenance(repo, data.get("commits", []), now)
        + checks.check_people(repo, data.get("owner"), data.get("contributors", []),
                              data.get("commits", []), now)
        + checks.check_license(repo)
        + checks.check_install(data.get("tree_paths", []), data.get("files", {}))
        + checks.check_identity(repo, data.get("name_hits", []))
    )
    findings.sort(key=lambda f: checks.SEVERITY_ORDER[f.severity])
    value, verdict = checks.score(findings)

    owner = data.get("owner") or {}
    contributors = data.get("contributors", [])
    releases = data.get("releases", [])
    author, share = checks.top_author_share(data.get("commits", []))
    facts = {
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "watchers": repo.get("subscribers_count"),
        "issues_and_prs_ever": issue_total,
        "age_days": round(checks.days_between(checks.parse_ts(repo["created_at"]), now)),
        "days_since_push": round(checks.days_between(checks.parse_ts(repo["pushed_at"]), now)),
        "license": (repo.get("license") or {}).get("spdx_id"),
        "language": repo.get("language"),
        "contributors": f"{len(contributors)}+" if len(contributors) >= 100 else len(contributors),
        "top_author": f"{author} ({share:.0%} of recent commits)" if author else None,
        "latest_release": releases[0].get("tag_name") if releases else None,
        "owner": f"{repo['owner']['login']} ({owner.get('type', repo['owner'].get('type'))})",
        "stargazer_profiles_sampled": len(data.get("profiles", [])),
    }
    return {
        "repo": repo["full_name"],
        "url": repo.get("html_url"),
        "description": repo.get("description"),
        "score": value,
        "verdict": verdict,
        "findings": [f.as_dict() for f in findings],
        "facts": facts,
        "alternatives": checks.alternatives(repo, data.get("topic_hits", [])),
        "errors": data.get("errors", []),
        "authenticated": authenticated,
    }


def vet(gh: GitHub, owner: str, name: str) -> dict:
    return analyze(collect(gh, owner, name), authenticated=bool(gh.token))
