$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Path '.tmp' -Force | Out-Null
$env:TEMP = Join-Path $PSScriptRoot '.tmp'
$env:TMP = $env:TEMP
python -m venv .venv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& '.\.venv\Scripts\python.exe' -c "from pathlib import Path; import pandas as pd; pd.read_csv('examples/clients.csv', sep=';').to_excel('examples/clients.xlsx', index=False)"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
Write-Host 'Установка завершена. Проверка без AI: .\start.ps1 -Demo'
