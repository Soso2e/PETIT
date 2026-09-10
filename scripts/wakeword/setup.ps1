param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Push-Location $root
try {
    & $Python -m venv storage/wakeword/.venv
    if ($LASTEXITCODE) { throw 'venv creation failed' }
    & storage/wakeword/.venv/Scripts/python.exe -m pip install -r scripts/wakeword/requirements.txt
    if ($LASTEXITCODE) { throw 'Dependency installation failed' }
    & storage/wakeword/.venv/Scripts/python.exe scripts/wakeword/train.py --download-only
    if ($LASTEXITCODE) { throw 'Feature model download failed' }
} finally { Pop-Location }
