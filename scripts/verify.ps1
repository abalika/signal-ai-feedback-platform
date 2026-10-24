$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'server\.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Missing server/.venv. Follow server/README.md to install backend dependencies.'
}

Write-Host '1/5 Frontend lint and request tests'
Push-Location (Join-Path $projectRoot 'app')
try {
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed.' }

    npm test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend request tests failed.' }

    Write-Host '2/5 Frontend production build'
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
finally {
    Pop-Location
}

Write-Host '3/5 Backend tests'
Push-Location $projectRoot
try {
    & $python -m pytest server/tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
}
finally {
    Pop-Location
}

Write-Host '4/5 Offline workflow and retrieval evaluation'
& $python (Join-Path $PSScriptRoot 'evaluate.py')
if ($LASTEXITCODE -ne 0) { throw 'Offline evaluation failed.' }
Write-Host '5/5 HTTP deployment smoke'
& $python (Join-Path $PSScriptRoot 'smoke.py')
if ($LASTEXITCODE -ne 0) { throw 'HTTP deployment smoke failed.' }
& $python (Join-Path $PSScriptRoot 'check_publication.py')
if ($LASTEXITCODE -ne 0) { throw 'Publication privacy check failed.' }
Write-Host 'All local verification checks passed.' -ForegroundColor Green
