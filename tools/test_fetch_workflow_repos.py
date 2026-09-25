"""Tests for the held-out workflow repository fetcher; no network is used.

Fake-git tests pin the argument vectors. Real-git tests fetch from a local file:// repository
(the manifest's HTTPS rule is monkeypatched) with an isolated Git configuration.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fetch_workflow_repos", ROOT / "tools" / "fetch_workflow_repos.py"
)
assert SPEC and SPEC.loader
fetcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetcher)

HAS_GIT = shutil.which("git") is not None
needs_git = pytest.mark.skipif(not HAS_GIT, reason="git is not installed")


def is_read(args: tuple[str, ...]) -> bool:
    return (args[0] in {"rev-parse", "status", "ls-tree"} or args[:3] == ("config", "--bool", "--default")
            or args == ("sparse-checkout", "list"))


def test_manifest_is_the_eight_named_full_pins() -> None:
    repos = fetcher.load_manifest()
    assert len(repos) == 8
    assert len({repo["name"] for repo in repos}) == 8
    assert all(len(repo["sha"]) == 40 for repo in repos)


def test_mmdetection_lists_the_five_exact_root_anchored_config_files() -> None:
    mmdetection = next(repo for repo in fetcher.load_manifest() if repo["name"] == "mmdetection")
    assert mmdetection["sparse"] == [
        "tools", "mmdet/apis", "mmdet/engine", "mmdet/models/detectors", "configs/common",
        "/configs/_base_/datasets/coco_detection.py",
        "/configs/_base_/default_runtime.py",
        "/configs/_base_/models/faster-rcnn_r50_fpn.py",
        "/configs/_base_/schedules/schedule_1x.py",
        "/configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py",
    ]


def write_manifest(monkeypatch, tmp_path: Path, mutate) -> None:
    manifest = json.loads((ROOT / "evals/workflow/repositories.json").read_text(encoding="utf-8"))
    mutate(manifest)
    path = tmp_path / "repositories.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(fetcher, "MANIFEST_PATH", path)


def test_manifest_repository_name_cannot_escape_destination(monkeypatch, tmp_path: Path) -> None:
    write_manifest(monkeypatch, tmp_path, lambda m: m["repos"][0].update(name="../outside"))
    with pytest.raises(fetcher.FetchError, match="invalid or duplicate repository name"):
        fetcher.load_manifest()


@pytest.mark.parametrize("pattern", ["!tools", "configs/", "**/x.py", "a?b", "[ab]", "a\\b", "./tools", "#tools"])
def test_manifest_rejects_sparse_syntax_the_coverage_matcher_does_not_implement(monkeypatch, tmp_path: Path,
                                                                                pattern: str) -> None:
    write_manifest(monkeypatch, tmp_path, lambda m: m["repos"][6]["sparse"].append(pattern))
    with pytest.raises(fetcher.FetchError, match="mmdetection: unsupported sparse pattern"):
        fetcher.load_manifest()


def test_manifest_requires_https(monkeypatch, tmp_path: Path) -> None:
    write_manifest(monkeypatch, tmp_path, lambda m: m["repos"][0].update(url="http://example.invalid/x"))
    with pytest.raises(fetcher.FetchError, match="url must be HTTPS"):
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


def test_mode_options() -> None:
    args = fetcher.build_parser().parse_args(["--repo", "flax", "--repo", "cleanrl"])
    assert args.repo == ["flax", "cleanrl"] and not args.verify and not args.update_sparse
    assert fetcher.build_parser().parse_args(["--verify", "--json"]).json
    with pytest.raises(SystemExit):
        fetcher.build_parser().parse_args(["--verify", "--update-sparse"])
    with pytest.raises(SystemExit):
        fetcher.main(["--json"])


# --------------------------------------------------------------------------------------------
# Fake git: argument vectors


class FakeGit:
    """Answers the verification reads for a clean, pinned checkout with ``patterns``."""

    def __init__(self, repo: dict, status: str = "", sparse: list[str] | None = None, tree: str = "") -> None:
        self.repo, self.status, self.tree = repo, status, tree
        self.sparse = repo["sparse"] if sparse is None else sparse
        self.calls: list[tuple[tuple[str, ...], bool]] = []

    def __call__(self, args, cwd, *, offline=False):
        args = tuple(args)
        self.calls.append((args, offline))
        if args[0] == "init":
            (Path(cwd) / ".git").mkdir()
        if args[:2] == ("rev-parse", "--verify"):
            return self.repo["sha"] + "\n"
        if args[0] == "status":
            return self.status
        if args[0] == "config" and args[-1] == "core.sparseCheckout":
            return "true\n" if self.sparse else "false\n"
        if args[0] == "config" and args[-1] == "core.sparseCheckoutCone":
            return "false\n"
        if args == ("sparse-checkout", "list"):
            return "".join(f"{pattern}\n" for pattern in self.sparse)
        if args[0] == "ls-tree":
            return self.tree
        return ""


def test_existing_dirty_checkout_is_refused_and_never_changed(monkeypatch, tmp_path: Path) -> None:
    repo = fetcher.load_manifest()[0]
    (tmp_path / repo["name"] / ".git").mkdir(parents=True)
    fake = FakeGit(repo, status=" M local.py\0")
    monkeypatch.setattr(fetcher, "_git", fake)
    with pytest.raises(fetcher.FetchError, match="local changes"):
        fetcher.fetch_one(repo, tmp_path)
    assert fake.calls and all(offline and is_read(args) for args, offline in fake.calls)


def test_verification_reads_are_offline_and_never_mutate(monkeypatch, tmp_path: Path) -> None:
    repo = next(item for item in fetcher.load_manifest() if item["name"] == "mmdetection")
    (tmp_path / repo["name"] / ".git").mkdir(parents=True)
    fake = FakeGit(repo)
    monkeypatch.setattr(fetcher, "_git", fake)
    report = fetcher.verify_repo(repo, tmp_path)
    assert report["ok"], report["problems"]
    commands = [args for args, _ in fake.calls]
    assert all(offline and is_read(args) for args, offline in fake.calls)
    assert ("status", "--porcelain=v1", "-z", "--untracked-files=normal") in commands
    assert ("ls-tree", "-r", "-z", "--full-tree", repo["sha"] + "^{commit}") in commands
    assert not any(args[0] in {"checkout", "reset", "clean", "fetch", "cat-file"} for args in commands)
    assert not any(args[:2] in {("sparse-checkout", "set"), ("sparse-checkout", "reapply")} for args in commands)


def test_new_checkout_uses_argument_vectors_disables_autocrlf_and_verifies_pin(monkeypatch, tmp_path: Path) -> None:
    repo = next(item for item in fetcher.load_manifest() if item["sparse"])
    fake = FakeGit(repo)
    monkeypatch.setattr(fetcher, "_git", fake)
    destination = fetcher.fetch_one(repo, tmp_path)
    assert destination == tmp_path / repo["name"] and destination.is_dir()
    calls = [args for args, _ in fake.calls]
    assert calls[0] == ("init", "--quiet")
    autocrlf = calls.index(("config", "core.autocrlf", "false"))
    checkout = calls.index(("checkout", "--quiet", "--detach", "FETCH_HEAD"))
    assert autocrlf < checkout
    assert ("remote", "add", "origin", repo["url"]) in calls
    init = calls.index(("sparse-checkout", "init", "--no-cone"))
    # No "set --no-cone": Git before 2.35 would store the flag as a pattern (DISTCI-F2).
    assert calls.index(("sparse-checkout", "set", "--", *repo["sparse"])) == init + 1
    assert not any(args[:2] == ("sparse-checkout", "set") and "--no-cone" in args for args in calls)
    assert calls.index(("fetch", "--depth", "1", "--filter=blob:none", "origin", repo["sha"])) < checkout
    after = fake.calls[checkout + 1:]
    assert after and all(offline and is_read(args) for args, offline in after)
    assert not [path for path in tmp_path.iterdir() if path.name.startswith(".")]


def test_new_checkout_at_the_wrong_commit_is_removed(monkeypatch, tmp_path: Path) -> None:
    repo = fetcher.load_manifest()[0]
    fake = FakeGit(dict(repo, sha="f" * 40))
    monkeypatch.setattr(fetcher, "_git", fake)
    with pytest.raises(fetcher.FetchError, match="fetched f{40}, expected"):
        fetcher.fetch_one(repo, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_sparse_difference_names_missing_and_extra_patterns(monkeypatch, tmp_path: Path) -> None:
    repo = next(item for item in fetcher.load_manifest() if item["name"] == "mmdetection")
    (tmp_path / repo["name"] / ".git").mkdir(parents=True)
    monkeypatch.setattr(fetcher, "_git", FakeGit(repo, sparse=repo["sparse"][:5] + ["docs"]))
    report = fetcher.verify_repo(repo, tmp_path)
    assert not report["ok"] and not report["sparseMatches"]
    assert report["problems"] == [
        "mmdetection: sparse patterns differ from the manifest (missing: /configs/_base_/datasets/coco_detection.py, "
        "/configs/_base_/default_runtime.py, /configs/_base_/models/faster-rcnn_r50_fpn.py, "
        "/configs/_base_/schedules/schedule_1x.py, /configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py; extra: docs); "
        "re-run with --update-sparse"
    ]


def test_a_failing_git_read_is_reported_not_raised(monkeypatch, tmp_path: Path) -> None:
    repo = fetcher.load_manifest()[0]
    (tmp_path / repo["name"] / ".git").mkdir(parents=True)

    def broken(args, cwd, *, offline=False):
        raise fetcher.FetchError("git rev-parse failed in the checkout: fatal: not a git repository")

    monkeypatch.setattr(fetcher, "_git", broken)
    report = fetcher.verify_repo(repo, tmp_path)
    assert report["ok"] is False and report["head"] is None
    assert report["problems"] == [f"{repo['name']}: cannot inspect the checkout (git rev-parse failed in the "
                                  "checkout: fatal: not a git repository)"]


def test_missing_checkout_and_non_checkout_are_reported(tmp_path: Path) -> None:
    repo = fetcher.load_manifest()[0]
    report = fetcher.verify_repo(repo, tmp_path)
    assert not report["ok"] and "not fetched" in report["problems"][0]
    assert f"--repo {repo['name']}" in report["problems"][0]
    (tmp_path / repo["name"]).mkdir()
    report = fetcher.verify_repo(repo, tmp_path)
    assert not report["ok"] and "is not a Git checkout" in report["problems"][0]


# --------------------------------------------------------------------------------------------
# Real git against a local file:// repository


@pytest.fixture
def git_home(monkeypatch, tmp_path: Path) -> Path:
    """Isolate Git from the user's configuration; the fetcher inherits this environment."""
    config = tmp_path / "gitconfig"
    config.write_text("", encoding="utf-8")
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Synthetic Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "synthetic@example.invalid")
        monkeypatch.setenv(f"GIT_{role}_DATE", "2026-01-01T00:00:00Z")
    monkeypatch.setattr(fetcher, "URL_PREFIXES", ("https://", "file://"))
    return config


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout.decode("utf-8")


