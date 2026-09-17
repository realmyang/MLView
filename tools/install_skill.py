#!/usr/bin/env python3
"""Install the portable MLView skill into a workspace."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def install(workspace: Path, destination: str = ".agents/skills/mlview") -> Path:
    root = workspace.resolve(strict=True)
    relative = Path(destination)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("destination must stay within the workspace")
    source = Path(__file__).resolve().parents[1] / "skills" / "mlview"
    target = root / relative
    resolved_parent = target.parent.resolve(strict=False)
    if not _inside(resolved_parent, root):
        raise ValueError("destination resolves outside the workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("destination must not be a symlink")
    resolved_target = target.resolve(strict=False)
    if not _inside(resolved_target, root):
        raise ValueError("destination resolves outside the workspace")
    if _inside(resolved_target, source) or _inside(source, resolved_target):
        raise ValueError("destination must not contain or be contained by the source skill")
    if target.exists():
        source_files = {
            path.relative_to(source)
            for path in source.rglob("*")
            if path.is_file() and "tests" not in path.relative_to(source).parts and "__pycache__" not in path.parts and path.suffix != ".pyc"
        }
        for path in target.rglob("*"):
            if path.is_symlink():
                raise ValueError("destination tree must not contain symlinks")
            if path.is_file() and path.relative_to(target) not in source_files:
                raise ValueError("destination contains files not owned by the MLView skill")
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
    return relative


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", nargs="?", default=".")
    parser.add_argument("--destination", default=".agents/skills/mlview")
    args = parser.parse_args()
    try:
        target = install(Path(args.workspace), args.destination)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(target.as_posix())
    return 0


if __name__ == "__main__": raise SystemExit(main())
