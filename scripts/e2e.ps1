# MLView -- the end-to-end acceptance run.
#
#   powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1 -SkipBuild
#
# Build everything, run every suite, analyze the dirty sample and its clean twin,
# then run the three parity gates and print a PASS/FAIL table. Exits non-zero if
# any step failed. Every step runs even when an earlier one failed -- a table that
# stops at the first failure hides the other three.
#
# Windows PowerShell 5.1 compatible: no `&&`, no `||`, no ternaries.

param(
    [switch]$SkipBuild,
    [switch]$SkipNpmInstall
)

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:MLVIEW_NO_OPEN = '1'
# Step 5 (the plugin suite) imports the vendored core and step 14
# (tools/verify.py --all) checks that vendor/ is clean. Without this, the first
# poisons the second and the run is not reproducible (HEALTH-01).
$env:PYTHONDONTWRITEBYTECODE = '1'

$script:Results = @()

function Add-Result {
    param([string]$Name, [string]$Status, [string]$Detail)
    $script:Results += [pscustomobject]@{ Name = $Name; Status = $Status; Detail = $Detail }
    $color = 'Green'
    if ($Status -eq 'FAIL') { $color = 'Red' }
    if ($Status -eq 'SKIP') { $color = 'Yellow' }
    Write-Host ('  [' + $Status + '] ' + $Name + '  ' + $Detail) -ForegroundColor $color
}

function Invoke-Step {
    param([string]$Name, [string]$WorkDir, [scriptblock]$Body, [string]$Detail = '')
    Write-Host ''
    Write-Host ('== ' + $Name) -ForegroundColor Cyan
    Push-Location $WorkDir
    $global:LASTEXITCODE = 0
    & $Body
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -eq 0) {
        Add-Result $Name 'PASS' $Detail
    } else {
        Add-Result $Name 'FAIL' ('exit ' + $code)
    }
}

function Resolve-Python {
    $found = Get-Command 'python' -ErrorAction SilentlyContinue
    if ($null -ne $found) { return $found.Source }
    Write-Host 'FAIL: no python interpreter on PATH' -ForegroundColor Red
    exit 1
}

$Python = Resolve-Python
$OutDir = Join-Path $RepoRoot '.mlview'
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

Write-Host ('MLView end-to-end -- repo ' + $RepoRoot)

# ------------------------------------------------------------------------- build
if ($SkipBuild) {
    Add-Result 'build' 'SKIP' '-SkipBuild'
} else {
    $buildArgs = @('-ExecutionPolicy', 'Bypass', '-File', (Join-Path $RepoRoot 'scripts/build.ps1'))
    if ($SkipNpmInstall) { $buildArgs += '-SkipNpmInstall' }
    Invoke-Step 'build' $RepoRoot { powershell @buildArgs }
}

# ------------------------------------------------------------------------ suites
Invoke-Step 'analyzer tests' $RepoRoot { & $Python -m pytest analyzer/tests -q }
Invoke-Step 'webview tests' (Join-Path $RepoRoot 'webview') { npm test }
Invoke-Step 'vscode-extension tests' (Join-Path $RepoRoot 'vscode-extension') { npm test }
# HEALTH-03: the plugin suite is subprocess-bound, not compute-bound -- 234
# tests take 38 s serially and 11 s under xdist, with the same outcome. `-n auto`
# only when xdist is installed, so a bare interpreter still runs the gate.
# find_spec instead of `import xdist` so a missing plugin prints nothing at all:
# redirecting a native command's stderr in PowerShell 5.1 turns clean output into
# a NativeCommandError.
& $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('xdist') else 1)"
$Xdist = if ($LASTEXITCODE -eq 0) { @('-n', 'auto') } else { @() }
Invoke-Step 'claude-plugin tests' $RepoRoot { & $Python -m pytest claude-plugin/tests -q @Xdist }

# ------------------------------------------------------------------ the samples
$Dirty = Join-Path $RepoRoot 'samples/vision_pipeline'
$Clean = Join-Path $RepoRoot 'samples/vision_pipeline_clean'

