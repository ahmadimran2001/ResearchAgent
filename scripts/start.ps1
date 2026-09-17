param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 1420
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Project Python environment is missing. Run scripts/setup-windows.ps1 first."
}
if (-not (Test-Path .env) -and (Test-Path .env.example)) {
    Copy-Item .env.example .env
}

function Test-PortOpen([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(300, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

$logDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$stdoutLog = Join-Path $logDir "sidecar-stdout.log"
$stderrLog = Join-Path $logDir "sidecar-stderr.log"

$backend = $null
if (Test-PortOpen $BackendPort) {
    Write-Host "Backend already running on port $BackendPort"
} else {
    Write-Host "Starting backend (this can take up to a minute on first launch)..."
    $backend = Start-Process -FilePath $python -WorkingDirectory $Root -ArgumentList @(
        "-m", "uvicorn", "backend.app.main:app",
        "--host", "127.0.0.1",
        "--port", "$BackendPort"
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
    $ready = $false
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        if ($backend.HasExited) {
            Write-Host "Backend exited with code $($backend.ExitCode). Log:"
            if (Test-Path $stderrLog) { Get-Content $stderrLog -ErrorAction SilentlyContinue }
            if (Test-Path $stdoutLog) { Get-Content $stdoutLog -ErrorAction SilentlyContinue }
            throw "Backend failed to start. See data/logs/sidecar-stderr.log"
        }
        if (Test-PortOpen $BackendPort) {
            $ready = $true
            break
        }
        Write-Host "  waiting for http://127.0.0.1:$BackendPort ..."
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        if (Test-Path $stderrLog) { Get-Content $stderrLog -ErrorAction SilentlyContinue }
        throw "Backend did not open port $BackendPort. See data/logs/"
    }
}

Write-Host "Starting UI on http://127.0.0.1:$FrontendPort (Ctrl+C stops the UI)"
Start-Job -ScriptBlock {
    param($Url)
    Start-Sleep -Seconds 2
    Start-Process $Url
} -ArgumentList "http://127.0.0.1:$FrontendPort" | Out-Null

try {
    npm run dev
} finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$($backend.Id)" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }
}
