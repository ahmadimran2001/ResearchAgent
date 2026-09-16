param(
    [int]$Port = 18771
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$Runtime = Join-Path $Root "data\packaged-sidecar-verification"
$Temp = Join-Path $Runtime "tmp"
New-Item -ItemType Directory -Force $Temp | Out-Null

$Token = "verification-$([guid]::NewGuid().ToString('N'))"
$env:TMP = $Temp
$env:TEMP = $Temp
$env:RESEARCH_AGENT_IPC_TOKEN = $Token
$env:RESEARCH_AGENT_DESKTOP = "1"
$env:DATABASE_PATH = Join-Path $Runtime "history.sqlite3"
$env:UPLOAD_PATH = Join-Path $Runtime "uploads"
$env:EXPERIMENT_ARTIFACT_PATH = Join-Path $Runtime "experiments"
$env:LITERATURE_CACHE_PATH = Join-Path $Runtime "cache"
$env:EXPORT_PATH = Join-Path $Runtime "exports"
$env:RESEARCH_AGENT_STARTUP_LOG = Join-Path $Runtime "startup.log"

$Executable = Join-Path $Root "src-tauri\binaries\research-agent-python-x86_64-pc-windows-msvc.exe"
if (-not (Test-Path $Executable)) {
    throw "Packaged sidecar not found. Run scripts/build-sidecar.ps1 first."
}
$Process = Start-Process -FilePath $Executable `
    -ArgumentList "--host", "127.0.0.1", "--port", "$Port" -PassThru

function Get-ResponseText($Response) {
    if ($Response.Content -is [byte[]]) {
        return [System.Text.Encoding]::UTF8.GetString($Response.Content)
    }
    return [string]$Response.Content
}

try {
    $Headers = @{ Authorization = "Bearer $Token" }
    $Ready = $false
    for ($Index = 0; $Index -lt 240; $Index++) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "Packaged sidecar exited with code $($Process.ExitCode)"
        }
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" `
                -Headers $Headers -TimeoutSec 1
            if ($Health.status -eq "ok") {
                $Ready = $true
                break
            }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    if (-not $Ready) {
        throw "Packaged sidecar did not become ready"
    }

    $Unauthorized = 0
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/health" `
            -TimeoutSec 2 | Out-Null
        throw "Unauthenticated health unexpectedly succeeded"
    } catch {
        if ($_.Exception.Message -eq "Unauthenticated health unexpectedly succeeded") {
            throw
        }
        $Unauthorized = $_.Exception.Response.StatusCode.value__
    }

    $Conversation = Invoke-RestMethod -Method Post `
        -Uri "http://127.0.0.1:$Port/api/chat/conversations" -Headers $Headers `
        -ContentType "application/json" -Body '{"model_id":"phi4-mini"}'
    $PhiRequest = @{
        conversation_id = $Conversation.id
        content = "Reply with exactly READY."
        model_id = "phi4-mini"
    } | ConvertTo-Json
    $Phi = Invoke-WebRequest -UseBasicParsing -Method Post `
        -Uri "http://127.0.0.1:$Port/api/chat/stream" -Headers $Headers `
        -ContentType "application/json" -Body $PhiRequest -TimeoutSec 180
    $Messages = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$Port/api/chat/conversations/$($Conversation.id)/messages" `
        -Headers $Headers

    $PhiCompleted = (Get-ResponseText $Phi) -match '"type"\s*:\s*"message.completed"'
    Write-Output (
        "health=$($Health.status) unauthorized=$Unauthorized " +
        "phi_completed=$PhiCompleted restored_messages=$($Messages.Count)"
    )
    if ($Unauthorized -ne 401 -or -not $PhiCompleted) {
        exit 1
    }
} finally {
    $Current = Get-CimInstance Win32_Process -Filter "ProcessId=$($Process.Id)" `
        -ErrorAction SilentlyContinue
    if ($Current -and $Current.ExecutablePath -eq $Executable) {
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
    }
}
