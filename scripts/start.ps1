param([switch]$Live, [int]$Port = 8010, [string]$Database = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'runtime/python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $projectRoot 'server/.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/setup.ps1 first (or use an existing Python environment).' }
$serveArgs = @((Join-Path $PSScriptRoot 'serve.py'), '--port', $Port)
if ($Live) { $serveArgs += '--live' }
if ($Database) { $serveArgs += @('--database', $Database) }
Write-Host "Signal: http://127.0.0.1:$Port | Ctrl+C to stop"
if (-not $Live) { Write-Host 'OFFLINE REPLAY: fixture data, no AI calls.' -ForegroundColor Yellow }
& $python @serveArgs
if ($LASTEXITCODE -ne 0) { throw 'Server stopped with an error. Check port availability and permissions.' }
