#!/usr/bin/env python3
"""Verify the skill and schema distribution, the viewer copies, and the package contents and metadata."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "claude-plugin"
# Every file of the Claude Code plugin folder. Any other file there, or a listed file that is
# absent, is a problem.
PLUGIN_FILES = frozenset({
    "claude-plugin/.claude-plugin/plugin.json",
    "claude-plugin/LICENSE",
    "claude-plugin/README.md",
    "claude-plugin/skills/mlview/LICENSE",
    "claude-plugin/skills/mlview/SKILL.md",
    "claude-plugin/skills/mlview/references/WORKFLOW_CONTRACT.md",
    "claude-plugin/skills/mlview/references/coverage-obligations.md",
    "claude-plugin/skills/mlview/references/notebooks-and-configuration.md",
    "claude-plugin/skills/mlview/references/training-state.md",
    "claude-plugin/skills/mlview/references/workflow-example.json",
    "claude-plugin/skills/mlview/scripts/artifact.py",
})
EXTENSION_MANIFEST = "vscode-extension/package.json"
# The keys the extension manifest may hold under `contributes`. For commands and custom editors
# the value is the field that names an entry and the exact set of names; menus are listed by key.
CONTRIBUTIONS = {
    "commands": ("command", frozenset({"mlview.openGeneratedDiagram", "mlview.revealInDiagram"})),
    "customEditors": ("viewType", frozenset({"mlview.diagram"})),
    "menus": None,
}

MANIFESTS = (
    "webview/package.json", "vscode-extension/package.json",
    "claude-plugin/.claude-plugin/plugin.json",
)
MARKETPLACE = ".claude-plugin/marketplace.json"
VIEWER_ENTRY = "webview/src/main.ts"
VIEWER_VERSION = re.compile(r"^export const version = '([^'\n]*)';$", re.MULTILINE)


def product_versions(root: Path = ROOT) -> dict[str, str | None]:
    """Every literal that names the product version, keyed by where it lives."""
    found: dict[str, str | None] = {}
    for path in MANIFESTS:
        found[path] = json.loads((root / path).read_text(encoding="utf-8")).get("version")
    marketplace = json.loads((root / MARKETPLACE).read_text(encoding="utf-8"))
    metadata = marketplace.get("metadata")
    found[f"{MARKETPLACE} metadata.version"] = metadata.get("version") if isinstance(metadata, dict) else None
    literals = VIEWER_VERSION.findall((root / VIEWER_ENTRY).read_text(encoding="utf-8"))
    found[f"{VIEWER_ENTRY} version literal"] = literals[0] if len(literals) == 1 else None
    return found


def check_metadata(root: Path = ROOT) -> list[str]:
    problems = []
    versions = product_versions(root)
    missing = [where for where, value in versions.items() if not isinstance(value, str) or not value]
    for where in missing:
        problems.append(f"product version missing or ambiguous: {where}")
    if len({value for value in versions.values() if isinstance(value, str) and value}) > 1:
        detail = ", ".join(f"{where}={value}" for where, value in versions.items() if where not in missing)
        problems.append(f"component versions differ: {detail}")
    from jsonschema import Draft202012Validator
    schema = json.loads((root / "contracts/workflow.schema.json").read_text(encoding="utf-8"))
    example = json.loads((root / "skills/mlview/references/workflow-example.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    for error in Draft202012Validator(schema).iter_errors(example):
        problems.append(f"bundled skill example violates the workflow schema: {error.message}")
    return problems


def plugin_files(root: Path = ROOT) -> set[str]:
    """Every file under the plugin folder, as a path from the root. A symbolic link counts as a file.

    The bytecode Python writes when it imports a script (a .pyc file directly in a __pycache__
    folder) is not a plugin file. Any other file in such a folder is.
    """
    found = set()
    for folder, folders, files in os.walk(root / PLUGIN):
        links = [name for name in folders if (Path(folder) / name).is_symlink()]
        if Path(folder).name == "__pycache__":
            files = [name for name in files if not name.endswith(".pyc")]
        found.update((Path(folder) / name).relative_to(root).as_posix() for name in (*files, *links))
    return found


def check_contents(root: Path = ROOT) -> list[str]:
    """Compare the plugin folder and the extension manifest's contributions with the exact lists."""
    found = plugin_files(root)
    problems = [f"unexpected plugin file: {name}" for name in sorted(found - PLUGIN_FILES)]
    problems += [f"missing plugin file: {name}" for name in sorted(PLUGIN_FILES - found)]
    contributes = json.loads((root / EXTENSION_MANIFEST).read_text(encoding="utf-8")).get("contributes")
    if not isinstance(contributes, dict):
        contributes = {}
    problems += [f"unexpected extension contribution: {key}" for key in sorted(set(contributes) - set(CONTRIBUTIONS))]
    problems += [f"missing extension contribution: {key}" for key in sorted(set(CONTRIBUTIONS) - set(contributes))]
    for key, names in CONTRIBUTIONS.items():
        if names is None or key not in contributes:
            continue
        field, expected = names
        entries = contributes[key] if isinstance(contributes[key], list) else [None]
        named = {str(entry.get(field)) if isinstance(entry, dict) else "(not an object)" for entry in entries}
        problems += [f"unexpected extension contribution: {key} {name}" for name in sorted(named - expected)]
        problems += [f"missing extension contribution: {key} {name}" for name in sorted(expected - named)]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="run all distribution checks (default)")
    parser.parse_args(argv)
    problems = check_metadata() + check_contents()
    for script in ("tools/sync-assets.py", "tools/sync-skill.py"):
        result = subprocess.run([sys.executable, str(ROOT / script), "--check"], cwd=ROOT)
        if result.returncode:
            problems.append(f"{script} --check failed")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print("VERIFY OK: package contents, matching versions, valid schema/example, skill and viewer copies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
