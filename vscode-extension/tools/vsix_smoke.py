#!/usr/bin/env python
"""Run the analyzer *out of the packaged VSIX*, the way an installed extension does.

    python vscode-extension/tools/vsix_smoke.py [path/to/mlview-0.1.0.vsix]

`scripts/vsix_check.py` proves the package CONTAINS an analyzer: the file count
under `extension/core/`, the 1 MB ceiling, no bytecode, every rule page. This
proves the analyzer it contains RUNS — which is a different claim, and the one
that broke when the bundled core stopped being a tracked directory (C2). The
VSIX is now built from a working tree by `vsce package` after
`tools/sync-core.py` has written `vscode-extension/core/`; if that step is ever
skipped, reordered or silently fails, every other gate in the tree stays green
and a marketplace install has no analyzer at all.

So: unzip the package into a throwaway directory, put `extension/core` on
PYTHONPATH exactly as `pythonEnv.ts` does for a bundled core, and from a cwd
*outside* this repository

  1. import `mlview` and assert the module actually resolved INSIDE the unzipped
     package (an installed copy on the same machine would otherwise answer, and
     the run would prove nothing about what shipped),
  2. `python -m mlview --version` and check it against
     `vscode-extension/package.json` (CONTRACTS A2: one version string),
  3. `python -m mlview analyze --demo --json -` and compare byte for byte with
     `contracts/graph.sample.json` — the frozen golden, so the bundled analyzer
     is held to the same document as the CLI in the analyzer job, and
  4. analyze a real (tiny) source file, so the schema, the rule pack and the
     viewer assets are exercised rather than replayed from a fixture.

Exit 0 when the packaged analyzer runs and agrees, 1 otherwise. Stdlib only, and
nothing in this file writes anywhere but the temporary directory it made.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

EXTENSION_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = EXTENSION_ROOT.parent
CORE_IN_PACKAGE = "extension/core"
PROBE_SOURCE = """\
import torch
from sklearn.model_selection import train_test_split


def main(frame):
    X_train, X_test, y_train, y_test = train_test_split(frame, frame)
    model = torch.nn.Linear(4, 2)
    return model, X_train, X_test, y_train, y_test
