#!/usr/bin/env python3
"""Synchronize the canonical portable MLView skill into the Claude plugin."""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

try:
    from tools.package_skill import portable
except ModuleNotFoundError:  # Run as a script: tools/ is on sys.path.
    from package_skill import portable

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "mlview"
TARGET = ROOT / "claude-plugin" / "skills" / "mlview"


def files(root: Path) -> dict[Path, Path]:
    """The portable skill files under root (package_skill.portable), keyed by relative path."""
    result: dict[Path, Path] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not portable(relative):
            continue
        if path.is_symlink():
            raise ValueError(f"skill tree must not contain symlinks: {relative.as_posix()}")
        if path.is_file():
            result[relative] = path
    return result


def check(source_root: Path = SOURCE, target_root: Path = TARGET) -> list[str]:
    source, target = files(source_root), files(target_root) if target_root.exists() else {}
    problems = [f"missing copy: {path.as_posix()}" for path in sorted(source.keys() - target.keys())]
    problems += [f"stale extra: {path.as_posix()}" for path in sorted(target.keys() - source.keys())]
    problems += [f"different copy: {path.as_posix()}" for path in sorted(source.keys() & target.keys()) if not filecmp.cmp(source[path], target[path], shallow=False)]
    return problems


def sync(source_root: Path = SOURCE, target_root: Path = TARGET) -> None:
    """Replace target_root with exactly the portable files of source_root (modes kept)."""
    source = files(source_root)
    if target_root.exists(): shutil.rmtree(target_root)
    for relative, path in sorted(source.items()):
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


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
