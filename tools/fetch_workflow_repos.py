#!/usr/bin/env python3
"""Fetch, verify or re-sparsify the eight pinned repositories used by held-out workflow evaluation.

Default: fetch every missing repository (a shallow, blob-filtered, non-cone sparse checkout with
core.autocrlf=false) and verify every existing one. An existing checkout is used only when it is
exactly the pinned commit, clean (apart from the analyzer-era marker .mlview-pinned-sha when it
holds the pin), on the manifest's sparse patterns, and every covered file is materialised and
blob-exact. The fetcher never resets, cleans or re-clones an existing checkout.

--verify [--json]  read-only report; exit 0 only when every selected repository passes.
--update-sparse    apply the manifest's sparse patterns to existing, clean, pinned checkouts;
                   refuses when that would drop a materialised file. Git may fetch newly included
                   blobs from the pinned remote, the only network use besides a fresh fetch.

Every read runs with GIT_NO_LAZY_FETCH=1 and GIT_OPTIONAL_LOCKS=0, compares worktree bytes with
the blob IDs of `git ls-tree`, and never reads a blob object.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))  # the fetcher shares eval_records with the evaluation tools
import eval_records  # noqa: E402

REPO_ROOT = TOOLS.parent
MANIFEST_PATH = REPO_ROOT / "evals" / "workflow" / "repositories.json"
DEFAULT_CORPUS_DIR = REPO_ROOT / ".public-corpus"
# The untracked file the retired analyzer's fetcher wrote into every checkout (EVAL-16, D19).
LEGACY_MARKER = ".mlview-pinned-sha"
# Manifest URLs must use one of these schemes; tests substitute a local file:// repository.
URL_PREFIXES: tuple[str, ...] = ("https://",)
# Variables that would redirect git to another repository, index or object store.
_GIT_REDIRECTS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
                  "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")
_PREVIEW = 5


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
        if not isinstance(url, str) or not url.startswith(URL_PREFIXES):
            raise FetchError(f"{name}: url must be HTTPS")
        if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            raise FetchError(f"{name}: sha must be a full lowercase 40-hex commit")
        sparse = repo.get("sparse", [])
        if not isinstance(sparse, list) or not all(isinstance(item, str) and item for item in sparse):
            raise FetchError(f"{name}: sparse must be a list of non-empty paths")
        try:
            eval_records.validate_sparse_patterns(sparse)
        except ValueError as exc:
            raise FetchError(f"{name}: {exc}") from exc
        seen.add(name)
    return repos


def _git_env(offline: bool) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in _GIT_REDIRECTS}
    env["GIT_TERMINAL_PROMPT"] = "0"
    if offline:
        env.update({"GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0"})
    return env


def _git(args: Sequence[str], cwd: Path, *, offline: bool = False) -> str:
    """Run git in ``cwd``. ``offline`` marks a read: lazy fetches, optional locks (index refresh
    writes) and every transport are disabled, so a missing object is an error."""
    command = ["git", "-c", "protocol.allow=never", *args] if offline else ["git", *args]
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, env=_git_env(offline), check=False)
    except OSError as exc:
        raise FetchError(f"cannot run git: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise FetchError(f"git {args[0]} failed in {cwd}: {detail or f'exit status {result.returncode}'}")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError(f"git {args[0]} in {cwd} printed output that is not UTF-8") from exc


def _preview(items: Sequence[str]) -> str:
    shown = ", ".join(items[:_PREVIEW])
    return shown + (f", … ({len(items)} in total)" if len(items) > _PREVIEW else "")


def _tree(checkout: Path, commit: str) -> dict[str, str]:
    """``{path: blob OID}`` of every blob at ``commit`` (trees only; no blob is read)."""
    listing = _git(["ls-tree", "-r", "-z", "--full-tree", f"{commit}^{{commit}}"], checkout, offline=True)
    tree: dict[str, str] = {}
    for entry in listing.split("\0"):
        if not entry:
            continue
        meta, _tab, path = entry.partition("\t")
        fields = meta.split(" ")
        if len(fields) == 3 and fields[1] == "blob":
            tree[path] = fields[2]
    return tree


def _worktree_blob(checkout: Path, path: str, safe_dirs: set[str]) -> bytes | None:
    """The blob content the worktree holds for ``path``: a regular file's bytes or a symbolic
    link's target. None when nothing is materialised there. Raises ValueError when a parent
    component is not a real directory (for example a symbolic link)."""
    parts = path.split("/")
    current = checkout
    for index, part in enumerate(parts[:-1]):
        current = current / part
        prefix = "/".join(parts[:index + 1])
        if prefix in safe_dirs:
            continue
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"{prefix} is not a real directory")
        safe_dirs.add(prefix)
    target = current / parts[-1]
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return os.fsencode(os.readlink(target))
    if stat.S_ISREG(info.st_mode):
        return target.read_bytes()
    raise ValueError(f"{path} is not a regular file")


def _legacy_marker_holds_pin(checkout: Path, sha: str) -> bool:
    marker = checkout / LEGACY_MARKER
    try:
        if not stat.S_ISREG(os.lstat(marker).st_mode):
            return False
        return marker.read_bytes() in (sha.encode("ascii"), sha.encode("ascii") + b"\n")
    except OSError:
        return False


def _sparse_difference(patterns: list[str], enabled: bool, cone: bool, actual: list[str]) -> str:
    if not enabled:
        return f"sparse checkout is disabled; the manifest lists {len(patterns)} pattern(s)"
    if cone:
        return "the checkout uses cone mode; the manifest uses non-cone patterns"
    if not patterns:
        return "the manifest asks for a full checkout"
    parts = []
    missing = [pattern for pattern in patterns if pattern not in actual]
    extra = [pattern for pattern in actual if pattern not in patterns]
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if extra:
        parts.append("extra: " + ", ".join(extra))
    return "; ".join(parts) or "the same patterns in a different order"


def _verify_checkout(repo: dict[str, Any], checkout: Path) -> dict[str, Any]:
    """The read-only verification behind verify_repo, for a checkout at any path. A failing git
    read becomes a problem in the report, so one broken checkout never hides the others."""
    report: dict[str, Any] = {
        "name": repo["name"], "head": None, "clean": False, "legacyMarker": False, "sparseMatches": False,
        "covered": 0, "missing": [], "extraMaterialized": [], "blobMismatches": [], "ok": False,
        "problems": [],
    }
    try:
        _inspect_checkout(repo, checkout, report)
    except FetchError as exc:
        report["problems"].append(f"{repo['name']}: cannot inspect the checkout ({exc})")
    report["ok"] = not report["problems"]
    return report


def _inspect_checkout(repo: dict[str, Any], checkout: Path, report: dict[str, Any]) -> None:
    name, pin = repo["name"], repo["sha"]
    patterns = list(repo.get("sparse", []))
    problems: list[str] = report["problems"]
    if not os.path.lexists(checkout):
        problems.append(f"{name}: not fetched ({checkout} does not exist); "
                        f"run python tools/fetch_workflow_repos.py --repo {name}")
        return
    if checkout.is_symlink() or not (checkout / ".git").is_dir():
        problems.append(f"{name}: {checkout} exists but is not a Git checkout; refusing to use it")
        return
    head = _git(["rev-parse", "--verify", "HEAD"], checkout, offline=True).strip()
    report["head"] = head
    if head != pin:
        problems.append(f"{name}: the checkout is at {head}, expected {pin}; refusing to change the checkout")

    status = _git(["status", "--porcelain=v1", "-z", "--untracked-files=normal"], checkout, offline=True)
    marker_entry = f"?? {LEGACY_MARKER}"
    changes = [entry for entry in status.split("\0") if entry and entry != marker_entry]
    if marker_entry in status.split("\0"):
        if _legacy_marker_holds_pin(checkout, pin):
            report["legacyMarker"] = True
        else:
            changes.append(f"{marker_entry} (it does not hold the pinned commit)")
    report["clean"] = not changes
    if changes:
        problems.append(f"{name}: the checkout has local changes ({_preview(changes)}); refusing to modify it")

    enabled = _git(["config", "--bool", "--default", "false", "core.sparseCheckout"],
                   checkout, offline=True).strip() == "true"
    cone = _git(["config", "--bool", "--default", "false", "core.sparseCheckoutCone"],
                checkout, offline=True).strip() == "true"
    actual = []
    if enabled:
        actual = [line.strip() for line in _git(["sparse-checkout", "list"], checkout, offline=True).splitlines()
                  if line.strip()]
    report["sparseMatches"] = (not enabled and not patterns) or (enabled and not cone and actual == patterns)
    if not report["sparseMatches"]:
        problems.append(f"{name}: sparse patterns differ from the manifest "
                        f"({_sparse_difference(patterns, enabled, cone, actual)}); re-run with --update-sparse")

    if head == pin:
        _compare_tree(repo, checkout, report)


def _compare_tree(repo: dict[str, Any], checkout: Path, report: dict[str, Any]) -> None:
    name, patterns = repo["name"], list(repo.get("sparse", []))
    problems: list[str] = report["problems"]
    try:
        tree = _tree(checkout, repo["sha"])
    except FetchError as exc:
        problems.append(f"{name}: cannot list the pinned tree ({exc})")
        return
    safe_dirs: set[str] = set()
    for path in sorted(tree):
        try:
            covered = eval_records.sparse_covers(patterns, path)
        except ValueError as exc:
            problems.append(f"{name}: cannot decide sparse coverage of {path!r} ({exc})")
            continue
        try:
            data = _worktree_blob(checkout, path, safe_dirs)
        except (OSError, ValueError):
            if covered:
                report["covered"] += 1
                report["blobMismatches"].append(path)
            continue
        if not covered:
            if data is not None:
                report["extraMaterialized"].append(path)
            continue
        report["covered"] += 1
        if data is None:
            report["missing"].append(path)
        elif eval_records.git_blob_oid(data) != tree[path]:
            report["blobMismatches"].append(path)
    if report["missing"]:
        problems.append(f"{name}: {len(report['missing'])} covered file(s) are not materialised "
                        f"({_preview(report['missing'])}); re-run with --update-sparse")
    if report["blobMismatches"]:
        problems.append(f"{name}: {len(report['blobMismatches'])} file(s) differ from the pinned blobs "
                        f"({_preview(report['blobMismatches'])}); the checkout was modified. Restore the "
                        "pinned bytes, or move the checkout aside and fetch again")


def verify_repo(repo: dict[str, Any], corpus_root: Path) -> dict[str, Any]:
    """Verify ``corpus_root/<name>`` against its manifest entry without changing anything.

    Returns ``{name, head, clean, legacyMarker, sparseMatches, covered, missing[],
    extraMaterialized[], blobMismatches[], ok, problems[]}``. ``ok`` requires HEAD = the pin, a
    clean status (the analyzer marker .mlview-pinned-sha is tolerated only when its bytes are the
    pin, optionally with one newline), ``git sparse-checkout list`` = the manifest (an empty list
    means sparse checkout disabled), and every covered path materialised and blob-exact. Extra
    materialised files outside the patterns are reported but do not fail: workspaces copy only
    covered paths. ``problems`` gives one sentence with a remedy per failure.
    """
    return _verify_checkout(repo, Path(corpus_root) / repo["name"])


def describe(report: dict[str, Any], repo: dict[str, Any]) -> str:
    """The one-line summary of a passing report: ``nanoGPT @ 3adf61e154c3 (...)``."""
    notes = [f"{report['covered']} covered files blob-exact"]
    if report["legacyMarker"]:
        notes.append(f"ignored the legacy analyzer marker {LEGACY_MARKER}")
    extra = report["extraMaterialized"]
    if extra:
        notes.append(f"{len(extra)} extra materialised file(s) outside the sparse patterns are ignored: "
                     f"{_preview(extra)}")
    return f"{repo['name']} @ {repo['sha'][:12]} ({'; '.join(notes)})"


def _have_line(report: dict[str, Any], repo: dict[str, Any]) -> str:
    line = f"have {repo['name']} @ {repo['sha'][:12]}"
    if report["legacyMarker"]:
        line += f" (ignored the legacy analyzer marker {LEGACY_MARKER})"
    return line


def fetch_one(repo: dict[str, Any], destination_root: Path) -> Path:
    destination = destination_root / repo["name"]
    if os.path.lexists(destination):
        report = verify_repo(repo, destination_root)
        if not report["ok"]:
            raise FetchError("; ".join(report["problems"]))
        print(_have_line(report, repo))
        return destination

    destination_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{repo['name']}-", dir=destination_root))
    try:
        _git(["init", "--quiet"], staging)
        # Worktree bytes must equal the pinned blobs on every OS (Git for Windows defaults to
        # core.autocrlf=true), so line-ending conversion is off before anything is checked out.
        _git(["config", "core.autocrlf", "false"], staging)
        _git(["remote", "add", "origin", repo["url"]], staging)
        sparse = repo.get("sparse", [])
        if sparse:
            _git(["sparse-checkout", "init", "--no-cone"], staging)
            _git(["sparse-checkout", "set", "--no-cone", "--", *sparse], staging)
        _git(["fetch", "--depth", "1", "--filter=blob:none", "origin", repo["sha"]], staging)
        _git(["checkout", "--quiet", "--detach", "FETCH_HEAD"], staging)
        report = _verify_checkout(repo, staging)
        if report["head"] is not None and report["head"] != repo["sha"]:
            raise FetchError(f"{repo['name']}: fetched {report['head']}, expected {repo['sha']}")
        if not report["ok"]:
            raise FetchError(f"{repo['name']}: the new checkout failed verification: "
                             + "; ".join(report["problems"]))
        staging.replace(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"fetched {repo['name']} @ {repo['sha'][:12]}")
    return destination


def update_sparse_one(repo: dict[str, Any], destination_root: Path) -> dict[str, Any]:
    """Apply the manifest's sparse patterns to an existing checkout at the pin that is clean apart
    from the tolerated marker. Refuses when a materialised file would be dropped; re-verifies."""
    name = repo["name"]
    if not os.path.lexists(destination_root / name):
        raise FetchError(f"{name}: not fetched; --update-sparse changes existing checkouts only. "
                         f"Run python tools/fetch_workflow_repos.py --repo {name}")
    report = verify_repo(repo, destination_root)
    if report["ok"]:
        print(f"{name}: sparse patterns already match the manifest; nothing to change")
        return report
    if report["head"] != repo["sha"] or not report["clean"] or report["blobMismatches"]:
        raise FetchError("; ".join(problem for problem in report["problems"] if "--update-sparse" not in problem))
    dropped = report["extraMaterialized"]
    if dropped:
        raise FetchError(f"{name}: the manifest's sparse patterns would drop {len(dropped)} materialised "
                         f"file(s) ({_preview(dropped)}); refusing to change the checkout. Add patterns "
                         "that cover them to evals/workflow/repositories.json, or move the checkout aside "
                         "and fetch again")
    patterns = list(repo.get("sparse", []))
    print(f"{name}: applying the manifest's sparse patterns; git may fetch newly included blobs from "
          f"{repo['url']}")
    checkout = destination_root / name
    if patterns:
        _git(["sparse-checkout", "set", "--no-cone", "--", *patterns], checkout)
    else:
        _git(["sparse-checkout", "disable"], checkout)
    after = verify_repo(repo, destination_root)
    if not after["ok"]:
        raise FetchError(f"{name}: the sparse patterns were applied but verification failed: "
                         + "; ".join(after["problems"]))
    print(f"updated {describe(after, repo)}")
    return after


def _select(repos: Sequence[dict[str, Any]], selected: Sequence[str]) -> list[dict[str, Any]]:
    by_name = {repo["name"]: repo for repo in repos}
    unknown = sorted(set(selected) - by_name.keys())
    if unknown:
        raise FetchError(
            "unknown --repo value(s): %s; choose from %s"
            % (", ".join(unknown), ", ".join(sorted(by_name)))
        )
    return [repo for repo in repos if not selected or repo["name"] in selected]


def fetch(repos: Sequence[dict[str, Any]], destination_root: Path, selected: Sequence[str]) -> list[Path]:
    return [fetch_one(repo, destination_root) for repo in _select(repos, selected)]


def update_sparse(repos: Sequence[dict[str, Any]], destination_root: Path,
                  selected: Sequence[str]) -> list[dict[str, Any]]:
    return [update_sparse_one(repo, destination_root) for repo in _select(repos, selected)]


def verify(repos: Sequence[dict[str, Any]], destination_root: Path,
           selected: Sequence[str]) -> list[dict[str, Any]]:
    return [verify_repo(repo, destination_root) for repo in _select(repos, selected)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="NAME",
        help="act on this repository only; repeat to select more than one",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true",
                      help="read-only report; exit 0 only when every selected repository passes")
    mode.add_argument("--update-sparse", action="store_true",
                      help="apply the manifest's sparse patterns to existing clean, pinned checkouts "
                           "(git may fetch newly included blobs)")
    parser.add_argument("--json", action="store_true", help="with --verify: print the reports as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.json and not args.verify:
        parser.error("--json applies only to --verify")
    try:
        repos = load_manifest()
        root = corpus_dir()
        if args.verify:
            selected = _select(repos, args.repo)
            reports = verify(repos, root, args.repo)
            passed = sum(1 for report in reports if report["ok"])
            if args.json:
                print(json.dumps({"ok": passed == len(reports), "repositories": reports}, indent=2))
            else:
                for report, repo in zip(reports, selected):
                    if report["ok"]:
                        print(f"ok   {describe(report, repo)}")
                    for problem in report["problems"]:
                        print(f"FAIL {problem}")
                verdict = "OK" if passed == len(reports) else "FAILED"
                print(f"fetch-workflow-repos: verify {verdict} ({passed} of {len(reports)} repositories pass)")
            return 0 if passed == len(reports) else 1
        if args.update_sparse:
            updated = update_sparse(repos, root, args.repo)
            print(f"fetch-workflow-repos: OK ({len(updated)} repositories on the manifest's sparse patterns)")
            return 0
        fetched = fetch(repos, root, args.repo)
    except FetchError as exc:
        print(f"fetch-workflow-repos: {exc}", file=sys.stderr)
        return 1
    print(f"fetch-workflow-repos: OK ({len(fetched)} repositories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