UPSTREAM_FILES = {
    "README.md": b"synthetic upstream\n",
    "tools/train.py": b"print('train')\n",
    "configs/common/a.py": b"a = 1\n",
    "configs/_base_/default_runtime.py": b"runtime = 'default'\n",
    "configs/_base_/other.py": b"other = 2\n",
    "configs/faster_rcnn/x.py": b"_base_ = ['../_base_/default_runtime.py']\n",
    "docs/tools/notes.md": b"unanchored patterns match any component\n",
}


def make_upstream(tmp_path: Path) -> tuple[str, str]:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "--quiet")
    for rel, data in UPSTREAM_FILES.items():
        (upstream / rel).parent.mkdir(parents=True, exist_ok=True)
        (upstream / rel).write_bytes(data)
    git(upstream, "add", "-A")
    git(upstream, "commit", "--quiet", "-m", "synthetic")
    git(upstream, "config", "uploadpack.allowFilter", "true")
    git(upstream, "config", "uploadpack.allowAnySHA1InWant", "true")
    return upstream.as_uri(), git(upstream, "rev-parse", "HEAD").strip()


def materialised(checkout: Path) -> set[str]:
    return {path.relative_to(checkout).as_posix() for path in checkout.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(checkout).parts}


@pytest.fixture
def local_repo(git_home, tmp_path: Path) -> dict:
    url, sha = make_upstream(tmp_path)
    return {"name": "synthetic", "url": url, "sha": sha, "sparse": ["tools", "configs/common"]}


