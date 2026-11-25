<#
.SYNOPSIS
Install the Revayat Comic skill with staged promotion, backups and explicit recovery.
.DESCRIPTION
Invokes the pure-Rust revayat-comic CLI binary (no Python required).
Set REVAYAT_BIN to override binary discovery.
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

$repoRoot = Split-Path -Parent $PSScriptRoot
$candidates = @()
if ($env:REVAYAT_BIN) { $candidates += $env:REVAYAT_BIN }
$candidates += (Join-Path $repoRoot 'bin\revayat-comic.exe')
$candidates += (Join-Path $repoRoot 'target\release\revayat-comic.exe')
$onPath = Get-Command revayat-comic -CommandType Application -ErrorAction SilentlyContinue
if ($onPath) { $candidates += $onPath.Path }

$binary = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $binary) {
    [Console]::Error.WriteLine('{0} [ERROR] [installer] revayat-comic.exe not found; build with "cargo build --release --locked -p revayat-comic-cli" or set REVAYAT_BIN.' -f [DateTime]::UtcNow.ToString('o'))
    exit 1
}

$arguments = @('install', '--agent', $Agent, '--scope', $Scope, '--path', $Path)
if ($Force) { $arguments += '--force' }
if ($Recover) { $arguments += '--recover' }
& $binary @arguments
exit $LASTEXITCODE
