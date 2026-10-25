param()
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitProcess) { throw 'Use 64-bit PowerShell.' }
$clang = (Get-Command clang-cl -ErrorAction Stop).Source
$link = (Get-Command lld-link -ErrorAction Stop).Source
$object = Join-Path $PSScriptRoot 'lan.obj'
$library = Join-Path $PSScriptRoot 'lan.dll'
& $clang /nologo /c /O2 /GS- /Zl "/Fo$object" (Join-Path $PSScriptRoot 'lan.c')
if ($LASTEXITCODE -ne 0) { throw 'Native LAN compilation failed.' }
& $link /dll /noentry /nodefaultlib "/out:$library" $object
if ($LASTEXITCODE -ne 0) { throw 'Native LAN link failed.' }
Write-Host "Built $library"
