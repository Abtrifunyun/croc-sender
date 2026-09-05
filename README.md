# croc-sender

A small native drag-and-drop GUI for [`croc`](https://github.com/schollz/croc), the encrypted peer-to-peer file-transfer CLI. One Python file, no bundled binaries, nothing hidden — built to be fully readable in a few minutes.

![Python](https://img.shields.io/badge/python-3.9%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Send tab** — drag and drop a file or folder, get a code (and a QR code) to share, watch live transfer status.
- **Receive tab** — paste a code, pick a save folder, done. "Show in folder" once it lands.
- **Status bar** — shows a genuine "delivered" / "received" confirmation, because croc's sender process only exits successfully after the other side has actually pulled every byte.
- **`croc://` link handler** — clicking a `croc://code` link opens straight into the Receive tab, already downloading.
- **"Send with croc" right-click menu** — on any file or folder in Explorer, including multi-select.

## Requirements

- Windows with Python 3.9+
- [croc](https://github.com/schollz/croc) itself, installed and on `PATH` (e.g. `winget install --id schollz.croc -e`)

## Install

```bash
pip install -r requirements.txt
```

Then just run it:

```bash
pythonw croc_app.pyw
```

(`.pyw` opens with no console window. Double-clicking the file works the same way once Python is installed.)

## Optional: OS integration

`register_integrations.ps1` adds the `croc://` link handler and the right-click "Send with croc" menu:

```powershell
.\register_integrations.ps1
```

Everything it writes lives under `HKEY_CURRENT_USER\Software\Classes` — your own user account only, no admin rights needed. Run `.\unregister_integrations.ps1` to remove it again; both scripts were round-trip tested (install → uninstall → verify every key gone → reinstall) before being included here.

Heads up: a `croc://code` link only does something special on a machine that has also run `register_integrations.ps1`. Sending one to someone who hasn't is a no-op for them — the plain code phrase (or the QR code) still works everywhere.

## How croc itself works

Both sides share a short code phrase. That phrase derives an encryption key via PAKE (password-authenticated key exchange), so the transfer is end-to-end encrypted without either side needing an account or a fixed IP — croc handles NAT traversal through a public relay automatically. See [schollz/croc](https://github.com/schollz/croc) for the full protocol details.

## License

MIT — see [LICENSE](LICENSE).
