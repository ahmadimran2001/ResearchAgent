param(
    [string]$InstallRoot = "D:\DevTools\Ollama",
    [string]$ModelsRoot = "D:\Caches\Ollama\models",
    [string]$Model = "phi4-mini"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Assert-NotOnCDrive([string]$Path, [string]$Label) {
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if ($resolved.StartsWith("C:\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label cannot be on C: ($resolved). Re-run with -InstallRoot and -ModelsRoot on another drive."
    }
}

Assert-NotOnCDrive $InstallRoot "Ollama install root"
Assert-NotOnCDrive $ModelsRoot "Ollama models root"

. (Join-Path $PSScriptRoot "native-env.ps1")

New-Item -ItemType Directory -Force $InstallRoot | Out-Null
New-Item -ItemType Directory -Force $ModelsRoot | Out-Null

$env:OLLAMA_MODELS = $ModelsRoot
$env:OLLAMA_HOST = "127.0.0.1:11434"
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $ModelsRoot, "User")
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", $env:OLLAMA_HOST, "User")

$OllamaExe = Join-Path $InstallRoot "ollama.exe"
if (-not (Test-Path $OllamaExe)) {
    $Zip = Join-Path $env:TEMP "ollama-windows-amd64.zip"
    $Url = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
    Write-Host "Downloading Ollama to $InstallRoot (not C:)"
    & curl.exe -L --fail --retry 3 -o $Zip $Url
    if ($LASTEXITCODE -ne 0) {
        throw "Could not download Ollama. Check the network and try again."
    }
    $Extract = Join-Path $env:TEMP "ollama-extract"
    if (Test-Path $Extract) {
        Remove-Item -Recurse -Force $Extract
    }
    Expand-Archive -Path $Zip -DestinationPath $Extract -Force
    $Found = Get-ChildItem -Path $Extract -Filter ollama.exe -Recurse | Select-Object -First 1
    if (-not $Found) {
        throw "The Ollama zip did not contain ollama.exe"
    }
    Copy-Item -Force $Found.FullName $OllamaExe
    Get-ChildItem $Extract | ForEach-Object {
        if ($_.Name -ne "ollama.exe") {
            Copy-Item -Force -Recurse $_.FullName (Join-Path $InstallRoot $_.Name)
        }
    }
}

$InstallBin = Split-Path $OllamaExe -Parent
if (($env:PATH -split ";") -notcontains $InstallBin) {
    $env:PATH = "$InstallBin;$env:PATH"
}
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$InstallBin*") {
    [Environment]::SetEnvironmentVariable("Path", "$InstallBin;$userPath", "User")
}

function Test-OllamaReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (Test-OllamaReady) {
    Write-Warning "Ollama is already running. Stop that process first if you need Phi-4 Mini stored at $ModelsRoot instead of the running server's model folder."
} else {
    Write-Host "Starting Ollama with models at $ModelsRoot"
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    $Ready = $false
    for ($Index = 0; $Index -lt 60; $Index++) {
        if (Test-OllamaReady) {
            $Ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $Ready) {
        throw "Ollama did not become ready on 127.0.0.1:11434"
    }
}

Write-Host "Pulling $Model into $ModelsRoot"
& $OllamaExe pull $Model
if ($LASTEXITCODE -ne 0) {
    throw "ollama pull $Model failed"
}
Write-Host "Ollama and $Model are ready. Binary: $OllamaExe"
Write-Host "Models: $ModelsRoot"
