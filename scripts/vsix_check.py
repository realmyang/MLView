#!/usr/bin/env python3
"""Check the actual VSIX payload, including exclusion of the retired analyzer."""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CEILING_BYTES = 1024 * 1024
REQUIRED = {
    "extension/package.json", "extension/out/extension.js", "extension/media/mlview.js",
    "extension/media/mlview.css", "extension/LICENSE.txt", "extension/THIRD_PARTY_NOTICES.md",
}
ALLOWED_COMMANDS = {"mlview.openGeneratedDiagram"}


def find_vsix(root: Path = ROOT) -> Path | None:
    candidates = list((root / "vscode-extension").glob("*.vsix"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def check(root: Path, vsix: Path) -> tuple[list[str], str]:
    problems = []
    if vsix.stat().st_size > CEILING_BYTES:
        problems.append("VSIX exceeds 1 MiB ceiling")
    with zipfile.ZipFile(vsix) as archive:
        names = set(archive.namelist())
        for name in sorted(REQUIRED - names):
            problems.append(f"missing required payload: {name}")
        for name in sorted(names):
            if (name.startswith(("extension/core/", "extension/docs/rules/", "extension/node_modules/"))
                    or name.endswith((".py", ".pyc", ".pyo")) or "__pycache__" in name):
                problems.append(f"unexpected runtime or legacy payload: {name}")
        if "extension/package.json" in names:
            package = json.loads(archive.read("extension/package.json"))
            commands = {item["command"] for item in package.get("contributes", {}).get("commands", [])}
            if not commands <= ALLOWED_COMMANDS or "mlview.openGeneratedDiagram" not in commands:
                problems.append("unexpected or missing extension commands")
            if any(package.get("contributes", {}).get(key) for key in ("languageModelTools", "chatParticipants")):
                problems.append("static analysis language tools remain")
        for name, relative in (("extension/LICENSE.txt", "LICENSE"),
                               ("extension/THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md")):
            source = root / relative
            if name in names and source.is_file() and archive.read(name) != source.read_bytes():
                problems.append(f"stale packaged notice: {relative}")
        for relative in ("media/mlview.js", "media/mlview.css", "out/extension.js"):
            name = "extension/" + relative
            source = root / "vscode-extension" / relative
            if name in names and source.is_file() and archive.read(name) != source.read_bytes():
                problems.append(f"stale packaged payload: {relative}")
    return problems, f"{len(names)} files, {vsix.stat().st_size} bytes; native diagram viewer"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vsix", type=Path, nargs="?")
    args = parser.parse_args()
    path = args.vsix or find_vsix()
    if path is None:
        parser.error("no VSIX found; run npm run package in vscode-extension")
    problems, measured = check(ROOT, path)
    print(measured)
    for problem in problems:
        print("FAIL: " + problem)
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
