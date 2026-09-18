param([switch]$SkipNpmInstall, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'check.py'), 'e2e')
if ($SkipNpmInstall) { $arguments += '--skip-npm-install' }
if ($SkipBuild) { $arguments += '--skip-build' }
& python @arguments
exit $LASTEXITCODE
