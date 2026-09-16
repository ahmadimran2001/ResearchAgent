$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
. (Join-Path $PSScriptRoot "native-env.ps1") -RequireMsvc

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Cargo is missing. Install rustup and the Visual Studio 2022 C++ desktop workload."
}

& (Join-Path $PSScriptRoot "build-sidecar.ps1")
npm ci
npm test
npm run build
npm run tauri build
