[CmdletBinding()]
param(
    [ValidateSet("start", "status", "stop")]
    [string]$Action = "start",

    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-TailscaleCommand {
    $command = Get-Command "tailscale.exe" -ErrorAction SilentlyContinue
    if (-not $command) {
        $command = Get-Command "tailscale" -ErrorAction SilentlyContinue
    }
    if (-not $command) {
        throw "Tailscaleコマンドが見つかりません。Tailscaleをインストールし、PowerShellを開き直してください。"
    }
    return $command.Source
}

function Assert-PetitIsRunning {
    $healthUrl = "http://127.0.0.1:$Port/api/health"
    try {
        $null = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 5
    }
    catch {
        throw "PETITへ接続できません: $healthUrl`n先にLM StudioとPETITを起動してください。"
    }
    Write-Host "PETIT接続OK: $healthUrl"
}

$tailscale = Get-TailscaleCommand

switch ($Action) {
    "start" {
        if (-not (Test-IsAdministrator)) {
            throw "管理者として実行したPowerShellで再実行してください。"
        }

        Assert-PetitIsRunning
        Write-Host "Tailscale Serveを開始します。公開範囲はtailnet内のみです。"
        & $tailscale serve --bg "http://127.0.0.1:$Port"
        if ($LASTEXITCODE -ne 0) {
            throw "Tailscale Serveの開始に失敗しました。終了コード: $LASTEXITCODE"
        }

        Write-Host ""
        Write-Host "iPhoneで開くURLを確認してください:"
        & $tailscale serve status
        if ($LASTEXITCODE -ne 0) {
            throw "Tailscale Serveの状態確認に失敗しました。終了コード: $LASTEXITCODE"
        }
    }

    "status" {
        & $tailscale serve status
        if ($LASTEXITCODE -ne 0) {
            throw "Tailscale Serveの状態確認に失敗しました。終了コード: $LASTEXITCODE"
        }
    }

    "stop" {
        if (-not (Test-IsAdministrator)) {
            throw "管理者として実行したPowerShellで再実行してください。"
        }

        Write-Host "このPCのTailscale Serve設定をリセットします。"
        & $tailscale serve reset
        if ($LASTEXITCODE -ne 0) {
            throw "Tailscale Serveの停止に失敗しました。終了コード: $LASTEXITCODE"
        }
        Write-Host "Tailscale Serveを停止しました。"
    }
}
