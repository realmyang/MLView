#!/usr/bin/env sh
# MLView — the end-to-end acceptance run.
#
#   sh scripts/e2e.sh [--skip-build] [--skip-npm-install]
#
# Build everything, run every suite, analyze the dirty sample and its clean twin,
# then run the three parity gates and print a PASS/FAIL table. Exits non-zero if
# any step failed. Every step runs even when an earlier one failed — a table that
# stops at the first failure hides the other three.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")

PYTHONUTF8=1
PYTHONIOENCODING=utf-8
MLVIEW_NO_OPEN=1
# Step 5 (the plugin suite) imports the vendored core and step 14
# (tools/verify.py --all) checks that vendor/ is clean. Without this, the first
# poisons the second and the run is not reproducible (HEALTH-01).
PYTHONDONTWRITEBYTECODE=1
export PYTHONUTF8 PYTHONIOENCODING MLVIEW_NO_OPEN PYTHONDONTWRITEBYTECODE

SKIP_BUILD=0
NPM_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    --skip-npm-install) NPM_FLAG="--skip-npm-install" ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "e2e.sh: unknown option $arg" >&2; exit 1 ;;
  esac
done

PYTHON=${PYTHON:-python}
command -v "$PYTHON" >/dev/null 2>&1 || { echo "FAIL: no python on PATH" >&2; exit 1; }

RESULTS_FILE=$(mktemp 2>/dev/null || echo "$REPO_ROOT/.mlview/e2e-results.txt")
: > "$RESULTS_FILE"
mkdir -p "$REPO_ROOT/.mlview"

record() {  # record <status> <name> <detail>
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$RESULTS_FILE"
  printf '  [%s] %s  %s\n' "$1" "$2" "$3"
}

step() {  # step <name> <workdir> <command...>
  name=$1; workdir=$2; shift 2
  printf '\n== %s\n' "$name"
  ( cd "$workdir" && "$@" )
  code=$?
  if [ $code -eq 0 ]; then record PASS "$name" ""; else record FAIL "$name" "exit $code"; fi
}

echo "MLView end-to-end — repo $REPO_ROOT"

# ------------------------------------------------------------------------- build
if [ "$SKIP_BUILD" -eq 1 ]; then
  record SKIP "build" "--skip-build"
else
  if [ -n "$NPM_FLAG" ]; then
    step "build" "$REPO_ROOT" sh scripts/build.sh "$NPM_FLAG"
  else
    step "build" "$REPO_ROOT" sh scripts/build.sh
  fi
fi

# ------------------------------------------------------------------------ suites
step "analyzer tests"          "$REPO_ROOT"                  "$PYTHON" -m pytest analyzer/tests -q
step "webview tests"           "$REPO_ROOT/webview"          npm test
step "vscode-extension tests"  "$REPO_ROOT/vscode-extension" npm test
step "claude-plugin tests"     "$REPO_ROOT"                  "$PYTHON" -m pytest claude-plugin/tests -q

# ------------------------------------------------------------------ the samples
OUT="$REPO_ROOT/.mlview"
if [ -d "$REPO_ROOT/samples/vision_pipeline" ]; then
  printf '\n== analyze samples/vision_pipeline\n'
  ( cd "$REPO_ROOT" && "$PYTHON" -X utf8 -m mlview analyze samples/vision_pipeline \
      --json "$OUT/graph.json" --html "$OUT/report.html" --format summary )
  code=$?
  if [ $code -eq 0 ]; then
    record PASS "analyze dirty sample" ".mlview/graph.json + .mlview/report.html"
  else
    record FAIL "analyze dirty sample" "exit $code"
  fi
else
  record SKIP "analyze dirty sample" "samples/vision_pipeline does not exist yet"
fi

if [ -d "$REPO_ROOT/samples/vision_pipeline_clean" ]; then
  printf '\n== analyze samples/vision_pipeline_clean\n'
  ( cd "$REPO_ROOT" && "$PYTHON" -X utf8 -m mlview analyze samples/vision_pipeline_clean \
      --json "$OUT/graph_clean.json" --html "$OUT/report_clean.html" --format summary )
  code=$?
  if [ $code -eq 0 ]; then
    record PASS "analyze clean twin" ".mlview/graph_clean.json + .mlview/report_clean.html"
  else
    record FAIL "analyze clean twin" "exit $code"
  fi
else
  record SKIP "analyze clean twin" "samples/vision_pipeline_clean does not exist yet"
fi

