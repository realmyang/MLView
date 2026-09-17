#!/usr/bin/env python3
"""Build a standalone workspace skill ZIP; no MLView checkout needed after extraction."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {"tests", "__pycache__"}


def canonical_files(source: Path | None = None) -> dict[str, bytes]:
    """Return the exact portable skill payload, keyed by POSIX relative path."""
    source = source or ROOT / "skills/mlview"
    return {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in sorted(source.rglob("*"))
        if path.is_file()
        and not any(part in SKIP_PARTS for part in path.relative_to(source).parts)
        and path.suffix != ".pyc"
    }


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
