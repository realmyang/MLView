#!/usr/bin/env sh
# MLView — build everything, in the only order that works.
#
#   sh scripts/build.sh [--skip-npm-install] [--skip-pip-install]
#
# 1. webview          npm install + npm run build       -> webview/dist/mlview.{js,css}
# 2. tools/sync-assets.py                               -> the extension and the analyzer get the SAME bundle
# 3. tools/sync-core.py                                 -> claude-plugin/vendor/mlview (tracked) + vscode-extension/core/mlview (BUILT, gitignored)
# 4. vscode-extension npm install + compile + check     -> out/extension.js, tsc clean
# 5. analyzer         pip install -e                    -> `python -m mlview` on this interpreter
# 6. analyzer         python -m build --wheel           -> analyzer/dist/*.whl (PACKAGING)
#
# The order matters: sync-assets must run after the viewer is built and before the
# analyzer emits anything, because `generator.rendererSha` is the SHA-256 of the
# bundle the analyzer ships. POSIX sh, so it also runs under Git Bash on Windows.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")

PYTHONUTF8=1
PYTHONIOENCODING=utf-8
# Never leave bytecode behind: step 3 vendors the analyzer into the plugin and
# any __pycache__ under claude-plugin/vendor would ship with it (HEALTH-01).
PYTHONDONTWRITEBYTECODE=1
export PYTHONUTF8 PYTHONIOENCODING PYTHONDONTWRITEBYTECODE

SKIP_NPM=0
SKIP_PIP=0
for arg in "$@"; do
  case "$arg" in
    --skip-npm-install) SKIP_NPM=1 ;;
    --skip-pip-install) SKIP_PIP=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "build.sh: unknown option $arg" >&2; exit 1 ;;
  esac
done

. "$SCRIPT_DIR/pythonpick.sh"
mlview_pick_python || exit 1

# Not named `head`: a shell function by that name shadows the real /usr/bin/head
# for the rest of the script, on every platform.
section() { printf '\n== %s\n' "$1"; }

echo "MLView build — repo $REPO_ROOT"
echo "python: $(command -v "$PYTHON")"

section "1/6 webview — install and build the viewer bundle"
cd "$REPO_ROOT/webview"
if [ "$SKIP_NPM" -eq 0 ]; then
  npm install --no-audit --no-fund --prefer-offline
fi
npm run build

section "2/6 tools/sync-assets.py — one renderer in all three places"
cd "$REPO_ROOT"
"$PYTHON" tools/sync-assets.py

# C2: the extension's copy is a gitignored BUILD ARTIFACT, so this step is the
# only thing that puts it on disk for a fresh clone. `npm run compile` in step 4
# runs the same script through vscode-extension/tools/sync-core.mjs, so a build
# that skipped this line would still package a current core — but the plugin's
# tracked copy is synced here too, and `tools/verify.py --vsix` is strict about
# the extension's copy existing.
section "3/6 tools/sync-core.py — vendor the analyzer into the plugin AND the extension"
"$PYTHON" tools/sync-core.py

section "4/6 vscode-extension — install, compile and type-check"
cd "$REPO_ROOT/vscode-extension"
if [ "$SKIP_NPM" -eq 0 ]; then
  npm install --no-audit --no-fund --prefer-offline
fi
npm run compile
npm run check

cd "$REPO_ROOT"
if [ "$SKIP_PIP" -eq 0 ]; then
  section "5/6 analyzer — editable install"
  "$PYTHON" -m pip install -e analyzer --quiet
else
  section "5/6 analyzer — skipped (--skip-pip-install)"
fi

# PACKAGING: the wheel is what `pip install mlview` installs, what the CI-ADOPT
# composite action installs, and what `installCore()` now tells a VS Code user to
# run -- so it is built here rather than by hand at release time. `build` is not a
# hard dependency of this repo: without it the step says so and the build carries
# on, because a missing publishing tool must never redden a developer's build.
section "6/6 analyzer — build the wheel into analyzer/dist"
if "$PYTHON" -c "import build" >/dev/null 2>&1; then
  rm -rf "$REPO_ROOT/analyzer/dist"
  "$PYTHON" -m build --wheel analyzer
  ls -l "$REPO_ROOT/analyzer/dist"
else
  echo "build is not installed - skipping the wheel (pip install build)"
fi

"$PYTHON" -m mlview --version

printf '\nBUILD OK\n'
echo "next: sh scripts/e2e.sh"
