"""Radar: new repos that match your stack, clones collapsed, ranked by real traction."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import checks
from .github import GitHub, GitHubError

# dependency name -> GitHub topic worth searching
DEP_TOPICS = {
    "react": "react", "next": "nextjs", "vue": "vue", "svelte": "svelte",
    "express": "express", "tailwindcss": "tailwindcss", "electron": "electron",
    "vite": "vite", "astro": "astro", "three": "threejs", "@anthropic-ai/sdk": "claude",
    "openai": "openai", "langchain": "langchain", "django": "django", "fastapi": "fastapi",
    "flask": "flask", "torch": "pytorch", "pandas": "pandas", "numpy": "numpy",
    "anthropic": "claude", "transformers": "transformers", "playwright": "playwright",
    "tokio": "tokio", "axum": "axum", "tauri": "tauri", "bevy": "bevy",
}


def detect_stack(path: Path) -> tuple[list[str], list[str]]:
    """Guess languages and topics from manifest files in a project folder."""
    languages: list[str] = []
    deps: list[str] = []

    def add_lang(lang: str):
        if lang not in languages:
            languages.append(lang)

    package = path / "package.json"
    if package.is_file():
        try:
            manifest = json.loads(package.read_text(encoding="utf-8", errors="replace"))
            names = list((manifest.get("dependencies") or {})) + list(
                (manifest.get("devDependencies") or {}))
        except (ValueError, OSError, AttributeError):
            names = []
        add_lang("TypeScript" if "typescript" in names or (path / "tsconfig.json").is_file()
                 else "JavaScript")
        deps += names

    for filename in ("requirements.txt", "pyproject.toml"):
        manifest_path = path / filename
        if manifest_path.is_file():
            add_lang("Python")
            try:
                text = manifest_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            deps += re.findall(r"^[\s\"']*([A-Za-z0-9_.-]+)\s*(?:[=<>~!\[\"',]|$)", text, re.M)

    for filename, lang in (("go.mod", "Go"), ("Cargo.toml", "Rust"), ("pom.xml", "Java"),
                           ("build.gradle", "Java"), ("build.gradle.kts", "Kotlin"),
                           ("Gemfile", "Ruby"), ("composer.json", "PHP")):
        manifest_path = path / filename
        if manifest_path.is_file():
            add_lang(lang)
            if filename == "Cargo.toml":
                try:
                    deps += re.findall(r"^([A-Za-z0-9_-]+)\s*=",
                                       manifest_path.read_text(encoding="utf-8",
                                                               errors="replace"), re.M)
                except OSError:
                    pass
    if any(path.glob("*.csproj")) or any(path.glob("*.sln")):
        add_lang("C#")

    topics: list[str] = []
    for dep in deps:
        topic = DEP_TOPICS.get(dep.lower())
        if topic and topic not in topics:
            topics.append(topic)
    return languages, topics


def rank(items: list[dict], now: datetime) -> list[dict]:
    """Collapse same-name clones, then order by age-adjusted traction."""
    groups: dict[str, list[dict]] = {}
    for item in {i["full_name"]: i for i in items}.values():
        groups.setdefault(checks.norm_name(item["name"]), []).append(item)

    rows = []
    for group in groups.values():
        group.sort(key=lambda i: (-i.get("stargazers_count", 0), i["created_at"]))
        best = group[0]
        stars = best.get("stargazers_count", 0)
        forks = best.get("forks_count", 0)
        age = max(checks.days_between(checks.parse_ts(best["created_at"]), now), 1)
        per_day = stars / age
        flags = []
        quality = 1.0
        if stars >= 500 and forks / stars < 0.01:
            flags.append("few forks")
            quality *= 0.4
        if not best.get("description"):
            flags.append("no description")
            quality *= 0.7
        if not best.get("license"):
            flags.append("no license")
            quality *= 0.85
        if len(group) > 1:
            flags.append(f"+{len(group) - 1} same-name clone(s) hidden")
        rows.append({
            "full_name": best["full_name"], "stars": stars, "forks": forks,
            "age_days": round(age), "stars_per_day": round(per_day, 1),
            "language": best.get("language"), "description": best.get("description") or "",
            "flags": flags, "rank_score": round(per_day * quality, 2),
            "url": best.get("html_url"),
        })
    rows.sort(key=lambda r: r["rank_score"], reverse=True)
    return rows


def radar(gh: GitHub, languages: list[str], topics: list[str], days: int = 14,
          min_stars: int = 100, top: int = 15) -> dict:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    base = f"created:>={since} stars:>={min_stars}"
    queries = [f"{base} language:\"{lang}\"" for lang in languages[:3]]
    queries += [f"{base} topic:{topic}" for topic in topics[:3]]
    if not queries:
        queries = [base]

    items: list[dict] = []
    errors: list[str] = []
    for query in queries:
        try:
            result = gh.get("/search/repositories",
                            {"q": query, "sort": "stars", "order": "desc", "per_page": 50})
            items += (result or {}).get("items", [])
        except GitHubError as err:
            errors.append(str(err))
            break
    return {"since": since, "languages": languages[:3], "topics": topics[:3],
            "queries": queries, "results": rank(items, now)[:top], "errors": errors}
