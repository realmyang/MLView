#!/usr/bin/env python3
"""Synchronize the canonical portable MLView skill into the Claude plugin."""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "mlview"
TARGET = ROOT / "claude-plugin" / "skills" / "mlview"
IGNORED = {"tests", "__pycache__"}


def files(root: Path) -> dict[Path, Path]:
    return {path.relative_to(root): path for path in root.rglob("*") if path.is_file() and not IGNORED.intersection(path.relative_to(root).parts) and path.suffix != ".pyc"}


def check() -> list[str]:
    source, target = files(SOURCE), files(TARGET) if TARGET.exists() else {}
    problems = [f"missing copy: {path.as_posix()}" for path in sorted(source.keys() - target.keys())]
    problems += [f"stale extra: {path.as_posix()}" for path in sorted(target.keys() - source.keys())]
    problems += [f"different copy: {path.as_posix()}" for path in sorted(source.keys() & target.keys()) if not filecmp.cmp(source[path], target[path], shallow=False)]
    return problems


def sync() -> None:
    if TARGET.exists(): shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check: sync()
    problems = check()
    if problems:
        for problem in problems: print("sync-skill: " + problem, file=sys.stderr)
        return 1
    print("sync-skill: OK canonical skill matches Claude plugin")
    return 0


if __name__ == "__main__": raise SystemExit(main())
