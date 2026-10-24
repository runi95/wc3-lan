# Installs wc3-lan's menu page on Windows: the "Local Area Network" button appears. Switching the
# game to LAN is a separate step each time: windows\lan-switch.ps1 (see README.md).
#
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1 [-Game "C:\...\Warcraft III"] [-Uninstall]
param(
    [string]$Game = "",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not $Game) {
    $key = "HKLM:\SOFTWARE\WOW6432Node\Blizzard Entertainment\Warcraft III"
    $Game = (Get-ItemProperty -Path $key -Name InstallPath -ErrorAction SilentlyContinue).InstallPath
    if (-not $Game) { $Game = "C:\Program Files (x86)\Warcraft III" }
}
$webui = Join-Path $Game "_retail_\webui"
if (-not (Test-Path (Join-Path $Game "_retail_"))) { throw "No Warcraft III at $Game (use -Game)" }
$page = Join-Path $webui "index.html"
$kept = Join-Path $webui "index.html.before-wc3-lan"

if ($Uninstall) {
    if (Test-Path $kept) { Move-Item -Force $kept $page }
    elseif ((Test-Path $page) -and (Select-String -Quiet -Path $page -Pattern "wc3-lan:")) { Remove-Item $page }
    "done"
    return
}

if (Get-Process -Name "Warcraft III" -ErrorAction SilentlyContinue) { throw "Close Warcraft III first" }
New-Item -ItemType Directory -Force -Path $webui | Out-Null
if ((Test-Path $page) -and -not (Select-String -Quiet -Path $page -Pattern "wc3-lan:") -and -not (Test-Path $kept)) {
    Copy-Item $page $kept
}
$gameExecutable = Join-Path $Game '_retail_\x86_64\Warcraft III.exe'
$buildVersion = (Get-Item -LiteralPath $gameExecutable).VersionInfo.FileVersion
$sourcePage = 'page\index.html'
if ($buildVersion -match '3\.0\.1\.24371') { $sourcePage = 'page\windows-loop.html' }
Copy-Item (Join-Path $root $sourcePage) $page
$settings = "HKCU:\Software\Blizzard Entertainment\Warcraft III"
if (-not (Test-Path $settings)) { New-Item -Path $settings | Out-Null }  # never -Force: it would replace the key
Set-ItemProperty -Path $settings -Name "Allow Local Files" -Type DWord -Value 1
if ($buildVersion -match '3\.0\.1\.24371') {
    "Installed into $webui. Start the game through Battle.net, then use windows\loop-lan.ps1. See docs\windows-24371.md."
} else {
    "Installed into $webui. Read the supported-build requirements before using windows\lan-switch.ps1."
}