if (Test-Path $Dirty) {
    Write-Host ''
    Write-Host '== analyze samples/vision_pipeline' -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Python -X utf8 -m mlview analyze $Dirty --json (Join-Path $OutDir 'graph.json') --html (Join-Path $OutDir 'report.html') --format summary
    $code = $LASTEXITCODE
    # 0 = clean, 2 = --fail-on threshold (not used here); anything else is a failure.
    if ($code -eq 0) {
        Add-Result 'analyze dirty sample' 'PASS' '.mlview/graph.json + .mlview/report.html'
    } else {
        Add-Result 'analyze dirty sample' 'FAIL' ('exit ' + $code)
    }
} else {
    Add-Result 'analyze dirty sample' 'SKIP' 'samples/vision_pipeline does not exist yet'
}

if (Test-Path $Clean) {
    Write-Host ''
    Write-Host '== analyze samples/vision_pipeline_clean' -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Python -X utf8 -m mlview analyze $Clean --json (Join-Path $OutDir 'graph_clean.json') --html (Join-Path $OutDir 'report_clean.html') --format summary
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        Add-Result 'analyze clean twin' 'PASS' '.mlview/graph_clean.json + .mlview/report_clean.html'
    } else {
        Add-Result 'analyze clean twin' 'FAIL' ('exit ' + $code)
    }
} else {
    Add-Result 'analyze clean twin' 'SKIP' 'samples/vision_pipeline_clean does not exist yet'
}

# ------------------------------------------------- the report actually renders
# Load the standalone report in jsdom: node cards, all three marker shapes, the
# ghost slots, the seven lane bands, the "not detected" chip, and an openLocation
# on a node click. A report that parses but draws nothing would pass every other
# gate in this file.
$Report = Join-Path $OutDir 'report.html'
if (Test-Path $Report) {
    Invoke-Step 'render report (jsdom)' (Join-Path $RepoRoot 'webview') { node test/render_report.mjs $Report }
} else {
    Add-Result 'render report (jsdom)' 'SKIP' '.mlview/report.html was not produced'
}

# The clean twin is a demo artifact too, and it exercises a different path: no
# findings at all, so no markers and no ghost slots. --min-ghosts=0 accepts a
# document that declares none; every ghost a document DOES declare must still be
# drawn, so the assertion is not weakened for the dirty report above.
$ReportClean = Join-Path $OutDir 'report_clean.html'
if (Test-Path $ReportClean) {
    Invoke-Step 'render clean report (jsdom)' (Join-Path $RepoRoot 'webview') { node test/render_report.mjs $ReportClean --min-ghosts=0 }
} else {
    Add-Result 'render clean report (jsdom)' 'SKIP' '.mlview/report_clean.html was not produced'
}

