param([switch]$SkipNpmInstall)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'check.py'), 'build')
if ($SkipNpmInstall) { $arguments += '--skip-npm-install' }
& python @arguments
exit $LASTEXITCODE
