"""Tests for the held-out workflow repository fetcher; no network is used."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fetch_workflow_repos", ROOT / "tools" / "fetch_workflow_repos.py"
)
assert SPEC and SPEC.loader
fetcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetcher)


def test_manifest_is_the_eight_named_full_pins() -> None:
    repos = fetcher.load_manifest()
    assert len(repos) == 8
    assert len({repo["name"] for repo in repos}) == 8
    assert all(len(repo["sha"]) == 40 for repo in repos)


def test_manifest_repository_name_cannot_escape_destination(monkeypatch, tmp_path: Path) -> None:
    manifest = json.loads((ROOT / "evals/workflow/repositories.json").read_text())
    manifest["repos"][0]["name"] = "../outside"
    path = tmp_path / "repositories.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(fetcher, "MANIFEST_PATH", path)
    with pytest.raises(fetcher.FetchError, match="invalid or duplicate repository name"):
        fetcher.load_manifest()


def test_corpus_dir_honors_environment_and_defaults_absolute(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MLVIEW_PUBLIC_CORPUS_DIR", raising=False)
    assert fetcher.corpus_dir() == ROOT / ".public-corpus"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MLVIEW_PUBLIC_CORPUS_DIR", "elsewhere")
    assert fetcher.corpus_dir() == (tmp_path / "elsewhere").resolve()


def test_unknown_selection_fails_before_any_fetch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fetcher, "fetch_one", lambda *_: pytest.fail("must not fetch"))
    with pytest.raises(fetcher.FetchError, match="unknown --repo"):
        fetcher.fetch(fetcher.load_manifest(), tmp_path, ["not-a-repository"])


def test_existing_dirty_checkout_is_never_changed(monkeypatch, tmp_path: Path) -> None:
    repo = fetcher.load_manifest()[0]
    destination = tmp_path / repo["name"]
    (destination / ".git").mkdir(parents=True)
    calls: list[tuple[str, ...]] = []

    def fake_git(args, cwd):
        calls.append(tuple(args))
        return " M local.py\n"

    monkeypatch.setattr(fetcher, "_git", fake_git)
    with pytest.raises(fetcher.FetchError, match="local changes"):
        fetcher.fetch_one(repo, tmp_path)
    assert calls == [("status", "--porcelain", "--untracked-files=normal")]


def test_new_checkout_uses_argument_vectors_and_verifies_pin(monkeypatch, tmp_path: Path) -> None:
    repo = next(item for item in fetcher.load_manifest() if item["sparse"])
    calls: list[tuple[str, ...]] = []

    def fake_git(args, cwd):
        calls.append(tuple(args))
        if args[:2] == ["rev-parse", "HEAD"]:
            return repo["sha"] + "\n"
        return ""

    monkeypatch.setattr(fetcher, "_git", fake_git)
    destination = fetcher.fetch_one(repo, tmp_path)
    assert destination.is_dir()
    assert calls[0] == ("init", "--quiet")
    assert ("remote", "add", "origin", repo["url"]) in calls
    assert ("sparse-checkout", "set", "--no-cone", "--", *repo["sparse"]) in calls
    assert ("fetch", "--depth", "1", "--filter=blob:none", "origin", repo["sha"]) in calls
    assert ("checkout", "--quiet", "--detach", "FETCH_HEAD") in calls
    assert calls[-2:] == [
        ("rev-parse", "HEAD"),
        ("status", "--porcelain", "--untracked-files=normal"),
    ]


def test_repo_option_is_repeatable() -> None:
    args = fetcher.build_parser().parse_args(["--repo", "flax", "--repo", "cleanrl"])
    assert args.repo == ["flax", "cleanrl"]
