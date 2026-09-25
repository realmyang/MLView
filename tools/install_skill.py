#!/usr/bin/env python3
"""Install the portable MLView skill into a workspace."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

try:
    from tools.package_skill import bundle_identity, canonical_files, portable
except ModuleNotFoundError:  # Direct invocation from outside the checkout.
    from package_skill import bundle_identity, canonical_files, portable

SOURCE = Path(__file__).resolve().parents[1] / "skills" / "mlview"
SKILL_LOCATIONS = (Path(".agents/skills/mlview"), Path(".claude/skills/mlview"))
# Written after every install: the exact files and bytes MLView put there, so a later install
# can tell unmodified files (replaced, or deleted once retired) from local edits (SKILL-15).
# The leading dot keeps it out of the portable payload and the bundle identity.
MANIFEST_NAME = ".mlview-install.json"
MANIFEST_FORMAT = 1
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
LINK_REMEDIATION = "{path} is a symbolic link; MLView installs only real directories. Remove the link (not its target), then run install_skill.py."


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(value: object) -> bool:
    """A slash-separated relative path that stays inside the install directory."""
    return (isinstance(value, str) and bool(value) and "\\" not in value and "\0" not in value
            and not re.match(r"[A-Za-z]:", value) and not value.startswith("/")
            and all(part not in {"", ".", ".."} for part in value.split("/")))


def _read_manifest(target: Path) -> dict[str, str] | None:
    """The {path: sha256} recorded by the last MLView install, or None when it is absent or unusable.

    An unreadable, malformed or unsafe manifest is ignored as a whole, so every differing file is
    then treated as a local edit: the conservative pre-manifest behaviour."""
    path = target / MANIFEST_NAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    files = value.get("files") if isinstance(value, dict) and value.get("format") == MANIFEST_FORMAT else None
    if not isinstance(files, dict):
        return None
    for key, digest in files.items():
        if not (_safe_relative(key) and portable(key) and isinstance(digest, str) and DIGEST_RE.fullmatch(digest)):
            return None
    return dict(files)


def _write_file(path: Path, data: bytes, mode_from: Path | None = None) -> None:
    """Replace path atomically: a temporary file in the same directory, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".mlview-tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode_from is not None:
            shutil.copymode(mode_from, temporary)
        else:
            mask = os.umask(0)
            os.umask(mask)
            os.chmod(temporary, 0o666 & ~mask)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _remove_empty_parents(path: Path, stop: Path) -> None:
    parent = path.parent
    while parent != stop and _inside(parent, stop):
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def install(workspace: Path, destination: str = ".agents/skills/mlview", *, force: bool = False) -> Path:
    """Install or upgrade the skill; returns the workspace-relative destination.

    A file MLView installed earlier (listed in the destination's .mlview-install.json with the
    bytes it still has) is replaced, and deleted when the new skill no longer ships it. A file
    whose bytes differ from both the recorded and the new canonical bytes is a local edit and is
    replaced (or, when retired, deleted) only with ``force``. Without a manifest (installs before
    0.3.0) every differing skill file counts as a local edit. Files MLView never installed are
    always refused and never deleted; editor and OS files (package_skill.portable) are left alone.
    """
    root = workspace.resolve(strict=True)
    relative = Path(destination)
    if not destination or "\\" in destination or relative.is_absolute() or any(part in {"", ".", ".."} for part in destination.split("/")):
        raise ValueError("destination must be a slash-separated relative path within the workspace")
    payload = canonical_files(SOURCE)
    target = root / relative
    resolved_parent = target.parent.resolve(strict=False)
    if not _inside(resolved_parent, root):
        raise ValueError("destination resolves outside the workspace")
    if target.is_symlink():
        raise ValueError("destination must not be a symlink")
    resolved_target = target.resolve(strict=False)
    if not _inside(resolved_target, root):
        raise ValueError("destination resolves outside the workspace")
    source = SOURCE.resolve()
    if _inside(resolved_target, source) or _inside(source, resolved_target):
        raise ValueError("destination must not contain or be contained by the source skill")
    if target.exists() and not target.is_dir():
        raise ValueError("destination exists and is not a directory")
    existing: dict[str, Path] = {}
    if target.exists():
        for path in target.rglob("*"):
            if path.is_symlink():
                raise ValueError("destination tree must not contain symlinks")
            rel = path.relative_to(target).as_posix()
            if path.is_file() and portable(rel):
                existing[rel] = path
    recorded = _read_manifest(target) if target.exists() else None
    owned = set(payload) | set(recorded or {})
    unowned = sorted(set(existing) - owned)
    if unowned:
        raise ValueError(f"destination contains files not owned by the MLView skill: {', '.join(unowned)}. Move them elsewhere; the installer never replaces or deletes them.")
    current = {rel: path.read_bytes() for rel, path in existing.items()}
    edited = sorted(rel for rel, data in current.items()
                    if data != payload.get(rel) and (recorded is None or recorded.get(rel) != _sha256(data)))
    if edited and not force:
        raise ValueError(f"destination has local edits: {', '.join(edited)}. Back them up and rerun with --force to replace them.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(exist_ok=True)
    for rel, data in sorted(payload.items()):
        if current.get(rel) != data:
            _write_file(target.joinpath(*rel.split("/")), data, mode_from=SOURCE.joinpath(*rel.split("/")))
    for rel in sorted(set(existing) - set(payload)):
        path = target.joinpath(*rel.split("/"))
        path.unlink()
        _remove_empty_parents(path, target)
    manifest = {"format": MANIFEST_FORMAT, "files": {rel: _sha256(data) for rel, data in sorted(payload.items())}}
    _write_file(target / MANIFEST_NAME, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return relative


def doctor(workspace: Path) -> tuple[dict[str, object], bool]:
    """Inspect the two documented skill locations without executing or modifying files."""
    root = workspace.resolve(strict=True)
    locations: list[dict[str, object]] = []
    installed = 0
    healthy = True
    links: list[str] = []
    expected = canonical_files(SOURCE)
    expected_identity = bundle_identity(expected)
    for relative in SKILL_LOCATIONS:
        target = root / relative
        # A symbolic link at the location (or on the way to it) is present but never read.
        present = target.is_symlink() or target.is_dir()
        lexical = root
        linked: str | None = None
        for part in relative.parts:
            lexical /= part
            if lexical.is_symlink():
                linked = lexical.relative_to(root).as_posix()
                break
        unsafe_ancestor = linked is not None
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
        symlinked = present and linked is not None
        if symlinked:
            links.append(LINK_REMEDIATION.format(path=linked))
        locations.append({"path": relative.as_posix(), "present": present, "symlinked": symlinked, "missing": missing,
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
        "remediation": links or (
            ["Choose one host layout; remove the duplicate only after preserving any local edits."] if collision else
            ["Install the skill into the workspace for the intended host."] if installed == 0 else
            ["Compare missing/changed/unexpected files with the canonical bundle; preserve local edits before reinstalling (install_skill.py replaces edited files only with --force)."] if not healthy else []
        ),
        "limitations": ["Filesystem checks cannot certify native assistant skill discovery.", "Filesystem checks cannot certify the MLView extension UI."],
    }
    return result, bool(result["ok"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", nargs="?", default=".")
    parser.add_argument("--destination", default=".agents/skills/mlview")
    parser.add_argument("--doctor", action="store_true", help="inspect documented workspace skill locations without writing")
    parser.add_argument("--force", action="store_true", help="replace (or delete, when retired) skill files that have local edits; back them up first")
    args = parser.parse_args()
    try:
        if args.doctor:
            result, ok = doctor(Path(args.workspace))
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if ok else 1
        target = install(Path(args.workspace), args.destination, force=args.force)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(target.as_posix())
    return 0


if __name__ == "__main__": raise SystemExit(main())
