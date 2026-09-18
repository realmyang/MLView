#!/usr/bin/env python3
"""Build or exercise the native skill and diagram viewer on any supported OS."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "e2e"))
    parser.add_argument("--skip-npm-install", action="store_true", help="reuse installed locked npm dependencies")
    parser.add_argument("--skip-build", action="store_true", help="e2e only: use existing build outputs")
    args = parser.parse_args()
    if args.mode == "build" and args.skip_build:
        parser.error("--skip-build applies only to e2e")
    if sys.version_info < (3, 10):
        parser.error("Python 3.10+ is required")
    npm = shutil.which("npm")
    if not npm:
        parser.error("Node 20.18.1+ and npm must be on PATH")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    gates = []

    def run(label: str, *command: str, cwd: Path = ROOT) -> None:
        print(f"\n{label}", flush=True)
        subprocess.run(command, cwd=cwd, env=env, check=True)
        gates.append(label)

    def python(label: str, *command: str) -> None:
        run(label, sys.executable, *command)

    try:
        if not args.skip_build:
            for component in ("webview", "vscode-extension"):
                if not args.skip_npm_install:
                    run(f"Install {component} dependencies", npm, "ci", cwd=ROOT / component)
            run("Build viewer", npm, "run", "build", cwd=ROOT / "webview")
            python("Sync viewer", "tools/sync-assets.py")
            python("Sync skill", "tools/sync-skill.py")
            run("Compile extension", npm, "run", "compile", cwd=ROOT / "vscode-extension")
        else:
            print("SKIP: build explicitly skipped; checking existing outputs", flush=True)
        for component in ("webview", "vscode-extension"):
            run(f"Type-check {component}", npm, "run", "check", cwd=ROOT / component)
        python("Distribution consistency", "tools/verify.py", "--all")
        python("Current documentation", "scripts/check_docs.py")
        if args.mode == "e2e":
            python("Python helper, distribution and evaluation regressions", "-m", "pytest",
                   "skills/mlview/tests", "tools", "evals", "scripts", "claude-plugin/tests", "-q")
            for component in ("webview", "vscode-extension"):
                run(f"Test {component}", npm, "test", cwd=ROOT / component)
            with tempfile.TemporaryDirectory(prefix="mlview-release-") as directory:
                for host in ("shared", "claude-code"):
                    python(f"Package {host} skill", "tools/package_skill.py", "--host", host,
                           "--output", str(Path(directory) / f"mlview-{host}.zip"))
                vsix = Path(directory) / "mlview.vsix"
                run("Package VSIX", npm, "run", "package", "--", "--out", str(vsix), cwd=ROOT / "vscode-extension")
                python("Check actual VSIX payload", "scripts/vsix_check.py", str(vsix))
        print(f"\n{args.mode.upper()} OK: {len(gates)} exercised gates", flush=True)
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"FAIL: {exc.cmd} exited {exc.returncode}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
