"""Minimal GitHub API client: stdlib only, on-disk cache, clear rate-limit errors."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
USER_AGENT = "repovet-cli"
MAX_RAW_BYTES = 200_000


class GitHubError(Exception):
    pass


class NotFound(GitHubError):
    pass


class RateLimited(GitHubError):
    def __init__(self, reset_epoch: int | None = None):
        self.reset_epoch = reset_epoch
        wait = ""
        if reset_epoch:
            mins = max(0, int((reset_epoch - time.time()) / 60) + 1)
            wait = f" (resets in ~{mins} min)"
        super().__init__(f"GitHub API rate limit hit{wait}")


def find_token() -> str | None:
    """Token from GITHUB_TOKEN / GH_TOKEN, else from the gh CLI if it is logged in."""
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


class GitHub:
    def __init__(self, token: str | None = None, cache_ttl: int = 3600,
                 cache_dir: Path | None = None):
        self.token = token
        self.cache_ttl = cache_ttl
        self.cache_dir = cache_dir or Path(
            os.environ.get("REPOVET_CACHE") or Path.home() / ".cache" / "repovet"
        )
        self.requests_made = 0

    # -- cache ---------------------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def _cache_get(self, key: str):
        if self.cache_ttl <= 0:
            return None
        path = self._cache_path(key)
        try:
            if time.time() - path.stat().st_mtime > self.cache_ttl:
                return None
            return json.loads(path.read_text(encoding="utf-8"))["body"]
        except (OSError, ValueError, KeyError):
            return None

    def _cache_put(self, key: str, body) -> None:
        if self.cache_ttl <= 0:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(key).write_text(json.dumps({"body": body}), encoding="utf-8")
        except OSError:
            pass

    # -- http ----------------------------------------------------------------
    def _open(self, url: str, headers: dict, data: bytes | None = None) -> bytes:
        headers = {"User-Agent": USER_AGENT, **headers}
        req = urllib.request.Request(url, data=data, headers=headers)
        self.requests_made += 1
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", "replace")[:500]
            if err.code == 404:
                raise NotFound(f"not found: {url}") from None
            if err.code in (403, 429) and (
                err.headers.get("x-ratelimit-remaining") == "0"
                or "rate limit" in body.lower()
            ):
                reset = err.headers.get("x-ratelimit-reset")
                raise RateLimited(int(reset) if reset and reset.isdigit() else None) from None
            raise GitHubError(f"HTTP {err.code} for {url}: {body[:160]}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise GitHubError(f"network error for {url}: {err}") from None

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get(self, path: str, params: dict | None = None,
            accept: str = "application/vnd.github+json"):
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        key = f"{accept}|{url}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        raw = self._open(url, {"Accept": accept, **self._auth()})
        body = json.loads(raw.decode("utf-8")) if raw else None
        if body is not None:
            self._cache_put(key, body)
        return body

    def graphql(self, query: str, variables: dict):
        if not self.token:
            raise GitHubError("GraphQL needs a token")
        key = "graphql|" + query + json.dumps(variables, sort_keys=True)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        payload = json.dumps({"query": query, "variables": variables}).encode()
        raw = self._open(API + "/graphql",
                         {"Content-Type": "application/json", **self._auth()}, payload)
        body = json.loads(raw.decode("utf-8"))
        if body.get("errors"):
            raise GitHubError("GraphQL: " + str(body["errors"][0].get("message")))
        self._cache_put(key, body["data"])
        return body["data"]

    def raw(self, full_name: str, ref: str, path: str) -> str | None:
        """Fetch a file from raw.githubusercontent.com (not counted against the API limit)."""
        url = f"{RAW}/{full_name}/{urllib.parse.quote(ref)}/{urllib.parse.quote(path)}"
        key = "raw|" + url
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        try:
            data = self._open(url, {})
        except GitHubError:
            return None
        text = data[:MAX_RAW_BYTES].decode("utf-8", "replace")
        self._cache_put(key, text)
        return text
