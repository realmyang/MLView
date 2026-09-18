#!/usr/bin/env python3
"""Verify native skill/schema distribution, renderer copies and package metadata."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = (
    "analyzer", "claude-plugin/vendor", "claude-plugin/server", "claude-plugin/hooks",
    "claude-plugin/.mcp.json", "vscode-extension/core", "tools/sync-core.py",
    "tools/action", ".pre-commit-hooks.yaml", "contracts/graph.schema.json",
)


def check_metadata(root: Path = ROOT) -> list[str]:
    problems = []
    manifests = [root / path for path in (
        "webview/package.json", "vscode-extension/package.json",
        "claude-plugin/.claude-plugin/plugin.json",
    )]
    versions = {json.loads(path.read_text(encoding="utf-8"))["version"] for path in manifests}
    if len(versions) != 1:
        problems.append("component versions differ")
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
