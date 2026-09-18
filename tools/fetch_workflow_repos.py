#!/usr/bin/env python3
"""Fetch the eight pinned repositories used by held-out workflow evaluation."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "evals" / "workflow" / "repositories.json"
DEFAULT_CORPUS_DIR = REPO_ROOT / ".public-corpus"


class FetchError(Exception):
    """A manifest or checkout cannot be used safely."""


def corpus_dir() -> Path:
    configured = os.environ.get("MLVIEW_PUBLIC_CORPUS_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_CORPUS_DIR


def load_manifest() -> list[dict[str, Any]]:
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"cannot read workflow repository manifest: {exc}") from exc
    repos = payload.get("repos") if isinstance(payload, dict) else None
    if not isinstance(repos, list) or len(repos) != 8:
        raise FetchError("workflow repository manifest must contain exactly eight repos")
    seen: set[str] = set()
    for repo in repos:
        if not isinstance(repo, dict):
            raise FetchError("every workflow repository entry must be an object")
        name, url, sha = repo.get("name"), repo.get("url"), repo.get("sha")
        if (not isinstance(name, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is None
                or name in seen):
            raise FetchError(f"invalid or duplicate repository name: {name!r}")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise FetchError(f"{name}: url must be HTTPS")
        if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            raise FetchError(f"{name}: sha must be a full lowercase 40-hex commit")
        sparse = repo.get("sparse", [])
        if not isinstance(sparse, list) or not all(isinstance(item, str) and item for item in sparse):
            raise FetchError(f"{name}: sparse must be a list of non-empty paths")
        seen.add(name)
    return repos


def _git(args: Sequence[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise FetchError(f"git {args[0]} failed in {cwd}: {detail}")
    return result.stdout


def _verify_existing(repo: dict[str, Any], destination: Path) -> None:
    if not (destination / ".git").is_dir():
        raise FetchError(f"{destination} exists but is not a Git checkout")
    dirty = _git(["status", "--porcelain", "--untracked-files=normal"], destination)
    if dirty.strip():
        raise FetchError(f"{destination} has local changes; refusing to modify it")
    head = _git(["rev-parse", "HEAD"], destination).strip()
    if head != repo["sha"]:
        raise FetchError(
            f"{destination} is at {head or 'an unknown commit'}, expected {repo['sha']}; "
            "refusing to change the checkout"
        )


def fetch_one(repo: dict[str, Any], destination_root: Path) -> Path:
    destination = destination_root / repo["name"]
    if destination.exists():
        _verify_existing(repo, destination)
        print(f"have {repo['name']} @ {repo['sha'][:12]}")
        return destination

    destination_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{repo['name']}-", dir=destination_root))
    try:
        _git(["init", "--quiet"], staging)
        _git(["remote", "add", "origin", repo["url"]], staging)
        sparse = repo.get("sparse", [])
        if sparse:
            _git(["sparse-checkout", "init", "--no-cone"], staging)
            _git(["sparse-checkout", "set", "--no-cone", "--", *sparse], staging)
        _git(["fetch", "--depth", "1", "--filter=blob:none", "origin", repo["sha"]], staging)
        _git(["checkout", "--quiet", "--detach", "FETCH_HEAD"], staging)
        head = _git(["rev-parse", "HEAD"], staging).strip()
        if head != repo["sha"]:
            raise FetchError(f"{repo['name']}: fetched {head}, expected {repo['sha']}")
        if _git(["status", "--porcelain", "--untracked-files=normal"], staging).strip():
            raise FetchError(f"{repo['name']}: new checkout unexpectedly has local changes")
        staging.replace(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"fetched {repo['name']} @ {repo['sha'][:12]}")
    return destination


def fetch(repos: Sequence[dict[str, Any]], destination_root: Path, selected: Sequence[str]) -> list[Path]:
    by_name = {repo["name"]: repo for repo in repos}
    unknown = sorted(set(selected) - by_name.keys())
    if unknown:
        raise FetchError(
            "unknown --repo value(s): %s; choose from %s"
            % (", ".join(unknown), ", ".join(sorted(by_name)))
        )
    chosen = [repo for repo in repos if not selected or repo["name"] in selected]
    return [fetch_one(repo, destination_root) for repo in chosen]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="NAME",
        help="fetch only this repository; repeat to select more than one",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fetched = fetch(load_manifest(), corpus_dir(), args.repo)
    except FetchError as exc:
        print(f"fetch-workflow-repos: {exc}", file=os.sys.stderr)
        return 1
    print(f"fetch-workflow-repos: OK ({len(fetched)} repositories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
