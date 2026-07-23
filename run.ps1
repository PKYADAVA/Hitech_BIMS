# Hitech BIMS - clean dev server launcher.
#
# Why this exists: launching `python manage.py runserver` from several
# terminals (some with the venv active, some not) leaves duplicate/stale
# server processes bound to port 8000, so the browser serves OLD code and
# newly-added templates 404. This script guarantees ONE fresh server from
# the project's own venv every time.
#
# Usage (from the project root):  .\run.ps1  [extra runserver args]
#   e.g.  .\run.ps1              -> http://127.0.0.1:8000
#         .\run.ps1 0.0.0.0:8080 -> bind all interfaces on 8080

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "venv python not found at $venvPython - create the venv first."
    exit 1
}

# Kill every existing Django dev server (any python, venv or system).
$stale = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -like '*manage.py*runserver*' }
if ($stale) {
    Write-Host ("Stopping {0} stale runserver process(es): {1}" -f `
        $stale.Count, ($stale.ProcessId -join ", ")) -ForegroundColor Yellow
    $stale | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
}

Write-Host "Starting fresh dev server from the venv..." -ForegroundColor Green
& $venvPython (Join-Path $root "manage.py") runserver @args
