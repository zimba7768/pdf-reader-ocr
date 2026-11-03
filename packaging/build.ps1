<#
.SYNOPSIS
  Builds the PyInstaller bundle, copies a trimmed Tesseract next to it and
  compiles the Inno Setup installer.

.USAGE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-Version 0.1.0] [-TesseractDir "C:\Program Files\Tesseract-OCR"] [-SkipInstaller]

  Requires: the project's Python environment on PATH (or .venv), Tesseract
  installed (UB-Mannheim build or choco), Inno Setup 6.
#>
param(
    [string]$Version = "",
    [string]$TesseractDir = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

# ---- python ---------------------------------------------------------------
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

if (-not $Version) {
    $Version = (& $py -c "import sys; sys.path.insert(0,'src'); import pdf_reader_ocr; print(pdf_reader_ocr.__version__)").Trim()
}
Write-Host "==> Building PDF Reader OCR $Version"

# ---- pyinstaller ----------------------------------------------------------
if (Test-Path "dist\PDFReaderOCR") { Remove-Item -Recurse -Force "dist\PDFReaderOCR" }
& $py -m PyInstaller "packaging\pdf_reader_ocr.spec" --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# ---- bundle tesseract -----------------------------------------------------
if (-not $TesseractDir) {
    foreach ($cand in @("$env:ProgramFiles\Tesseract-OCR", "${env:ProgramFiles(x86)}\Tesseract-OCR", "$env:LOCALAPPDATA\Programs\Tesseract-OCR", "C:\tools\tesseract")) {
        if (Test-Path (Join-Path $cand "tesseract.exe")) { $TesseractDir = $cand; break }
    }
}
if (-not $TesseractDir -or -not (Test-Path (Join-Path $TesseractDir "tesseract.exe"))) {
    throw "Tesseract not found. Install it or pass -TesseractDir."
}
$dest = "dist\PDFReaderOCR\tesseract"
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
New-Item -ItemType Directory -Force "$dest\tessdata" | Out-Null

# Copy tesseract.exe plus every DLL it (transitively) imports from the install
# folder, determined from the PE import tables. This is deterministic and does
# not depend on what happens to be on PATH on the build machine.
$runtime = & $py "packaging\tess_deps.py" $TesseractDir
if ($LASTEXITCODE -ne 0 -or -not $runtime) { throw "tess_deps.py failed" }
foreach ($n in $runtime) { Copy-Item (Join-Path $TesseractDir $n) $dest }
Write-Host "==> Tesseract runtime files: $($runtime -join ', ')"
foreach ($f in @("eng.traineddata", "pdf.ttf")) {
    $src = Join-Path $TesseractDir "tessdata\$f"
    if (Test-Path $src) { Copy-Item $src "$dest\tessdata" } else { Write-Warning "missing tessdata\$f" }
}
if (Test-Path (Join-Path $TesseractDir "tessdata\configs")) {
    Copy-Item -Recurse -Force (Join-Path $TesseractDir "tessdata\configs") "$dest\tessdata\configs"
}
foreach ($lic in @("LICENSE", "LICENSE.txt", "README.md")) {
    $src = Join-Path $TesseractDir $lic
    if (Test-Path $src) { Copy-Item $src "$dest\TESSERACT-$lic" }
}

# Self-check: run the bundled tesseract.exe with PATH reduced to the Windows
# system folder only, so a DLL found elsewhere on this machine (Git's mingw
# folder ships libcurl, libcrypto...) cannot mask a missing file in the bundle.
# A missing DLL makes the loader exit with 0xC0000135 (-1073741515).
$savedPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$env:TESSDATA_PREFIX = (Resolve-Path "$dest\tessdata").Path
$langs = & "$dest\tesseract.exe" --list-langs 2>&1
$code = $LASTEXITCODE
$env:PATH = $savedPath
Remove-Item Env:\TESSDATA_PREFIX
if ($code -ne 0 -or -not ($langs -match "eng")) {
    throw "Bundled tesseract.exe does not run in isolation (exit $code): $langs"
}
Write-Host "==> Bundled Tesseract from $TesseractDir ($((Get-ChildItem $dest -Recurse | Measure-Object Length -Sum).Sum / 1MB) MB)"

# ---- installer ------------------------------------------------------------
if ($SkipInstaller) { Write-Host "==> Skipping installer"; exit 0 }

$iscc = ""
foreach ($cand in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $cand) { $iscc = $cand; break }
}
if (-not $iscc) { $cmd = Get-Command iscc -ErrorAction SilentlyContinue; if ($cmd) { $iscc = $cmd.Source } }
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) not found." }

& $iscc "/DAppVersion=$Version" "packaging\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "==> Installer written to installer_output\PDFReaderOCR-Setup-$Version.exe"