@needs_git
def test_real_fetch_from_file_url_is_sparse_blob_exact_and_verified(local_repo, tmp_path: Path, capsys) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    assert materialised(checkout) == {"tools/train.py", "configs/common/a.py", "docs/tools/notes.md"}
    assert git(checkout, "config", "core.autocrlf").strip() == "false"
    report = fetcher.verify_repo(local_repo, corpus)
    assert report == {
        "name": "synthetic", "head": local_repo["sha"], "clean": True, "legacyMarker": False, "sparseMatches": True,
        "covered": 3, "missing": [], "extraMaterialized": [], "blobMismatches": [], "treeChecked": True,
        "unclassified": [], "ok": True, "problems": [],
    }
    fetcher.fetch_one(local_repo, corpus)
    assert capsys.readouterr().out.splitlines()[-1] == f"have synthetic @ {local_repo['sha'][:12]}"


@needs_git
def test_fetch_disables_autocrlf_so_bytes_equal_blobs_despite_global_config(local_repo, git_home,
                                                                            tmp_path: Path) -> None:
    git_home.write_text("[core]\n\tautocrlf = true\n", encoding="utf-8")
    checkout = fetcher.fetch_one(local_repo, tmp_path / "corpus")
    assert (checkout / "tools/train.py").read_bytes() == UPSTREAM_FILES["tools/train.py"]
    assert fetcher.verify_repo(local_repo, tmp_path / "corpus")["ok"]


