"""Regression checks for incomplete, stale or legacy-bearing distributions."""
import importlib.util
import json
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("vsix_check", Path(__file__).with_name("vsix_check.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def package(tmp_path, missing=None, extra=None, commands=None, contributions=None):
    path = tmp_path / "test.vsix"
    with zipfile.ZipFile(path, "w") as archive:
        for name in module.REQUIRED - {missing}:
            value = b"asset"
            if name.endswith("package.json"):
                value = json.dumps({"contributes": {**(contributions or {}), "commands": [
                    {"command": command} for command in (commands or ["mlview.openGeneratedDiagram"])
                ]}}).encode()
            archive.writestr(name, value)
        if extra:
            archive.writestr(extra, "legacy")
    return path


def test_native_package_passes(tmp_path):
    result = module.check(tmp_path, package(tmp_path), payload_only=True)
    assert not result.problems
    assert result.skipped == [f"SKIP: bundle freshness not compared (--payload-only): {label}"
                              for _, _, _, label in module.FRESHNESS]


def write_sources(root, **overrides):
    for _, relative, _, label in module.FRESHNESS:
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(overrides.get(label, b"asset"))


def test_current_sources_pass_with_every_comparison_made(tmp_path):
    write_sources(tmp_path)
    result = module.check(tmp_path, package(tmp_path))
    assert result.problems == [] and result.skipped == []


def test_missing_working_tree_source_is_a_problem_not_a_silent_skip(tmp_path):
    write_sources(tmp_path)
    (tmp_path / "vscode-extension/out/extension.js").unlink()
    assert module.check(tmp_path, package(tmp_path)).problems == [
        "cannot compare out/extension.js: vscode-extension/out/extension.js is missing "
        "(build first, or pass --payload-only)"]


def test_payload_only_never_reports_stale_bundles(tmp_path):
    write_sources(tmp_path, **{"out/extension.js": b"newer bundle"})
    assert module.check(tmp_path, package(tmp_path)).problems == ["stale packaged payload: out/extension.js"]
    assert module.check(tmp_path, package(tmp_path), payload_only=True).problems == []


def test_missing_renderer_fails(tmp_path):
    assert any("missing required" in p for p in module.check(tmp_path, package(tmp_path, missing="extension/media/mlview.js"))[0])


def test_legacy_runtime_fails(tmp_path):
    assert any("legacy payload" in p for p in module.check(tmp_path, package(tmp_path, extra="extension/core/mlview/cli.py"))[0])


def test_legacy_command_fails(tmp_path):
    assert any("commands" in p for p in module.check(tmp_path, package(tmp_path, commands=["mlview.visualize"]))[0])


def test_retired_show_output_command_fails(tmp_path):
    vsix = package(tmp_path, commands=["mlview.openGeneratedDiagram", "mlview.showOutput"])
    assert any("commands" in p for p in module.check(tmp_path, vsix)[0])


def test_stale_renderer_fails(tmp_path):
    write_sources(tmp_path, **{"media/mlview.js": b"new renderer"})
    assert module.check(tmp_path, package(tmp_path))[0] == ["stale packaged payload: media/mlview.js"]


def test_stale_notice_fails(tmp_path):
    write_sources(tmp_path, LICENSE=b"new license")
    assert module.check(tmp_path, package(tmp_path))[0] == ["stale packaged notice: LICENSE"]


def test_stale_packaged_chat_participant_fails(tmp_path):
    vsix = package(tmp_path, contributions={"chatParticipants": [{"id": "mlview", "name": "mlview"}]})
    assert any("language tools" in p for p in module.check(tmp_path, vsix)[0])
