param([switch]$WithoutML, [switch]$SkipInstaller, [switch]$SingleFile)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:OS -ne "Windows_NT") { throw "Build requires Windows x64" }
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "Install uv and Python 3.11 x64 first; see README.md"
}
$sync = @("sync", "--locked", "--python", "3.11", "--extra", "build")
if (-not $WithoutML) { $sync += @("--extra", "ml") }
& uv @sync
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
$python = Join-Path $root ".venv\Scripts\python.exe"
$ffmpeg = (Get-Command ffmpeg.exe -ErrorAction Stop).Source
$ffprobe = (Get-Command ffprobe.exe -ErrorAction Stop).Source
if ($env:ChocolateyInstall -and $ffmpeg.StartsWith((Join-Path $env:ChocolateyInstall "bin"))) {
    $realFfmpeg = Get-ChildItem (Join-Path $env:ChocolateyInstall "lib\ffmpeg") -Filter ffmpeg.exe -Recurse |
        Select-Object -First 1
    if (-not $realFfmpeg) { throw "Cannot resolve Chocolatey FFmpeg shim" }
    $ffmpeg = $realFfmpeg.FullName
    $ffprobe = Join-Path (Split-Path $ffmpeg) "ffprobe.exe"
    if (-not (Test-Path $ffprobe)) { throw "FFprobe missing next to FFmpeg" }
}
$tools = Join-Path $root "build\bundled_tools"
New-Item -ItemType Directory -Force -Path $tools | Out-Null
Copy-Item -LiteralPath $ffmpeg -Destination (Join-Path $tools "ffmpeg.exe") -Force
Copy-Item -LiteralPath $ffprobe -Destination (Join-Path $tools "ffprobe.exe") -Force
Get-ChildItem (Split-Path $ffmpeg) -Filter *.dll | Copy-Item -Destination $tools -Force
$tesseract = Get-Command tesseract.exe -ErrorAction SilentlyContinue
$tesseractPath = if ($tesseract) { $tesseract.Source } else { $null }
$standardTesseract = Join-Path $env:ProgramFiles "Tesseract-OCR\tesseract.exe"
if (Test-Path $standardTesseract) { $tesseractPath = $standardTesseract }
if ($tesseractPath -and $env:ChocolateyInstall -and
    $tesseractPath.StartsWith((Join-Path $env:ChocolateyInstall "bin"))) {
    throw "Resolve the Tesseract shim to its installation directory before bundling"
}
if ($tesseractPath) {
    # Tesseract's DLLs and tessdata must travel with the executable.
    Copy-Item -Path (Join-Path (Split-Path $tesseractPath) "*") -Destination $tools -Recurse -Force
}
$licenses = Join-Path $root "build\third_party_licenses"
& $python scripts\collect_licenses.py $licenses
if ($LASTEXITCODE -ne 0) { throw "License collection failed" }
$layout = if ($SingleFile) { "--onefile" } else { "--onedir" }
$arguments = @("-m", "PyInstaller", "--noconfirm", "--clean", $layout, "--windowed",
    "--additional-hooks-dir", "scripts\pyinstaller_hooks",
    "--name", "GuitarTabAI", "--collect-all", "guitar_tab_ai",
    "--collect-all", "librosa", "--collect-all", "soundfile", "--copy-metadata", "guitar-tab-ai",
    "--add-data", "$tools;tools", "--add-data", "docs\THIRD_PARTY.md;.",
    "--add-data", "$licenses;third_party_licenses",
    "--exclude-module", "tensorflow", "--exclude-module", "tensorboard", "--exclude-module", "keras")
if (-not $WithoutML) {
    $arguments += @("--collect-all", "basic_pitch", "--collect-all", "onnxruntime",
        "--collect-all", "resampy", "--copy-metadata", "resampy")
}
# Explicitly retain Qt runtime plugins; hook discovery can fail in isolated
# Windows/Wine child processes even when importing PySide6 normally succeeds.
$pyside = Join-Path $root ".venv\Lib\site-packages\PySide6"
foreach ($group in @("platforms", "multimedia", "imageformats", "iconengines", "styles")) {
    $directory = Join-Path $pyside "plugins\$group"
    if (Test-Path $directory) {
        $arguments += @("--add-binary", "$directory\*.dll;PySide6\plugins\$group")
    }
}
foreach ($pattern in @("avcodec*.dll", "avformat*.dll", "avutil*.dll", "swresample*.dll", "swscale*.dll")) {
    foreach ($library in (Get-ChildItem $pyside -Filter $pattern)) {
        $arguments += @("--add-binary", "$($library.FullName);PySide6")
    }
}
$arguments += "src\guitar_tab_ai\app\main.py"
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
if ($SingleFile) {
    Write-Host "Portable executable: dist\GuitarTabAI.exe"
    if (-not $SkipInstaller) { Write-Host "SingleFile builds skip the directory-based installer" }
    exit 0
}
Copy-Item -Path $licenses -Destination dist\GuitarTabAI\third_party_licenses -Recurse -Force
Copy-Item docs\THIRD_PARTY.md dist\GuitarTabAI\THIRD_PARTY.md -Force
if ($SkipInstaller) { exit 0 }
$iscc = $env:INNO_ISCC
if (-not $iscc) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $iscc = $command.Source }
}
if (-not $iscc) {
    $candidate = Get-ChildItem "${env:ProgramFiles(x86)}\Inno Setup*" -Filter ISCC.exe -Recurse |
        Select-Object -First 1
    if ($candidate) { $iscc = $candidate.FullName }
}
if (-not $iscc) { throw "Inno Setup 6 not found. Install it or use -SkipInstaller." }
& $iscc installer\guitar_tab_ai.iss
if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed" }
$installer = Join-Path $root "dist_installer\GuitarTabAISetup.exe"
$hash = (Get-FileHash -Algorithm SHA256 $installer).Hash.ToLowerInvariant()
"$hash  GuitarTabAISetup.exe" | Set-Content dist_installer\SHA256SUMS.txt -Encoding ascii
Write-Host "Built $installer"
