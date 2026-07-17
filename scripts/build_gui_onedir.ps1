# Build green onedir package for YilanChengWen (一览成文).
# Strategy (same as JingYe / PDF project):
#   dist/YilanChengWen/                    -> always latest (overwrite)
#   dist/releases/YilanChengWen-x.y.z/     -> versioned folder (optional large)
#   dist/releases/YilanChengWen-x.y.z.zip  -> versioned zip (share this)
#
# IMPORTANT: Do NOT put Chinese string literals in this .ps1 for filenames.
# Windows PowerShell 5.1 often mis-decodes script encoding and corrupts names.
# All Chinese text/files are written by packaging/*.py with utf-8-sig.
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File scripts\build_gui_onedir.ps1
# Optional:
#   -SkipInstall       skip pip install
#   -WithModels        bundle models/ (very large)
#   -SkipZip           skip versioned zip
#   -SkipReleaseDir    only zip, do not copy full versioned folder (~1GB)

param(
    [switch]$SkipInstall,
    [switch]$WithModels,
    [switch]$SkipZip,
    [switch]$SkipReleaseDir
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    $Py = "python"
    Write-Host "Warning: .venv not found, using system python"
}

Write-Host "Project root: $Root"
Write-Host "Python: $Py"

# Single source of truth: package __version__
$env:PYTHONPATH = (Join-Path $Root "src")
$ver = & $Py -c "from video_to_article import __version__; print(__version__)"
if (-not $ver) { $ver = "0.0.0" }
$ver = $ver.Trim()
Write-Host "Version: $ver"

if (-not $SkipInstall) {
    Write-Host "==> Installing GUI + packaging deps"
    & $Py -m pip install -q "PySide6>=6.6" "PySide6-Fluent-Widgets>=1.6" "pyinstaller>=6.0"
}

$DistRoot = Join-Path $Root "dist"
$Build = Join-Path $Root "build"
$Spec = Join-Path $Root "packaging\video_to_article_gui.spec"
$AppName = "YilanChengWen"
$OutDir = Join-Path $DistRoot $AppName

Write-Host "==> Cleaning previous dist/$AppName (if any)"
if (Test-Path $OutDir) {
    Remove-Item -Recurse -Force $OutDir
}

Write-Host "==> PyInstaller onedir (may take a long time)"
& $Py -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath $Build $Spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$ExePath = Join-Path $OutDir "$AppName.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build finished but $AppName.exe not found under $OutDir"
}

# FunASR imports package data version.txt; fail fast if PyInstaller dropped it
$funasrVersion = Join-Path $OutDir "_internal\funasr\version.txt"
if (-not (Test-Path -LiteralPath $funasrVersion)) {
    throw "Missing bundled FunASR data: $funasrVersion (check packaging/*.spec collect_data_files('funasr'))"
}
Write-Host "    FunASR version.txt OK: $funasrVersion"

Write-Host "==> Assembling runtime files next to exe"
$exSrc = Join-Path $Root "config.example.json"
if (Test-Path $exSrc) {
    Copy-Item $exSrc (Join-Path $OutDir "config.example.json") -Force
}

# Bundle FFmpeg (prefer project ffmpeg\, else PATH / VQE_FFMPEG_DIR)
Write-Host "==> Bundling FFmpeg into dist"
$ffmpegTarget = Join-Path $OutDir "ffmpeg"
& $Py (Join-Path $Root "packaging\bundle_ffmpeg.py") --target $ffmpegTarget --also-project
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: FFmpeg not bundled. Users need system FFmpeg or copy into ffmpeg\"
}

$PromptsDst = Join-Path $OutDir "prompts"
$PromptsSrc = Join-Path $Root "prompts"
if (Test-Path $PromptsSrc) {
    if (Test-Path $PromptsDst) {
        Remove-Item $PromptsDst -Recurse -Force
    }
    Copy-Item $PromptsSrc $PromptsDst -Recurse -Force
}

$cfg = Join-Path $OutDir "config.json"
$ex = Join-Path $OutDir "config.example.json"
if ((-not (Test-Path $cfg)) -and (Test-Path $ex)) {
    Copy-Item $ex $cfg -Force
    Write-Host "    created config.json from example (fill API keys before use)"
}

if ($WithModels) {
    Write-Host "==> Copying models/ (large)"
    $modelsSrc = Join-Path $Root "models"
    if (Test-Path $modelsSrc) {
        Copy-Item $modelsSrc (Join-Path $OutDir "models") -Recurse -Force
    }
}

$Launcher = Join-Path $OutDir "start.bat"
@(
    "@echo off",
    "cd /d ""%~dp0""",
    "start """" ""%~dp0$AppName.exe"""
) | Set-Content -Path $Launcher -Encoding ascii

# Meta: VERSION.txt / README / Chinese 使用说明 (UTF-8 BOM via Python)
Write-Host "==> Writing dist meta (VERSION / readme)"
& $Py (Join-Path $Root "packaging\write_dist_meta.py") $OutDir $ver
if ($LASTEXITCODE -ne 0) {
    throw "write_dist_meta.py failed"
}

# Versioned release under dist/releases/
$relRoot = Join-Path $DistRoot "releases"
$relDirName = "$AppName-$ver"
$relDir = Join-Path $relRoot $relDirName
New-Item -ItemType Directory -Force -Path $relRoot | Out-Null

if (-not $SkipReleaseDir) {
    Write-Host "==> Copying versioned release folder: $relDir"
    if (Test-Path -LiteralPath $relDir) {
        Remove-Item -LiteralPath $relDir -Recurse -Force
    }
    & $Py -c @"
import shutil
from pathlib import Path
src = Path(r'''$OutDir''')
dst = Path(r'''$relDir''')
if dst.exists():
    shutil.rmtree(dst)
shutil.copytree(src, dst, dirs_exist_ok=False)
print('copied to', dst)
"@
}

if (-not $SkipZip) {
    $zipPath = Join-Path $relRoot ("{0}-{1}.zip" -f $AppName, $ver)
    Write-Host "==> Zipping: $zipPath"
    $zipSrc = $OutDir
    if ((-not $SkipReleaseDir) -and (Test-Path -LiteralPath $relDir)) {
        $zipSrc = $relDir
    }
    # clear logs before zip
    $logsDir = Join-Path $zipSrc "logs"
    if (Test-Path $logsDir) {
        Remove-Item (Join-Path $logsDir "*") -Force -Recurse -ErrorAction SilentlyContinue
    }
    & $Py (Join-Path $Root "packaging\make_release_zip.py") $zipSrc $zipPath
    if ($LASTEXITCODE -ne 0) {
        throw "make_release_zip.py failed"
    }
}

Write-Host ""
Write-Host "OK latest : $OutDir\$AppName.exe"
if (-not $SkipReleaseDir) {
    Write-Host "OK release: $relDir"
}
if (-not $SkipZip) {
    Write-Host "OK zip    : $relRoot\$AppName-$ver.zip"
}
Write-Host "Version   : $ver"
Write-Host "Share the zip under dist\releases\ ; keep dist\$AppName as working latest."
Write-Host ""
