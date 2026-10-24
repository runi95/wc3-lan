param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) 'investigation\loop-bridge' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$object = Join-Path $OutputDirectory 'loop_bridge.obj'
$dll = Join-Path $OutputDirectory 'loop_bridge.dll'
& clang-cl /nologo /c /O2 /GS- /Zl /Oi /clang:-ffreestanding /clang:-fasynchronous-unwind-tables (Join-Path $PSScriptRoot 'loop_bridge.c') "/Fo$object"
if ($LASTEXITCODE) { throw 'LOOP bridge compilation failed.' }
& lld-link /dll /noentry /nodefaultlib /machine:x64 /dynamicbase /nxcompat "/out:$dll" $object
if ($LASTEXITCODE) { throw 'LOOP bridge linking failed.' }
Get-FileHash -LiteralPath $dll -Algorithm SHA256 | Select-Object Path,Hash | ConvertTo-Json
