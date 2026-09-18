#!/usr/bin/env python3
"""Build a standalone workspace skill ZIP; no MLView checkout needed after extraction."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {"tests", "__pycache__"}


def canonical_files(source: Path | None = None) -> dict[str, bytes]:
    """Return the exact portable skill payload, keyed by POSIX relative path."""
    source = source or ROOT / "skills/mlview"
    payload: dict[str, bytes] = {}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in SKIP_PARTS for part in relative.parts) or path.suffix == ".pyc":
            continue
        # Following a repository symlink here could silently package arbitrary
        # bytes from outside the reviewed skill tree.
        if path.is_symlink():
            raise ValueError(f"canonical skill must not contain symlinks: {relative.as_posix()}")
        if path.is_file():
            payload[relative.as_posix()] = path.read_bytes()
    return payload


def bundle_identity(payload: dict[str, bytes]) -> dict:
    """Identify every distributed file, using the evaluation path/NUL/bytes/NUL format."""
    digest = hashlib.sha256()
    files = []
    for relative, contents in sorted(payload.items()):
        digest.update(relative.encode("utf-8") + b"\0" + contents + b"\0")
        files.append({"path": relative, "sha256": hashlib.sha256(contents).hexdigest(), "bytes": len(contents)})
    return {"algorithm": "sha256-sorted-path-nul-bytes-nul", "sha256": digest.hexdigest(), "files": files}


def package(output: Path, host: str) -> int:
    prefix = ".claude/skills/mlview" if host == "claude-code" else ".agents/skills/mlview"
    payload = canonical_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Store rather than deflate: the small text payload stays byte-reproducible
    # across platforms without depending on the runner's zlib implementation.
    with ZipFile(output, "w", ZIP_STORED) as archive:
        for relative, contents in payload.items():
            info = ZipInfo(f"{prefix}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, contents)
    return len(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("shared", "claude-code"), default="shared")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / ".mlview/dist" / f"mlview-skill-{args.host}.zip"
    count = package(output, args.host)
    print(f"Packaged {count} files: {output}")


if __name__ == "__main__":
    main()
