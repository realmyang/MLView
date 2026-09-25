"""The repository manifest fetches every path the held-out tasks need (Campaign 2 section 5.2).

(a) every required path of every held-out task is covered by its repository's sparse patterns;
(b) the coverage matcher agrees with real `git sparse-checkout set --no-cone`;
(c) the commit triple: tasks.json commit = repositories.json sha = ledger repositoryCommit;
(d) corpus-gated: in each local checkout the covered set equals the materialised set and every
    required file is blob-exact (skipped, with the reason, when the checkout is absent).

No network is used. These are local configuration checks, not semantic accuracy, human review
or live-host validation.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import eval_records as er  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("fetch_workflow_repos_coverage", ROOT / "tools" / "fetch_workflow_repos.py")
assert _SPEC and _SPEC.loader
fetcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fetcher)

HAS_GIT = shutil.which("git") is not None
MANIFEST = json.loads((ROOT / "evals/workflow/tasks.json").read_text(encoding="utf-8"))
HELD_OUT = [task for task in MANIFEST["tasks"] if task["split"] == "heldout"]
REPOS = {repo["name"]: repo for repo in fetcher.load_manifest()}
PRE_CAMPAIGN_MMDETECTION = ["tools", "mmdet/apis", "mmdet/engine", "mmdet/models/detectors", "configs/common"]
MMDETECTION_CONFIGS = [
    "configs/_base_/datasets/coco_detection.py",
    "configs/_base_/default_runtime.py",
    "configs/_base_/models/faster-rcnn_r50_fpn.py",
    "configs/_base_/schedules/schedule_1x.py",
    "configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py",
]


def uncovered(repos: dict[str, dict]) -> dict[str, list[str]]:
    result = {}
    for task in HELD_OUT:
        patterns = repos[task["repository"]]["sparse"]
        missing = [path for path in er.required_paths(task["id"], ROOT) if not er.sparse_covers(patterns, path)]
        if missing:
            result[task["id"]] = missing
    return result


# (a) ----------------------------------------------------------------------------------------


def test_every_required_path_of_every_held_out_task_is_covered() -> None:
    assert len(HELD_OUT) == 8
    assert uncovered(REPOS) == {}


def test_the_pre_campaign_mmdetection_list_misses_exactly_the_five_config_files() -> None:
    old = {name: dict(repo) for name, repo in REPOS.items()}
    old["mmdetection"]["sparse"] = PRE_CAMPAIGN_MMDETECTION
    assert uncovered(old) == {"pilot-registry": MMDETECTION_CONFIGS}


def test_required_paths_are_computed_not_parsed_from_arguments() -> None:
    registry = er.required_paths("pilot-registry", ROOT)
    assert "tools/train.py" in registry and set(MMDETECTION_CONFIGS) <= set(registry)
    flax = er.required_paths("pilot-flax", ROOT)
    assert not [path for path in flax if "workdir" in path or "<" in path]


# (b) ----------------------------------------------------------------------------------------

SPEC_VECTORS = [
    (["tools"], "mmdet/tools/x.py", True),
    (["configs/common"], "configs/x/common/y.py", False),
    (["/*.ipynb"], "sub/b.ipynb", False),
    (["examples"], "docs/examples/f.py", True),
]
DECOYS = [
    "README.md", "setup.py", "mmdet/tools/x.py", "configs/x/common/y.py", "configs/common/lsj.py",
    "configs/_base_/models/retinanet.py", "configs/_base_/datasets/voc.py", "configs/_base_/schedules/schedule_2x.py",
    "configs/faster_rcnn/faster-rcnn_r101_fpn_1x_coco.py", "a.ipynb", "sub/b.ipynb", "x.ipynb/inner.py",
    "docs/examples/f.py", "examples/pytorch/other/run.py", "src/cleanrl/y.py", "cleanrl_utils/x.py",
    "mmdet/models/backbones/resnet.py", "tests/test_train.py",
]


def representative_paths() -> list[str]:
    paths = set(DECOYS) | {path for _, path, _ in SPEC_VECTORS}
    for task in HELD_OUT:
        paths.update(er.required_paths(task["id"], ROOT))
    return sorted(paths)


def git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Synthetic Test", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
                "GIT_COMMITTER_NAME": "Synthetic Test", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid"})
    return env


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=git_env(), check=True)


def test_specification_vectors() -> None:
    for patterns, path, expected in SPEC_VECTORS:
        assert er.sparse_covers(patterns, path) is expected, (patterns, path)


@pytest.mark.skipif(not HAS_GIT, reason="git is not installed")
def test_coverage_matcher_agrees_with_real_git_on_every_manifest_pattern_set(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    paths = representative_paths()
    for rel in paths:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(rel.encode("utf-8") + b"\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "synthetic")
    pattern_sets = [repo_entry["sparse"] for repo_entry in REPOS.values()] + [PRE_CAMPAIGN_MMDETECTION]
    pattern_sets += [patterns for patterns, _, _ in SPEC_VECTORS]
    for patterns in pattern_sets:
        if patterns:
            git(repo, "sparse-checkout", "set", "--no-cone", "--", *patterns)
        else:
            git(repo, "sparse-checkout", "disable")
        present = {path.relative_to(repo).as_posix() for path in repo.rglob("*")
                   if path.is_file() and ".git" not in path.relative_to(repo).parts}
        assert present == {rel for rel in paths if er.sparse_covers(patterns, rel)}, patterns
    for patterns, path, expected in SPEC_VECTORS:
        git(repo, "sparse-checkout", "set", "--no-cone", "--", *patterns)
        assert (repo / path).is_file() is expected, (patterns, path)


# (c) ----------------------------------------------------------------------------------------


def test_commit_triple_and_repository_identity() -> None:
    assert sorted(task["repository"] for task in HELD_OUT) == sorted(REPOS)
    for task in HELD_OUT:
        repo = REPOS[task["repository"]]
        ledger = json.loads((ROOT / "evals/workflow/reference-candidates" / f"{task['id']}.json").read_text(encoding="utf-8"))
        assert ledger["taskId"] == task["id"]
        assert task["commit"] == repo["sha"] == ledger["repositoryCommit"], task["id"]
        assert task["url"] == repo["url"], task["id"]


# (d) ----------------------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_GIT, reason="git is not installed")
@pytest.mark.parametrize("name", sorted(REPOS))
def test_local_checkout_materialises_exactly_the_covered_set(name: str) -> None:
    corpus = fetcher.corpus_dir()
    if not (corpus / name / ".git").is_dir():
        pytest.skip(f"corpus checkout {name} is absent under {corpus} "
                    "(set MLVIEW_PUBLIC_CORPUS_DIR or run python tools/fetch_workflow_repos.py)")
    repo = REPOS[name]
    report = fetcher.verify_repo(repo, corpus)
    assert report["head"] == repo["sha"], report["problems"]
    assert report["missing"] == [] and report["extraMaterialized"] == [], report
    assert report["blobMismatches"] == [], report
    tree = er.pinned_tree(corpus / name, repo["sha"])
    for task in (task for task in HELD_OUT if task["repository"] == name):
        for path in er.required_paths(task["id"], ROOT):
            er.pinned_bytes(corpus / name, repo["sha"], path, tree=tree)