@needs_git
def test_full_checkout_manifest_means_sparse_disabled(local_repo, tmp_path: Path) -> None:
    repo = dict(local_repo, sparse=[])
    checkout = fetcher.fetch_one(repo, tmp_path / "corpus")
    assert materialised(checkout) == set(UPSTREAM_FILES)
    report = fetcher.verify_repo(repo, tmp_path / "corpus")
    assert report["ok"] and report["covered"] == len(UPSTREAM_FILES)
    assert not fetcher.verify_repo(dict(repo, sparse=["tools"]), tmp_path / "corpus")["sparseMatches"]


@needs_git
def test_legacy_marker_is_tolerated_only_when_it_holds_the_pin(local_repo, tmp_path: Path, capsys) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    marker = checkout / ".mlview-pinned-sha"
    for content in (local_repo["sha"], local_repo["sha"] + "\n"):
        marker.write_bytes(content.encode("ascii"))
        report = fetcher.verify_repo(local_repo, corpus)
        assert report["ok"] and report["clean"] and report["legacyMarker"]
    fetcher.fetch_one(local_repo, corpus)
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"have synthetic @ {local_repo['sha'][:12]} (ignored the legacy analyzer marker .mlview-pinned-sha)")
    for content in (b"0" * 40 + b"\n", local_repo["sha"].encode("ascii") + b"\n\n", b"marker"):
        marker.write_bytes(content)
        report = fetcher.verify_repo(local_repo, corpus)
        assert not report["ok"] and not report["clean"] and not report["legacyMarker"]
        assert "does not hold the pinned commit" in report["problems"][0]
    assert marker.read_bytes() == b"marker"  # never deleted


