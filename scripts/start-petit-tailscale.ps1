param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$ProjectPath = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$LocalUrl = "http://127.0.0.1:$Port"

function Stop-WithMessage([string]$Message) {
    Write-Host "[ERROR] $Message"
    Read-Host "Press Enter to exit"
    exit 1
}

# Tailscale Serve requires an elevated PowerShell on this machine.
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    $elevatedArgs = @(
        "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath, "-Port", $Port
    )
    $elevated = Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -PassThru -ArgumentList $elevatedArgs
    exit $elevated.ExitCode
}

Clear-Host
Write-Host "===================================="
Write-Host "          PETIT Launcher"
Write-Host "===================================="
Write-Host ""
Write-Host "[0] Normal start"
Write-Host "[1] Development start (--reload)"
Write-Host ""

$mode = Read-Host "Select startup mode [0/1]"
if ($mode -notin @("0", "1")) {
    Stop-WithMessage "Enter 0 or 1."
}

if (-not (Test-Path -LiteralPath $ProjectPath)) {
    Stop-WithMessage "PETIT project folder was not found: $ProjectPath"
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    Stop-WithMessage "Virtual-environment Python was not found: $PythonPath"
}
Set-Location -LiteralPath $ProjectPath

Write-Host ""
Write-Host "[1/5] Checking Tailscale..."
$tailscale = Get-Command "tailscale.exe" -ErrorAction SilentlyContinue
if (-not $tailscale) {
    $tailscale = Get-Command "tailscale" -ErrorAction SilentlyContinue
}
if (-not $tailscale) {
    Stop-WithMessage "tailscale.exe was not found. Install Tailscale first."
}

& $tailscale.Source status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Tailscale] Not connected. Running tailscale up..."
    & $tailscale.Source up
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "Tailscale connection failed."
    }
}
Write-Host "[OK] Tailscale connected"

Write-Host ""
Write-Host "[2/5] Starting PETIT..."
$uvicornArgs = @(
    "-m", "uvicorn", "backend.main:app",
    "--host", "127.0.0.1", "--port", $Port,
    "--env-file", ".env"
)
if ($mode -eq "1") {
    $uvicornArgs += @("--reload", "--reload-dir", "backend")
    Write-Host "Mode: DEVELOPMENT / reload ON (watch backend/ only)"
}
else {
    Write-Host "Mode: NORMAL / reload OFF"
}

$serverProcess = Start-Process -FilePath $PythonPath -ArgumentList $uvicornArgs -WorkingDirectory $ProjectPath -PassThru
Write-Host "[OK] PETIT process started (PID: $($serverProcess.Id))"

Write-Host ""
Write-Host "[3/5] Waiting for PETIT health check..."
$started = $false
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-WebRequest -Uri "$LocalUrl/api/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $started = $true
            break
        }
    }
    catch {
    }
    Write-Host -NoNewline "."
}
Write-Host ""
if (-not $started) {
    if (-not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
    }
    Stop-WithMessage "PETIT health check failed: $LocalUrl/api/health"
}
Write-Host "[OK] PETIT is ready"

Write-Host ""
Write-Host "[4/5] Starting Discord Bot..."
$existingBot = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*backend.channels.discord*" } |
    Select-Object -First 1
if ($existingBot) {
    Write-Host "[OK] Discord Bot is already running (PID: $($existingBot.ProcessId))"
}
else {
    $discordConfigured = & $PythonPath -c "import os; from dotenv import load_dotenv; load_dotenv(); print('1' if os.environ.get('DISCORD_BOT_TOKEN') and len(os.environ.get('PETIT_DISCORD_SERVICE_TOKEN','')) >= 32 else '0')"
    if ($discordConfigured -eq "1") {
        $botArgs = @("-m", "backend.channels.discord")
        $botProcess = Start-Process -FilePath $PythonPath -ArgumentList $botArgs -WorkingDirectory $ProjectPath -WindowStyle Minimized -PassThru
        Write-Host "[OK] Discord Bot started (PID: $($botProcess.Id))"
    }
    else {
        Write-Host "[SKIP] Discord Bot settings not found in .env"
    }
}

Write-Host ""
Write-Host "[5/5] Starting Tailscale Serve..."
& $tailscale.Source serve --bg $LocalUrl
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "Tailscale Serve setup failed."
}
Write-Host "[OK] Tailscale Serve is ready"
Write-Host ""
& $tailscale.Source serve status

Start-Process $LocalUrl
Write-Host ""
Write-Host "PETIT is ready: $LocalUrl"
Write-Host "The server continues after closing this launcher window."
Read-Host "Press Enter to exit"
