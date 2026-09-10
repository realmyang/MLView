"""The plugin manifests are the part Claude Code reads before any of our code runs.

A typo in `plugin.json` or `.mcp.json` does not fail loudly — the plugin simply
does not appear, or the MCP server silently never starts. So the shapes are
asserted here, and, when the `claude` CLI is on PATH, its own validator is run
against the real directory (CONTRACTS section 5 and A7).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from plugin_support import PLUGIN_ROOT, REPO_ROOT, SERVER_SCRIPT

PLUGIN_JSON = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")
MCP_JSON = os.path.join(PLUGIN_ROOT, ".mcp.json")
MARKETPLACE_JSON = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------- plugin.json
def test_plugin_json_exists_in_the_only_place_that_is_scanned():
    assert os.path.isfile(PLUGIN_JSON), (
        "plugin.json must live in claude-plugin/.claude-plugin/, not the plugin root"
    )


def test_plugin_json_carries_the_contract_fields():
    manifest = _load(PLUGIN_JSON)
    assert manifest["name"] == "mlview"
    assert manifest["version"] == "0.1.0"
    assert manifest["displayName"] == "MLView"
    assert manifest["license"] == "MIT"
    assert isinstance(manifest["author"], dict) and manifest["author"].get("name")
    assert len(manifest["description"]) > 30
    assert "static-analysis" in manifest["keywords"]


def test_plugin_json_omits_every_component_path_field():
    # CONTRACTS section 5: `skills` ADDS to the default scan while `commands` and
    # `agents` REPLACE it, so setting one by accident silently drops the defaults.
    manifest = _load(PLUGIN_JSON)
    for field in ("commands", "skills", "agents", "hooks", "mcpServers"):
        assert field not in manifest, "%s must be left to the conventional directory" % field


def test_the_conventional_directories_exist_and_are_populated():
    assert os.path.isfile(os.path.join(PLUGIN_ROOT, "commands", "mlview.md"))
    assert os.path.isfile(os.path.join(PLUGIN_ROOT, "commands", "mlview-issues.md"))
    assert os.path.isfile(os.path.join(PLUGIN_ROOT, "skills", "mlview-visualize", "SKILL.md"))
    assert os.path.isfile(os.path.join(PLUGIN_ROOT, "skills", "mlview-triage", "SKILL.md"))
    assert os.path.isfile(os.path.join(PLUGIN_ROOT, "server", "mlview_mcp.py"))


@pytest.mark.parametrize(
    "relative",
    [
        "commands/mlview.md",
        "commands/mlview-issues.md",
        "skills/mlview-visualize/SKILL.md",
        "skills/mlview-triage/SKILL.md",
    ],
)
def test_every_markdown_component_opens_with_yaml_frontmatter(relative):
    path = os.path.join(PLUGIN_ROOT, relative.replace("/", os.sep))
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert text.startswith("---\n"), "%s must open with YAML frontmatter" % relative
    frontmatter = text.split("---", 2)[1]
    if relative.startswith("commands/"):
        assert "description:" in frontmatter
        assert "argument-hint:" in frontmatter
        assert "allowed-tools:" in frontmatter
    else:
        assert "name:" in frontmatter
        assert "description:" in frontmatter


def test_the_command_bodies_document_the_cli_fallback():
    # The demo must not depend on MCP registration succeeding.
    for name in ("mlview.md", "mlview-issues.md"):
        with open(os.path.join(PLUGIN_ROOT, "commands", name), "r", encoding="utf-8") as fh:
            body = fh.read()
        assert "python -m mlview" in body, name
        assert "mlview_" in body, "%s should prefer the MCP tools when present" % name


def test_the_triage_skill_promises_not_to_edit():
    path = os.path.join(PLUGIN_ROOT, "skills", "mlview-triage", "SKILL.md")
    with open(path, "r", encoding="utf-8") as fh:
        body = fh.read().lower()
    assert "never edits" in body or "never apply" in body or "never applies" in body


# ---------------------------------------------------------------------- .mcp.json
def test_mcp_json_is_at_the_plugin_root_in_the_windows_safe_form():
    config = _load(MCP_JSON)
    server = config["mcpServers"]["mlview"]
    assert server["type"] == "stdio"
    # TB-13 / CLEANUP 7 widened this from the bare "python" to the same
    # ${VAR:-default} expansion the args and env already rely on. The DEFAULT is
    # still the Windows-safe `python`, so an unset MLVIEW_PYTHON spawns exactly
    # what it spawned before; the variable is the fix for a plugin installed
    # read-only, where editing this file is not an option.
    assert server["command"] == "${MLVIEW_PYTHON:-python}"
    assert server["args"] == ["${CLAUDE_PLUGIN_ROOT}/server/mlview_mcp.py"]


def test_the_interpreter_override_defaults_to_the_windows_safe_spelling():
    """CLEANUP 7 asked for `python3` to be documented AND an `MLVIEW_PYTHON`
    override to be honoured. Only the documentation half shipped (TB-13): a
    macOS / Linux user still had to edit a checked-in file. Both halves now hold,
    and the default may not regress to something absent on Windows."""
    command = _load(MCP_JSON)["mcpServers"]["mlview"]["command"]
    name, _, default = command.strip("${}").partition(":-")
    assert name == "MLVIEW_PYTHON"
    assert default == "python", "the default must stay the one spelling Windows has"
    with open(os.path.join(PLUGIN_ROOT, "README.md"), "r", encoding="utf-8") as fh:
        readme = fh.read()
    assert "MLVIEW_PYTHON" in readme, "the override has to be documented to be usable"
    with open(SERVER_SCRIPT, "r", encoding="utf-8") as fh:
        assert "MLVIEW_PYTHON" in fh.read(), "and named by the too-old-Python message"


def test_mcp_json_env_makes_the_plugin_work_without_a_pip_install():
    env = _load(MCP_JSON)["mcpServers"]["mlview"]["env"]
    assert env["PYTHONPATH"] == "${CLAUDE_PLUGIN_ROOT}/vendor"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["MLVIEW_PROJECT_DIR"] == "${CLAUDE_PROJECT_DIR}"
    assert env["MLVIEW_DATA_DIR"] == "${CLAUDE_PLUGIN_DATA}"


# CLEANUP 7: `.mcp.json` can only spell ONE command, and `python` is the only
# spelling that works out of the box on Windows. JSON has no comments, so the note
# that belongs beside that field lives in the README - and it has to stay there.
def test_the_python3_caveat_is_documented_where_the_reader_will_look():
    with open(os.path.join(PLUGIN_ROOT, "README.md"), "r", encoding="utf-8") as fh:
        readme = fh.read()
    assert '"command"' in readme and "python3" in readme, (
        "the README must tell a macOS / Linux reader to change .mcp.json's command "
        "to python3; JSON cannot carry the comment itself"
    )
    assert ".mcp.json" in readme
    # And the server must not merely document it: it has to say so at startup.
    with open(SERVER_SCRIPT, "r", encoding="utf-8") as fh:
        server = fh.read()
    assert "python_version_problem" in server


def test_the_server_path_in_mcp_json_actually_exists():
    relative = _load(MCP_JSON)["mcpServers"]["mlview"]["args"][0]
    relative = relative.replace("${CLAUDE_PLUGIN_ROOT}/", "")
    assert os.path.isfile(os.path.join(PLUGIN_ROOT, relative.replace("/", os.sep)))


# ------------------------------------------------------------------- marketplace
def _entry(name):
    for entry in _load(MARKETPLACE_JSON)["plugins"]:
        if entry["name"] == name:
            return entry
    raise AssertionError("no marketplace entry named %r" % name)


def test_the_repo_root_marketplace_points_at_this_plugin():
    market = _load(MARKETPLACE_JSON)
    assert market["name"] == "mlview-local"
    assert market["owner"]["name"]
    local = _entry("mlview")
    assert local["source"] == "./claude-plugin"
    assert local["description"]
    names = [e["name"] for e in market["plugins"]]
    assert len(names) == len(set(names)), "two entries may not share a name: %s" % names


def test_the_marketplace_also_offers_a_hosted_source():
    """PACKAGING: a checkout is not an install channel.

    The local `./claude-plugin` entry only works for somebody who already cloned the
    repo, which is exactly the audience that does not need a marketplace. The hosted
    entry is the github source form from the Claude Code plugin docs, and it ships
    beside the local one rather than replacing it so `claude plugin install
    mlview@mlview-local` keeps working from a checkout.
    """
    hosted = _entry("mlview-github")
    source = hosted["source"]
    assert isinstance(source, dict), "the hosted entry must use the github source object"
    assert source["source"] == "github"
    assert "/" in source["repo"], "repo is `owner/name`, not a URL: %r" % source["repo"]
    assert not source["repo"].startswith("http"), "repo is `owner/name`, not a URL"
    assert hosted["description"]


def test_the_marketplace_source_resolves_to_the_plugin_directory():
    source = _entry("mlview")["source"].lstrip("./")
    resolved = os.path.join(REPO_ROOT, source.replace("/", os.sep))
    assert os.path.isfile(os.path.join(resolved, ".claude-plugin", "plugin.json"))


def test_the_plugin_and_marketplace_versions_agree():
    assert _load(PLUGIN_JSON)["version"] == _load(MARKETPLACE_JSON)["metadata"]["version"]


# ------------------------------------------------------- the CLI's own validator
def _claude_cli():
    return shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")


def _validate(target, strict):
    argv = [_claude_cli(), "plugin", "validate", target] + (["--strict"] if strict else [])
    return subprocess.run(
        argv, cwd=REPO_ROOT, capture_output=True, text=True, shell=False, timeout=120
    )


@pytest.mark.parametrize(
    "target", ["./claude-plugin", "./.claude-plugin/marketplace.json"]
)
def test_claude_plugin_validate_strict_passes(target):
    if _claude_cli() is None:
        pytest.skip("the `claude` CLI is not on PATH; skipping its manifest validator")

    proc = _validate(target, strict=True)
    if proc.returncode != 0 and "--strict" in (proc.stderr + proc.stdout):
        # An older CLI may not know --strict; the non-strict run is still a gate.
        proc = _validate(target, strict=False)
    assert proc.returncode == 0, (
        "claude plugin validate %s failed:\n%s\n%s" % (target, proc.stdout, proc.stderr)
    )
    assert "Validation passed" in proc.stdout or "passed" in proc.stdout.lower()
