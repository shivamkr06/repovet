"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__
from .github import GitHub, GitHubError, NotFound, RateLimited, find_token
from .radar import detect_stack, radar
from .render import render_radar, render_vet
from .vet import vet


def parse_target(target: str) -> tuple[str, str]:
    cleaned = target.strip()
    cleaned = re.sub(r"^(https?://)?(www\.)?github\.com/", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^git@github\.com:", "", cleaned, flags=re.I)
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"expected owner/repo or a GitHub URL, got: {target}")
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError(f"not a valid repo reference: {target}")
    return owner, name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repovet",
        description="Vet a GitHub repo before you trust it, and find new repos for your stack.")
    parser.add_argument("--version", action="version", version=f"repovet {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser):
        p.add_argument("--json", action="store_true", help="machine-readable output")
        p.add_argument("--no-cache", action="store_true",
                       help="ignore the 1-hour response cache")

    p_vet = sub.add_parser("vet", help="score one repo for trust signals")
    p_vet.add_argument("repo", help="owner/repo or GitHub URL")
    p_vet.add_argument("--fail-under", type=int, metavar="N",
                       help="exit with code 2 if the score is below N (for CI)")
    common(p_vet)

    p_radar = sub.add_parser("radar", help="new repos matching your stack")
    p_radar.add_argument("--path", default=".", help="project folder to read the stack from")
    p_radar.add_argument("--lang", action="append", default=[],
                         help="language to follow (repeatable); overrides detection")
    p_radar.add_argument("--topic", action="append", default=[],
                         help="GitHub topic to follow (repeatable)")
    p_radar.add_argument("--days", type=int, default=14, help="how far back to look")
    p_radar.add_argument("--min-stars", type=int, default=100)
    p_radar.add_argument("--top", type=int, default=15, help="how many results to show")
    common(p_radar)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    gh = GitHub(token=find_token(), cache_ttl=0 if args.no_cache else 3600)

    try:
        if args.command == "vet":
            owner, name = parse_target(args.repo)
            report = vet(gh, owner, name)
            print(json.dumps(report, indent=2) if args.json else render_vet(report))
            if args.fail_under is not None and report["score"] < args.fail_under:
                return 2
            return 0

        languages, topics = list(args.lang), list(args.topic)
        if not languages and not topics:
            languages, topics = detect_stack(Path(args.path))
        report = radar(gh, languages, topics, days=args.days,
                       min_stars=args.min_stars, top=args.top)
        print(json.dumps(report, indent=2) if args.json else render_radar(report))
        return 0
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except NotFound:
        print("error: repository not found (private, renamed, or misspelled)", file=sys.stderr)
        return 1
    except RateLimited as err:
        print(f"error: {err}. Set GITHUB_TOKEN to raise the limit.", file=sys.stderr)
        return 1
    except GitHubError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