# --------------------------------------------------- the scoped demo artifacts
# Feature 2, the three demos from docs/FEATURES_FLOW_AND_SCOPE.md section 8: the
# custom train/test split, model optimization, and evaluation on the inference
# result. Each report embeds the WHOLE graph and merely opens AT the scope, so a
# reader can widen it in the toolbar (CONTRACTS 11.8).
$Split = Join-Path $OutDir 'split.html'
$Optimization = Join-Path $OutDir 'optimization.html'
$Evaluation = Join-Path $OutDir 'evaluation.html'
if (Test-Path $Dirty) {
    Write-Host ''
    Write-Host '== scoped demo artifacts' -ForegroundColor Cyan
    $scopeFailures = 0
    # The depths mirror docs/FEATURES_FLOW_AND_SCOPE.md section 8 exactly: Demo B
    # and Demo C take the per-kind default, Demo D is `--depth 1` -- the ring that
    # shows WHAT FEEDS evaluation (7 core / 7 boundary / 3 context, F2-A6).
    $scopeDemos = @(
        @('unit:train_test_split', $Split, ''),
        @('concern:optimization', $Optimization, ''),
        @('concern:evaluation', $Evaluation, '1')
    )
    foreach ($demo in $scopeDemos) {
        $global:LASTEXITCODE = 0
        if ($demo[2] -eq '') {
            & $Python -X utf8 -m mlview analyze $Dirty --scope $demo[0] --html $demo[1] --format summary
        } else {
            & $Python -X utf8 -m mlview analyze $Dirty --scope $demo[0] --depth $demo[2] --html $demo[1] --format summary
        }
        if ($LASTEXITCODE -ne 0) { $scopeFailures = $scopeFailures + 1 }
    }
    # A4's size band, measured instead of described. The two figures the docs used
    # to carry ("254-293 KB", "~270 KB of HTML") rotted the moment the viewer
    # bundle grew for the flow and scope UI, because nothing measured them
    # (MLV-R1-H06). The band -- 100 KB to 2 MB with the bundle inlined -- is
    # contractual, so the docs now cite the band and this step checks it over
    # every report the run wrote, printing the real numbers in the table.
    $Inlined = Join-Path $RepoRoot 'analyzer/src/mlview/emit/assets/mlview.js'
    $bundlePresent = $false
    if (Test-Path $Inlined) { $bundlePresent = (Get-Item $Inlined).Length -gt 0 }
    $sizeDetail = ', bundle not synced - size band not asserted'
    $sizeFailures = 0
    if ($bundlePresent) {
        $reports = @()
        foreach ($name in @('report.html', 'report_clean.html', 'split.html', 'optimization.html', 'evaluation.html')) {
            $file = Join-Path $OutDir $name
            if (Test-Path $file) { $reports += (Get-Item $file) }
        }
        $outside = @($reports | Where-Object { ($_.Length -lt 102400) -or ($_.Length -gt 2097152) })
        $sizeFailures = $outside.Count
        if ($sizeFailures -gt 0) {
            foreach ($bad in $outside) {
                Write-Host ('  ' + $bad.Name + ' is ' + [int]($bad.Length / 1024) + ' KB, outside A4 100 KB - 2 MB') -ForegroundColor Red
            }
            $sizeDetail = ', ' + $sizeFailures + ' outside A4 100 KB - 2 MB'
        } elseif ($reports.Count -gt 0) {
            $low = [int](($reports | Measure-Object -Property Length -Minimum).Minimum / 1024)
            $high = [int](($reports | Measure-Object -Property Length -Maximum).Maximum / 1024)
            $sizeDetail = ', ' + $reports.Count + ' reports ' + $low + '-' + $high + ' KB, inside A4 100 KB - 2 MB'
        }
    }
    if (($scopeFailures -eq 0) -and ($sizeFailures -eq 0)) {
        Add-Result 'scoped demo artifacts' 'PASS' ('.mlview/split.html + optimization.html + evaluation.html' + $sizeDetail)
    } elseif ($scopeFailures -gt 0) {
        Add-Result 'scoped demo artifacts' 'FAIL' ($scopeFailures.ToString() + ' of 3 scoped runs failed')
    } else {
        Add-Result 'scoped demo artifacts' 'FAIL' ($sizeFailures.ToString() + ' report(s) outside A4 100 KB - 2 MB')
    }
} else {
    Add-Result 'scoped demo artifacts' 'SKIP' 'samples/vision_pipeline does not exist yet'
}

# The scoped report must still DRAW: the breadcrumb, the "not in this scope" chip
# row, and only the scope's cards. Two preconditions, each reported as its own
# SKIP reason rather than as a failure, because neither is this step's subject:
# the viewer's own `--scope=` flag, and a report whose INLINED bundle is the one
# webview/dist currently holds. A report built before tools/sync-assets.py ran
# embeds a pre-scope viewer, which the bundle-hash gate already reports.
$RenderReport = Join-Path $RepoRoot 'webview/test/render_report.mjs'
$ScopeFlag = $false
if (Test-Path $RenderReport) {
    $ScopeFlag = (Select-String -Path $RenderReport -Pattern '--scope=' -SimpleMatch -Quiet) -eq $true
}
$BundleSrc = Join-Path $RepoRoot 'webview/dist/mlview.js'
$BundleInlined = Join-Path $RepoRoot 'analyzer/src/mlview/emit/assets/mlview.js'
$BundleSynced = $false
if ((Test-Path $BundleSrc) -and (Test-Path $BundleInlined)) {
    $BundleSynced = (Get-FileHash $BundleSrc).Hash -eq (Get-FileHash $BundleInlined).Hash
}
if (-not (Test-Path $Evaluation)) {
    Add-Result 'render scoped report (jsdom)' 'SKIP' '.mlview/evaluation.html was not produced'
} elseif (-not $ScopeFlag) {
    Add-Result 'render scoped report (jsdom)' 'SKIP' 'webview test/render_report.mjs has no --scope flag yet'
} elseif (-not $BundleSynced) {
    Add-Result 'render scoped report (jsdom)' 'SKIP' 'the report inlines a stale viewer bundle - run tools/sync-assets.py'
} else {
    Invoke-Step 'render scoped report (jsdom)' (Join-Path $RepoRoot 'webview') { node test/render_report.mjs $Evaluation --scope=concern:evaluation }
}

