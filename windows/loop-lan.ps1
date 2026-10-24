param(
    [ValidateSet('query', 'list', 'join')]
    [string]$Action = 'list',
    [string]$HostAddress = '127.0.0.1',
    [string]$Name = '',
    [int]$ProcessId = 0,
    [switch]$KeepProvider,
    [int]$WatchSeconds = 5
)
$ErrorActionPreference = 'Stop'
$bridge = Join-Path (Split-Path -Parent $PSScriptRoot) 'investigation\loop-bridge\loop_bridge.dll'
$source = Join-Path $PSScriptRoot 'loop_bridge.c'
if (-not (Test-Path -LiteralPath $bridge) -or
    (Get-Item -LiteralPath $source).LastWriteTimeUtc -gt
    (Get-Item -LiteralPath $bridge).LastWriteTimeUtc) {
    & (Join-Path $PSScriptRoot 'build-loop-bridge.ps1')
}
$loopArguments = @(
    '-u', (Join-Path $PSScriptRoot 'loop-lan.py'),
    '--action', $Action,
    '--host-address', $HostAddress,
    '--watch-seconds', "$WatchSeconds"
)
if (-not $KeepProvider) {
    $loopArguments += '--initialize'
}
if ($Name) {
    $loopArguments += @('--name', $Name)
}
if ($ProcessId) {
    $loopArguments += @('--pid', "$ProcessId")
}
& python @loopArguments
exit $LASTEXITCODE
