param([string]$PythonCommand = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & $PythonCommand -c "import sys; assert sys.version_info >= (3, 12), 'Python 3.12+ required'"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
    & $PythonCommand -m venv server/.venv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment.' }
    & ./server/.venv/Scripts/python.exe -m pip install -r server/requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed.' }
    Push-Location app
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
} finally { Pop-Location }
Write-Host 'Ready. Run scripts/start.ps1 for offline replay.' -ForegroundColor Green