@needs_git
def test_untracked_or_modified_files_are_refused_and_never_changed(local_repo, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    (checkout / "scratch.txt").write_text("local", encoding="utf-8")
    with pytest.raises(fetcher.FetchError, match=r"local changes \(\?\? scratch.txt\); refusing to modify it"):
        fetcher.fetch_one(local_repo, corpus)
    with pytest.raises(fetcher.FetchError, match="local changes"):
        fetcher.update_sparse_one(dict(local_repo, sparse=["tools"]), corpus)
    assert (checkout / "scratch.txt").read_text(encoding="utf-8") == "local"
    assert git(checkout, "sparse-checkout", "list").split() == ["tools", "configs/common"]


@needs_git
def test_wrong_head_is_refused(local_repo, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    fetcher.fetch_one(local_repo, corpus)
    report = fetcher.verify_repo(dict(local_repo, sha="1" * 40), corpus)
    assert not report["ok"] and report["head"] == local_repo["sha"]
    assert report["problems"][0] == (f"synthetic: the checkout is at {local_repo['sha']}, expected {'1' * 40}; "
                                     "refusing to change the checkout")


@needs_git
def test_hidden_modification_and_hidden_deletion_are_caught_by_blob_comparison(local_repo, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    (checkout / "tools/train.py").write_bytes(b"print('edited')\n")
    git(checkout, "update-index", "--assume-unchanged", "tools/train.py")
    (checkout / "configs/common/a.py").unlink()
    git(checkout, "update-index", "--skip-worktree", "configs/common/a.py")
    report = fetcher.verify_repo(local_repo, corpus)
    assert report["clean"] and report["sparseMatches"] and not report["ok"]
    assert report["blobMismatches"] == ["tools/train.py"]
    assert report["missing"] == ["configs/common/a.py"]
    with pytest.raises(fetcher.FetchError, match="differ from the pinned blobs"):
        fetcher.fetch_one(local_repo, corpus)


@needs_git
def test_update_sparse_keeps_hand_materialised_files_offline_and_reverifies(local_repo, monkeypatch, tmp_path: Path,
                                                                           capsys) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    # Reproduce the EVAL-3 state: a covered-later file materialised by hand, skip-worktree cleared.
    (checkout / "configs/_base_").mkdir()
    (checkout / "configs/_base_/default_runtime.py").write_bytes(UPSTREAM_FILES["configs/_base_/default_runtime.py"])
    git(checkout, "update-index", "--no-skip-worktree", "configs/_base_/default_runtime.py")
    (checkout / ".mlview-pinned-sha").write_bytes(local_repo["sha"].encode("ascii") + b"\n")
    before = materialised(checkout)
    new = dict(local_repo, sparse=["tools", "configs/common", "/configs/_base_/default_runtime.py"])
    report = fetcher.verify_repo(new, corpus)
    assert report["clean"] and not report["sparseMatches"] and not report["missing"] and not report["extraMaterialized"]
    assert report["problems"] == ["synthetic: sparse patterns differ from the manifest (missing: "
                                  "/configs/_base_/default_runtime.py); re-run with --update-sparse"]
    with pytest.raises(fetcher.FetchError, match="re-run with --update-sparse"):
        fetcher.fetch_one(new, corpus)
    monkeypatch.setenv("GIT_NO_LAZY_FETCH", "1")  # the files are already present: no fetch may happen
    after = fetcher.update_sparse_one(new, corpus)
    monkeypatch.delenv("GIT_NO_LAZY_FETCH")
    assert after["ok"] and after["legacyMarker"] and after["covered"] == 4
    assert materialised(checkout) == before
    assert git(checkout, "sparse-checkout", "list").split() == new["sparse"]
    output = capsys.readouterr().out
    assert "git may fetch newly included blobs" in output
    assert fetcher.update_sparse_one(new, corpus)["ok"]
    assert "already match the manifest; nothing to change" in capsys.readouterr().out


@needs_git
def test_update_sparse_fetches_a_newly_included_blob_from_the_pinned_remote(local_repo, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    new = dict(local_repo, sparse=["tools", "configs/common", "/configs/faster_rcnn/x.py"])
    assert fetcher.verify_repo(new, corpus)["missing"] == ["configs/faster_rcnn/x.py"]
    assert fetcher.update_sparse_one(new, corpus)["ok"]
    assert (checkout / "configs/faster_rcnn/x.py").read_bytes() == UPSTREAM_FILES["configs/faster_rcnn/x.py"]


@needs_git
def test_update_sparse_refuses_to_drop_materialised_files(local_repo, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    narrower = dict(local_repo, sparse=["/tools"])
    report = fetcher.verify_repo(narrower, corpus)
    assert report["ok"] is False and report["extraMaterialized"] == ["configs/common/a.py", "docs/tools/notes.md"]
    with pytest.raises(fetcher.FetchError, match=r"would drop 2 materialised file\(s\) \(configs/common/a.py, "
                                                 r"docs/tools/notes.md\); refusing to change the checkout"):
        fetcher.update_sparse_one(narrower, corpus)
    assert git(checkout, "sparse-checkout", "list").split() == ["tools", "configs/common"]
    assert (checkout / "configs/common/a.py").is_file()


@needs_git
def test_update_sparse_refuses_when_the_tree_was_not_fully_inspected(local_repo, monkeypatch, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    narrower = dict(local_repo, sparse=["/tools"])
    real_tree = fetcher._tree

    def unlisted(checkout_path, sha):
        raise fetcher.FetchError("git ls-tree failed")

    monkeypatch.setattr(fetcher, "_tree", unlisted)
    report = fetcher.verify_repo(narrower, corpus)
    assert report["treeChecked"] is False and report["extraMaterialized"] == []
    with pytest.raises(fetcher.FetchError, match="cannot list the pinned tree"):
        fetcher.update_sparse_one(narrower, corpus)
    monkeypatch.setattr(fetcher, "_tree", real_tree)
    real_covers = fetcher.eval_records.sparse_covers

    def undecided(patterns, path):
        if path.startswith("configs/"):
            raise ValueError("synthetic undecidable pattern")
        return real_covers(patterns, path)

    monkeypatch.setattr(fetcher.eval_records, "sparse_covers", undecided)
    report = fetcher.verify_repo(narrower, corpus)
    assert report["treeChecked"] is True and "configs/common/a.py" in report["unclassified"]
    with pytest.raises(fetcher.FetchError, match="cannot decide sparse coverage"):
        fetcher.update_sparse_one(narrower, corpus)
    assert git(checkout, "sparse-checkout", "list").split() == ["tools", "configs/common"]
    assert (checkout / "configs/common/a.py").is_file()


@needs_git
def test_extra_materialised_files_are_reported_but_do_not_fail(local_repo, tmp_path: Path, capsys) -> None:
    corpus = tmp_path / "corpus"
    checkout = fetcher.fetch_one(local_repo, corpus)
    (checkout / "configs/_base_").mkdir()
    (checkout / "configs/_base_/other.py").write_bytes(UPSTREAM_FILES["configs/_base_/other.py"])
    git(checkout, "update-index", "--no-skip-worktree", "configs/_base_/other.py")
    report = fetcher.verify_repo(local_repo, corpus)
    assert report["ok"] and report["extraMaterialized"] == ["configs/_base_/other.py"]
    assert "1 extra materialised file(s) outside the sparse patterns are ignored" in fetcher.describe(report, local_repo)


@needs_git
def test_main_verify_and_update_sparse_through_a_manifest(local_repo, monkeypatch, tmp_path: Path, capsys) -> None:
    repos = [dict(local_repo, name=f"repo{index}") for index in range(8)]
    manifest = tmp_path / "repositories.json"
    manifest.write_text(json.dumps({"repos": repos}), encoding="utf-8")
    monkeypatch.setattr(fetcher, "MANIFEST_PATH", manifest)
    monkeypatch.setenv("MLVIEW_PUBLIC_CORPUS_DIR", str(tmp_path / "corpus"))
    assert fetcher.main(["--verify", "--repo", "repo0"]) == 1
    assert "not fetched" in capsys.readouterr().out
    assert fetcher.main(["--repo", "repo0"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "fetch-workflow-repos: OK (1 repositories)"
    assert fetcher.main(["--verify", "--json", "--repo", "repo0"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] and payload["repositories"][0]["covered"] == 3
    assert str(tmp_path) not in json.dumps(payload)
    repos[0]["sparse"] = ["tools", "configs/common", "/configs/_base_/default_runtime.py"]
    manifest.write_text(json.dumps({"repos": repos}), encoding="utf-8")
    assert fetcher.main(["--verify", "--repo", "repo0"]) == 1
    assert "re-run with --update-sparse" in capsys.readouterr().out
    assert fetcher.main(["--update-sparse", "--repo", "repo0"]) == 0
    assert fetcher.main(["--verify", "--repo", "repo0"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "fetch-workflow-repos: verify OK (1 of 1 repositories pass)"
    assert fetcher.main(["--update-sparse", "--repo", "repo1"]) == 1
    assert "changes existing checkouts only" in capsys.readouterr().err
