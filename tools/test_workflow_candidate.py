"""Tests for candidate snapshot v2 (Campaign 2 section 3.2, CRIT-9).

The pilot capture runs against a synthetic Git checkout with a synthetic frozen campaign; the real
`npm run package` and check-frozen are stubbed (the integration dry run exercises the real
packager). Nothing here reviews, approves or scores anything.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("workflow_candidate.py")
SPEC = importlib.util.spec_from_file_location("workflow_candidate", SCRIPT)
assert SPEC and SPEC.loader
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
CAMPAIGN = "pilot-01"
MACHINE_PATHS = ("/Users/", "/home/", "/private/", "C:\\")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout.decode("utf-8")


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Synthetic Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "synthetic@example.invalid")


def world_files(version: str = "0.3.0") -> dict[str, bytes]:
    reference_set = dumps({"format": "mlview-reference-set/1", "campaign": CAMPAIGN, "note": "synthetic"})
    policy = dumps({"format": "mlview-run-policy/1", "campaign": CAMPAIGN, "note": "synthetic"})
    revision = "sha256:" + sha(reference_set)
    freeze = dumps({"format": "mlview-freeze/1", "campaign": CAMPAIGN, "frozenAt": "2026-10-03T10:00:00Z",
                    "referenceRevision": revision,
                    "files": {"reference-set.json": sha(reference_set), "policy.json": sha(policy)},
                    "note": "synthetic freeze for tests"})
    targets = {"structurallyValid": 1.0, "exactAnchors": 1.0, "supportedClaimPrecision": 0.95,
               "essentialFactRecall": 0.85, "knownUnresolvedQualified": 1.0, "highSeverityFalseAccusations": 0}
    tasks = {"version": 1, "hosts": ["codex"], "repetitions": 3, "pilotTargets": targets,
             "tasks": [{"id": "pilot-demo", "split": "heldout", "title": "synthetic", "repository": "demo",
                        "url": "https://example.invalid/demo", "commit": "a" * 40, "entrypoints": ["train.py"],
                        "prompt": "Explain the synthetic training scenario.", "referenceStatus": "frozen"}],
             "pilotFreeze": {"campaign": CAMPAIGN, "freeze": f"pilot/{CAMPAIGN}/freeze.json",
                             "referenceRevision": revision}}
    package = {"name": "mlview", "version": version,
               "contributes": {"commands": [{"command": "mlview.openGeneratedDiagram"}]}}
    return {
        ".gitignore": b"vscode-extension/out/\n*.vsix\n*.log\n",
        "contracts/workflow.schema.json": b'{"title": "synthetic schema"}\n',
        "evals/workflow/tasks.json": dumps(tasks),
        "evals/workflow/repositories.json": b'{"repos": []}\n',
        f"evals/workflow/pilot/{CAMPAIGN}/reference-set.json": reference_set,
        f"evals/workflow/pilot/{CAMPAIGN}/policy.json": policy,
        f"evals/workflow/pilot/{CAMPAIGN}/freeze.json": freeze,
        "webview/dist/mlview.js": b"renderViewer();\n",
        "webview/dist/mlview.css": b"body { margin: 0; }\n",
        "vscode-extension/package.json": dumps(package),
        "vscode-extension/media/mlview.js": b"renderViewer();\n",
        "vscode-extension/media/mlview.css": b"body { margin: 0; }\n",
        "vscode-extension/media/README.md": b"Synthetic media.\n",
        "LICENSE": b"MIT License (synthetic)\n",
        "THIRD_PARTY_NOTICES.md": b"Synthetic notices.\n",
        "skills/mlview/SKILL.md": b"# Synthetic skill\n",
        "skills/mlview/LICENSE": b"MIT License (synthetic)\n",
        "skills/mlview/scripts/artifact.py": b"print('synthetic helper')\n",
        "skills/mlview/tests/test_helper.py": b"def test_nothing():\n    pass\n",
    }


def make_world(tmp_path: Path, **overrides: bytes | None) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    git(root, "init", "--quiet")
    files = world_files()
    files.update(overrides)
    for rel, data in files.items():
        if data is None:
            continue
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "synthetic candidate world")
    return root


def stub_package(root: Path, output: Path, *, media_extra: dict[str, bytes] | None = None,
                 version: str | None = None) -> None:
    """What `npm run package` does, in miniature: compile the ignored bundle, then zip the payload."""
    bundle = root / "vscode-extension/out/extension.js"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_bytes(b"activate();\n")
    package = json.loads((root / "vscode-extension/package.json").read_text(encoding="utf-8"))
    if version is not None:
        package["version"] = version
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("extension/package.json", json.dumps(package))
        archive.writestr("extension/out/extension.js", bundle.read_bytes())
        for media in sorted((root / "vscode-extension/media").iterdir()):
            archive.writestr(f"extension/media/{media.name}", media.read_bytes())
        for name, data in (media_extra or {}).items():
            archive.writestr(f"extension/media/{name}", data)
        archive.writestr("extension/LICENSE.txt", (root / "LICENSE").read_bytes())
        archive.writestr("extension/THIRD_PARTY_NOTICES.md", (root / "THIRD_PARTY_NOTICES.md").read_bytes())


def never_package(root: Path, output: Path) -> None:
    pytest.fail("the capture must refuse before packaging")


def capture(root: Path, pilot: Path, package=stub_package, check_frozen=lambda root: None):
    return candidate.capture_pilot(CAMPAIGN, pilot, root, package=package, check_frozen=check_frozen)


# --------------------------------------------------------------------------------------------
# Pilot capture


@needs_git
def test_pilot_capture_pins_the_v2_component_set_and_never_claims_approval(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    target, record = capture(root, tmp_path / "pilot")
    assert target == root / f"evals/workflow/pilot/{CAMPAIGN}/candidate.json"
    assert target.read_bytes() == candidate.er.canonical_json(record)
    assert record["version"] == 2 and record["kind"] == "pilot-candidate" and record["campaign"] == CAMPAIGN
    assert record["pilotApproved"] is False
    assert [entry["path"] for entry in record["components"]] == [
        "contracts/workflow.schema.json", "evals/workflow/tasks.json", "evals/workflow/repositories.json",
        "webview/dist/mlview.js", "webview/dist/mlview.css", "vscode-extension/package.json",
        f"evals/workflow/pilot/{CAMPAIGN}/freeze.json"]
    assert not any(entry["path"].startswith("vscode-extension/out/") for entry in record["components"])
    head = git(root, "rev-parse", "HEAD").strip()
    assert record["source"]["commit"] == head and record["source"]["clean"] is True
    assert record["source"]["tree"] == git(root, "rev-parse", "HEAD^{tree}").strip()
    assert [entry["path"] for entry in record["skill"]["files"]] == ["LICENSE", "SKILL.md", "scripts/artifact.py"]
    vsix = record["vsix"]
    assert vsix["file"] == "mlview-0.3.0.vsix" and vsix["version"] == "0.3.0" and vsix["builtByCapture"] is True
    assert [entry["path"] for entry in vsix["entries"]] == list(candidate.VSIX_ENTRIES)
    assert vsix["sha256"] == sha((tmp_path / "pilot/mlview-0.3.0.vsix").read_bytes())
    tasks = json.loads((root / "evals/workflow/tasks.json").read_text(encoding="utf-8"))
    assert record["referenceRevision"] == tasks["pilotFreeze"]["referenceRevision"]
    assert record["remainingGates"] == candidate.PILOT_GATES
    assert "does not authenticate" in record["note"] and "pilot approval" in record["note"]
    text = target.read_text(encoding="utf-8")
    assert str(tmp_path) not in text and not any(marker in text for marker in MACHINE_PATHS)
    assert candidate.check(record, root) == []
    candidate.require_pilot_candidate(record, CAMPAIGN)
    with pytest.raises(ValueError, match="belongs to campaign pilot-01"):
        candidate.require_pilot_candidate(record, "pilot-02")


@needs_git
@pytest.mark.parametrize("change", ["untracked", "modified"])
def test_dirty_tree_is_refused_before_anything_is_built(tmp_path: Path, change: str) -> None:
    root = make_world(tmp_path)
    if change == "untracked":
        (root / "notes.txt").write_text("local", encoding="utf-8")
    else:
        (root / "webview/dist/mlview.js").write_bytes(b"edited();\n")
    with pytest.raises(candidate.CaptureError, match="the working tree is not clean before the capture"):
        capture(root, tmp_path / "pilot", package=never_package)
    assert not (root / f"evals/workflow/pilot/{CAMPAIGN}/candidate.json").exists()
    assert not (tmp_path / "pilot").exists()


@needs_git
def test_pre_existing_vsix_is_refused_and_left_untouched(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "mlview-0.3.0.vsix").write_bytes(b"an older build")
    with pytest.raises(candidate.CaptureError, match="mlview-0.3.0.vsix already exists in MLVIEW_PILOT_DIR"):
        capture(root, pilot, package=never_package)
    assert (pilot / "mlview-0.3.0.vsix").read_bytes() == b"an older build"


@needs_git
def test_packaging_that_rewrites_a_tracked_file_is_refused_and_its_vsix_removed(tmp_path: Path) -> None:
    root = make_world(tmp_path)

    def rewriting(root: Path, output: Path) -> None:
        (root / "THIRD_PARTY_NOTICES.md").write_bytes(b"Regenerated notices.\n")
        stub_package(root, output)

    with pytest.raises(candidate.CaptureError, match="not clean after packaging"):
        capture(root, tmp_path / "pilot", package=rewriting)
    assert list((tmp_path / "pilot").iterdir()) == []
    assert not (root / f"evals/workflow/pilot/{CAMPAIGN}/candidate.json").exists()


@needs_git
def test_vsix_media_must_equal_the_committed_media(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    with pytest.raises(candidate.CaptureError, match="the VSIX media differ from the committed vscode-extension/media/"):
        capture(root, tmp_path / "pilot", package=lambda r, o: stub_package(r, o, media_extra={"extra.png": b"x"}))

    def stale_readme(root: Path, output: Path) -> None:
        stub_package(root, output)
        with zipfile.ZipFile(output) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["extension/media/README.md"] = b"stale media\n"
        with zipfile.ZipFile(output, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)

    with pytest.raises(candidate.CaptureError, match="extension/media/README.md differs from the committed"):
        capture(root, tmp_path / "pilot", package=stale_readme)


@needs_git
def test_vsix_version_must_equal_the_extension_package_version(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    with pytest.raises(candidate.CaptureError, match="the VSIX version 0.2.9 differs from vscode-extension/package.json "
                                                     "version 0.3.0"):
        capture(root, tmp_path / "pilot", package=lambda r, o: stub_package(r, o, version="0.2.9"))


@needs_git
def test_vsix_check_problems_abort_the_capture(tmp_path: Path) -> None:
    root = make_world(tmp_path)

    def stale_bundle(root: Path, output: Path) -> None:
        stub_package(root, output)
        (root / "vscode-extension/out/extension.js").write_bytes(b"rebuilt later();\n")

    with pytest.raises(candidate.CaptureError, match="failed vsix_check: stale packaged payload: out/extension.js"):
        capture(root, tmp_path / "pilot", package=stale_bundle)


@needs_git
def test_skill_payload_is_cross_checked_against_git_ls_files(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    (root / "skills/mlview/debug.log").write_bytes(b"ignored by git, but it would be packaged\n")
    assert git(root, "status", "--porcelain") == ""
    with pytest.raises(candidate.CaptureError, match=r"differs from git ls-files skills/mlview \(not tracked: "
                                                     r"debug.log\)"):
        capture(root, tmp_path / "pilot")
    assert list((tmp_path / "pilot").iterdir()) == []


@needs_git
def test_capture_needs_the_committed_freeze_of_the_campaign(tmp_path: Path) -> None:
    files = world_files()
    tasks = json.loads(files["evals/workflow/tasks.json"])
    del tasks["pilotFreeze"]
    tasks["tasks"][0]["referenceStatus"] = "needs-human-review"
    root = make_world(tmp_path, **{"evals/workflow/tasks.json": dumps(tasks)})
    with pytest.raises(candidate.CaptureError, match="has no pilotFreeze for pilot-01; freeze the campaign"):
        capture(root, tmp_path / "pilot", package=never_package)
    other = make_world(tmp_path / "b", **{f"evals/workflow/pilot/{CAMPAIGN}/policy.json": b'{"edited": true}\n'})
    with pytest.raises(candidate.CaptureError, match="policy.json does not match its freeze.json hash"):
        capture(other, tmp_path / "pilot", package=never_package)


@needs_git
def test_check_frozen_must_pass_and_an_existing_candidate_is_never_replaced(tmp_path: Path) -> None:
    root = make_world(tmp_path)

    def failing(root: Path) -> None:
        raise candidate.CaptureError("check-frozen did not pass (exit status 1)")

    with pytest.raises(candidate.CaptureError, match="check-frozen did not pass"):
        capture(root, tmp_path / "pilot", package=never_package, check_frozen=failing)
    capture(root, tmp_path / "pilot")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "record the candidate")
    with pytest.raises(candidate.CaptureError, match="candidate.json already exists"):
        capture(root, tmp_path / "pilot2", package=never_package)


@needs_git
def test_a_removed_candidate_is_never_captured_again_and_a_shallow_clone_cannot_tell(tmp_path: Path) -> None:
    """A committed candidate that was deleted blocks a second capture, also where check-frozen cannot
    see the history: capture refuses a shallow clone itself (DISTCI3-2)."""
    root = make_world(tmp_path)
    capture(root, tmp_path / "pilot")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "record the candidate")
    git(root, "rm", "--quiet", f"evals/workflow/pilot/{CAMPAIGN}/candidate.json")
    git(root, "commit", "--quiet", "-m", "synthetic deletion")
    with pytest.raises(candidate.CaptureError, match="candidate.json was committed in [0-9a-f]{12}; a campaign has one "
                                                     "candidate and a removed candidate is never captured again"):
        capture(root, tmp_path / "pilot2", package=never_package)
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", root.resolve().as_uri(), str(clone)], check=True,
                   capture_output=True)
    with pytest.raises(candidate.CaptureError, match="cannot tell from the Git history whether pilot-01 was captured "
                                                     "before: this is a shallow clone"):
        capture(clone, tmp_path / "pilot3", package=never_package)


@needs_git
@pytest.mark.parametrize("name", ["stage1-summary.json", "stage2-summary.md", "invalidation.md"])
def test_a_campaign_with_a_summary_or_invalidation_is_never_captured(tmp_path: Path, name: str) -> None:
    root = make_world(tmp_path, **{f"evals/workflow/pilot/{CAMPAIGN}/{name}": b"synthetic leftover\n"})
    with pytest.raises(candidate.CaptureError, match=f"already holds {name}; summaries and invalidations follow a "
                                                     "capture"):
        capture(root, tmp_path / "pilot", package=never_package)
    assert not (root / f"evals/workflow/pilot/{CAMPAIGN}/candidate.json").exists()


@needs_git
def test_a_relative_pilot_directory_is_made_absolute_before_packaging(tmp_path: Path, monkeypatch) -> None:
    root = make_world(tmp_path)
    outputs: list[Path] = []

    def recording(root: Path, output: Path) -> None:
        outputs.append(output)
        stub_package(root, output)

    monkeypatch.chdir(tmp_path)
    target, record = capture(root, Path("relative-pilot"), package=recording)
    assert outputs == [Path.cwd() / "relative-pilot" / "mlview-0.3.0.vsix"] and outputs[0].is_absolute()
    assert (tmp_path / "relative-pilot" / "mlview-0.3.0.vsix").is_file() and target.is_file()
    assert record["vsix"]["file"] == "mlview-0.3.0.vsix"
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(candidate.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(candidate.subprocess, "run", lambda args, **kwargs: calls.append(args) or Done())
    candidate.package_vsix(root, Path("relative.vsix"))
    assert Path(calls[0][-1]).is_absolute() and calls[0][-2] == "--out"
    assert Path(calls[0][-1]).name == "relative.vsix"


@needs_git
def test_pilot_directory_is_required_and_must_be_outside_every_work_tree(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    with pytest.raises(candidate.CaptureError, match="MLVIEW_PILOT_DIR is not set; export MLVIEW_PILOT_DIR"):
        capture(root, None, package=never_package)
    with pytest.raises(candidate.CaptureError, match="MLVIEW_PILOT_DIR cannot hold pilot evidence"):
        capture(root, root / "pilot", package=never_package)


@needs_git
def test_default_check_frozen_runs_the_dispatcher_and_fails_closed(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    with pytest.raises(candidate.CaptureError, match="check-frozen did not pass"):
        candidate.run_check_frozen(root)  # the synthetic world has no tools/workflow_eval.py


# --------------------------------------------------------------------------------------------
# Check


@needs_git
def test_check_proves_the_record_at_its_commit_and_reports_head_drift_as_information(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    _, record = capture(root, tmp_path / "pilot")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "record the candidate")
    (root / "webview/dist/mlview.js").write_bytes(b"renderViewerV2();\n")
    git(root, "commit", "--quiet", "-am", "later viewer change")
    assert candidate.check(record, root) == []
    assert candidate.drift(record, root) == ["changed since capture: webview/dist/mlview.js"]
    forged = json.loads(json.dumps(record))
    forged["components"][3]["sha256"] = "0" * 64
    assert candidate.check(forged, root) == [
        f"component webview/dist/mlview.js differs from its bytes at {record['source']['commit'][:12]}"]
    forged = json.loads(json.dumps(record))
    forged["skill"]["sha256"] = "0" * 64
    assert candidate.check(forged, root) == [
        f"the skill identity differs from the skill bytes at {record['source']['commit'][:12]}"]
    forged = json.loads(json.dumps(record))
    forged["referenceRevision"] = "sha256:" + "1" * 64
    assert "differs from freeze.json" in candidate.check(forged, root)[0]


@needs_git
def test_check_requires_the_commit_to_exist_and_be_an_ancestor_of_head(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    _, record = capture(root, tmp_path / "pilot")
    missing = json.loads(json.dumps(record))
    missing["source"]["commit"] = "b" * 40
    assert candidate.check(missing, root) == [f"source.commit {'b' * 40} is not in this clone"]
    base = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "--quiet", "--orphan", "elsewhere")
    git(root, "commit", "--quiet", "-m", "unrelated history")
    problems = candidate.check(record, root)
    assert problems == [f"source.commit {base[:12]} is not an ancestor of HEAD; check out the candidate commit "
                        "or a descendant of it"]


@needs_git
def test_check_compares_a_supplied_vsix(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    _, record = capture(root, tmp_path / "pilot")
    vsix = tmp_path / "pilot/mlview-0.3.0.vsix"
    assert candidate.check(record, root, vsix) == []
    with zipfile.ZipFile(vsix, "a") as archive:
        archive.writestr("extension/extra.txt", "tampered")
    assert candidate.check(record, root, vsix) == ["the VSIX bytes differ from the recorded mlview-0.3.0.vsix"]


@needs_git
def test_check_rejects_forged_approval_gates_and_fields(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    _, record = capture(root, tmp_path / "pilot")
    cases = [
        (("pilotApproved",), True, "pilotApproved must be false"),
        (("remainingGates",), [], "cannot waive a gate"),
        (("note",), "Human approved", "cannot waive a gate"),
        (("source", "clean"), False, "captured on a clean tree"),
        (("vsix", "builtByCapture"), False, "must be built by the capture"),
        (("vsix", "file"), "/tmp/mlview-0.3.0.vsix", "never a path"),
        (("campaign",), "Pilot 01", "campaign must be a lowercase campaign name"),
        (("referenceRevision",), "sha256:x", "referenceRevision must be"),
    ]
    for keys, value, message in cases:
        forged = json.loads(json.dumps(record))
        target = forged
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
        problems = candidate.check(forged, root)
        assert problems and any(message in problem for problem in problems), (keys, problems)
    forged = dict(record, approvedBy="someone")
    assert candidate.check(forged, root) == ["candidate record has unexpected or missing fields"]
    forged = json.loads(json.dumps(record))
    forged["components"].pop()
    assert "candidate requires exactly the component identities" in candidate.check(forged, root)[0]
    assert candidate.check("not a record", root) == ["candidate record must be a JSON object"]


def test_version_1_byte_snapshots_are_no_longer_read() -> None:
    legacy = {"version": 1, "kind": "candidate-byte-snapshot", "pilotApproved": False}
    problems = candidate.check(legacy)
    assert problems and "version 1" in problems[0] and "capture a new one" in problems[0]
    with pytest.raises(ValueError, match="version 1"):
        candidate.require_pilot_candidate(legacy)


# --------------------------------------------------------------------------------------------
# Development snapshot


def dev_fixture(root: Path) -> None:
    for rel, data in world_files().items():
        if rel.startswith(("contracts/", "evals/workflow/tasks.json", "evals/workflow/repositories.json",
                           "webview/dist/", "vscode-extension/package.json", "skills/")):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)


def test_development_snapshot_needs_no_build_output_and_is_rejected_as_a_pilot_candidate(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    dev_fixture(root)
    record = candidate.snapshot(root)
    assert record["kind"] == "development-snapshot" and record["pilotApproved"] is False and record["vsix"] is None
    assert [entry["path"] for entry in record["components"]] == list(candidate.DEVELOPMENT_COMPONENTS)
    assert "evals/workflow/repositories.json" in candidate.DEVELOPMENT_COMPONENTS
    assert record["source"] == {"commit": None, "tree": None, "clean": None,
                                "capturedAt": record["source"]["capturedAt"]}
    assert candidate.check(record, root) == []
    with pytest.raises(ValueError, match="a development snapshot cannot identify a pilot campaign"):
        candidate.require_pilot_candidate(record)
    (root / "webview/dist/mlview.js").write_text("changed", encoding="utf-8")
    (root / "skills/mlview/references").mkdir()
    (root / "skills/mlview/references/extra.md").write_text("new", encoding="utf-8")
    assert candidate.check(record, root) == ["portable skill payload changed", "changed component: webview/dist/mlview.js"]


@needs_git
def test_development_snapshot_allows_a_dirty_tree_and_records_a_vsix_by_name_only(tmp_path: Path) -> None:
    root = make_world(tmp_path)
    (root / "notes.txt").write_text("dirty", encoding="utf-8")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    stub_package(root, outside / "mlview-0.3.0.vsix")
    record = candidate.snapshot(root, outside / "mlview-0.3.0.vsix")
    assert record["source"]["clean"] is False and record["source"]["commit"] == git(root, "rev-parse", "HEAD").strip()
    assert record["vsix"]["file"] == "mlview-0.3.0.vsix" and record["vsix"]["builtByCapture"] is False
    assert str(tmp_path) not in json.dumps(record)
    assert candidate.check(record, root, outside / "mlview-0.3.0.vsix") == []
    (outside / "not-vsix.zip").write_bytes(b"zip")
    with pytest.raises(ValueError, match=r"regular \*\.vsix file"):
        candidate.snapshot(root, outside / "not-vsix.zip")


def test_development_snapshot_rejects_symlinked_components_without_absolute_diagnostics(tmp_path: Path) -> None:
    root = (tmp_path / "root").resolve()
    root.mkdir()
    dev_fixture(root)
    real = root / "real-dist"
    real.mkdir()
    (real / "mlview.js").write_text("alias", encoding="utf-8")
    dist = root / "webview/dist"
    shutil.rmtree(dist)
    try:
        dist.symlink_to(real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ValueError, match="regular non-symlink") as caught:
        candidate.snapshot(root)
    assert str(root) not in str(caught.value)
    target = tmp_path / "private.vsix"
    target.write_bytes(b"private")
    (tmp_path / "linked.vsix").symlink_to(target)
    with pytest.raises(ValueError, match="not a symbolic link") as linked:
        candidate.vsix_identity(tmp_path / "linked.vsix", built_by_capture=False)
    assert str(tmp_path) not in str(linked.value)


def test_cli_modes(tmp_path: Path, capsys) -> None:
    output = tmp_path / "snapshot.json"
    assert candidate.main(["--output", str(output)]) == 0
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["kind"] == "development-snapshot"
    assert output.read_bytes() == candidate.er.canonical_json(record)
    with pytest.raises(SystemExit):
        candidate.main(["--output", str(output)])  # never overwritten
    capsys.readouterr()
    assert candidate.main(["--check", str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["kind"] == "development-snapshot" and report["pilotApproved"] is False
    assert report["candidateSha256"] == sha(output.read_bytes())
    for argv in (["--campaign", CAMPAIGN], ["--build-vsix"], ["--campaign", CAMPAIGN, "--build-vsix", "--vsix", "x.vsix"],
                 ["--campaign", CAMPAIGN, "--build-vsix", "--output", "x.json"], ["--check", str(output), "--output", "y"],
                 ["--pilot-dir", str(tmp_path)]):
        with pytest.raises(SystemExit) as exit_info:
            candidate.main(argv)
        assert exit_info.value.code == 2, argv


def test_cli_capture_without_a_pilot_directory_fails_with_the_remedy(monkeypatch, capsys) -> None:
    monkeypatch.delenv("MLVIEW_PILOT_DIR", raising=False)
    assert candidate.main(["--campaign", CAMPAIGN, "--build-vsix"]) == 1
    assert "MLVIEW_PILOT_DIR is not set; export MLVIEW_PILOT_DIR=~/mlview-pilot" in capsys.readouterr().err
