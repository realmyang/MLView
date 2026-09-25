#!/usr/bin/env python3
"""Capture or check a candidate identity. A candidate record identifies exact bytes only; it is
never human review, semantic quality, host discovery or pilot approval.

Pilot candidate (version 2, kind "pilot-candidate"), captured once per campaign on a clean tree:

    git status --porcelain                      # must print nothing
    (cd webview && npm ci) && (cd vscode-extension && npm ci)
    python tools/workflow_candidate.py --campaign pilot-01 --build-vsix     # uses $MLVIEW_PILOT_DIR

The capture refuses unless tasks.json names the campaign's committed freeze and check-frozen
passes, builds the VSIX itself into $MLVIEW_PILOT_DIR, re-checks that the tree is still clean,
checks the VSIX payload, media and version, cross-checks the skill payload against
`git ls-files skills/mlview`, and creates evals/workflow/pilot/<campaign>/candidate.json
exclusively. The operator commits it; candidateSha256 = sha256(candidate.json).

Development snapshot (version 2, kind "development-snapshot") for local drift checks; dirty trees
are allowed, the VSIX is optional, and summarize refuses this kind:

    python tools/workflow_candidate.py --output .mlview/candidate.json [--vsix PATH]

Check either kind (a pilot record is proven against `git show <commit>:<path>`; drift at HEAD is
reported as information):

    python tools/workflow_candidate.py --check PATH [--vsix PATH]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Callable

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))  # the tool imports its siblings eval_records and package_skill
import eval_records as er  # noqa: E402
from package_skill import bundle_identity, canonical_files  # noqa: E402

ROOT = TOOLS.parent
VERSION = 2
PILOT_KIND = "pilot-candidate"
DEVELOPMENT_KIND = "development-snapshot"
ALGORITHM = "sha256-sorted-path-nul-bytes-nul"
SKILL_DIR = "skills/mlview"
TASKS_REL = "evals/workflow/tasks.json"
PILOT_REL = "evals/workflow/pilot"
EXTENSION_PACKAGE = "vscode-extension/package.json"
MEDIA_DIR = "vscode-extension/media"
BASE_COMPONENTS = ("contracts/workflow.schema.json", TASKS_REL, "evals/workflow/repositories.json",
                   "webview/dist/mlview.js", "webview/dist/mlview.css", EXTENSION_PACKAGE)
DEVELOPMENT_COMPONENTS = BASE_COMPONENTS
VSIX_ENTRIES = ("extension/media/mlview.css", "extension/media/mlview.js", "extension/out/extension.js",
                "extension/package.json")
PILOT_GATES = [
    "Stage 1 skill runs (and any planned baselines) prepared and sealed with run-prepare and run-finish",
    "A named human review of every completed run",
    "The Stage 1 stop/go computation by summarize against the predefined targets",
    "Stage 2 repeats only after a committed Stage 1 go",
    "The owner's pilot decision",
]
PILOT_NOTE = ("This record identifies the candidate's bytes and binds the frozen campaign through freeze.json. "
              "It does not authenticate the capture, establish semantic quality or host discovery, or record "
              "human review or pilot approval.")
DEVELOPMENT_GATES = [
    "Named human source-reference review",
    "Frozen scenarios and essential-fact denominator",
    "Frozen expanded prompts, model/host settings, budgets and privacy policy",
    "Reviewed development outcomes and Stage 1 stop/go decision",
]
DEVELOPMENT_NOTE = ("This development snapshot checks selected candidate bytes only. It cannot identify a pilot "
                    "candidate (summarize refuses it), does not authenticate the snapshot, establish semantic "
                    "quality or host discovery, or record human review or pilot approval.")
IDENTITY_KEYS = {"path", "sha256", "bytes"}
SOURCE_KEYS = {"commit", "tree", "clean", "capturedAt"}
VSIX_KEYS = {"file", "sha256", "bytes", "version", "builtByCapture", "entries"}
SKILL_KEYS = {"algorithm", "sha256", "files"}
DEVELOPMENT_KEYS = {"version", "kind", "pilotApproved", "source", "skill", "components", "vsix",
                    "remainingGates", "note"}
PILOT_KEYS = DEVELOPMENT_KEYS | {"campaign", "referenceRevision"}
FREEZE_FORMAT = "mlview-freeze/1"
HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]+)?\Z")
_PREVIEW = 5


class CaptureError(ValueError):
    """A precondition of the pilot capture failed; nothing was recorded."""


def pilot_components(campaign: str) -> tuple[str, ...]:
    return BASE_COMPONENTS + (f"{PILOT_REL}/{campaign}/freeze.json",)


def candidate_path(campaign: str) -> str:
    return f"{PILOT_REL}/{campaign}/candidate.json"


def _preview(items: list[str]) -> str:
    return ", ".join(items[:_PREVIEW]) + (f", … ({len(items)} in total)" if len(items) > _PREVIEW else "")


# --------------------------------------------------------------------------------------------
# Identities


def identity(path: str, data: bytes) -> dict:
    return {"path": path, "sha256": er.sha256_bytes(data), "bytes": len(data)}


def file_identity(path: Path, root: Path) -> dict:
    root = root.resolve()
    try:
        relative_path = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("candidate file must be a regular non-symlink file inside the checkout") from exc
    cursor = root
    for part in relative_path.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("candidate file must be a regular non-symlink file inside the checkout")
    resolved = path.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError("candidate file must be a regular non-symlink file inside the checkout")
    return identity(relative_path.as_posix(), path.read_bytes())


def validate_identity(value: object, *, expected_path: str | None = None) -> dict:
    if not isinstance(value, dict) or set(value) != IDENTITY_KEYS:
        raise ValueError("invalid candidate file identity")
    path, digest, size = value.get("path"), value.get("sha256"), value.get("bytes")
    if (not isinstance(path, str) or "\\" in path or path.startswith("/") or
            any(part in {"", ".", ".."} for part in path.split("/"))):
        raise ValueError("invalid candidate file identity")
    if expected_path is not None and path != expected_path:
        raise ValueError("candidate component inventory does not match the required set")
    if not isinstance(digest, str) or not HEX_64.fullmatch(digest):
        raise ValueError("invalid candidate file identity")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("invalid candidate file identity")
    return value


def validate_bundle_identity(value: object) -> None:
    if not isinstance(value, dict) or set(value) != SKILL_KEYS:
        raise ValueError("invalid portable skill identity")
    if value.get("algorithm") != ALGORITHM:
        raise ValueError("invalid portable skill identity")
    digest, files = value.get("sha256"), value.get("files")
    if not isinstance(digest, str) or not HEX_64.fullmatch(digest) or not isinstance(files, list) or not files:
        raise ValueError("invalid portable skill identity")
    paths = [validate_identity(entry)["path"] for entry in files]
    if paths != sorted(set(paths)):
        raise ValueError("invalid portable skill identity")


def _validate_components(value: object, expected: tuple[str, ...]) -> None:
    if not isinstance(value, list) or len(value) != len(expected):
        raise ValueError("candidate requires exactly the component identities " + ", ".join(expected))
    for entry, path in zip(value, expected):
        validate_identity(entry, expected_path=path)


def _vsix_file_name(name: object) -> bool:
    return (isinstance(name, str) and name.endswith(".vsix") and not name.startswith(".")
            and not any(char in name for char in "/\\:\0"))


def validate_vsix(value: object, *, built_by_capture: bool) -> None:
    if not isinstance(value, dict) or set(value) != VSIX_KEYS:
        raise ValueError("invalid VSIX identity")
    if not _vsix_file_name(value.get("file")):
        raise ValueError("invalid VSIX identity: file is a plain *.vsix file name, never a path")
    digest, size, version = value.get("sha256"), value.get("bytes"), value.get("version")
    if not isinstance(digest, str) or not HEX_64.fullmatch(digest):
        raise ValueError("invalid VSIX identity")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("invalid VSIX identity")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError("invalid VSIX identity: version")
    if value.get("builtByCapture") is not built_by_capture:
        raise ValueError("a pilot candidate's VSIX must be built by the capture" if built_by_capture
                         else "a development snapshot never claims a VSIX built by the capture")
    _validate_components(value.get("entries"), VSIX_ENTRIES)


def vsix_identity(path: Path, *, built_by_capture: bool) -> dict:
    """The identity of a VSIX file: its name (never a path), bytes, version and pinned entries."""
    path = Path(path)
    try:
        info = os.lstat(path)
    except OSError:
        raise ValueError("candidate VSIX does not exist") from None
    if not stat.S_ISREG(info.st_mode) or path.suffix.lower() != ".vsix" or not _vsix_file_name(path.name):
        raise ValueError("candidate VSIX must be a regular *.vsix file (not a symbolic link)")
    data = path.read_bytes()
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            missing = [name for name in VSIX_ENTRIES if name not in names]
            if missing:
                raise ValueError(f"candidate VSIX lacks {', '.join(missing)}")
            entries = [identity(name, archive.read(name)) for name in VSIX_ENTRIES]
            version = json.loads(archive.read("extension/package.json")).get("version")
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"candidate VSIX cannot be read: {exc}") from None
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError("candidate VSIX package.json has no valid version")
    return {"file": path.name, "sha256": er.sha256_bytes(data), "bytes": len(data), "version": version,
            "builtByCapture": built_by_capture, "entries": entries}


def structure_problems(record: object) -> list[str]:
    """Why ``record`` is not a well-formed version 2 candidate (empty when it is)."""
    if not isinstance(record, dict):
        return ["candidate record must be a JSON object"]
    version = record.get("version")
    if version == 1 and type(version) is int:
        return ["unsupported candidate snapshot version 1 (candidate-byte-snapshot is no longer read); capture a "
                "new one: --output for a development snapshot, --campaign C --build-vsix for a pilot candidate"]
    if type(version) is not int or version != VERSION:
        return ["unsupported candidate snapshot version"]
    kind = record.get("kind")
    if kind not in (PILOT_KIND, DEVELOPMENT_KIND):
        return [f"unsupported candidate kind {kind!r}"]
    pilot = kind == PILOT_KIND
    keys = PILOT_KEYS if pilot else DEVELOPMENT_KEYS
    if set(record) != keys:
        return ["candidate record has unexpected or missing fields"]
    problems = []
    if record.get("pilotApproved") is not False:
        problems.append("pilotApproved must be false: a candidate record never approves a pilot")
    gates, note = (PILOT_GATES, PILOT_NOTE) if pilot else (DEVELOPMENT_GATES, DEVELOPMENT_NOTE)
    if record.get("remainingGates") != gates or record.get("note") != note:
        problems.append("remainingGates and note must be the fixed texts; a record cannot waive a gate")
    source = record.get("source")
    if not isinstance(source, dict) or set(source) != SOURCE_KEYS:
        return problems + ["invalid source metadata"]
    commit, tree, clean = source.get("commit"), source.get("tree"), source.get("clean")
    for label, value in (("commit", commit), ("tree", tree)):
        if not (isinstance(value, str) and HEX_40.fullmatch(value)) and (pilot or value is not None):
            problems.append(f"invalid source metadata: {label}")
    if pilot and clean is not True:
        problems.append("a pilot candidate is captured on a clean tree (source.clean must be true)")
    if not pilot and clean is not None and not isinstance(clean, bool):
        problems.append("invalid source metadata: clean")
    captured = source.get("capturedAt")
    if not isinstance(captured, str) or not er.is_rfc3339(captured):
        problems.append("invalid source metadata: capturedAt")
    campaign = record.get("campaign") if pilot else None
    if pilot and (not isinstance(campaign, str) or not er.NAME_RE.fullmatch(campaign)):
        return problems + ["campaign must be a lowercase campaign name such as pilot-01"]
    if pilot and (not isinstance(record.get("referenceRevision"), str)
                  or not er.REVISION_RE.fullmatch(record["referenceRevision"])):
        problems.append('referenceRevision must be "sha256:" followed by 64 hex digits')
    for check_part in (lambda: validate_bundle_identity(record.get("skill")),
                       lambda: _validate_components(record.get("components"),
                                                    pilot_components(campaign) if pilot else DEVELOPMENT_COMPONENTS),
                       lambda: (validate_vsix(record.get("vsix"), built_by_capture=True) if pilot else
                                record.get("vsix") is None or validate_vsix(record.get("vsix"), built_by_capture=False))):
        try:
            check_part()
        except ValueError as exc:
            problems.append(str(exc))
    return problems


# --------------------------------------------------------------------------------------------
# Git


def _git_run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items()
           if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR"}}
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"})
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, env=env, check=False)
    except OSError as exc:
        raise ValueError(f"cannot run git: {exc}") from exc


def _git(root: Path, *args: str) -> str:
    result = _git_run(root, *args)
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip() or f"exit status {result.returncode}"
        raise ValueError(f"git {args[0]} failed: {detail}")
    return result.stdout.decode("utf-8")


def git_value(root: Path, *args: str) -> str | None:
    try:
        result = _git_run(root, *args)
    except ValueError:
        return None
    return result.stdout.decode("utf-8", "replace").strip() if result.returncode == 0 else None


def _ls_files(root: Path, *paths: str) -> list[str]:
    return [item for item in _git(root, "ls-files", "-z", "--", *paths).split("\0") if item]


def _skill_paths(paths: list[str]) -> list[str]:
    """``skills/mlview/...`` paths without the prefix, minus tests/ (the canonical skill payload)."""
    prefix = SKILL_DIR + "/"
    return sorted(path[len(prefix):] for path in paths
                  if path.startswith(prefix) and "tests" not in PurePosixPath(path[len(prefix):]).parts)


# --------------------------------------------------------------------------------------------
# Check


def _prove_pilot(record: dict, root: Path) -> list[str]:
    """Prove every pinned byte at ``git show <source.commit>:<path>``."""
    commit = record["source"]["commit"]
    short = commit[:12]
    if _git_run(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode:
        shallow = git_value(root, "rev-parse", "--is-shallow-repository") == "true"
        return [f"source.commit {commit} is not in this clone"
                + ("; this is a shallow clone, fetch the full history (git fetch --unshallow)" if shallow else "")]
    problems = []
    ancestor = _git_run(root, "merge-base", "--is-ancestor", commit, "HEAD").returncode
    if ancestor:
        problems.append(f"source.commit {short} is not an ancestor of HEAD; check out the candidate commit "
                        "or a descendant of it")
    if git_value(root, "rev-parse", f"{commit}^{{tree}}") != record["source"]["tree"]:
        problems.append(f"source.tree is not the tree of {short}")
    for entry in record["components"]:
        try:
            data = er.git_show(root, commit, entry["path"])
        except ValueError:
            problems.append(f"component {entry['path']} does not exist at {short}")
            continue
        if identity(entry["path"], data) != entry:
            problems.append(f"component {entry['path']} differs from its bytes at {short}")
    try:
        listed = _skill_paths([path for path in
                               _git(root, "ls-tree", "-r", "-z", "--name-only", commit, "--", SKILL_DIR + "/")
                               .split("\0") if path])
    except ValueError as exc:
        return problems + [f"cannot list {SKILL_DIR} at {short}: {exc}"]
    recorded = [entry["path"] for entry in record["skill"]["files"]]
    if listed != recorded:
        problems.append(f"the skill files at {short} differ from the recorded list")
    else:
        try:
            payload = {path: er.git_show(root, commit, f"{SKILL_DIR}/{path}") for path in recorded}
        except ValueError as exc:
            payload = None
            problems.append(f"cannot read the skill at {short}: {exc}")
        if payload is not None and bundle_identity(payload) != record["skill"]:
            problems.append(f"the skill identity differs from the skill bytes at {short}")
    campaign, revision = record["campaign"], record["referenceRevision"]
    try:
        freeze = json.loads(er.git_show(root, commit, pilot_components(campaign)[-1]))
        tasks = json.loads(er.git_show(root, commit, TASKS_REL))
    except (ValueError, UnicodeDecodeError):
        return problems + [f"cannot read freeze.json and tasks.json at {short}"]
    if not isinstance(freeze, dict) or freeze.get("referenceRevision") != revision or freeze.get("campaign") != campaign:
        problems.append(f"referenceRevision or campaign differs from freeze.json at {short}")
    pointer = tasks.get("pilotFreeze") if isinstance(tasks, dict) else None
    if (not isinstance(pointer, dict) or pointer.get("campaign") != campaign
            or pointer.get("referenceRevision") != revision):
        problems.append(f"referenceRevision or campaign differs from tasks.json pilotFreeze at {short}")
    return problems


def _working_tree_changes(record: dict, root: Path, *, label: str) -> list[str]:
    changes = []
    try:
        current = bundle_identity(canonical_files(root / SKILL_DIR))
    except (OSError, ValueError):
        current = None
    if record["skill"] != current:
        changes.append("portable skill payload changed" if label == "changed" else "portable skill payload changed since capture")
    for entry in record["components"]:
        name = entry["path"]
        try:
            now = file_identity(root / name, root)
        except (OSError, ValueError):
            changes.append(f"missing component: {name}" if label == "changed" else f"missing since capture: {name}")
            continue
        if now != entry:
            changes.append(f"changed component: {name}" if label == "changed" else f"changed since capture: {name}")
    return changes


def _vsix_problems(recorded: dict | None, path: Path) -> list[str]:
    if recorded is None:
        return ["the record names no VSIX to compare"]
    try:
        actual = vsix_identity(path, built_by_capture=recorded["builtByCapture"])
    except (OSError, ValueError) as exc:
        return [str(exc)]
    if (actual["sha256"], actual["bytes"]) != (recorded["sha256"], recorded["bytes"]):
        return [f"the VSIX bytes differ from the recorded {recorded['file']}"]
    return []


def check(record: object, root: Path = ROOT, vsix: Path | None = None) -> list[str]:
    """Record defects of a version 2 candidate (empty when none). A pilot candidate is proven at
    ``git show <source.commit>:<path>`` and its commit must be an ancestor of HEAD; a development
    snapshot is compared with the working tree. ``vsix`` also compares a VSIX file's bytes. Never
    raises for a malformed record, never changes anything and never claims readiness."""
    problems = structure_problems(record)
    if problems:
        return problems
    root = Path(root).resolve()
    assert isinstance(record, dict)
    if record["kind"] == PILOT_KIND:
        try:
            problems = _prove_pilot(record, root)
        except ValueError as exc:
            problems = [str(exc)]
    else:
        problems = _working_tree_changes(record, root, label="changed")
    if vsix is not None:
        problems += _vsix_problems(record["vsix"], Path(vsix))
    return problems


def drift(record: dict, root: Path = ROOT) -> list[str]:
    """Information only: how the working tree at ``root`` differs from a well-formed record."""
    if structure_problems(record):
        return []
    return _working_tree_changes(record, Path(root).resolve(), label="drift")


def require_pilot_candidate(record: object, campaign: str | None = None) -> None:
    """Raise ValueError unless ``record`` is a well-formed pilot candidate (of ``campaign``).
    Summaries and run preparation call this: a development snapshot cannot identify a pilot."""
    problems = structure_problems(record)
    if problems:
        raise ValueError("; ".join(problems))
    assert isinstance(record, dict)
    if record["kind"] != PILOT_KIND:
        raise ValueError("a development snapshot cannot identify a pilot campaign; capture a pilot candidate with "
                         "python tools/workflow_candidate.py --campaign <campaign> --build-vsix")
    if campaign is not None and record["campaign"] != campaign:
        raise ValueError(f"the candidate belongs to campaign {record['campaign']}, not {campaign}")


# --------------------------------------------------------------------------------------------
# Capture


def snapshot(root: Path = ROOT, vsix: Path | None = None) -> dict:
    """A development snapshot of the working tree (dirty trees allowed; never a pilot candidate)."""
    root = root.resolve()
    components = [file_identity(root / name, root) for name in DEVELOPMENT_COMPONENTS]
    status = git_value(root, "status", "--porcelain")
    return {
        "version": VERSION, "kind": DEVELOPMENT_KIND, "pilotApproved": False,
        "source": {"commit": git_value(root, "rev-parse", "--verify", "HEAD"),
                   "tree": git_value(root, "rev-parse", "--verify", "HEAD^{tree}"),
                   "clean": None if status is None else not status,
                   "capturedAt": er.rfc3339_utc_now()},
        "skill": bundle_identity(canonical_files(root / SKILL_DIR)),
        "components": components,
        "vsix": None if vsix is None else vsix_identity(Path(vsix), built_by_capture=False),
        "remainingGates": DEVELOPMENT_GATES,
        "note": DEVELOPMENT_NOTE,
    }


def _vsix_check_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mlview_vsix_check", ROOT / "scripts" / "vsix_check.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check_frozen(root: Path) -> None:
    """Require `python tools/workflow_eval.py check-frozen` to pass in ``root``."""
    result = subprocess.run([sys.executable, str(root / "tools" / "workflow_eval.py"), "check-frozen"],
                            cwd=root, capture_output=True, check=False)
    if result.returncode:
        output = (result.stdout + result.stderr).decode("utf-8", "replace").strip().splitlines()
        raise CaptureError("check-frozen did not pass (exit status %d)%s; fix the frozen campaign before capturing"
                           % (result.returncode, ": " + " / ".join(output[-3:]) if output else ""))


def package_vsix(root: Path, output: Path) -> None:
    """Build the VSIX from ``root`` with `npm --prefix vscode-extension run package -- --out OUTPUT`
    (vscode:prepublish compiles the bundle from the clean tree)."""
    npm = shutil.which("npm")
    if npm is None:
        raise CaptureError("npm is not on PATH; install Node 20.18.1+ and run npm ci in webview and vscode-extension")
    # npm runs the package script in vscode-extension/, so a relative --out would land there.
    out = Path(output).expanduser().absolute()
    result = subprocess.run([npm, "--prefix", "vscode-extension", "run", "package", "--", "--out", str(out)],
                            cwd=root, check=False)
    if result.returncode:
        raise CaptureError(f"npm run package failed (exit status {result.returncode})")


def _require_clean(root: Path, when: str) -> None:
    status = [line for line in _git(root, "status", "--porcelain", "--untracked-files=normal").splitlines() if line]
    if status:
        raise CaptureError(f"the working tree is not clean {when} ({_preview(status)}); "
                           + ("commit or remove the changes, then capture again" if when == "before the capture" else
                              "packaging rewrote tracked files, so the committed build outputs or notices are stale; "
                              "rebuild, commit and capture again"))


def _read_json(root: Path, rel: str) -> object:
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaptureError(f"cannot read {rel}: {exc}") from None


def _frozen_campaign(root: Path, campaign: str) -> str:
    """Check tasks.json and the committed freeze of ``campaign``; return its referenceRevision."""
    tasks = _read_json(root, TASKS_REL)
    problems = er.check_task_manifest(tasks) if isinstance(tasks, dict) else ["tasks.json must be a JSON object"]
    if problems:
        raise CaptureError(f"{TASKS_REL} is not usable: {'; '.join(problems)}")
    pointer = tasks.get("pilotFreeze")
    if not isinstance(pointer, dict) or pointer.get("campaign") != campaign:
        raise CaptureError(f"{TASKS_REL} has no pilotFreeze for {campaign}; freeze the campaign "
                           f"(python tools/workflow_eval.py freeze --campaign {campaign} --write) and commit it first")
    revision = pointer["referenceRevision"]
    campaign_dir = f"{PILOT_REL}/{campaign}"
    freeze_rel = f"{campaign_dir}/freeze.json"
    tracked = set(_ls_files(root, campaign_dir))
    if freeze_rel not in tracked:
        raise CaptureError(f"{freeze_rel} is not tracked; commit the freeze before capturing")
    freeze = _read_json(root, freeze_rel)
    files = freeze.get("files") if isinstance(freeze, dict) else None
    if (not isinstance(freeze, dict) or freeze.get("format") != FREEZE_FORMAT or freeze.get("campaign") != campaign
            or not isinstance(files, dict) or not files):
        raise CaptureError(f"{freeze_rel} is not a {FREEZE_FORMAT} record of {campaign}")
    if freeze.get("referenceRevision") != revision:
        raise CaptureError(f"{freeze_rel} referenceRevision differs from {TASKS_REL} pilotFreeze")
    for rel, digest in sorted(files.items()):
        path = f"{campaign_dir}/{rel}"
        if path not in tracked:
            raise CaptureError(f"{path} (listed in freeze.json) is not tracked; commit the whole campaign directory")
        try:
            actual = er.sha256_bytes(er.confined_file(root, path).read_bytes())
        except (OSError, ValueError) as exc:
            raise CaptureError(f"{path} cannot be read: {exc}") from None
        if actual != digest:
            raise CaptureError(f"{path} does not match its freeze.json hash")
    if revision != "sha256:" + str(files.get("reference-set.json")):
        raise CaptureError("referenceRevision is not sha256 of reference-set.json in freeze.json")
    return revision


def _check_built_vsix(root: Path, commit: str, vsix: Path, version: str) -> None:
    problems, _measured, *_rest = _vsix_check_module().check(root, vsix)
    if problems:
        raise CaptureError("the built VSIX failed vsix_check: " + "; ".join(problems))
    media = sorted(path for path in _ls_files(root, MEDIA_DIR + "/") if path.startswith(MEDIA_DIR + "/"))
    with zipfile.ZipFile(vsix) as archive:
        packaged = sorted(name for name in archive.namelist() if name.startswith("extension/media/")
                          and not name.endswith("/"))
        expected = ["extension/media/" + path[len(MEDIA_DIR) + 1:] for path in media]
        if packaged != expected:
            raise CaptureError(f"the VSIX media differ from the committed {MEDIA_DIR}/ "
                               f"(packaged: {_preview(packaged)}; committed: {_preview(expected)})")
        for name, path in zip(packaged, media):
            if archive.read(name) != er.git_show(root, commit, path):
                raise CaptureError(f"the VSIX {name} differs from the committed {path}")
        packaged_version = json.loads(archive.read("extension/package.json")).get("version")
    if packaged_version != version:
        raise CaptureError(f"the VSIX version {packaged_version} differs from {EXTENSION_PACKAGE} version {version}")


def _check_skill_payload(root: Path) -> dict[str, bytes]:
    payload = canonical_files(root / SKILL_DIR)
    tracked = _skill_paths(_ls_files(root, SKILL_DIR + "/"))
    if sorted(payload) != tracked:
        extra = sorted(set(payload) - set(tracked))
        missing = sorted(set(tracked) - set(payload))
        detail = "; ".join(part for part in (f"not tracked: {_preview(extra)}" if extra else "",
                                             f"missing: {_preview(missing)}" if missing else "") if part)
        raise CaptureError(f"the skill payload differs from git ls-files {SKILL_DIR} ({detail}); remove local files "
                           "such as .DS_Store from the skill directory")
    return payload


def capture_pilot(campaign: str, pilot_dir: Path | None, root: Path = ROOT, *,
                  package: Callable[[Path, Path], None] | None = None,
                  check_frozen: Callable[[Path], None] | None = None) -> tuple[Path, dict]:
    """Capture the pilot candidate of ``campaign``; returns (candidate.json path, record). The
    first failed precondition raises CaptureError and nothing is recorded."""
    root = Path(root).resolve()
    if not isinstance(campaign, str) or not er.NAME_RE.fullmatch(campaign):
        raise CaptureError(f"not a campaign name: {campaign!r} (use a lowercase name such as pilot-01)")
    if pilot_dir is None:
        raise CaptureError("MLVIEW_PILOT_DIR is not set; export MLVIEW_PILOT_DIR=~/mlview-pilot (outside every Git "
                           "work tree) or pass --pilot-dir")
    pilot_dir = Path(pilot_dir).expanduser().absolute()
    reasons = er.outside_repositories(pilot_dir, root)
    if reasons:
        raise CaptureError("MLVIEW_PILOT_DIR cannot hold pilot evidence: " + "; ".join(reasons)
                           + ". Use for example export MLVIEW_PILOT_DIR=~/mlview-pilot")
    _require_clean(root, "before the capture")
    revision = _frozen_campaign(root, campaign)
    target = root / candidate_path(campaign)
    if os.path.lexists(target):
        raise CaptureError(f"{candidate_path(campaign)} already exists; a campaign has one candidate and candidate "
                           "files are never overwritten")
    campaign_dir = root / PILOT_REL / campaign
    leftovers = sorted(path.name for path in campaign_dir.glob("stage*summary*"))
    if os.path.lexists(campaign_dir / "invalidation.md"):
        leftovers.append("invalidation.md")
    if leftovers:
        raise CaptureError(f"{PILOT_REL}/{campaign} already holds {', '.join(leftovers)}; summaries and invalidations "
                           "follow a capture, so this campaign cannot be captured. Freeze a new campaign instead")
    (check_frozen or run_check_frozen)(root)
    package_json = _read_json(root, EXTENSION_PACKAGE)
    version = package_json.get("version") if isinstance(package_json, dict) else None
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise CaptureError(f"{EXTENSION_PACKAGE} has no valid version")
    vsix = pilot_dir / f"mlview-{version}.vsix"
    if os.path.lexists(vsix):
        raise CaptureError(f"{vsix.name} already exists in MLVIEW_PILOT_DIR; the capture builds its own VSIX and never "
                           "reuses or overwrites one. Move it aside or use a fresh MLVIEW_PILOT_DIR")
    commit = _git(root, "rev-parse", "--verify", "HEAD").strip()
    tree = _git(root, "rev-parse", "--verify", "HEAD^{tree}").strip()
    pilot_dir.mkdir(parents=True, exist_ok=True)
    try:
        (package or package_vsix)(root, vsix)
        if not vsix.is_file():
            raise CaptureError(f"packaging did not produce {vsix.name}")
        _require_clean(root, "after packaging")
        _check_built_vsix(root, commit, vsix, version)
        payload = _check_skill_payload(root)
        record = {
            "version": VERSION, "kind": PILOT_KIND, "campaign": campaign, "pilotApproved": False,
            "source": {"commit": commit, "tree": tree, "clean": True, "capturedAt": er.rfc3339_utc_now()},
            "skill": bundle_identity(payload),
            "components": [file_identity(root / name, root) for name in pilot_components(campaign)],
            "vsix": vsix_identity(vsix, built_by_capture=True),
            "referenceRevision": revision,
            "remainingGates": PILOT_GATES,
            "note": PILOT_NOTE,
        }
        problems = check(record, root)
        if problems:
            raise CaptureError("the captured record does not verify: " + "; ".join(problems))
        er.write_exclusive(target, er.canonical_json(record))
    except BaseException:
        try:
            vsix.unlink()  # only the VSIX this capture built; a pre-existing one was refused above
        except OSError:
            pass
        raise
    return target, record


# --------------------------------------------------------------------------------------------
# Command line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campaign", help="capture the pilot candidate of this frozen campaign (needs --build-vsix)")
    parser.add_argument("--build-vsix", action="store_true",
                        help="build the VSIX into the pilot directory as part of the pilot capture")
    parser.add_argument("--pilot-dir", type=Path, help="the pilot evidence directory (default: $MLVIEW_PILOT_DIR)")
    parser.add_argument("--check", type=Path, help="check an existing candidate record")
    parser.add_argument("--vsix", type=Path,
                        help="with --check: compare this VSIX; with a development snapshot: record this VSIX")
    parser.add_argument("--output", type=Path,
                        help="create a development snapshot file; existing files are never overwritten")
    args = parser.parse_args(argv)
    if args.check:
        if args.output or args.campaign or args.build_vsix:
            parser.error("--check cannot be combined with --output, --campaign or --build-vsix")
        try:
            raw = args.check.read_bytes()
            record = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            parser.error(f"cannot read the candidate record: {exc}")
        problems = check(record, ROOT, args.vsix)
        kind = record.get("kind") if isinstance(record, dict) else None
        info = drift(record) if not problems and kind == PILOT_KIND else []
        print(json.dumps({"ok": not problems, "kind": kind, "candidateSha256": er.sha256_bytes(raw),
                          "problems": problems, "drift": info, "pilotApproved": False}, indent=2))
        return int(bool(problems))
    if args.campaign or args.build_vsix:
        if not (args.campaign and args.build_vsix):
            parser.error("the pilot capture needs both --campaign and --build-vsix (it builds its own VSIX)")
        if args.output or args.vsix:
            parser.error("the pilot capture builds its own VSIX and writes candidate.json; --output and --vsix are "
                         "for development snapshots")
        pilot_dir = args.pilot_dir or (Path(os.environ["MLVIEW_PILOT_DIR"]) if os.environ.get("MLVIEW_PILOT_DIR")
                                       else None)
        try:
            target, record = capture_pilot(args.campaign, pilot_dir)
        except (OSError, ValueError) as exc:
            print(f"workflow-candidate: {exc}", file=sys.stderr)
            return 1
        rel = target.relative_to(ROOT).as_posix()
        print(f"Wrote {rel} (candidateSha256 {er.sha256_file(target)}).")
        print(f"VSIX: {record['vsix']['file']} in MLVIEW_PILOT_DIR (install this file for every run).")
        print(f"Next: commit {rel}. This record identifies bytes; it is not an approval.")
        return 0
    if args.pilot_dir:
        parser.error("--pilot-dir applies only to the pilot capture")
    try:
        value = snapshot(vsix=args.vsix)
        serialized = er.canonical_json(value)
        if args.output:
            er.write_exclusive(args.output, serialized)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    sys.stdout.write(serialized.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
