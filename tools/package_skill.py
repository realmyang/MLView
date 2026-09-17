#!/usr/bin/env python3
"""Build a standalone workspace skill ZIP; no MLView checkout needed after extraction."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def package(output: Path, host: str) -> int:
    source = ROOT / "skills/mlview"
    prefix = ".claude/skills/mlview" if host == "claude-code" else ".agents/skills/mlview"
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if not path.is_file() or any(part in {"tests", "__pycache__"} for part in relative.parts) or path.suffix == ".pyc":
                continue
            info = ZipInfo(f"{prefix}/{relative.as_posix()}")
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
            count += 1
    return count


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
