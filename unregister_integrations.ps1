# Removes everything register_integrations.ps1 added.
# Uses -LiteralPath so the literal key named "*" isn't misread as a wildcard.

Remove-Item -LiteralPath "HKCU:\Software\Classes\croc" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "HKCU:\Software\Classes\*\shell\SendWithCroc" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "HKCU:\Software\Classes\Directory\shell\SendWithCroc" -Recurse -Force -ErrorAction SilentlyContinue

Write-Output "Removed croc:// handler and 'Send with croc' context menu entries."
