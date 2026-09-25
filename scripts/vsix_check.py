#!/usr/bin/env python3
"""Check the actual VSIX payload, including exclusion of the retired analyzer.

By default every packaged notice and bundle is compared with its working-tree source, and a
missing source is a problem (build first). --payload-only checks a downloaded or attached VSIX
without a build: it prints one SKIP line per comparison it does not make.
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
CEILING_BYTES = 1024 * 1024
REQUIRED = {
    "extension/package.json", "extension/out/extension.js", "extension/media/mlview.js",
    "extension/media/mlview.css", "extension/LICENSE.txt", "extension/THIRD_PARTY_NOTICES.md",
}
ALLOWED_COMMANDS = {"mlview.openGeneratedDiagram"}
# (packaged entry, working-tree source relative to the checkout, label used in messages)
FRESHNESS = (
    ("extension/LICENSE.txt", "LICENSE", "notice", "LICENSE"),
    ("extension/THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md", "notice", "THIRD_PARTY_NOTICES.md"),
    ("extension/media/mlview.js", "vscode-extension/media/mlview.js", "payload", "media/mlview.js"),
    ("extension/media/mlview.css", "vscode-extension/media/mlview.css", "payload", "media/mlview.css"),
    ("extension/out/extension.js", "vscode-extension/out/extension.js", "payload", "out/extension.js"),
)
SKIP_MESSAGE = "SKIP: bundle freshness not compared (--payload-only)"


class Result(NamedTuple):
    problems: list[str]
    measured: str
    skipped: list[str]


def find_vsix(root: Path = ROOT) -> Path | None:
    candidates = list((root / "vscode-extension").glob("*.vsix"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def check(root: Path, vsix: Path, payload_only: bool = False) -> Result:
    problems: list[str] = []
    skipped: list[str] = []
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
        for name, relative, kind, label in FRESHNESS:
            if name not in names:
                continue  # already reported as missing required payload
            if payload_only:
                skipped.append(f"{SKIP_MESSAGE}: {label}")
                continue
            source = root / relative
            if not source.is_file():
                problems.append(f"cannot compare {label}: {relative} is missing (build first, or pass --payload-only)")
            elif archive.read(name) != source.read_bytes():
                problems.append(f"stale packaged {kind}: {label}")
    return Result(problems, f"{len(names)} files, {vsix.stat().st_size} bytes; native diagram viewer", skipped)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vsix", type=Path, nargs="?")
    parser.add_argument("--payload-only", action="store_true",
                        help="check the payload without comparing bundles and notices with working-tree sources")
    args = parser.parse_args()
    path = args.vsix or find_vsix()
    if path is None:
        parser.error("no VSIX found; run npm run package in vscode-extension")
    problems, measured, skipped = check(ROOT, path, payload_only=args.payload_only)
    print(measured)
    for line in skipped:
        print(line)
    for problem in problems:
        print("FAIL: " + problem)
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
