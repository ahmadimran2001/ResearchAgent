$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
. (Join-Path $PSScriptRoot "native-env.ps1")

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' was not found. Install Python 3.10 or newer."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js 20 or newer."
}

if (-not (Test-Path .venv)) {
    py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
npm ci

Write-Host "Python and UI dependencies are ready."
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Warning "Rust is missing. Install rustup from https://rustup.rs and the MSVC C++ workload before desktop builds."
}
