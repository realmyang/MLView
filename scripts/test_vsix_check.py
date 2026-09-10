#!/usr/bin/env python
"""Tests for scripts/vsix_check.py (HOST-8).

Every case builds a throwaway repo *and* a throwaway `.vsix` in a temp
directory, so nothing here depends on a package having been built. The last case
reads the real one when it happens to be on disk, and skips itself otherwise --
CI builds it in the `packaging` job, and a developer may not have.

Run:  python scripts/test_vsix_check.py      (or: pytest scripts/test_vsix_check.py)
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vsix_check  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# Two core modules and two rule pages is enough shape to test every rule.
CORE_FILES = ["mlview/__init__.py", "mlview/cli.py"]
RULE_PAGES = ["README.md", "MLV101.md"]


def _tree(core=CORE_FILES, rules=RULE_PAGES) -> Path:
    root = Path(tempfile.mkdtemp(prefix="mlview-vsix-"))
    for rel in core:
        target = root / "vscode-extension" / "core" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        io.open(target, "w", encoding="utf-8", newline="\n").write("# core\n")
    for rel in rules:
        target = root / "docs" / "rules" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        io.open(target, "w", encoding="utf-8", newline="\n").write("# rule\n")
    return root


def _package(root: Path, core=CORE_FILES, rules=RULE_PAGES, extra=(),
             filler: int = 0) -> Path:
    vsix = root / "vscode-extension" / "mlview-0.1.0.vsix"
    vsix.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(vsix, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("extension/package.json", "{}\n")
        zf.writestr("extension/out/extension.js", "// bundle\n")
        for rel in core:
            zf.writestr(vsix_check.CORE_PREFIX + rel, "# core\n")
        for rel in rules:
            zf.writestr(vsix_check.RULES_PREFIX + rel, "# rule\n")
        for rel in extra:
            zf.writestr(rel, "x\n")
        if filler:
            # Random bytes so ZIP_STORED size is the size on disk.
            zf.writestr("extension/media/big.bin", os.urandom(filler))
    return vsix


def test_a_sound_package_passes_and_prints_what_it_measured():
    root = _tree()
    try:
        problems, measured = vsix_check.check(root, _package(root))
        assert problems == [], problems
        assert "2 under extension/core/" in measured, measured
        assert "2 rule page(s)" in measured, measured
        assert "0 bytecode" in measured, measured
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_package_with_no_analyzer_at_all_is_caught():
    """The failure `.vscodeignore` produces: it installs, and does nothing."""
    root = _tree()
    try:
        problems = vsix_check.check(root, _package(root, core=[]))[0]
        assert any("no analyzer at all" in p for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_partly_bundled_analyzer_is_caught():
    """`__init__.py` alone is enough to import and not enough to analyze."""
    root = _tree()
    try:
        problems = vsix_check.check(
            root, _package(root, core=["mlview/__init__.py"]))[0]
        assert len(problems) == 1, problems
        assert "1 file(s) under extension/core/" in problems[0]
        assert "holds 2 on disk" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_bytecode_inside_the_package_is_caught():
    root = _tree()
    try:
        problems = vsix_check.check(root, _package(
            root, extra=["extension/core/mlview/__pycache__/cli.cpython-313.pyc"]))[0]
        assert any("bytecode" in p for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_missing_rule_page_is_caught():
    """Every `Issue.docs` deep link the Problems panel offers has to resolve."""
    root = _tree()
    try:
        problems = vsix_check.check(root, _package(root, rules=["README.md"]))[0]
        assert len(problems) == 1, problems
        assert "dead `Issue.docs` link" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_ceiling_is_the_assertion_that_actually_matters():
    root = _tree()
    try:
        problems = vsix_check.check(
            root, _package(root, filler=vsix_check.CEILING_BYTES + 4096))[0]
        assert any("ceiling" in p for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_bytecode_beside_the_analyzer_never_counts_as_a_bundled_file():
    """A local pytest run leaves `__pycache__` in vscode-extension/core; the
    on-disk count has to ignore it or the gate reddens for the wrong reason."""
    root = _tree()
    try:
        stale = root / "vscode-extension/core/mlview/__pycache__/cli.pyc"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"\x00")
        assert vsix_check.count_files(root / "vscode-extension/core") == 2
        assert vsix_check.check(root, _package(root))[0] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_package_is_sound_when_one_has_been_built():
    """`.vsix` is gitignored, so this case is opportunistic on purpose.

    A package older than the analyzer it bundles is *stale*, not broken, and
    failing the doc gate's self-test over somebody's week-old build would be a
    red for the wrong reason -- CI builds a fresh one in the `packaging` job and
    runs `vsix_check.py` against it there.
    """
    vsix = vsix_check.find_vsix(REPO)
    if vsix is None or not vsix.is_file():
        print("     (skipped: no .vsix built; `npm run package` in vscode-extension)")
        return
    core = REPO / "vscode-extension" / "core"
    newest = max((p.stat().st_mtime for p in core.rglob("*") if p.is_file()),
                 default=0.0)
    if vsix.stat().st_mtime < newest:
        print("     (skipped: %s predates vscode-extension/core; re-package)"
              % vsix.name)
        return
    problems, measured = vsix_check.check(REPO, vsix)
    assert problems == [], "\n".join(problems) + "\n" + measured
    assert "extension/core/" in measured


def main() -> int:
    import test_check_docs

    failed = test_check_docs.run_module(sys.modules[__name__])
    print(("%d test(s) failed" % failed) if failed else "vsix_check self-test OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
