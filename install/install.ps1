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
$python = $env:REVAYAT_PYTHON
if (-not $python) {
    foreach ($name in @('python', 'python3')) {
        $found = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
        if ($found) { $python = $found.Source; break }
    }
}
try {
    if (-not $python) { throw 'Python executable was not found' }
    & $python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Python is older than the supported floor' }
} catch {
    [Console]::Error.WriteLine('{0} [ERROR] [installer] Python 3.10+ is required; set REVAYAT_PYTHON.' -f [DateTime]::UtcNow.ToString('o'))
    exit 1
}
$arguments = @('-B', (Join-Path $PSScriptRoot 'safe_install.py'), '--agent', $Agent, '--scope', $Scope, '--path', $Path)
if ($Force) { $arguments += '--force' }
if ($Recover) { $arguments += '--recover' }
& $python @arguments
exit $LASTEXITCODE
