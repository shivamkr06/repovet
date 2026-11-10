"""Terminal output."""

from __future__ import annotations

import os
import sys

COLORS = {"red": "31", "yellow": "33", "green": "32", "cyan": "36", "dim": "2", "bold": "1"}
SEVERITY_COLOR = {"high": "red", "medium": "yellow", "low": "cyan", "info": "dim"}
VERDICT_COLOR = {"LOOKS OK": "green", "CAUTION": "yellow", "HIGH RISK": "red"}


def use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def paint(text: str, color: str, enabled: bool) -> str:
    return f"\033[{COLORS[color]}m{text}\033[0m" if enabled else text


def human(number) -> str:
    if number is None:
        return "?"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 10_000:
        return f"{number / 1000:.0f}k"
    if number >= 1000:
        return f"{number / 1000:.1f}k"
    return str(number)


def render_vet(report: dict) -> str:
    color = use_color()
    lines = []
    verdict = report["verdict"]
    lines.append(paint(report["repo"], "bold", color) + "  " + (report.get("url") or ""))
    if report.get("description"):
        lines.append(paint(report["description"][:110], "dim", color))
    filled = round(report["score"] / 5)
    bar = "#" * filled + "-" * (20 - filled)
    lines.append("")
    lines.append(paint(f"{verdict}  {report['score']}/100  [{bar}]",
                       VERDICT_COLOR[verdict], color))
    lines.append("")

    findings = report["findings"]
    if findings:
        for finding in findings:
            tag = paint(f"[{finding['severity'].upper():<6}]",
                        SEVERITY_COLOR[finding["severity"]], color)
            lines.append(f"{tag} {finding['title']}")
            if finding["detail"]:
                lines.append(f"         {paint(finding['detail'], 'dim', color)}")
    else:
        lines.append(paint("No red flags found.", "green", color))

    facts = report["facts"]
    lines.append("")
    lines.append(paint("Facts", "bold", color))
    rows = [
        ("stars / forks / watchers",
         f"{human(facts['stars'])} / {human(facts['forks'])} / {human(facts['watchers'])}"),
        ("issues + PRs ever", human(facts["issues_and_prs_ever"])),
        ("age / last push", f"{facts['age_days']}d / {facts['days_since_push']}d ago"),
        ("license", facts["license"] or "none"),
        ("language", facts["language"] or "?"),
        ("contributors", facts["contributors"]),
        ("top author", facts["top_author"] or "?"),
        ("latest release", facts["latest_release"] or "none"),
        ("owner", facts["owner"]),
    ]
    for label, value in rows:
        lines.append(f"  {label:<26} {value}")

    if report["alternatives"]:
        lines.append("")
        lines.append(paint("Similar repos (same topics)", "bold", color))
        for alt in report["alternatives"]:
            lines.append(f"  {human(alt['stars']):>6}  {alt['full_name']}  "
                         + paint(alt["description"], "dim", color))

    notes = list(report["errors"])
    if not report["authenticated"]:
        notes.append("No GitHub token: stargazer checks (fake accounts, star spikes) skipped "
                     "and the API allows only ~6 vets/hour. Set GITHUB_TOKEN for full results.")
    if notes:
        lines.append("")
        for note in notes:
            lines.append(paint(f"note: {note}", "yellow", color))
    lines.append("")
    lines.append(paint("Heuristics, not proof. A flag is a reason to look closer.",
                       "dim", color))
    return "\n".join(lines)


def render_radar(report: dict) -> str:
    color = use_color()
    scope = ", ".join(report["languages"] + report["topics"]) or "all languages"
    lines = [paint(f"New repos since {report['since']}  ({scope})", "bold", color), ""]
    if not report["results"]:
        lines.append("Nothing matched. Try --days 30 or --min-stars 20.")
    for index, row in enumerate(report["results"], 1):
        head = (f"{index:>2}. {paint(row['full_name'], 'bold', color)}  "
                f"{human(row['stars'])} stars  {row['age_days']}d old  "
                f"~{row['stars_per_day']:,.0f}/day  {row['language'] or ''}")
        lines.append(head)
        if row["description"]:
            lines.append(f"    {paint(row['description'][:100], 'dim', color)}")
        if row["flags"]:
            lines.append(f"    {paint('! ' + '; '.join(row['flags']), 'yellow', color)}")
    for error in report["errors"]:
        lines.append(paint(f"note: {error}", "yellow", color))
    lines.append("")
    lines.append(paint("Check any of them with: repovet vet owner/name", "dim", color))
    return "\n".join(lines)
