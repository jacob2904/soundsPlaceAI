# Build the CineSFX Windows installer (build\CineSFX-Setup.exe).
#
# Run on Windows in PowerShell (needs Python + Inno Setup's ISCC on PATH).
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build_exe.ps1
#
# Optional: drop static FFmpeg binaries into build\payload\ffmpeg before this so
# the plugin needs nothing else installed.
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$Payload = Join-Path $RepoRoot "build\payload"

Write-Host "Staging payload (+ vendored deps) into $Payload ..."
python "$RepoRoot\packaging\stage_payload.py" --out $Payload

# Locate the Inno Setup compiler.
$Iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $candidate = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $candidate) { $Iscc = $candidate }
}
if (-not $Iscc) {
    throw "Inno Setup (ISCC.exe) not found. Install from https://jrsoftware.org/isdl.php"
}

Write-Host "Compiling installer with $Iscc ..."
& $Iscc "$RepoRoot\packaging\windows\CineSFX.iss"

Write-Host ""
Write-Host "Built: $RepoRoot\build\CineSFX-Setup.exe"
Write-Host "(For public distribution, sign the .exe with signtool — see packaging\README.md.)"
