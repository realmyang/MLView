#!/usr/bin/env python3
"""Check local links in active documentation and LF in maintained shell scripts.

Historical decision records and immutable evaluation logs intentionally describe
older revisions; they are not checked as current operational instructions.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = (
    "README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
    "THIRD_PARTY_NOTICES.md", "docs/README.md", "docs/STATUS.md", "docs/VALIDATION.md",
    "docs/LLM_WORKFLOW.md", "docs/WORKFLOW_CONTRACT.md", "contracts/README.md",
    "scripts/README.md", "webview/README.md", "vscode-extension/README.md",
    "claude-plugin/README.md", "samples/README.md", "evals/workflow/README.md",
    "evals/workflow/fixtures/README.md", "skills/mlview/SKILL.md",
)
LINK = re.compile(r"!?\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+[^)]*)?\)")


def run(root: Path = ROOT) -> tuple[list[str], list[Path]]:
    problems = []
    files = []
    for relative in ACTIVE:
        path = root / relative
        if not path.is_file():
            problems.append(f"missing active document: {relative}")
            continue
        files.append(path)
        text = path.read_text(encoding="utf-8")
        # Fenced examples may intentionally show placeholders, not live links.
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for match in LINK.finditer(text):
            target = match[1]
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith("#") or not parsed.path:
                continue
            resolved = path.parent / unquote(parsed.path)
            if not resolved.exists():
                problems.append(f"{relative}: dead local link {target}")
    for path in sorted((root / "scripts").glob("*.sh")):
        files.append(path)
        if b"\r" in path.read_bytes():
            problems.append(f"{path.relative_to(root)}: shell script must use LF")
    return problems, files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    problems, files = run(args.root)
    for problem in problems:
        print("FAIL: " + problem)
    if not problems and not args.quiet:
        print(f"DOC CHECK OK: {len(files)} active documents/scripts")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
