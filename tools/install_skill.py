#!/usr/bin/env python3
"""Install the portable MLView skill into a workspace."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL_LOCATIONS = (Path(".agents/skills/mlview"), Path(".claude/skills/mlview"))
REQUIRED_FILES = (Path("SKILL.md"), Path("scripts/artifact.py"), Path("references/WORKFLOW_CONTRACT.md"), Path("references/workflow-example.json"))


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


def doctor(workspace: Path) -> tuple[dict[str, object], bool]:
    """Inspect the two documented skill locations without executing or modifying files."""
    root = workspace.resolve(strict=True)
    locations: list[dict[str, object]] = []
    installed = 0
    healthy = True
    for relative in SKILL_LOCATIONS:
        target = root / relative
        present = target.is_dir() and not target.is_symlink()
        missing = [path.as_posix() for path in REQUIRED_FILES if present and not (target / path).is_file()]
        installed += int(present)
        healthy = healthy and not missing
        locations.append({"path": relative.as_posix(), "present": present, "missing": missing})
    collision = installed > 1
    result: dict[str, object] = {
        "ok": sys.version_info >= (3, 10) and healthy and installed == 1,
        "python": {"version": ".".join(str(part) for part in sys.version_info[:3]), "supported": sys.version_info >= (3, 10), "minimum": "3.10"},
        "locations": locations,
        "collision": collision,
        "limitations": ["Filesystem checks cannot certify native assistant skill discovery.", "Filesystem checks cannot certify the MLView extension UI."],
    }
    return result, bool(result["ok"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", nargs="?", default=".")
    parser.add_argument("--destination", default=".agents/skills/mlview")
    parser.add_argument("--doctor", action="store_true", help="inspect documented workspace skill locations without writing")
    args = parser.parse_args()
    try:
        if args.doctor:
            result, ok = doctor(Path(args.workspace))
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if ok else 1
        target = install(Path(args.workspace), args.destination)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(target.as_posix())
    return 0


if __name__ == "__main__": raise SystemExit(main())
