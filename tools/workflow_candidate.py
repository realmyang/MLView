#!/usr/bin/env python3
"""Capture/check exact candidate bytes. A snapshot is not human review or pilot approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

try:
    from tools.package_skill import bundle_identity, canonical_files
except ModuleNotFoundError:
    from package_skill import bundle_identity, canonical_files

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ("contracts/workflow.schema.json", "evals/workflow/tasks.json",
              "webview/dist/mlview.js", "webview/dist/mlview.css",
              "vscode-extension/out/extension.js")
GATES = ["Named human source-reference review", "Frozen scenarios and essential-fact denominator",
         "Frozen expanded prompts, model/host settings, budgets and privacy policy",
         "Reviewed development outcomes and Stage 1 stop/go decision"]
NOTE = ("This record checks selected candidate bytes only. It does not authenticate the snapshot, "
        "establish semantic quality or host discovery, or record human review or pilot approval.")
IDENTITY_KEYS = {"path", "sha256", "bytes"}
ROOT_KEYS = {"version", "kind", "pilotApproved", "source", "skill", "components", "vsix",
             "remainingGates", "note"}
HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")


def file_identity(path: Path, root: Path) -> dict:
    root = root.resolve()
    try:
        relative_path = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("candidate file must be a regular non-symlink file inside the checkout") from exc
    cursor = root
    for part in relative_path.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("candidate file must be a regular non-symlink file inside the checkout")
    resolved = path.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError("candidate file must be a regular non-symlink file inside the checkout")
    relative = relative_path.as_posix()
    data = path.read_bytes()
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def validate_identity(value: object, *, expected_path: str | None = None) -> dict:
    if not isinstance(value, dict) or set(value) != IDENTITY_KEYS:
        raise ValueError("invalid candidate file identity")
    path, digest, size = value.get("path"), value.get("sha256"), value.get("bytes")
    if (not isinstance(path, str) or "\\" in path or path.startswith("/") or
            any(part in {"", ".", ".."} for part in path.split("/"))):
        raise ValueError("invalid candidate file identity")
    if expected_path is not None and path != expected_path:
        raise ValueError("candidate component inventory does not match the required set")
    if not isinstance(digest, str) or not HEX_64.fullmatch(digest):
        raise ValueError("invalid candidate file identity")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("invalid candidate file identity")
    return value


def validate_bundle_identity(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"algorithm", "sha256", "files"}:
        raise ValueError("invalid portable skill identity")
    if value.get("algorithm") != "sha256-sorted-path-nul-bytes-nul":
        raise ValueError("invalid portable skill identity")
    digest, files = value.get("sha256"), value.get("files")
    if not isinstance(digest, str) or not HEX_64.fullmatch(digest) or not isinstance(files, list):
        raise ValueError("invalid portable skill identity")
    paths = []
    for entry in files:
        paths.append(validate_identity(entry)["path"])
    if paths != sorted(set(paths)):
        raise ValueError("invalid portable skill identity")


def git_value(root: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def snapshot(root: Path = ROOT, vsix: Path | None = None) -> dict:
    root = root.resolve()
    components = [file_identity(root / name, root) for name in COMPONENTS]
    vsix_identity = None
    if vsix is not None:
        path = (root / vsix) if not vsix.is_absolute() else vsix
        if path.suffix.lower() != ".vsix":
            raise ValueError("candidate VSIX must use the .vsix extension")
        vsix_identity = file_identity(path, root)
    status = git_value(root, "status", "--porcelain")
    return {
        "version": 1, "kind": "candidate-byte-snapshot", "pilotApproved": False,
        "source": {"commit": git_value(root, "rev-parse", "HEAD"),
                   "workingTreeChanged": None if status is None else bool(status)},
        "skill": bundle_identity(canonical_files(root / "skills/mlview")),
        "components": components,
        "vsix": vsix_identity,
        "remainingGates": GATES,
        "note": NOTE,
    }


def check(record: dict, root: Path = ROOT) -> list[str]:
    """Detect drift without changing the captured record or claiming readiness."""
    root = root.resolve()
    if not isinstance(record, dict) or set(record) != ROOT_KEYS:
        raise ValueError("candidate snapshot has unexpected or missing fields")
    if (type(record.get("version")) is not int or record.get("version") != 1 or
            record.get("kind") != "candidate-byte-snapshot" or
            record.get("pilotApproved") is not False or record.get("remainingGates") != GATES or
            record.get("note") != NOTE):
        raise ValueError("unsupported candidate snapshot")
    source = record.get("source")
    if not isinstance(source, dict) or set(source) != {"commit", "workingTreeChanged"}:
        raise ValueError("invalid informational source metadata")
    commit, changed = source.get("commit"), source.get("workingTreeChanged")
    if (commit is not None and (not isinstance(commit, str) or not HEX_40.fullmatch(commit)) or
            changed is not None and not isinstance(changed, bool)):
        raise ValueError("invalid informational source metadata")
    problems = []
    validate_bundle_identity(record.get("skill"))
    if record.get("skill") != bundle_identity(canonical_files(root / "skills/mlview")):
        problems.append("portable skill payload changed")
    components = record.get("components")
    if not isinstance(components, list) or len(components) != len(COMPONENTS):
        raise ValueError("snapshot requires component identities")
    by_path = {}
    for entry in components:
        checked = validate_identity(entry)
        name = checked["path"]
        if name in by_path:
            raise ValueError("candidate component inventory does not match the required set")
        by_path[name] = checked
    if set(by_path) != set(COMPONENTS):
        raise ValueError("candidate component inventory does not match the required set")
    for name in COMPONENTS:
        try:
            current = file_identity(root / name, root)
        except OSError:
            problems.append(f"missing component: {name}")
            continue
        if by_path[name] != current:
            problems.append(f"changed component: {name}")
    vsix = record.get("vsix")
    if vsix is not None:
        checked_vsix = validate_identity(vsix)
        if Path(checked_vsix["path"]).suffix.lower() != ".vsix":
            raise ValueError("candidate VSIX must use the .vsix extension")
        try:
            current = file_identity(root / checked_vsix["path"], root)
        except OSError:
            problems.append(f"missing component: {checked_vsix['path']}")
        else:
            if checked_vsix != current:
                problems.append(f"changed component: {checked_vsix['path']}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path, help="check an existing snapshot against this checkout")
    parser.add_argument("--vsix", type=Path, help="include a built VSIX inside the checkout")
    parser.add_argument("--output", type=Path, help="create a new snapshot file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        if args.check:
            if args.output or args.vsix:
                parser.error("--check cannot be combined with --output or --vsix")
            problems = check(json.loads(args.check.read_text(encoding="utf-8")))
            print(json.dumps({"ok": not problems, "problems": problems, "pilotApproved": False}, indent=2))
            return int(bool(problems))
        value = snapshot(vsix=args.vsix)
        serialized = json.dumps(value, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(serialized)
        print(serialized, end="")
        return 0
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
