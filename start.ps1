param([string]$InputFile = 'examples\clients.xlsx', [switch]$Demo, [switch]$Check)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Сначала выполните .\setup.ps1'
    exit 1
}
$arguments = @('-m', 'studio', $InputFile)
if ($Demo) { $arguments += '--demo' }
if ($Check) { $arguments += '--check' }
& $python @arguments
exit $LASTEXITCODE
