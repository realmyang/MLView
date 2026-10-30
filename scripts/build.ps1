param([switch]$SkipNpmInstall)
$ErrorActionPreference = 'Stop'

# Pick the interpreter like scripts/pythonpick.sh. $env:PYTHON wins when set, but it must qualify;
# otherwise python, py -3 and python3 are tried in that order, so an activated virtualenv or
# setup-python wins. A candidate must report Python 3.10+ and must not resolve under \WindowsApps\
# (the Microsoft Store app-execution alias, which is not an interpreter).
function Resolve-MLViewPython([string]$Name, [string[]]$Prefix) {
    $ErrorActionPreference = 'Continue'
    $command = Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command -or $command.Path -like '*\WindowsApps\*') { return $null }
    try {
        & $command.Path @Prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' *> $null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -eq 0) { return $command.Path }
    return $null
}

$python = $null
$pythonPrefix = @()
if ($env:PYTHON) {
    $python = Resolve-MLViewPython $env:PYTHON @()
    if (-not $python) {
        [Console]::Error.WriteLine("FAIL: PYTHON=$env:PYTHON is not a Python 3.10+ interpreter (a \WindowsApps\ Store alias does not count)")
        exit 1
    }
} else {
    foreach ($candidate in @(@{ Name = 'python'; Prefix = @() }, @{ Name = 'py'; Prefix = @('-3') }, @{ Name = 'python3'; Prefix = @() })) {
        $python = Resolve-MLViewPython $candidate.Name $candidate.Prefix
        if ($python) { $pythonPrefix = $candidate.Prefix; break }
    }
    if (-not $python) {
        [Console]::Error.WriteLine('FAIL: no Python 3.10+ found (tried: python, py -3, python3)')
        [Console]::Error.WriteLine('      set $env:PYTHON to a Python 3.10+ interpreter and re-run')
        exit 1
    }
}

$arguments = @($pythonPrefix) + @((Join-Path $PSScriptRoot 'check.py'), 'build')
if ($SkipNpmInstall) { $arguments += '--skip-npm-install' }
& $python @arguments
exit $LASTEXITCODE
