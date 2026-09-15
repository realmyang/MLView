#!/usr/bin/env python
"""Install the built wheel into a throwaway venv and run it (PACKAGING).

    python tools/wheel_check.py            # build if needed, install, run
    python tools/wheel_check.py --sdist    # the same, for the source distribution
    python tools/wheel_check.py --no-build # fail rather than build a missing artifact

`pip install mlview` is now the instruction the VS Code extension prints, the line
`tools/action/action.yml` runs in CI, and the thing `.pre-commit-hooks.yaml` resolves
to. All three are claims about an artifact nobody was testing: `analyzer/dist` did not
exist, and a wheel that omits `schema/*.json` or `emit/assets/*` installs perfectly and
then fails on the first analysis. So the acceptance is end to end and deliberately
paranoid — a fresh interpreter, no MLView on `sys.path`, `mlview --version --json`
through the **console script** (not `python -m`), and then one real analysis, because
`--version` alone cannot tell a complete wheel from one missing its package data.

`--sdist` runs the identical acceptance against `analyzer/dist/*.tar.gz`, because
`twine upload analyzer/dist/*` publishes BOTH and `pip install mlview` falls back to
the sdist on any platform with no matching wheel. An sdist can omit package data a
wheel carries (a `MANIFEST.in`/`sdist` include is a separate mechanism from
`[tool.setuptools.package-data]`), and PyPI never lets a version be re-uploaded, so
the fallback artifact is gated before the first upload rather than after it.

One driver, called identically by `scripts/e2e.sh` and `scripts/e2e.ps1`, so the two
tables stay the same table (`scripts/doc_numbers.py` check 11).

Exit 0 on success **and** when there is no wheel to test (the message says which);
1 when a wheel exists and is broken. A missing publishing tool must not redden a
developer's acceptance run, but a broken wheel must.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYZER = os.path.join(REPO_ROOT, "analyzer")
DIST = os.path.join(ANALYZER, "dist")

#: The smallest analysis that proves the package data came along: a leak the
#: analyzer must find, in a file the wheel's own rules have to load to report.
SAMPLE = (
    "from sklearn.preprocessing import StandardScaler\n"
    "from sklearn.model_selection import train_test_split\n"
    "\n"
    "\n"
    "def build(X, y):\n"
    "    Xs = StandardScaler().fit_transform(X)\n"
    "    return train_test_split(Xs, y, test_size=0.2)\n"
)


def _run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, check=False, **kwargs)


def _newest(pattern: str) -> str:
    found = sorted(glob.glob(os.path.join(DIST, pattern)), key=os.path.getmtime)
    return found[-1] if found else ""


def newest_wheel() -> str:
    return _newest("*.whl")


def newest_sdist() -> str:
    return _newest("*.tar.gz")


def build_dist(flag: str = "--wheel") -> str:
    """Build it if `build` is installed; return the artifact path or ''."""
    probe = _run([sys.executable, "-c", "import build"])
    if probe.returncode != 0:
        return ""
    made = _run([sys.executable, "-m", "build", flag, ANALYZER], cwd=REPO_ROOT)
    if made.returncode != 0:
        print("wheel-check: `python -m build %s analyzer` failed:" % flag, file=sys.stderr)
        print(made.stdout[-2000:], file=sys.stderr)
        print(made.stderr[-2000:], file=sys.stderr)
        return ""
    return newest_sdist() if flag == "--sdist" else newest_wheel()


def build_wheel() -> str:
    """Kept for callers that predate `--sdist`."""
    return build_dist("--wheel")


def venv_python(root: str) -> str:
    if os.name == "nt":
        return os.path.join(root, "Scripts", "python.exe")
    return os.path.join(root, "bin", "python")


def venv_script(root: str, name: str) -> str:
    if os.name == "nt":
        return os.path.join(root, "Scripts", name + ".exe")
    return os.path.join(root, "bin", name)


def expected_version() -> str:
    scope: dict = {}
    path = os.path.join(ANALYZER, "src", "mlview", "version.py")
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("__version__"):
                exec(line, scope)  # noqa: S102 - one assignment from our own tree
                break
    return str(scope.get("__version__", ""))


def check(wheel: str) -> int:
    temp = tempfile.mkdtemp(prefix="mlview-wheel-")
    try:
        env_dir = os.path.join(temp, "venv")
        made = _run([sys.executable, "-m", "venv", env_dir])
        if made.returncode != 0:
            print("wheel-check: could not create a venv: %s" % made.stderr.strip(), file=sys.stderr)
            return 1
        python = venv_python(env_dir)
        install = _run([python, "-m", "pip", "install", "--quiet",
                        "--disable-pip-version-check", wheel])
        if install.returncode != 0:
            print("wheel-check: pip install %s failed:\n%s"
                  % (os.path.basename(wheel), install.stderr[-2000:]), file=sys.stderr)
            return 1

        # The CONSOLE SCRIPT, not `python -m`: `pip install mlview` promises `mlview`
        # on PATH, and a broken entry point is invisible to `python -m mlview`.
        script = venv_script(env_dir, "mlview")
        if not os.path.exists(script):
            print("wheel-check: the wheel installed no `mlview` console script", file=sys.stderr)
            return 1
        version = _run([script, "--version", "--json"])
        if version.returncode != 0:
            print("wheel-check: `mlview --version --json` exited %d:\n%s"
                  % (version.returncode, version.stderr[-2000:]), file=sys.stderr)
            return 1
        try:
            payload = json.loads(version.stdout)
        except ValueError as exc:
            print("wheel-check: --version --json is not JSON (%s): %r"
                  % (exc, version.stdout[:200]), file=sys.stderr)
            return 1
        got = str(payload.get("version") or payload.get("mlview") or "")
        want = expected_version()
        if want and got != want:
            print("wheel-check: the wheel reports %r, this tree is %r" % (got, want),
                  file=sys.stderr)
            return 1

        # One real analysis, on a file the wheel has never seen.
        corpus = os.path.join(temp, "proj")
        os.makedirs(corpus, exist_ok=True)
        with open(os.path.join(corpus, "pipeline.py"), "w", encoding="utf-8") as fh:
            fh.write(SAMPLE)
        analysis = _run([script, "analyze", corpus, "--json", "-"])
        if analysis.returncode not in (0, 2):
            print("wheel-check: the installed wheel cannot analyze (exit %d):\n%s"
                  % (analysis.returncode, analysis.stderr[-2000:]), file=sys.stderr)
            return 1
        try:
            doc = json.loads(analysis.stdout)
        except ValueError:
            print("wheel-check: the installed wheel emitted no document", file=sys.stderr)
            return 1
        if not doc.get("issues"):
            print("wheel-check: the installed wheel found no issue in a planted leak - "
                  "package data (schema/, emit/assets/) is probably missing", file=sys.stderr)
            return 1

        print("wheel-check: OK %s -> mlview %s, %d node(s), %d issue(s) in a clean venv"
              % (os.path.basename(wheel), got, len(doc.get("nodes") or []),
                 len(doc.get("issues") or [])))
        return 0
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="wheel-check",
        description="pip install analyzer/dist/*.whl into a throwaway venv and run it.",
    )
    parser.add_argument("--no-build", action="store_true",
                        help="do not build a missing artifact; report and exit 0")
    parser.add_argument("--sdist", action="store_true",
                        help="gate the source distribution instead of the wheel")
    args = parser.parse_args(argv)

    flag = "--sdist" if args.sdist else "--wheel"
    artifact = newest_sdist() if args.sdist else newest_wheel()
    if not artifact and not args.no_build:
        artifact = build_dist(flag)
    if not artifact:
        print("wheel-check: SKIP no %s in analyzer/dist - run `pip install build` "
              "then `python -m build %s analyzer` (scripts/build.sh does both)"
              % ("sdist" if args.sdist else "wheel", flag))
        return 0
    return check(artifact)


if __name__ == "__main__":
    sys.exit(main())
