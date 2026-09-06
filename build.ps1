# Builds a standalone croc-sender.exe (no Python install required to run it)
# and bundles a copy of croc.exe next to it, so the packaged app works on a
# machine with nothing installed at all.
#
# The bundled croc.exe is copied from your own winget install -- it is NOT
# downloaded from the internet by this script. If you don't have croc
# installed yet: winget install --id schollz.croc -e

$ErrorActionPreference = "Stop"

py -m pip install --quiet pyinstaller

py -m PyInstaller --onefile --windowed --name croc-sender --exclude-module numpy croc_app.pyw
# numpy is pulled in only as an optional Pillow dependency we never exercise
# (verified: QR generation still works fine without it) -- excluding it
# roughly halves the exe size.

$croc = (py -c "import shutil; print(shutil.which('croc') or '')").Trim()
if (-not $croc) {
    $winget = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\schollz.croc_*\croc.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($winget) { $croc = $winget.FullName }
}
if (-not $croc) {
    throw "Could not find a local croc.exe to bundle. Install croc first: winget install --id schollz.croc -e"
}

Copy-Item -Path $croc -Destination "dist\croc.exe" -Force

# Optional: a v10.x croc for the "compatible with older/mobile apps" toggle.
# v11 changed the PAKE handshake (binds it to participants/sessions) in a way
# that v10 clients -- e.g. crocgui on Android, still pinned to v10.6.0 as of
# this writing -- can't complete. Not downloaded automatically; grab it once
# from https://github.com/schollz/croc/releases/tag/v10.7.0 (Windows-64bit
# build) and place croc-v10.exe next to this script if you want that toggle
# to work. The app runs fine without it -- that checkbox just stays unusable.
if (Test-Path "croc-v10.exe") {
    Copy-Item -Path "croc-v10.exe" -Destination "dist\croc-v10.exe" -Force
    Write-Output "Bundled croc-v10.exe (compatible-mode toggle) from: $(Resolve-Path 'croc-v10.exe')"
} else {
    Write-Output "No croc-v10.exe found next to build.ps1 -- compatible-mode toggle will be unavailable in this build."
}

Write-Output "Built dist\croc-sender.exe"
Write-Output "Bundled croc.exe from: $croc"
Write-Output "Distribute all files in dist\ together (e.g. zip the folder and send it)."
