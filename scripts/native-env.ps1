param(
    [string]$ToolRoot = "D:\DevTools",
    [string]$CacheRoot = "D:\Caches",
    [switch]$RequireMsvc
)

$env:RUSTUP_HOME = Join-Path $ToolRoot "Rust\rustup"
$env:CARGO_HOME = Join-Path $ToolRoot "Rust\cargo"
$env:CARGO_TARGET_DIR = Join-Path $CacheRoot "ResearchAgent\cargo-target"
$env:PIP_CACHE_DIR = Join-Path $CacheRoot "pip"
$env:npm_config_cache = Join-Path $CacheRoot "npm"
$env:TEMP = Join-Path $CacheRoot "Temp"
$env:TMP = $env:TEMP

foreach ($Path in @(
    $env:RUSTUP_HOME,
    $env:CARGO_HOME,
    $env:CARGO_TARGET_DIR,
    $env:PIP_CACHE_DIR,
    $env:npm_config_cache,
    $env:TEMP
)) {
    New-Item -ItemType Directory -Force $Path | Out-Null
}

$CargoBin = Join-Path $env:CARGO_HOME "bin"
if (($env:PATH -split ";") -notcontains $CargoBin) {
    $env:PATH = "$CargoBin;$env:PATH"
}

$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$Installation = $null
if (Test-Path $VsWhere) {
    $Installation = & $VsWhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
}
if ($Installation) {
    $VsDevCmd = Join-Path $Installation "Common7\Tools\VsDevCmd.bat"
    if (Test-Path $VsDevCmd) {
        & cmd.exe /s /c "`"$VsDevCmd`" -arch=x64 -host_arch=x64 >nul && set" |
            ForEach-Object {
                if ($_ -match "^([^=]+)=(.*)$") {
                    [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
                }
            }
    }
} elseif ($RequireMsvc) {
    throw "MSVC C++ tools were not found. Run scripts/install-build-tools.ps1 elevated."
}
