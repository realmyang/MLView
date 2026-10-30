#!/usr/bin/env python
"""Copy the built WorkflowDocument viewer into the VS Code extension.

Edit webview/src, build webview/dist, then run this script. --check verifies
byte-identical JavaScript and CSS without changing either copy.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from typing import Dict, List, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(REPO_ROOT, "webview", "dist")
TARGET_DIRS = (
    os.path.join(REPO_ROOT, "vscode-extension", "media"),
)
ASSETS = ("mlview.js", "mlview.css")


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hashes() -> Dict[str, str]:
    """SHA-256 of every asset in `webview/dist`; missing files are absent keys."""
    out: Dict[str, str] = {}
    for name in ASSETS:
        path = os.path.join(SOURCE_DIR, name)
        if os.path.isfile(path):
            out[name] = sha256_of(path)
    return out


def survey() -> Tuple[Dict[str, str], List[str]]:
    """Return (source hashes, problems) without touching anything."""
    problems: List[str] = []
    src = source_hashes()
    for name in ASSETS:
        if name not in src:
            problems.append(
                "missing source: webview/dist/%s — run `npm run build` in webview/" % name
            )
    for target_dir in TARGET_DIRS:
        rel_dir = os.path.relpath(target_dir, REPO_ROOT).replace("\\", "/")
        for name, want in src.items():
            path = os.path.join(target_dir, name)
            if not os.path.isfile(path):
                problems.append("missing copy: %s/%s" % (rel_dir, name))
            elif sha256_of(path) != want:
                problems.append("stale copy: %s/%s" % (rel_dir, name))
    return src, problems


def sync(quiet: bool = False) -> int:
    src = source_hashes()
    if not src:
        print(
            "sync-assets: FAIL no bundle in webview/dist — run `npm run build` in webview/",
            file=sys.stderr,
        )
        return 1
    copied = 0
    for target_dir in TARGET_DIRS:
        os.makedirs(target_dir, exist_ok=True)
        for name in src:
            source = os.path.join(SOURCE_DIR, name)
            target = os.path.join(target_dir, name)
            if os.path.isfile(target) and sha256_of(target) == src[name]:
                continue
            shutil.copyfile(source, target)
            copied += 1
    if not quiet:
        for name, digest in sorted(src.items()):
            print("sync-assets: %-12s %s" % (name, digest))
        print(
            "sync-assets: %d file(s) copied into %d target(s)"
            % (copied, len(TARGET_DIRS))
        )
        missing = [n for n in ASSETS if n not in src]
        if missing:
            print("sync-assets: WARNING no source for %s" % ", ".join(missing), file=sys.stderr)
    return 0


def check(quiet: bool = False) -> int:
    src, problems = survey()
    if problems:
        print("sync-assets: FAIL viewer bundle is out of sync", file=sys.stderr)
        for problem in problems:
            print("  " + problem, file=sys.stderr)
        print("  fix: python tools/sync-assets.py", file=sys.stderr)
        return 1
    if not quiet:
        for name, digest in sorted(src.items()):
            print("sync-assets: OK %-12s %s" % (name, digest))
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync-assets",
        description="Copy webview/dist/{mlview.js,mlview.css} into the extension.",
    )
    parser.add_argument("--check", action="store_true", help="verify only; exit 1 on drift")
    parser.add_argument("--quiet", action="store_true", help="print only problems")
    args = parser.parse_args(argv)
    return check(args.quiet) if args.check else sync(args.quiet)


if __name__ == "__main__":
    sys.exit(main())