"""


def find_vsix(root: Path) -> Path | None:
    found = sorted((root / "vscode-extension").glob("*.vsix"))
    return found[-1] if found else None


def _run(argv: list, cwd: Path, core: Path) -> subprocess.CompletedProcess:
    """`python <argv>` with ONLY the unzipped core on PYTHONPATH."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(core)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # never leave bytecode in the unzip
    env.pop("MLVIEW_CONFIG", None)
    return subprocess.run(
        [sys.executable] + argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def check(vsix: Path, workdir: Path, problems: list) -> str:
    """Unzip, run, compare. Returns the one-line measurement."""
    unpacked = workdir / "unpacked"
    with zipfile.ZipFile(vsix) as zf:
        zf.extractall(unpacked)
    core = unpacked / CORE_IN_PACKAGE
    if not (core / "mlview" / "__init__.py").is_file():
        problems.append(
            "the package holds no %s/mlview/__init__.py — this VSIX installs and "
            "has no analyzer at all" % CORE_IN_PACKAGE
        )
        return "%s: no bundled core" % vsix.name

    # 1. the import resolves inside the unzipped package, not to an installed copy
    where = _run(["-c", "import mlview, sys; sys.stdout.write(mlview.__file__)"], workdir, core)
    resolved = where.stdout.decode("utf-8", "replace").strip()
    if where.returncode != 0:
        problems.append("the bundled core does not import: %s"
                        % where.stderr.decode("utf-8", "replace").strip()[:400])
        return "%s: bundled core does not import" % vsix.name
    if not resolved or not Path(resolved).resolve().is_relative_to(unpacked.resolve()):
        problems.append(
            "`import mlview` resolved to %s, which is outside the unzipped package "
            "— this run would prove nothing about what shipped" % (resolved or "nothing")
        )

    # 2. one version string everywhere (CONTRACTS A2)
    manifest = json.loads((EXTENSION_ROOT / "package.json").read_text(encoding="utf-8"))
    version = _run(["-m", "mlview", "--version"], workdir, core)
    printed = version.stdout.decode("utf-8", "replace").strip()
    if version.returncode != 0:
        problems.append("`python -m mlview --version` failed out of the package: %s"
                        % version.stderr.decode("utf-8", "replace").strip()[:400])
    elif manifest["version"] not in printed:
        problems.append(
            "the bundled core prints %r but vscode-extension/package.json declares "
            "%s — the VSIX ships an analyzer of a different version than it claims"
            % (printed, manifest["version"])
        )

    # 3. the frozen golden, byte for byte
    demo = _run(["-m", "mlview", "analyze", "--demo", "--json", "-"], workdir, core)
    golden = (REPO_ROOT / "contracts" / "graph.sample.json").read_bytes()
    if demo.returncode != 0:
        problems.append("`analyze --demo` failed out of the package: %s"
                        % demo.stderr.decode("utf-8", "replace").strip()[:400])
    elif demo.stdout != golden:
        problems.append(
            "`analyze --demo` out of the package is not byte-identical to "
            "contracts/graph.sample.json (%d bytes vs %d) — the bundled analyzer is "
            "not the analyzer this repository holds"
            % (len(demo.stdout), len(golden))
        )

    # 4. a real analysis, so the schema, the rules and the assets are exercised
    project = workdir / "probe"
    project.mkdir(exist_ok=True)
    (project / "train.py").write_text(PROBE_SOURCE, encoding="utf-8")
    real = _run(
        ["-m", "mlview", "analyze", str(project), "--json", "-", "--no-cache"],
        workdir,
        core,
    )
    nodes = issues = 0
    if real.returncode not in (0, 1):  # 1 = findings present, which is the point
        problems.append("analyzing a two-import file out of the package failed: %s"
                        % real.stderr.decode("utf-8", "replace").strip()[:400])
    else:
        try:
            document = json.loads(real.stdout.decode("utf-8"))
        except ValueError as exc:
            problems.append("the packaged analyzer emitted no readable JSON: %s" % exc)
        else:
            nodes = len(document.get("nodes") or [])
            issues = len(document.get("issues") or [])
            if nodes == 0:
                problems.append(
                    "the packaged analyzer drew 0 nodes for a file that imports torch "
                    "and calls train_test_split — the knowledge tables did not ship"
                )

    stray = [str(p) for p in unpacked.rglob("__pycache__")]
    if stray:
        problems.append("running the bundled core left bytecode behind: %s" % stray[0])

    return ("%s: bundled core imports from the package, %s, --demo byte-identical to "
            "contracts/graph.sample.json (%d bytes), a live analysis drew %d nodes / "
            "%d finding(s)" % (vsix.name, printed or "no version", len(golden), nodes, issues))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="run the analyzer out of the packaged VSIX")
    ap.add_argument("vsix", nargs="?", help="the .vsix to run (default: the newest built)")
    args = ap.parse_args(argv)

    vsix = Path(args.vsix).resolve() if args.vsix else find_vsix(REPO_ROOT)
    if vsix is None or not vsix.is_file():
        print("vsix-smoke: FAILED - no .vsix found; run `npm run package` in "
              "vscode-extension first")
        return 1

    problems: list = []
    with tempfile.TemporaryDirectory(prefix="mlview-vsix-") as tmp:
        measured = check(vsix, Path(tmp), problems)
    if problems:
        print("vsix-smoke: FAILED - " + measured)
        for problem in problems:
            print("  " + problem)
        return 1
    print("vsix-smoke: OK " + measured)
    return 0


if __name__ == "__main__":
    sys.exit(main())
