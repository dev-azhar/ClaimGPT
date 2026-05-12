# ClaimGPT — WeasyPrint Windows setup helper
#
# Diagnoses why "import weasyprint" fails on Windows and prints the fix.
# Does NOT install anything (admin-required); guides the user to the
# correct one-click installer.
#
# Usage (from PowerShell, with .venv activated):
#   .\infra\scripts\setup_weasyprint_windows.ps1

$ErrorActionPreference = "Stop"

Write-Host "ClaimGPT — WeasyPrint Windows diagnostic" -ForegroundColor Cyan
Write-Host "----------------------------------------"

# 1. Confirm we're inside a venv with WeasyPrint pip-installed
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: 'python' not on PATH. Activate your venv first." -ForegroundColor Red
    exit 1
}

$weasyVersion = & python -c "import weasyprint, sys; print(weasyprint.__version__)" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "OK   WeasyPrint $weasyVersion imports cleanly." -ForegroundColor Green
    Write-Host "     The IRDAI modern renderer should work. Verify with:"
    Write-Host "     curl http://localhost:8000/submission/health"
    exit 0
}

Write-Host ""
Write-Host "FAIL  python -c 'import weasyprint' raised an error:" -ForegroundColor Yellow
Write-Host $weasyVersion -ForegroundColor DarkYellow
Write-Host ""

# 2. Look for GTK3 runtime DLLs on PATH
$gtkOnPath = $false
foreach ($dir in $env:PATH -split ';') {
    if ($dir -and (Test-Path "$dir\libpango-1.0-0.dll" -ErrorAction SilentlyContinue)) {
        Write-Host "Found Pango at: $dir" -ForegroundColor Green
        $gtkOnPath = $true
        break
    }
}

if ($gtkOnPath) {
    Write-Host ""
    Write-Host "GTK DLLs are on PATH but WeasyPrint still fails." -ForegroundColor Yellow
    Write-Host "Common cause: a 32-bit/64-bit mismatch with your Python interpreter."
    Write-Host "Run:  python -c 'import platform; print(platform.architecture())'"
    Write-Host "      and install the matching GTK runtime."
    exit 1
}

Write-Host "GTK3 runtime not detected on PATH." -ForegroundColor Yellow
Write-Host ""
Write-Host "Fix — pick ONE of the options below:" -ForegroundColor Cyan
Write-Host ""
Write-Host "Option A) MSYS2 (recommended, ongoing updates)"
Write-Host "  1. Install MSYS2 from https://www.msys2.org/"
Write-Host "  2. In the MSYS2 UCRT64 shell:"
Write-Host "     pacman -S mingw-w64-ucrt-x86_64-pango mingw-w64-ucrt-x86_64-cairo \\"
Write-Host "               mingw-w64-ucrt-x86_64-gdk-pixbuf2 mingw-w64-ucrt-x86_64-libffi"
Write-Host "  3. Add C:\msys64\ucrt64\bin to your USER PATH"
Write-Host ""
Write-Host "Option B) GTK3 standalone runtime (one-click installer)"
Write-Host "  1. Download the latest gtk3-runtime-*-installer.exe from"
Write-Host "     https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases"
Write-Host "  2. During install, CHECK 'Set up PATH environment variable to include GTK+'"
Write-Host ""
Write-Host "After installing, open a NEW PowerShell window and re-run this script."
Write-Host ""
Write-Host "Note: 'pip install pango cairo gdk-pixbuf libffi' will NOT work." -ForegroundColor Red
Write-Host "      Those are C libraries, not Python packages."
exit 1
