param([string]$Output = '', [string]$Baseline = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'runtime/python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $projectRoot 'server/.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/setup.ps1 first.' }
$evalArgs = @((Join-Path $PSScriptRoot 'evaluate.py'))
if ($Output) { $evalArgs += @('--output', $Output) }
if ($Baseline) { $evalArgs += @('--baseline', $Baseline) }
& $python @evalArgs
if ($LASTEXITCODE -ne 0) { throw 'Evaluation failed. Inspect report and console output.' }