# ------------------------------------------------- the report actually renders
# Load the standalone report in jsdom: node cards, all three marker shapes, the
# ghost slots, the seven lane bands, the "not detected" chip, and an openLocation
# on a node click. A report that parses but draws nothing would pass every other
# gate in this file.
if [ -f "$OUT/report.html" ]; then
  step "render report (jsdom)" "$REPO_ROOT/webview" node test/render_report.mjs "$OUT/report.html"
else
  record SKIP "render report (jsdom)" ".mlview/report.html was not produced"
fi

# The clean twin is a demo artifact too, and it exercises a different path: no
# findings at all, so no markers and no ghost slots. --min-ghosts=0 accepts a
# document that declares none; every ghost a document DOES declare must still be
# drawn, so the assertion is not weakened for the dirty report above.
if [ -f "$OUT/report_clean.html" ]; then
  step "render clean report (jsdom)" "$REPO_ROOT/webview" node test/render_report.mjs "$OUT/report_clean.html" --min-ghosts=0
else
  record SKIP "render clean report (jsdom)" ".mlview/report_clean.html was not produced"
fi

# --------------------------------------------------- the scoped demo artifacts
# Feature 2, the three demos from docs/FEATURES_FLOW_AND_SCOPE.md section 8: the
# custom train/test split, model optimization, and evaluation on the inference
# result. Each report embeds the WHOLE graph and merely opens AT the scope, so a
# reader can widen it in the toolbar (CONTRACTS 11.8).
if [ -d "$REPO_ROOT/samples/vision_pipeline" ]; then
  printf '\n== scoped demo artifacts\n'
  scope_failures=0
  # The depths mirror docs/FEATURES_FLOW_AND_SCOPE.md section 8 exactly: Demo B and
  # Demo C take the per-kind default ("-"), Demo D is `--depth 1` -- the ring that
  # shows WHAT FEEDS evaluation (7 core / 7 boundary / 3 context, F2-A6).
  for demo in "unit:train_test_split split.html -" "concern:optimization optimization.html -" "concern:evaluation evaluation.html 1"; do
    spec=${demo%% *}
    rest=${demo#* }
    file=${rest%% *}
    depth=${rest##* }
    if [ "$depth" = "-" ]; then
      ( cd "$REPO_ROOT" && "$PYTHON" -X utf8 -m mlview analyze samples/vision_pipeline \
          --scope "$spec" --html "$OUT/$file" --format summary )
    else
      ( cd "$REPO_ROOT" && "$PYTHON" -X utf8 -m mlview analyze samples/vision_pipeline \
          --scope "$spec" --depth "$depth" --html "$OUT/$file" --format summary )
    fi
    if [ $? -ne 0 ]; then scope_failures=$((scope_failures + 1)); fi
  done
  # A4's size band, measured instead of described. The two figures the docs used
  # to carry ("254-293 KB", "~270 KB of HTML") rotted the moment the viewer bundle
  # grew for the flow and scope UI, because nothing measured them (MLV-R1-H06).
  # The band -- 100 KB to 2 MB with the bundle inlined -- is contractual, so the
  # docs now cite the band and this step checks it over every report the run
  # wrote, printing the real numbers in the table.
  size_detail=", bundle not synced - size band not asserted"
  size_failures=0
  INLINED="$REPO_ROOT/analyzer/src/mlview/emit/assets/mlview.js"
  if [ -s "$INLINED" ]; then
    low=0; high=0; count=0
    for name in report.html report_clean.html split.html optimization.html evaluation.html; do
      [ -f "$OUT/$name" ] || continue
      bytes=$(wc -c < "$OUT/$name" | tr -d ' ')
      count=$((count + 1))
      if [ "$bytes" -lt 102400 ] || [ "$bytes" -gt 2097152 ]; then
        size_failures=$((size_failures + 1))
        echo "  $name is $((bytes / 1024)) KB, outside A4 100 KB - 2 MB"
      fi
      if [ "$low" -eq 0 ] || [ "$bytes" -lt "$low" ]; then low=$bytes; fi
      if [ "$bytes" -gt "$high" ]; then high=$bytes; fi
    done
    if [ "$size_failures" -gt 0 ]; then
      size_detail=", $size_failures outside A4 100 KB - 2 MB"
    elif [ "$count" -gt 0 ]; then
      size_detail=", $count reports $((low / 1024))-$((high / 1024)) KB, inside A4 100 KB - 2 MB"
    fi
  fi
  if [ "$scope_failures" -eq 0 ] && [ "$size_failures" -eq 0 ]; then
    record PASS "scoped demo artifacts" ".mlview/split.html + optimization.html + evaluation.html$size_detail"
  elif [ "$scope_failures" -gt 0 ]; then
    record FAIL "scoped demo artifacts" "$scope_failures of 3 scoped runs failed"
  else
    record FAIL "scoped demo artifacts" "$size_failures report(s) outside A4 100 KB - 2 MB"
  fi
else
  record SKIP "scoped demo artifacts" "samples/vision_pipeline does not exist yet"
fi

# The scoped report must still DRAW: the breadcrumb, the "not in this scope" chip
# row, and only the scope's cards. Two preconditions, each reported as its own
# SKIP reason rather than as a failure, because neither is this step's subject:
# the viewer's own `--scope=` flag, and a report whose INLINED bundle is the one
# `webview/dist` currently holds. A report built before `tools/sync-assets.py` ran
# embeds a pre-scope viewer, which the bundle-hash gate already reports.
BUNDLE_SRC="$REPO_ROOT/webview/dist/mlview.js"
BUNDLE_INLINED="$REPO_ROOT/analyzer/src/mlview/emit/assets/mlview.js"
if [ ! -f "$OUT/evaluation.html" ]; then
  record SKIP "render scoped report (jsdom)" ".mlview/evaluation.html was not produced"
elif ! grep -q -e '--scope=' "$REPO_ROOT/webview/test/render_report.mjs" 2>/dev/null; then
  record SKIP "render scoped report (jsdom)" "webview test/render_report.mjs has no --scope flag yet"
elif ! cmp -s "$BUNDLE_INLINED" "$BUNDLE_SRC"; then
  record SKIP "render scoped report (jsdom)" "the report inlines a stale viewer bundle - run tools/sync-assets.py"
else
  step "render scoped report (jsdom)" "$REPO_ROOT/webview" node test/render_report.mjs "$OUT/evaluation.html" --scope=concern:evaluation
fi

# --------------------------------------------- the extension can load the bundle
step "panel html + media bundle" "$REPO_ROOT/vscode-extension" node --test test/panelhtml.test.js

# Both §11.7 suites stand on ONE side of the wire: the viewer posts into a
# recording bridge, the extension reads a hand-written message. This step joins
# them -- the real dist/mlview.js answers the real setScope, and the real
# out/test-entry.cjs parses what it answers -- so a drifting field name (`spec`
# vs `scope`) fails here instead of in a running editor. It SKIPs itself when the
# extension's test bundle has not been built.
if [ ! -f "$REPO_ROOT/webview/test/crosshost.mjs" ]; then
  record SKIP "cross-host scope handshake" "webview/test/crosshost.mjs is absent"
elif [ ! -f "$REPO_ROOT/vscode-extension/out/test-entry.cjs" ]; then
  record SKIP "cross-host scope handshake" "vscode-extension/out/test-entry.cjs is not built"
else
  step "cross-host scope handshake" "$REPO_ROOT/webview" node test/crosshost.mjs "$OUT/graph.json"
fi

# ------------------------------------------------------------------ parity gates
# CONTRACTS 11.15 puts the scope gate BETWEEN the CLI-vs-MCP parity gate and the
# bundle-hash gate; `--all` runs it in exactly that position. It is also named on
# its own line here, because "the Python projection and the TypeScript port
# disagree" deserves its own row in the table rather than one word inside another.
step "scope parity (tools/verify.py --scopes)" "$REPO_ROOT" "$PYTHON" tools/verify.py --scopes
step "parity gates (tools/verify.py --all)" "$REPO_ROOT" "$PYTHON" tools/verify.py --all

# --------------------------------------------------------------------- the docs
# Dead paths, dead links, and "known gap" bullets that still describe a failure
# somebody already fixed. The gate's own self-test runs first.
step "doc gate self-test"  "$REPO_ROOT" "$PYTHON" scripts/test_check_docs.py
step "docs match the tree" "$REPO_ROOT" "$PYTHON" scripts/check_docs.py

# ------------------------------------------------------------------------- table
echo ""
echo "================ MLView end-to-end ================"
awk -F'\t' '{ printf "  %-6s %-32s %s\n", $1, $2, $3 }' "$RESULTS_FILE"
echo "=================================================="
total=$(wc -l < "$RESULTS_FILE" | tr -d ' ')
failed=$(grep -c '^FAIL' "$RESULTS_FILE" || true)
skipped=$(grep -c '^SKIP' "$RESULTS_FILE" || true)
echo "  $total steps · $failed failed · $skipped skipped"
echo ""

if [ "$failed" -gt 0 ]; then
  echo "E2E FAILED"
  exit 1
fi
echo "E2E OK"
exit 0
