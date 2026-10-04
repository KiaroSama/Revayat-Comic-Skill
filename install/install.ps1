<#
.SYNOPSIS
Install the skill with staged promotion, backups and explicit recovery.
.DESCRIPTION
Requires Python 3.10+. Set REVAYAT_PYTHON to select its executable.
The standard-library helper owns validation, transactions and diagnostic logs.
#>
[CmdletBinding()]
param(
    [ValidateSet('claude','kiro','codex','cursor','cline','hermes','opencode','antigravity','all')]
    [string] $Agent = 'all',
    [ValidateSet('user','project')]
    [string] $Scope = 'user',
    [string] $Path = (Get-Location).Path,
    [switch] $Force,
    [switch] $Recover
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$requestedPython = $env:REVAYAT_PYTHON
$candidates = @()
if ($requestedPython) {
    $candidates = @($requestedPython)
} else {
    foreach ($name in @('python', 'python3')) {
        # ApplicationInfo.Path is one executable. Never invoke an array of
        # matches as a command, and do not let an unusable first match hide
        # another installed interpreter that meets the supported floor.
        foreach ($found in @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)) {
            if ($found.Path -and $found.Path -notin $candidates) {
                $candidates += [string] $found.Path
            }
        }
    }
}
$python = $null
foreach ($candidate in $candidates) {
    try {
        $probe = & $candidate -c 'import sys; print(sys.version_info.major, sys.version_info.minor); sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0 -and ($probe -match '^\d+ \d+$')) {
            $python = $candidate
            break
        }
    } catch {
        # No raw exception/arguments: an explicit override may be sensitive.
        if ($env:REVAYAT_LOG_LEVEL -eq 'DEBUG') {
            [Console]::Error.WriteLine('{0} [DEBUG] [installer] Interpreter probe failed ({1}).' -f [DateTime]::UtcNow.ToString('o'), $_.Exception.GetType().Name)
        }
    }
}
if (-not $python) {
    [Console]::Error.WriteLine('{0} [ERROR] [installer] Python 3.10+ is required; set REVAYAT_PYTHON.' -f [DateTime]::UtcNow.ToString('o'))
    exit 1
}
$arguments = @('-B', (Join-Path $PSScriptRoot 'safe_install.py'), '--agent', $Agent, '--scope', $Scope, '--path', $Path)
if ($Force) { $arguments += '--force' }
if ($Recover) { $arguments += '--recover' }
& $python @arguments
exit $LASTEXITCODE
