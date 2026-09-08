"""HEALTH-01 — running the plugin suite may never poison the vendor gate.

`tools/verify.py --all` runs `pytest claude-plugin/tests` (gate 8) and then
`tools/sync-core.py --check` (gate 9), and `scripts/e2e` runs them in that same
order as steps 5 and 14. The suite imports the vendored analyzer in-process, so
with `PYTHONDONTWRITEBYTECODE` unset CPython writes `__pycache__` trees under
`claude-plugin/vendor/mlview/` — bytecode that would ship with the plugin, and
that gate 9 used to report as a failure. Two halves keep that from returning:

* the drivers and `conftest.py` set `PYTHONDONTWRITEBYTECODE=1`, so no residue
  is written in the first place;
* `sync-core --check` prunes any residue that some *other* entry point (an
  editor, `claude plugin validate`, a bare `pytest`) left behind, and says so
  rather than turning red.

This test proves both, over a throwaway copy of the vendored tree so the real
one is never the experiment, and then asserts the real gate is green.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from plugin_support import REPO_ROOT

VENDOR = os.path.join(REPO_ROOT, "claude-plugin", "vendor", "mlview")

IMPORTS_THE_VENDORED_CORE = '''\
import os

import mlview


def test_the_vendored_core_imports():
    """It must be the throwaway copy that got imported, not an installed core."""
    here = os.path.realpath(os.getcwd())
    assert os.path.realpath(mlview.__file__).startswith(here), mlview.__file__
'''


def _pycache_dirs(root: str) -> list[str]:
    found = []
    for dirpath, dirnames, _files in os.walk(root):
        for name in list(dirnames):
            if name == "__pycache__":
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def _throwaway_tree(tmp_path, name: str) -> str:
    """A pristine copy of `claude-plugin/vendor/mlview`, minus any residue."""
    work = tmp_path / name
    work.mkdir()
    shutil.copytree(
        VENDOR,
        str(work / "mlview"),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (work / "test_vendor_import.py").write_text(IMPORTS_THE_VENDORED_CORE, encoding="utf-8")
    assert _pycache_dirs(str(work)) == [], "the throwaway tree starts clean"
    return str(work)


def _run_pytest(work: str, write_bytecode: bool) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = work
    env["PYTHONUTF8"] = "1"
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    if not write_bytecode:
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "test_vendor_import.py", "-q", "-p", "no:cacheprovider"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_pytest_over_a_vendored_tree_leaves_no_bytecode_when_the_flag_is_set(tmp_path):
    """The half the drivers own: with the flag, importing writes nothing."""
    work = _throwaway_tree(tmp_path, "guarded")
    done = _run_pytest(work, write_bytecode=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _pycache_dirs(work) == [], (
        "PYTHONDONTWRITEBYTECODE=1 was set and CPython still wrote bytecode into the "
        "vendored tree: %s" % _pycache_dirs(work)
    )


def test_the_hazard_is_real_without_the_flag(tmp_path):
    """The guard on the guard — if this stops failing, the test above is vacuous."""
    work = _throwaway_tree(tmp_path, "unguarded")
    done = _run_pytest(work, write_bytecode=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _pycache_dirs(work), (
        "no bytecode appeared even without PYTHONDONTWRITEBYTECODE, so this suite can "
        "no longer detect the regression it exists to catch"
    )


def test_sync_core_check_is_green_after_this_suite_imported_the_vendored_core():
    """The half `sync-core --check` owns: residue is pruned, not reported as drift."""
    residue = os.path.join(VENDOR, "__pycache__")
    os.makedirs(residue, exist_ok=True)
    with open(os.path.join(residue, "mlview-health01.pyc"), "wb") as handle:
        handle.write(b"not really bytecode")

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    done = subprocess.run(
        [sys.executable, "tools/sync-core.py", "--check"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "pruned" in done.stdout, done.stdout
    assert not os.path.isdir(residue), "the residue was reported but not removed"
