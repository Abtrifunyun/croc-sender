# Registers OS-level shortcuts for croc_app.pyw:
#   - croc:// URL protocol handler (clicking a croc://code link opens the Receive tab)
#   - "Send with croc" right-click entry on files and folders in Explorer
#
# Everything below is written under HKEY_CURRENT_USER\Software\Classes, so it
# affects only this Windows user account and needs no admin rights. Run
# unregister_integrations.ps1 to remove it all again.
#
# The registry key literally named "*" (meaning "every file type", per
# Microsoft's own shell-extension docs) is NOT a wildcard here, but
# PowerShell's registry provider treats a bare "*" in -Path as a glob unless
# told otherwise. Every read/write/delete below uses -LiteralPath to disable
# that. New-Item is the one exception: Windows PowerShell 5.1's New-Item has
# no -LiteralPath parameter at all -- it's confirmed (by testing, not
# assumption) to create the literal "*" key correctly via plain -Path anyway.

$ErrorActionPreference = "Stop"

$pythonExe = (py -c "import sys; print(sys.executable)").Trim()
$pythonwExe = Join-Path (Split-Path $pythonExe) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonwExe)) {
    throw "Could not find pythonw.exe next to $pythonExe"
}

$script = Join-Path $PSScriptRoot "croc_app.pyw"
if (-not (Test-Path -LiteralPath $script)) {
    throw "Could not find croc_app.pyw at $script"
}

$command = "`"$pythonwExe`" `"$script`" `"%1`""

# --- croc:// URL protocol handler ---
New-Item -Path "HKCU:\Software\Classes\croc" -Force | Out-Null
Set-ItemProperty -LiteralPath "HKCU:\Software\Classes\croc" -Name "(Default)" -Value "URL:croc Protocol"
Set-ItemProperty -LiteralPath "HKCU:\Software\Classes\croc" -Name "URL Protocol" -Value ""
New-Item -Path "HKCU:\Software\Classes\croc\shell\open\command" -Force | Out-Null
Set-ItemProperty -LiteralPath "HKCU:\Software\Classes\croc\shell\open\command" -Name "(Default)" -Value $command

# --- "Send with croc" on files (the literal key "*") ---
New-Item -Path "HKCU:\Software\Classes\*\shell\SendWithCroc" -Force | Out-Null
Set-ItemProperty -LiteralPath "HKCU:\Software\Classes\*\shell\SendWithCroc" -Name "(Default)" -Value "Send with croc"
Set-ItemProperty -LiteralPath "HKCU:\Software\Classes\*\shell\SendWithCroc" -Name "MultiSelectModel" -Value "Player"
New-Item -Path "HKCU:\Software\Classes\*\shell\SendWithCroc\command" -Force | Out-Null
Set-ItemProperty -LiteralPath "HKCU:\Software\Classes\*\shell\SendWithCroc\command" -Name "(Default)" -Value $command

# --- "Send with croc" on folders ---
New-Item -Path "HKCU:\Software\Classes\Directory\shell\SendWithCroc" -Force | Out-Null
Set-ItemProperty -LiteralPath "HKCU:\Software\Classes\Directory\shell\SendWithCroc" -Name "(Default)" -Value "Send with croc"
New-Item -Path "HKCU:\Software\Classes\Directory\shell\SendWithCroc\command" -Force | Out-Null
Set-ItemProperty -LiteralPath "HKCU:\Software\Classes\Directory\shell\SendWithCroc\command" -Name "(Default)" -Value $command

Write-Output "Registered:"
Write-Output "  croc:// links           -> HKCU\Software\Classes\croc"
Write-Output "  Send with croc (file)   -> HKCU\Software\Classes\*\shell\SendWithCroc"
Write-Output "  Send with croc (folder) -> HKCU\Software\Classes\Directory\shell\SendWithCroc"
Write-Output "Command used: $command"
