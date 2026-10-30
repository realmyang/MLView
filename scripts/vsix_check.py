#!/usr/bin/env python3
"""Check the actual VSIX payload against the exact list of its entries.

By default every packaged notice, the changelog, the page, the manifest, the icon and every bundle
is compared with its working-tree source, and a source that cannot be compared is a problem: a
missing file, or an out/extension.js that is the unminified build (npm run compile and npm test
write it; npm run package writes the packaged one). --payload-only checks a downloaded or attached
VSIX without a build: it prints one SKIP line per comparison it does not make.

The package's own two XML files are read as well: extension.vsixmanifest must offer the changelog
as an asset, and [Content_Types].xml must name a content type for Markdown.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
CEILING_BYTES = 1024 * 1024
# Every entry of the package. Any other entry, or a listed entry that is absent, is a problem.
ENTRIES = frozenset({
    "[Content_Types].xml", "extension.vsixmanifest",
    "extension/LICENSE.txt", "extension/THIRD_PARTY_NOTICES.md", "extension/changelog.md",
    "extension/package.json", "extension/readme.md",
    "extension/media/icon.png", "extension/media/mlview.css", "extension/media/mlview.js",
    "extension/out/extension.js",
})
# The keys the packaged manifest may hold under `contributes`.
CONTRIBUTIONS = frozenset({"commands", "customEditors", "menus"})
BUNDLE = "extension/out/extension.js"
# The commands the manifest may contribute; Open Generated Diagram must be among them.
ALLOWED_COMMANDS = {"mlview.openGeneratedDiagram", "mlview.revealInDiagram"}
# The one custom editor, read-only, which opens a *.mlview.json as its diagram, and the file
# pattern it may claim. Any other custom editor, or another file pattern, is unexpected.
ALLOWED_CUSTOM_EDITORS = {"mlview.diagram": ("*.mlview.json",)}
# (packaged entry, working-tree source relative to the checkout, label used in messages)
FRESHNESS = (
    ("extension/LICENSE.txt", "LICENSE", "notice", "LICENSE"),
    ("extension/THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md", "notice", "THIRD_PARTY_NOTICES.md"),
    ("extension/changelog.md", "CHANGELOG.md", "changelog", "CHANGELOG.md"),
    ("extension/readme.md", "vscode-extension/README.md", "page", "vscode-extension/README.md"),
    ("extension/package.json", "vscode-extension/package.json", "manifest", "package.json"),
    ("extension/media/icon.png", "vscode-extension/media/icon.png", "payload", "media/icon.png"),
    ("extension/media/mlview.js", "vscode-extension/media/mlview.js", "payload", "media/mlview.js"),
    ("extension/media/mlview.css", "vscode-extension/media/mlview.css", "payload", "media/mlview.css"),
    ("extension/out/extension.js", "vscode-extension/out/extension.js", "payload", "out/extension.js"),
)
SKIP_MESSAGE = "SKIP: bundle freshness not compared (--payload-only)"
# The asset that makes a marketplace and VS Code show the changelog, as the package's manifest names it.
CHANGELOG_ASSET = ("Microsoft.VisualStudio.Services.Content.Changelog", "extension/changelog.md")
TAG = re.compile(rb"<(Asset|Default)\b([^>]*)>")
ATTRIBUTE = re.compile(rb"([\w:.-]+)\s*=\s*\"([^\"]*)\"")


class Result(NamedTuple):
    problems: list[str]
    measured: str
    skipped: list[str]


def find_vsix(root: Path = ROOT) -> Path | None:
    candidates = list((root / "vscode-extension").glob("*.vsix"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def development_marks(bundle: bytes) -> list[str]:
    """What a bundle holds that the production build does not: a source map link, a comment line."""
    marks = []
    if b"sourceMappingURL" in bundle:
        marks.append("it links a source map")
    for number, line in enumerate(bundle.splitlines(), 1):
        if line.lstrip().startswith((b"//", b"/*")):
            marks.append(f"line {number} is a comment")
            break
    return marks


def elements(xml: bytes, tag: bytes) -> list[dict[str, str]]:
    """The attributes of each element of that name in one of the package's XML files."""
    return [{name.decode(): value.decode("utf-8", "replace") for name, value in ATTRIBUTE.findall(rest)}
            for found, rest in TAG.findall(xml) if found == tag]


