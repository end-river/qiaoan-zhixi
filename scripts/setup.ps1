$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not (Get-Command python.exe -ErrorAction SilentlyContinue)) {
    throw 'Python 3.11 or later is required. Install it and add it to PATH before retrying.'
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Node.js and npm are required. Install Node.js, then reopen the installer.'
}
python.exe -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
if ($LASTEXITCODE -ne 0) { throw 'A working Python 3.11 or later is required.' }

Write-Host '[1/3] Preparing the Python environment...'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python.exe -m venv --without-pip .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python venv setup failed.' }
}
Write-Host '[2/3] Installing Python dependencies...'
python.exe -m pip --python .venv install --disable-pip-version-check -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed.' }
Write-Host '[3/3] Installing and building the web interface...'
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host 'Setup complete. Double-click the platform launcher next.' -ForegroundColor Green