# --------------------------------------------- the extension can load the bundle
Invoke-Step 'panel html + media bundle' (Join-Path $RepoRoot 'vscode-extension') { node --test test/panelhtml.test.js }

# Both §11.7 suites stand on ONE side of the wire: the viewer posts into a
# recording bridge, the extension reads a hand-written message. This step joins
# them -- the real dist/mlview.js answers the real setScope, and the real
# out/test-entry.cjs parses what it answers -- so a drifting field name (`spec`
# vs `scope`) fails here instead of in a running editor. It SKIPs itself when the
# extension's test bundle has not been built.
$CrossHost = Join-Path $RepoRoot 'webview/test/crosshost.mjs'
if (-not (Test-Path $CrossHost)) {
    Add-Result 'cross-host scope handshake' 'SKIP' 'webview/test/crosshost.mjs is absent'
} elseif (-not (Test-Path (Join-Path $RepoRoot 'vscode-extension/out/test-entry.cjs'))) {
    Add-Result 'cross-host scope handshake' 'SKIP' 'vscode-extension/out/test-entry.cjs is not built'
} else {
    Invoke-Step 'cross-host scope handshake' (Join-Path $RepoRoot 'webview') { node test/crosshost.mjs (Join-Path $OutDir 'graph.json') }
}

# ------------------------------------------------------------------ parity gates
# CONTRACTS 11.15 puts the scope gate BETWEEN the CLI-vs-MCP parity gate and the
# bundle-hash gate; `--all` runs it in exactly that position. It is also named on
# its own line here, because "the Python projection and the TypeScript port
# disagree" deserves its own row in the table rather than one word inside another.
Invoke-Step 'scope parity (tools/verify.py --scopes)' $RepoRoot { & $Python tools/verify.py --scopes }
Invoke-Step 'parity gates (tools/verify.py --all)' $RepoRoot { & $Python tools/verify.py --all }

# ------------------------------------------------------------------ the referee
# ANA-12. The analyzer over `analyzer/tests/accuracy/corpus/`, scored against its
# hand-written labels: zero `forbidden` findings ever, and recall and graph
# fidelity may only ratchet up against analyzer/tests/accuracy/baseline.json.
# It runs in well under a second, so the acceptance run carries it rather than
# leaving the only accuracy signal on a machine that can reach GitHub Actions.
Invoke-Step 'accuracy corpus' $RepoRoot { & $Python tools/accuracy.py }

# --------------------------------------------------------------------- the docs
# Dead paths, dead links, and "known gap" bullets that still describe a failure
# somebody already fixed. The gate's own self-test runs first.
Invoke-Step 'doc gate self-test' $RepoRoot { & $Python scripts/test_check_docs.py }
Invoke-Step 'docs match the tree' $RepoRoot { & $Python scripts/check_docs.py }

# ------------------------------------------------------------------------- table
Write-Host ''
Write-Host '================ MLView end-to-end ================'
foreach ($row in $script:Results) {
    Write-Host ('  {0,-6} {1,-32} {2}' -f $row.Status, $row.Name, $row.Detail)
}
Write-Host '=================================================='

$failed = @($script:Results | Where-Object { $_.Status -eq 'FAIL' })
$skipped = @($script:Results | Where-Object { $_.Status -eq 'SKIP' })
Write-Host ('  ' + $script:Results.Count + ' steps | ' + $failed.Count + ' failed | ' + $skipped.Count + ' skipped')
Write-Host ''

if ($failed.Count -gt 0) {
    Write-Host 'E2E FAILED' -ForegroundColor Red
    exit 1
}
Write-Host 'E2E OK' -ForegroundColor Green
exit 0
