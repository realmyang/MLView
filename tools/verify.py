#!/usr/bin/env python3
"""Verify native skill/schema distribution, renderer copies and package metadata."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = (
    "analyzer", "claude-plugin/vendor", "claude-plugin/server", "claude-plugin/hooks",
    "claude-plugin/.mcp.json", "vscode-extension/core", "tools/sync-core.py",
    "tools/action", ".pre-commit-hooks.yaml", "contracts/graph.schema.json",
)


MANIFESTS = (
    "webview/package.json", "vscode-extension/package.json",
    "claude-plugin/.claude-plugin/plugin.json",
)
MARKETPLACE = ".claude-plugin/marketplace.json"
VIEWER_ENTRY = "webview/src/main.ts"
VIEWER_VERSION = re.compile(r"^export const version = '([^'\n]*)';$", re.MULTILINE)


def product_versions(root: Path = ROOT) -> dict[str, str | None]:
    """Every literal that names the product version, keyed by where it lives (CRIT-4)."""
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
    for retired in RETIRED:
        if (root / retired).exists():
            problems.append(f"retired static analyzer surface remains: {retired}")
    package = json.loads((root / "vscode-extension/package.json").read_text(encoding="utf-8"))
    contributes = package.get("contributes", {})
    if contributes.get("languageModelTools") or contributes.get("chatParticipants"):
        problems.append("extension still contributes static analysis chat tools")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="run all distribution checks (default)")
    parser.parse_args()
    problems = check_metadata()
    for script in ("tools/sync-assets.py", "tools/sync-skill.py"):
        result = subprocess.run([sys.executable, str(ROOT / script), "--check"], cwd=ROOT)
        if result.returncode:
            problems.append(f"{script} --check failed")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print("VERIFY OK: native-only packages, matching versions, valid schema/example, skill and viewer copies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
