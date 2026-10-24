param(
    [Parameter(Mandatory=$true)]
    [string]$Map,
    [string]$Name = 'WC3-LAN',
    [string[]]$PlayerNames = @('Player1', 'Player2'),
    [int]$ControlPort = 8778,
    [int]$OpponentSeat = -1,
    [string]$HostBinary = ''
)
$ErrorActionPreference = 'Stop'
if (-not $HostBinary) {
    $HostBinary = Join-Path (Split-Path -Parent $PSScriptRoot) 'investigation\references\wc3-slop-lan\host\target\release\wc3-slop-lan.exe'
}
if (-not (Test-Path -LiteralPath $HostBinary)) {
    throw 'Build the external host first; see docs/windows-24371.md.'
}
$mapPath = (Resolve-Path -LiteralPath $Map).Path
$hostArguments = @(
    'host', '--map', $mapPath,
    '--name', $Name,
    '--control', "$ControlPort"
)
if ($OpponentSeat -ge 0) {
    $hostArguments += @('--host', 'active', '--seat', "$OpponentSeat")
}
$hostArguments += $PlayerNames
& $HostBinary @hostArguments
exit $LASTEXITCODE
