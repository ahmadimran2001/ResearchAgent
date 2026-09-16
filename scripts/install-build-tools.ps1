param(
    [string]$ToolRoot = "D:\DevTools",
    [string]$CacheRoot = "D:\Caches"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "native-env.ps1") -ToolRoot $ToolRoot -CacheRoot $CacheRoot
$InstallRoot = Join-Path $ToolRoot "Microsoft\VisualStudio\2022\BuildTools"
$SharedRoot = Join-Path $ToolRoot "Microsoft\VisualStudio\Shared"
$InstallerCache = Join-Path $CacheRoot "VisualStudio\Packages"
$Principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window (Run as administrator)."
}
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget was not found. Install Microsoft's App Installer first."
}
$SystemDriveName = $env:SystemDrive.TrimEnd(":")
$SystemFree = (Get-PSDrive $SystemDriveName).Free
if ($SystemFree -lt 4GB) {
    throw "At least 4 GB free is required on $env:SystemDrive for unavoidable Windows SDK and shared components."
}
$InstallDriveName = (Split-Path $InstallRoot -Qualifier).TrimEnd(":")
$InstallDrive = Get-PSDrive $InstallDriveName
if ($InstallDrive.Free -lt 20GB) {
    throw "At least 20 GB free is required on $($InstallDrive.Root) for Build Tools."
}

$TempRoot = Join-Path $CacheRoot "Temp"
New-Item -ItemType Directory -Force $TempRoot | Out-Null
$env:TEMP = $TempRoot
$env:TMP = $TempRoot

winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --silent `
    --accept-package-agreements --accept-source-agreements `
    --override (
        "--wait --quiet --norestart --nocache " +
        "--installPath `"$InstallRoot`" --path cache=`"$InstallerCache`" " +
        "--path shared=`"$SharedRoot`" " +
        "--add Microsoft.VisualStudio.Workload.VCTools " +
        "--add Microsoft.VisualStudio.Component.Windows11SDK.26100 " +
        "--includeRecommended"
    )
if ($LASTEXITCODE -ne 0) {
    throw "Build Tools installer failed with exit code $LASTEXITCODE"
}

Write-Host "Build Tools installation completed. Open a new terminal before building."
