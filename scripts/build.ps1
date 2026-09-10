# MLView -- build everything, in the only order that works.
#
#   powershell -ExecutionPolicy Bypass -File scripts/build.ps1
#
# 1. webview          npm install + npm run build       -> webview/dist/mlview.{js,css}
# 2. tools/sync-assets.py                               -> the extension and the analyzer get the SAME bundle
# 3. tools/sync-core.py                                 -> claude-plugin/vendor/mlview (no pip install for the plugin)
# 4. vscode-extension npm install + compile + check     -> out/extension.js, tsc clean
# 5. analyzer         pip install -e                    -> `python -m mlview` on this interpreter
#
# The order matters: sync-assets must run after the viewer is built and before the
# analyzer emits anything, because `generator.rendererSha` is the SHA-256 of the
# bundle the analyzer ships. Written for Windows PowerShell 5.1: no `&&`, no `||`,
# no ternaries -- every step checks $LASTEXITCODE explicitly.

param(
    [switch]$SkipNpmInstall,   # reuse the existing node_modules
    [switch]$SkipPipInstall    # the analyzer is already installed in this interpreter
)

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# Never leave bytecode behind: step 3 vendors the analyzer into the plugin and
# any __pycache__ under claude-plugin/vendor would ship with it (HEALTH-01).
$env:PYTHONDONTWRITEBYTECODE = '1'

function Write-Head {
    param([string]$Text)
    Write-Host ''
    Write-Host ('== ' + $Text) -ForegroundColor Cyan
}

function Assert-Ok {
    param([string]$Name)
    if ($LASTEXITCODE -ne 0) {
        Write-Host ('FAIL: ' + $Name + ' (exit ' + $LASTEXITCODE + ')') -ForegroundColor Red
        exit 1
    }
}

function Resolve-Python {
    $candidates = @('python', 'py')
    foreach ($candidate in $candidates) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $found) { return $found.Source }
    }
    Write-Host 'FAIL: no python interpreter on PATH' -ForegroundColor Red
    exit 1
}

$Python = Resolve-Python
Write-Host ('MLView build -- repo ' + $RepoRoot)
Write-Host ('python: ' + $Python)

# --------------------------------------------------------------- 1. viewer bundle
Write-Head '1/6 webview -- install and build the viewer bundle'
Push-Location (Join-Path $RepoRoot 'webview')
if (-not $SkipNpmInstall) {
    $global:LASTEXITCODE = 0
    npm install --no-audit --no-fund --prefer-offline
    Assert-Ok 'npm install (webview)'
}
$global:LASTEXITCODE = 0
npm run build
Assert-Ok 'npm run build (webview)'
Pop-Location

# ---------------------------------------------------------------- 2. sync assets
Write-Head '2/6 tools/sync-assets.py -- one renderer in all three places'
$global:LASTEXITCODE = 0
& $Python (Join-Path $RepoRoot 'tools/sync-assets.py')
Assert-Ok 'sync-assets'

# ------------------------------------------------------------------ 3. sync core
Write-Head '3/6 tools/sync-core.py -- vendor the analyzer into the plugin AND the extension'
$global:LASTEXITCODE = 0
& $Python (Join-Path $RepoRoot 'tools/sync-core.py')
Assert-Ok 'sync-core'

# ------------------------------------------------------------- 4. vscode extension
Write-Head '4/6 vscode-extension -- install, compile and type-check'
Push-Location (Join-Path $RepoRoot 'vscode-extension')
if (-not $SkipNpmInstall) {
    $global:LASTEXITCODE = 0
    npm install --no-audit --no-fund --prefer-offline
    Assert-Ok 'npm install (vscode-extension)'
}
$global:LASTEXITCODE = 0
npm run compile
Assert-Ok 'npm run compile (vscode-extension)'
$global:LASTEXITCODE = 0
npm run check
Assert-Ok 'npm run check (vscode-extension)'
Pop-Location

# ---------------------------------------------------------------- 5. analyzer core
if (-not $SkipPipInstall) {
    Write-Head '5/6 analyzer -- editable install'
    $global:LASTEXITCODE = 0
    & $Python -m pip install -e (Join-Path $RepoRoot 'analyzer') --quiet
    Assert-Ok 'pip install -e analyzer'
} else {
    Write-Head '5/6 analyzer -- skipped (-SkipPipInstall)'
}

# PACKAGING: the wheel `pip install mlview`, the CI-ADOPT action and the VS Code
# install prompt all name. `build` is not a hard dependency: without it the step
# says so and the build carries on.
Write-Head '6/6 analyzer -- build the wheel into analyzer/dist'
& $Python -c 'import build' 2>$null
if ($LASTEXITCODE -eq 0) {
    $dist = Join-Path $RepoRoot 'analyzer/dist'
    if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
    $global:LASTEXITCODE = 0
    & $Python -m build --wheel (Join-Path $RepoRoot 'analyzer')
    Assert-Ok 'python -m build --wheel analyzer'
    Get-ChildItem $dist | Format-Table Name, Length
} else {
    Write-Host 'build is not installed - skipping the wheel (pip install build)'
}

$global:LASTEXITCODE = 0
& $Python -m mlview --version
Assert-Ok 'python -m mlview --version'

Write-Host ''
Write-Host 'BUILD OK' -ForegroundColor Green
Write-Host 'next: powershell -ExecutionPolicy Bypass -File scripts/e2e.ps1'
exit 0
