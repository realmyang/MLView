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
    assert not module.check(tmp_path, package(tmp_path))[0]


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
    source = tmp_path / "vscode-extension/media/mlview.js"
    source.parent.mkdir(parents=True)
    source.write_text("new renderer")
    assert any("stale packaged" in p for p in module.check(tmp_path, package(tmp_path))[0])


def test_stale_packaged_chat_participant_fails(tmp_path):
    vsix = package(tmp_path, contributions={"chatParticipants": [{"id": "mlview", "name": "mlview"}]})
    assert any("language tools" in p for p in module.check(tmp_path, vsix)[0])
