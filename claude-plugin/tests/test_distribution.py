"""Distribution checks for the skill-only Claude Code plugin."""

from __future__ import annotations

import filecmp
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "claude-plugin"
MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
SKILL_FILES = {
    "LICENSE",
    "SKILL.md",
    "references/WORKFLOW_CONTRACT.md",
    "references/coverage-obligations.md",
    "references/notebooks-and-configuration.md",
    "references/training-state.md",
    "references/workflow-example.json",
    "scripts/artifact.py",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_describes_the_native_skill_plugin() -> None:
    manifest = _load(MANIFEST)
    assert manifest["name"] == "mlview"
    assert manifest["displayName"] == "MLView"
    assert manifest["license"] == "MIT"
    assert "active Claude model" in manifest["description"]
    for component in ("commands", "agents", "hooks", "mcpServers", "skills"):
        assert component not in manifest


def test_plugin_contains_only_the_native_skill_distribution() -> None:
    assert not (PLUGIN_ROOT / ".mcp.json").exists()
    for retired in ("commands", "docs", "hooks", "server", "vendor"):
        assert not (PLUGIN_ROOT / retired).exists()
    skill_dirs = {path.name for path in (PLUGIN_ROOT / "skills").iterdir() if path.is_dir()}
    assert skill_dirs == {"mlview"}
    actual = {
        path.relative_to(PLUGIN_ROOT / "skills" / "mlview").as_posix()
        for path in (PLUGIN_ROOT / "skills" / "mlview").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert actual == SKILL_FILES


def test_shipped_skill_matches_the_canonical_skill() -> None:
    canonical = REPO_ROOT / "skills" / "mlview"
    shipped = PLUGIN_ROOT / "skills" / "mlview"
    pending = [filecmp.dircmp(canonical, shipped, ignore=["__pycache__", "tests"])]
    while pending:
        comparison = pending.pop()
        assert not comparison.left_only
        assert not comparison.right_only
        assert not comparison.diff_files
        assert not comparison.funny_files
        pending.extend(comparison.subdirs.values())


def test_distribution_carries_the_declared_license() -> None:
    root_license = (REPO_ROOT / "LICENSE").read_bytes()
    assert (PLUGIN_ROOT / "LICENSE").read_bytes() == root_license
    assert (PLUGIN_ROOT / "skills" / "mlview" / "LICENSE").read_bytes() == root_license


def test_marketplace_entries_resolve_to_the_skill_plugin() -> None:
    marketplace = _load(MARKETPLACE)
    entries = {entry["name"]: entry for entry in marketplace["plugins"]}
    assert entries["mlview"]["source"] == "./claude-plugin"
    assert entries["mlview-github"]["source"] == {
        "source": "git-subdir",
        "url": "https://github.com/realmyang/MLView.git",
        "path": "claude-plugin",
    }
    assert _load(MANIFEST)["version"] == marketplace["metadata"]["version"]


INSTALL_DOCS = (REPO_ROOT / "README.md", PLUGIN_ROOT / "README.md")
INSTALL_COMMAND = re.compile(r"/plugin install\s+([^\s@`]+)@([^\s`]+)")


def _documented_installs() -> list[tuple[str, str, str]]:
    found = []
    for doc in INSTALL_DOCS:
        for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if "/plugin install" not in line:
                continue
            match = INSTALL_COMMAND.search(line)
            assert match, f"{doc.relative_to(REPO_ROOT)}:{number}: expected /plugin install <plugin>@<marketplace>"
            found.append((f"{doc.relative_to(REPO_ROOT)}:{number}", match[1], match[2]))
    return found


def test_documented_install_commands_name_the_marketplace_and_its_plugins() -> None:
    marketplace = _load(MARKETPLACE)
    plugins = {entry["name"] for entry in marketplace["plugins"]}
    installs = _documented_installs()
    assert installs, "the plugin README documents no /plugin install command"
    for where, plugin, market in installs:
        assert market == marketplace["name"], f"{where}: marketplace {market!r} is not {marketplace['name']!r}"
        assert plugin in plugins, f"{where}: plugin {plugin!r} is not listed in marketplace.json"


def test_bundled_helper_validates_the_shipped_example(tmp_path: Path) -> None:
    example = PLUGIN_ROOT / "skills" / "mlview" / "references" / "workflow-example.json"
    helper = PLUGIN_ROOT / "skills" / "mlview" / "scripts" / "artifact.py"
    (tmp_path / "train.py").write_text("def train():\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(helper), "validate", str(example), "--workspace", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0, payload
    assert payload["ok"] is True


@pytest.mark.parametrize("target", ["./claude-plugin", "./.claude-plugin/marketplace.json"])
def test_claude_plugin_validate_strict_passes(target: str) -> None:
    claude = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if claude is None:
        pytest.skip("the Claude CLI is unavailable")
    result = subprocess.run(
        [claude, "plugin", "validate", target, "--strict"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
