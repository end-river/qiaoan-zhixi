[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Host 'Python environment missing. Run the dependency installer first.' -ForegroundColor Red
    exit 1
}
$launcherArgs = @('-m', 'scripts.launch', '--port', $Port)
if ($NoBrowser) { $launcherArgs += '--no-browser' }
& $pythonExe @launcherArgs
exit $LASTEXITCODE
