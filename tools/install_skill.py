#!/usr/bin/env python3
"""Install the portable MLView skill into a workspace."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    from tools.package_skill import bundle_identity, canonical_files, portable
except ModuleNotFoundError:  # Direct invocation from outside the checkout.
    from package_skill import bundle_identity, canonical_files, portable

SKILL_LOCATIONS = (Path(".agents/skills/mlview"), Path(".claude/skills/mlview"))
REQUIRED_FILES = (Path("SKILL.md"), Path("LICENSE"), Path("scripts/artifact.py"), Path("references/WORKFLOW_CONTRACT.md"), Path("references/workflow-example.json"))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _portable_files(source: Path) -> set[Path]:
    files: set[Path] = set()
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if not portable(relative):
            continue
        if path.is_symlink():
            raise ValueError(f"source skill must not contain symlinks: {relative.as_posix()}")
        if path.is_file():
            files.add(relative)
    return files


def install(workspace: Path, destination: str = ".agents/skills/mlview") -> Path:
    root = workspace.resolve(strict=True)
    relative = Path(destination)
    if not destination or "\\" in destination or relative.is_absolute() or any(part in {"", ".", ".."} for part in destination.split("/")):
        raise ValueError("destination must be a slash-separated relative path within the workspace")
    source = Path(__file__).resolve().parents[1] / "skills" / "mlview"
    source_files = _portable_files(source)
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
        for path in target.rglob("*"):
            if path.is_symlink():
                raise ValueError("destination tree must not contain symlinks")
            # Editor and OS files (package_skill.portable) are left alone.
            if path.is_file() and portable(path.relative_to(target)) and path.relative_to(target) not in source_files:
                raise ValueError("destination contains files not owned by the MLView skill")
    for file in sorted(source_files):
        (target / file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / file, target / file)
    return relative


def doctor(workspace: Path) -> tuple[dict[str, object], bool]:
    """Inspect the two documented skill locations without executing or modifying files."""
    root = workspace.resolve(strict=True)
    locations: list[dict[str, object]] = []
    installed = 0
    healthy = True
    expected = canonical_files(Path(__file__).resolve().parents[1] / "skills/mlview")
    expected_identity = bundle_identity(expected)
    for relative in SKILL_LOCATIONS:
        target = root / relative
        present = target.is_dir() and not target.is_symlink()
        lexical = root
        unsafe_ancestor = False
        for part in relative.parts:
            lexical /= part
            if lexical.is_symlink():
                unsafe_ancestor = True
                break
        if present and not unsafe_ancestor:
            try:
                unsafe_ancestor = not _inside(target.resolve(strict=True), root)
            except OSError:
                unsafe_ancestor = True
        unsafe_tree = present and not unsafe_ancestor and any(path.is_symlink() for path in target.rglob("*"))
        unsafe = unsafe_ancestor or unsafe_tree
        # Do not read through unsafe ancestors or any linked subtree.
        actual = canonical_files(target) if present and not unsafe else {}
        missing = sorted(name for name in expected if present and
                         (unsafe_ancestor or not (target / name).is_file() or (target / name).is_symlink()))
        changed = sorted(name for name in set(expected) & set(actual) if expected[name] != actual[name])
        unexpected = sorted(set(actual) - set(expected))
        identity = bundle_identity(actual) if present and not unsafe else None
        installed += int(present)
        healthy = healthy and not missing and not changed and not unexpected and not unsafe
        locations.append({"path": relative.as_posix(), "present": present, "missing": missing,
                          "changed": changed, "unexpected": unexpected,
                          "identity": identity, "matchesCanonical": present and not unsafe and actual == expected,
                          "unsafeSymlinks": unsafe})
    collision = installed > 1
    result: dict[str, object] = {
        "ok": sys.version_info >= (3, 10) and healthy and installed == 1,
        "python": {"version": ".".join(str(part) for part in sys.version_info[:3]), "supported": sys.version_info >= (3, 10), "minimum": "3.10"},
        "locations": locations,
        "canonicalIdentity": expected_identity,
        "collision": collision,
        "remediation": (
            ["Choose one host layout; remove the duplicate only after preserving any local edits."] if collision else
            ["Install the skill into the workspace for the intended host."] if installed == 0 else
            ["Compare missing/changed/unexpected files with the canonical bundle; preserve local edits before reinstalling."] if not healthy else []
        ),
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
