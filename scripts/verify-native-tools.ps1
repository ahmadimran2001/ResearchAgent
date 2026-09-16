$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "native-env.ps1") -RequireMsvc

foreach ($Command in "rustc", "cargo", "link.exe") {
    $Resolved = Get-Command $Command -ErrorAction Stop
    Write-Host "$Command -> $($Resolved.Source)"
}
rustc --version
cargo --version
link.exe /? 2>&1 | Select-Object -First 1

if (-not $env:WindowsSdkDir -or -not (Test-Path $env:WindowsSdkDir)) {
    throw "Windows SDK was not discovered by the Visual Studio developer environment."
}
Write-Host "Windows SDK -> $env:WindowsSdkDir ($env:WindowsSDKVersion)"
