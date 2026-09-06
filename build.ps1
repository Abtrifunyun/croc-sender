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

Write-Output "Built dist\croc-sender.exe"
Write-Output "Bundled croc.exe from: $croc"
Write-Output "Distribute both files together (e.g. zip dist\ and send it)."
