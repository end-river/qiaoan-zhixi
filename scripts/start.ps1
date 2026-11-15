$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Please run scripts\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Frontend is not built. Run scripts\setup.ps1 first.' }
Write-Host 'Bridge Insight: http://127.0.0.1:8000'
& $pythonExe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
