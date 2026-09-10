#!/usr/bin/env python
"""Gate the packaged VSIX against the tree it was built from (HOST-8).

`vsce package` prints `Packaged: mlview-0.1.0.vsix (127 files, 593.08 KB)` and
for two sprints those two numbers lived, hand-copied, in `scripts/README.md`
row 27 and in `docs/STATUS.md`'s component table. They drift on every module
that lands in the analyzer -- both were one file and ~16 KB behind the real
package, and `docs/STATUS.md` had `core/mlview` at 79 files while
`tools/verify.py --all` printed 80 for the same directory on the same commit.
`scripts/check_docs.py` cannot reach either figure: they are not in any
machine-readable file.

So stop asserting the numbers in prose and assert the *properties* here, the way
`webview/test/bundle.test.mjs` asserts the renderer bundle:

1. **Under the 1 MB ceiling** that `docs/CONTRACTS.md` §11.25 and the packaging
   job both name. This is the thing that actually matters; the file count is
   only interesting when it is zero.
2. **The bundled analyzer is complete.** `extension/core/` must hold exactly as
   many files as `vscode-extension/core/` does on disk -- a `.vscodeignore` that
   drops `core/**` produces a VSIX that installs perfectly and has no analyzer
   at all, which no other gate in the tree would notice.
3. **No bytecode rides along.** A `__pycache__` written by a local test run is
   both dead weight and a stale-analyzer hazard inside the package.
4. **Every rule page ships**, because `Issue.docs` deep-links into them from the
   extension and a missing page is a dead link in the Problems panel.

Then it prints the measured figures on one line, so the run itself is the record
and nobody has to retype them into a doc.

Usage:  python scripts/vsix_check.py [path/to/mlview-0.1.0.vsix] [--root DIR]
Exit 0 when the package is sound, 1 otherwise. Stdlib only.
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
CEILING_BYTES = 1024 * 1024          # §11.25: the VSIX stays under 1 MB
CORE_PREFIX = "extension/core/"
RULES_PREFIX = "extension/docs/rules/"
BYTECODE = ("__pycache__", ".pyc", ".pyo")


def find_vsix(root: Path) -> Path | None:
    found = sorted((root / "vscode-extension").glob("*.vsix"))
    return found[0] if len(found) == 1 else (found[-1] if found else None)


def count_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.rglob("*")
               if p.is_file() and not any(b in p.parts for b in ("__pycache__",)))


def check(root: Path, vsix: Path) -> tuple[list[str], str]:
    """Return (problems, the one-line measurement)."""
    problems: list[str] = []
    size = vsix.stat().st_size
    with zipfile.ZipFile(vsix) as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]

    core = [n for n in names if n.startswith(CORE_PREFIX)]
    rules = [n for n in names if n.startswith(RULES_PREFIX) and n.endswith(".md")]
    bytecode = [n for n in names if any(b in n for b in BYTECODE)]
    on_disk_core = count_files(root / "vscode-extension" / "core")
    on_disk_rules = len(list((root / "docs" / "rules").glob("*.md")))

    if size >= CEILING_BYTES:
        problems.append(
            "%s is %d bytes, at or over the %d-byte ceiling docs/CONTRACTS.md "
            "§11.25 sets" % (vsix.name, size, CEILING_BYTES))
    if not any(n == CORE_PREFIX + "mlview/__init__.py" for n in core):
        problems.append(
            "the package carries no `%smlview/__init__.py`: this VSIX installs "
            "and has no analyzer at all" % CORE_PREFIX)
    if len(core) != on_disk_core:
        problems.append(
            "the package carries %d file(s) under %s but vscode-extension/core "
            "holds %d on disk -- .vscodeignore is dropping part of the bundled "
            "analyzer" % (len(core), CORE_PREFIX, on_disk_core))
    if bytecode:
        problems.append(
            "the package carries %d compiled-bytecode entr(y/ies), e.g. %s -- "
            "a stale .pyc beside a fresh .py is an analyzer nobody can debug"
            % (len(bytecode), bytecode[0]))
    if len(rules) != on_disk_rules:
        problems.append(
            "the package carries %d rule page(s) under %s but docs/rules holds "
            "%d -- every missing page is a dead `Issue.docs` link in the "
            "Problems panel" % (len(rules), RULES_PREFIX, on_disk_rules))

    # KB as `vsce package` prints it -- 1024 bytes -- so this line and the
    # packager's own `Packaged: ... (127 files, 593.08 KB)` are the same figure.
    measured = ("%s: %d files, %.2f KB (%.1f%% of the 1 MB ceiling), "
                "%d under %s, %d rule page(s), %d bytecode entr(y/ies)"
                % (vsix.name, len(names), size / 1024.0,
                   100.0 * size / CEILING_BYTES, len(core), CORE_PREFIX,
                   len(rules), len(bytecode)))
    return problems, measured


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="gate the packaged VSIX")
    ap.add_argument("vsix", nargs="?", help="the .vsix to inspect")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="repo root")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    vsix = Path(args.vsix).resolve() if args.vsix else find_vsix(root)
    if vsix is None or not vsix.is_file():
        print("vsix-check: FAILED - no .vsix found; run `npm run package` in "
              "vscode-extension first")
        return 1

    problems, measured = check(root, vsix)
    if problems:
        print("vsix-check: FAILED - " + measured)
        for problem in problems:
            print("  " + problem)
        return 1
    print("vsix-check: OK " + measured)
    return 0


if __name__ == "__main__":
    sys.exit(main())
