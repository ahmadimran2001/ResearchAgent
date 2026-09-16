$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
. (Join-Path $PSScriptRoot "native-env.ps1")

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing .venv. Run scripts/setup-windows.ps1 first."
}

& $Python -m PyInstaller --clean --noconfirm backend/research-agent-sidecar.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
$Bundle = Join-Path $Root "dist\research-agent-sidecar"
$Source = Join-Path $Bundle "research-agent-sidecar.exe"
$RuntimeSource = Join-Path $Bundle "_internal"
if (-not (Test-Path $Source) -or -not (Test-Path $RuntimeSource)) {
    throw "PyInstaller did not produce a complete onedir bundle at $Bundle"
}

$DestinationDirectory = Join-Path $Root "src-tauri\binaries"
New-Item -ItemType Directory -Force $DestinationDirectory | Out-Null
$Destination = Join-Path $DestinationDirectory "research-agent-python-x86_64-pc-windows-msvc.exe"
Copy-Item $Source $Destination -Force
$RuntimeDestination = Join-Path $DestinationDirectory "_internal"
if (Test-Path $RuntimeDestination) {
    Remove-Item $RuntimeDestination -Recurse -Force
}
Copy-Item $RuntimeSource $RuntimeDestination -Recurse -Force
Write-Host "Sidecar ready: $Destination"
