# Build the Windows installer: dist\AutoVideo-Setup-<version>.exe
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# Needs uv, FFmpeg (winget install --id Gyan.FFmpeg -e) and
# Inno Setup (winget install --id JRSoftware.InnoSetup -e --scope user).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot)

function Find-Tool([string] $Name, [string[]] $Candidates) {
    $onPath = Get-Command $Name -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    foreach ($pattern in $Candidates) {
        $found = Get-ChildItem $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    throw "$Name not found. See the top of packaging\build.ps1 for how to install it."
}

$winget = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"
$uv = Find-Tool "uv" @("$winget\astral-sh.uv_*\uv.exe")
$ffmpeg = Find-Tool "ffmpeg" @("$winget\Gyan.FFmpeg*\*\bin\ffmpeg.exe")
$iscc = Find-Tool "iscc" @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
                           "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe")
$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value

Write-Host "AutoVideo $version  (FFmpeg: $ffmpeg)"
& $uv sync --inexact --no-install-project  # the libraries only: works while AutoVideo is open
if ($LASTEXITCODE) { throw "uv sync failed" }

$env:AUTOVIDEO_FFMPEG = $ffmpeg
& $uv run --no-sync pyinstaller packaging\autovideo.spec --noconfirm --clean `
    --distpath dist --workpath build\pyinstaller
if ($LASTEXITCODE) { throw "PyInstaller failed" }

& $iscc /Qp "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
Write-Host "Installer: dist\AutoVideo-Setup-$version.exe"
