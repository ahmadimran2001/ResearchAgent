param(
    [string]$ToolRoot = "D:\DevTools",
    [string]$CacheRoot = "D:\Caches",
    [switch]$RemoveMigratedSource
)

$ErrorActionPreference = "Stop"
$SourceRustup = Join-Path $env:USERPROFILE ".rustup"
$SourceCargo = Join-Path $env:USERPROFILE ".cargo"
$DestinationRustup = Join-Path $ToolRoot "Rust\rustup"
$DestinationCargo = Join-Path $ToolRoot "Rust\cargo"

if (Get-Process cargo, rustc, rustup -ErrorAction SilentlyContinue) {
    throw "Close Cargo, rustc, and rustup processes before migration."
}

function Copy-And-Verify([string]$Source, [string]$Destination) {
    if (-not (Test-Path $Source)) {
        return
    }
    New-Item -ItemType Directory -Force $Destination | Out-Null
    & robocopy.exe $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS
    if ($LASTEXITCODE -ge 8) {
        throw "Robocopy failed for $Source with exit code $LASTEXITCODE"
    }
    $SourceFiles = Get-ChildItem $Source -Recurse -File
    $DestinationFiles = Get-ChildItem $Destination -Recurse -File
    $SourceBytes = ($SourceFiles | Measure-Object Length -Sum).Sum
    $DestinationBytes = ($DestinationFiles | Measure-Object Length -Sum).Sum
    if (
        $SourceFiles.Count -ne $DestinationFiles.Count -or
        $SourceBytes -ne $DestinationBytes
    ) {
        throw "Migration verification failed for $Source"
    }
    Write-Host (
        "Verified migration: $Source -> $Destination " +
        "($($SourceFiles.Count) files, $SourceBytes bytes)"
    )
}

Copy-And-Verify $SourceRustup $DestinationRustup
Copy-And-Verify $SourceCargo $DestinationCargo

$Settings = @{
    RUSTUP_HOME = $DestinationRustup
    CARGO_HOME = $DestinationCargo
    CARGO_TARGET_DIR = (Join-Path $CacheRoot "ResearchAgent\cargo-target")
    PIP_CACHE_DIR = (Join-Path $CacheRoot "pip")
    npm_config_cache = (Join-Path $CacheRoot "npm")
    TEMP = (Join-Path $CacheRoot "Temp")
    TMP = (Join-Path $CacheRoot "Temp")
}
foreach ($Item in $Settings.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($Item.Key, $Item.Value, "User")
}

$CargoBin = Join-Path $DestinationCargo "bin"
$UserPath = [Environment]::GetEnvironmentVariable("PATH", "User")
$OldCargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$PathItems = @($UserPath -split ";" | Where-Object {
    $_ -and $_.TrimEnd("\") -ne $OldCargoBin.TrimEnd("\")
})
if ($PathItems -notcontains $CargoBin) {
    $PathItems = @($CargoBin) + $PathItems
}
[Environment]::SetEnvironmentVariable("PATH", ($PathItems -join ";"), "User")

. (Join-Path $PSScriptRoot "native-env.ps1") -ToolRoot $ToolRoot -CacheRoot $CacheRoot
& (Join-Path $CargoBin "rustc.exe") --version
& (Join-Path $CargoBin "cargo.exe") --version

if ($RemoveMigratedSource) {
    foreach ($Pair in @(
        @($SourceRustup, $DestinationRustup),
        @($SourceCargo, $DestinationCargo)
    )) {
        if (Test-Path $Pair[0]) {
            if (-not (Test-Path $Pair[1])) {
                throw "Refusing source removal because destination is missing: $($Pair[1])"
            }
            Remove-Item $Pair[0] -Recurse -Force
            Write-Host "Removed verified migrated source: $($Pair[0])"
        }
    }
}