def check(root: Path, vsix: Path, payload_only: bool = False) -> Result:
    problems: list[str] = []
    skipped: list[str] = []
    if vsix.stat().st_size > CEILING_BYTES:
        problems.append("VSIX exceeds 1 MiB ceiling")
    with zipfile.ZipFile(vsix) as archive:
        listed = archive.namelist()
        names = set(listed)
        for name in sorted(ENTRIES - names):
            problems.append(f"missing entry: {name}")
        for name in sorted(names - ENTRIES):
            problems.append(f"unexpected entry: {name}")
        for name in sorted(name for name in names if listed.count(name) > 1):
            problems.append(f"repeated entry: {name}")
        if "extension/package.json" in names:
            package = json.loads(archive.read("extension/package.json"))
            contributes = package.get("contributes", {})
            commands = {item["command"] for item in contributes.get("commands", [])}
            if not commands <= ALLOWED_COMMANDS or "mlview.openGeneratedDiagram" not in commands:
                problems.append("unexpected or missing extension commands")
            for key in sorted(set(contributes) - CONTRIBUTIONS):
                problems.append(f"unexpected contribution: {key}")
            editors = contributes.get("customEditors", [])
            if not isinstance(editors, list) or any(
                    not isinstance(editor, dict)
                    or editor.get("viewType") not in ALLOWED_CUSTOM_EDITORS
                    or tuple(item.get("filenamePattern") for item in editor.get("selector", []) if isinstance(item, dict))
                    != ALLOWED_CUSTOM_EDITORS[editor.get("viewType")]
                    for editor in editors):
                problems.append("unexpected custom editors")
        if "extension.vsixmanifest" in names:
            assets = elements(archive.read("extension.vsixmanifest"), b"Asset")
            if not any((asset.get("Type"), asset.get("Path")) == CHANGELOG_ASSET for asset in assets):
                problems.append(f"extension.vsixmanifest offers no changelog asset at {CHANGELOG_ASSET[1]}")
        if "[Content_Types].xml" in names:
            types = elements(archive.read("[Content_Types].xml"), b"Default")
            if not any(item.get("Extension", "").lower() == ".md" and item.get("ContentType") for item in types):
                problems.append("[Content_Types].xml names no content type for .md")
        if BUNDLE in names:
            for mark in development_marks(archive.read(BUNDLE)):
                problems.append(f"packaged bundle is not the production build: {mark}")
        for name, relative, kind, label in FRESHNESS:
            if name not in names:
                continue  # already reported as a missing entry
            if payload_only:
                skipped.append(f"{SKIP_MESSAGE}: {label}")
                continue
            source = root / relative
            if not source.is_file():
                # Of the compared sources, npm run package writes only the bundle.
                how = ("run npm run package first, or pass --payload-only" if name == BUNDLE
                       else "pass --payload-only to check the package alone")
                problems.append(f"cannot compare {label}: {relative} is missing ({how})")
                continue
            current = source.read_bytes()
            if archive.read(name) == current:
                continue
            if name == BUNDLE and development_marks(current):
                # The working tree holds the other build of the same file, so the comparison says
                # nothing about the package.
                problems.append(f"cannot compare {label}: {relative} is the unminified build that npm run compile "
                                "and npm test write (run npm run package again, or pass --payload-only)")
            else:
                problems.append(f"stale packaged {kind}: {label}")
    return Result(problems, f"{len(listed)} files, {vsix.stat().st_size} bytes", skipped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vsix", type=Path, nargs="?")
    parser.add_argument("--payload-only", action="store_true",
                        help="check the payload without comparing bundles and notices with working-tree sources")
    args = parser.parse_args(argv)
    path = args.vsix or find_vsix()
    if path is None:
        parser.error("no VSIX found; run npm run package in vscode-extension")
    problems, measured, skipped = check(ROOT, path, payload_only=args.payload_only)
    print(measured)
    for line in skipped:
        print(line)
    for problem in problems:
        print("FAIL: " + problem)
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
