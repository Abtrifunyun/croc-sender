import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

import psutil
import qrcode
from PIL import Image, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD


def find_croc():
    path = shutil.which("croc")
    if path:
        return path
    winget_packages = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if winget_packages.exists():
        for entry in winget_packages.glob("schollz.croc_*/croc.exe"):
            return str(entry)
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).parent / "croc.exe"
        if bundled.exists():
            return str(bundled)
    return None


def find_croc_compat():
    """Older v10.x croc, for peers that haven't moved to v11's PAKE-binding
    protocol change (e.g. crocgui on Android, pinned to v10.6.0) — v10 and
    v11 cannot complete a handshake with each other."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    candidate = base / "croc-v10.exe"
    return str(candidate) if candidate.exists() else None


CROC_PATH = find_croc()
CROC_COMPAT_PATH = find_croc_compat()
SEND_CODE_PATTERN = re.compile(r"^croc (.+)$")
RECEIVE_FILE_PATTERN = re.compile(r"Receiving '([^']+)'")
RECEIVE_PROGRESS_DONE_PATTERN = re.compile(r"^(\S+)\s+100%\s*\|")
PERCENT_PATTERN = re.compile(r"(\d{1,3})%")
SIZE_PATTERN = re.compile(r"\(([\d.]+)\s*(B|kB|MB|GB)\)")
SPEED_PATTERN = re.compile(r"([\d.]+)\s*(B|kB|MB|GB)/s")
UNIT_MULTIPLIERS = {"B": 1, "kB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000}

BG = "#1e1e1e"
BG_DROP = "#2a2a2a"
BG_DROP_ACTIVE = "#33403a"
FG = "#e6e6e6"
ACCENT = "#4caf50"
MUTED = "#8a8a8a"
ERROR = "#e05555"
STATUSBAR_OK_BG = "#1f4d2b"
STATUSBAR_ERROR_BG = "#4d1f1f"
STATUSBAR_IDLE_BG = "#2a2a2a"

NOT_FOUND_MSG = "croc not found on PATH. Install it, then restart this app."
COMPAT_NOT_FOUND_MSG = "Compatible (v10) croc not bundled with this build."

SETTINGS_PATH = Path.home() / "AppData/Local/croc-sender/settings.json"


def load_settings():
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except Exception:
        return {}


def save_settings(data):
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(data))
    except Exception:
        pass


def format_bytes_per_sec(bps):
    if bps >= 1_000_000_000:
        return f"{bps / 1_000_000_000:.2f} GB/s"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} MB/s"
    if bps >= 1_000:
        return f"{bps / 1_000:.1f} kB/s"
    return f"{bps:.0f} B/s"


def format_elapsed(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class TransferStats:
    """Tracks speed/elapsed/peak for one transfer from start to finish,
    parsed straight from croc's own progress output."""

    def __init__(self):
        self.start_time = None
        self.total_bytes = None
        self.peak_bps = 0.0
        self.last_bps = None

    def start(self):
        self.start_time = time.monotonic()
        self.total_bytes = None
        self.peak_bps = 0.0
        self.last_bps = None

    def feed_line(self, line):
        if self.total_bytes is None:
            m = SIZE_PATTERN.search(line)
            if m:
                self.total_bytes = float(m.group(1)) * UNIT_MULTIPLIERS.get(m.group(2), 1)
        m = SPEED_PATTERN.search(line)
        if m:
            bps = float(m.group(1)) * UNIT_MULTIPLIERS.get(m.group(2), 1)
            self.last_bps = bps
            if bps > self.peak_bps:
                self.peak_bps = bps

    def elapsed(self):
        return time.monotonic() - self.start_time if self.start_time else 0.0

    def text(self, final=False):
        parts = [f"Elapsed {format_elapsed(self.elapsed())}"]
        if final and self.total_bytes and self.elapsed() > 0:
            parts.append(f"avg {format_bytes_per_sec(self.total_bytes / self.elapsed())}")
        elif self.last_bps is not None:
            parts.append(f"now {format_bytes_per_sec(self.last_bps)}")
        if self.peak_bps:
            parts.append(f"peak {format_bytes_per_sec(self.peak_bps)}")
        return "   ·   ".join(parts)


def stream_process(args, on_line, on_done):
    """Launch args, streaming decoded output lines to on_line and the final
    (returncode, error) to on_done. Both callbacks may be called from a
    background thread — callers must hop back to the Tk thread themselves.
    Returns the Popen (or None if it failed to start)."""
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        on_done(None, e)
        return None

    def reader():
        buf = ""
        while True:
            ch = proc.stdout.read(1)
            if ch == "" and proc.poll() is not None:
                break
            if ch in ("\n", "\r"):
                line, buf_ = buf.strip(), ""
                buf = buf_
                if line:
                    on_line(line)
            else:
                buf += ch
        if buf.strip():
            on_line(buf.strip())
        on_done(proc.returncode, None)

    threading.Thread(target=reader, daemon=True).start()
    return proc


def make_qr_photo(data, size=140, master=None):
    buf = io.BytesIO()
    qrcode.make(data).save(buf, format="PNG")
    buf.seek(0)
    img = Image.open(buf).convert("RGB").resize((size, size))
    return ImageTk.PhotoImage(img, master=master)


class SendTab(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=BG)
        self.app = app
        self.proc = None
        self.busy = False
        self.cancelled = False
        self.last_line = ""
        self.stats = TransferStats()
        self._build_ui()

    def _build_ui(self):
        settings = tk.Frame(self, bg=BG_DROP)
        settings.pack(fill="x", padx=20, pady=(14, 0))

        relay_row = tk.Frame(settings, bg=BG_DROP)
        relay_row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(relay_row, text="Relay (optional):", bg=BG_DROP, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self.relay_entry = tk.Entry(
            relay_row, textvariable=self.app.relay_var, font=("Segoe UI", 9),
            bg=BG, fg=FG, insertbackground=FG, relief="flat",
        )
        self.relay_entry.pack(side="left", fill="x", expand=True, ipady=3, padx=(6, 0))

        self.compat_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            settings, text="Compatible with older/mobile apps (v10)", variable=self.compat_var,
            bg=BG_DROP, fg=MUTED, selectcolor=BG, activebackground=BG_DROP, activeforeground=FG,
            highlightthickness=0, bd=0, font=("Segoe UI", 9),
        ).pack(anchor="w", padx=10, pady=(0, 8))

        self.drop_zone = tk.Frame(self, bg=BG_DROP, highlightbackground=MUTED, highlightthickness=2, bd=0)
        self.drop_zone.pack(fill="both", expand=True, padx=20, pady=(10, 10))

        self.drop_label = tk.Label(
            self.drop_zone,
            text="Drop files or a folder here to send",
            font=("Segoe UI", 12),
            bg=BG_DROP,
            fg=MUTED,
            justify="center",
        )
        self.drop_label.place(relx=0.5, rely=0.5, anchor="center")

        mono_font = tkfont.Font(family="Consolas", size=15, weight="bold")
        self.code_label = tk.Label(self, text="", font=mono_font, bg=BG, fg=ACCENT)
        self.code_label.pack(pady=(4, 0))

        self.qr_photo = None
        self.qr_label = tk.Label(self, bg=BG)
        self.qr_label.pack(pady=(6, 0))

        self.copy_btn = tk.Button(self, text="Copy code", command=self._copy_code, state="disabled")
        self.copy_btn.pack(pady=(6, 0))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            self, variable=self.progress_var, maximum=100, style="Croc.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill="x", padx=20, pady=(10, 0))

        self.status_label = tk.Label(
            self, text="Drop a file to send it.", font=("Segoe UI", 10),
            bg=BG, fg=MUTED, wraplength=420, justify="center",
        )
        self.status_label.pack(pady=(6, 0), padx=16)

        self.stats_label = tk.Label(self, text="", font=("Segoe UI", 9), bg=BG, fg=MUTED)
        self.stats_label.pack(pady=(2, 4))

        self.cancel_btn = tk.Button(self, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_btn.pack(pady=(0, 14))

        for widget in (self.drop_zone, self.drop_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.dnd_bind("<<DropEnter>>", self._on_enter)
            widget.dnd_bind("<<DropLeave>>", self._on_leave)

        if CROC_PATH is None:
            self._set_status(NOT_FOUND_MSG, error=True)

    def _active_croc(self):
        return CROC_COMPAT_PATH if self.compat_var.get() else CROC_PATH

    def _on_enter(self, event):
        if not self.busy:
            self.drop_zone.config(bg=BG_DROP_ACTIVE)
            self.drop_label.config(bg=BG_DROP_ACTIVE)

    def _on_leave(self, event):
        self.drop_zone.config(bg=BG_DROP)
        self.drop_label.config(bg=BG_DROP)

    def _on_drop(self, event):
        self._on_leave(event)
        if self.busy:
            self._set_status("Still sending the previous drop — wait for it to finish or cancel it.")
            return
        paths = [p for p in self.tk.splitlist(event.data) if os.path.exists(p)]
        if paths:
            self._start_send(paths)

    def _start_send(self, paths):
        croc = self._active_croc()
        if croc is None:
            msg = COMPAT_NOT_FOUND_MSG if self.compat_var.get() else NOT_FOUND_MSG
            self._set_status(msg, error=True)
            return

        self.busy = True
        self.cancelled = False
        names = ", ".join(os.path.basename(p) for p in paths)
        self.drop_label.config(text=f"Sending:\n{names}")
        self.code_label.config(text="")
        self.qr_label.config(image="")
        self.qr_photo = None
        self.copy_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress_var.set(0)
        self._set_status("Starting croc…")
        self.app.set_statusbar(f"Sending {names}…", "busy")
        self.last_line = ""
        self.stats.start()
        self.stats_label.config(text=self.stats.text())
        self.after(1000, self._tick_stats)

        args = [croc, "--yes"]
        relay = self.app.relay_var.get().strip()
        if relay:
            args += ["--relay", relay]
        args += ["send", *paths]

        self.proc = stream_process(
            args,
            on_line=lambda line: self.after(0, self._handle_line, line),
            on_done=lambda rc, err: self.after(0, self._on_finished, rc, err, names),
        )

    def _tick_stats(self):
        if self.busy:
            self.stats_label.config(text=self.stats.text())
            self.after(1000, self._tick_stats)

    def _handle_line(self, line):
        self.last_line = line
        self.stats.feed_line(line)
        pm = PERCENT_PATTERN.search(line)
        if pm:
            self.progress_var.set(int(pm.group(1)))
        match = SEND_CODE_PATTERN.search(line)
        if match:
            # The code is always the last token on the line -- anything
            # between "croc" and it (e.g. --relay <address>) is just an
            # extra flag croc is suggesting the receiver also pass.
            tail = re.sub(r"\s*\(.*\)\s*$", "", match.group(1)).strip()
            code = tail.split()[-1]
            self.code_label.config(text=code)
            self.copy_btn.config(state="normal")
            try:
                self.qr_photo = make_qr_photo(f"https://getcroc.com/?code={code}", master=self)
                self.qr_label.config(image=self.qr_photo)
            except Exception:
                pass
            self._set_status(f"Waiting for the other person to run: croc {code}")
        else:
            self._set_status(line)
        self.stats_label.config(text=self.stats.text())

    def _on_finished(self, returncode, error, names):
        if error is not None:
            self._set_status(f"Failed to start croc: {error}", error=True)
            self.app.set_statusbar("Send failed to start.", "error")
        elif self.cancelled:
            self._set_status("Cancelled.")
            self.app.set_statusbar("Send cancelled.", "error")
        elif returncode == 0:
            self.progress_var.set(100)
            self._set_status("Done — the other side finished downloading it.")
            self.app.set_statusbar(f"✓ Delivered: {names}", "ok")
            self.stats_label.config(text=self.stats.text(final=True))
        else:
            detail = f": {self.last_line}" if self.last_line else ""
            self._set_status(f"croc exited (code {returncode}){detail}", error=True)
            self.app.set_statusbar("Send failed.", "error")
        self._reset_idle()

    def _copy_code(self):
        code = self.code_label.cget("text")
        if code:
            self.clipboard_clear()
            self.clipboard_append(code)

    def _cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self._set_status("Cancelling…")
        self.cancel_btn.config(state="disabled")

    def _reset_idle(self):
        self.busy = False
        self.proc = None
        self.cancel_btn.config(state="disabled")
        self.drop_label.config(text="Drop files or a folder here to send")

    def _set_status(self, text, error=False):
        self.status_label.config(text=text, fg=ERROR if error else MUTED)

    def shutdown(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass


class ReceiveTab(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=BG)
        self.app = app
        self.proc = None
        self.busy = False
        self.cancelled = False
        self.out_dir = str(Path.home() / "Downloads")
        self.last_saved_path = None
        self.received_files = []
        self.last_line = ""
        self.stats = TransferStats()
        self._build_ui()

    def _build_ui(self):
        tk.Label(self, text="Code from sender:", font=("Segoe UI", 11), bg=BG, fg=FG).pack(pady=(20, 4))

        entry_row = tk.Frame(self, bg=BG)
        entry_row.pack(pady=(0, 10), padx=20, fill="x")
        self.code_entry = tk.Entry(
            entry_row, font=("Consolas", 13), bg=BG_DROP, fg=FG, insertbackground=FG, relief="flat",
        )
        self.code_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        self.code_entry.bind("<Return>", lambda e: self._start_receive())

        self.receive_btn = tk.Button(entry_row, text="Receive", command=self._start_receive)
        self.receive_btn.pack(side="left")

        folder_row = tk.Frame(self, bg=BG)
        folder_row.pack(pady=(0, 10), padx=20, fill="x")
        tk.Label(folder_row, text="Save to:", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self.folder_label = tk.Label(
            folder_row, text=self.out_dir, bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w",
        )
        self.folder_label.pack(side="left", fill="x", expand=True, padx=(6, 8))
        tk.Button(folder_row, text="Change…", command=self._choose_folder).pack(side="right")

        settings = tk.Frame(self, bg=BG_DROP)
        settings.pack(fill="x", padx=20, pady=(0, 10))

        relay_row = tk.Frame(settings, bg=BG_DROP)
        relay_row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(relay_row, text="Relay (optional):", bg=BG_DROP, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self.relay_entry = tk.Entry(
            relay_row, textvariable=self.app.relay_var, font=("Segoe UI", 9),
            bg=BG, fg=FG, insertbackground=FG, relief="flat",
        )
        self.relay_entry.pack(side="left", fill="x", expand=True, ipady=3, padx=(6, 0))

        self.compat_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            settings, text="Compatible with older/mobile apps (v10)", variable=self.compat_var,
            bg=BG_DROP, fg=MUTED, selectcolor=BG, activebackground=BG_DROP, activeforeground=FG,
            highlightthickness=0, bd=0, font=("Segoe UI", 9),
        ).pack(anchor="w", padx=10, pady=(0, 8))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            self, variable=self.progress_var, maximum=100, style="Croc.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill="x", padx=20, pady=(6, 0))

        self.status_label = tk.Label(
            self, text="Paste a code and click Receive.", font=("Segoe UI", 10),
            bg=BG, fg=MUTED, wraplength=420, justify="center",
        )
        self.status_label.pack(pady=(10, 0), padx=16)

        self.stats_label = tk.Label(self, text="", font=("Segoe UI", 9), bg=BG, fg=MUTED)
        self.stats_label.pack(pady=(2, 4))

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(pady=(0, 10))
        self.cancel_btn = tk.Button(btn_row, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.show_btn = tk.Button(btn_row, text="Show in folder", command=self._show_in_folder, state="disabled")
        self.show_btn.pack(side="left", padx=4)

        if CROC_PATH is None:
            self._set_status(NOT_FOUND_MSG, error=True)

    def _choose_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.out_dir)
        if chosen:
            self.out_dir = chosen
            self.folder_label.config(text=self.out_dir)

    def _active_croc(self):
        return CROC_COMPAT_PATH if self.compat_var.get() else CROC_PATH

    def _start_receive(self):
        croc = self._active_croc()
        if croc is None:
            msg = COMPAT_NOT_FOUND_MSG if self.compat_var.get() else NOT_FOUND_MSG
            self._set_status(msg, error=True)
            return
        if self.busy:
            return
        code = self.code_entry.get().strip()
        if not code:
            self._set_status("Enter the code your friend sent you.", error=True)
            return

        self.busy = True
        self.cancelled = False
        self.last_saved_path = None
        self.received_files = []
        self.receive_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.show_btn.config(state="disabled")
        self.progress_var.set(0)
        self._set_status("Connecting…")
        self.app.set_statusbar(f"Receiving with code {code}…", "busy")
        self.last_line = ""
        self.stats.start()
        self.stats_label.config(text=self.stats.text())
        self.after(1000, self._tick_stats)

        os.makedirs(self.out_dir, exist_ok=True)
        args = [croc, "--yes"]
        relay = self.app.relay_var.get().strip()
        if relay:
            args += ["--relay", relay]
        args += ["--out", self.out_dir, code]

        self.proc = stream_process(
            args,
            on_line=lambda line: self.after(0, self._handle_line, line),
            on_done=lambda rc, err: self.after(0, self._on_finished, rc, err),
        )

    def _tick_stats(self):
        if self.busy:
            self.stats_label.config(text=self.stats.text())
            self.after(1000, self._tick_stats)

    def _handle_line(self, line):
        self.last_line = line
        self.stats.feed_line(line)
        pm = PERCENT_PATTERN.search(line)
        if pm:
            self.progress_var.set(int(pm.group(1)))
        match = RECEIVE_FILE_PATTERN.search(line) or RECEIVE_PROGRESS_DONE_PATTERN.search(line)
        if match:
            name = match.group(1)
            self.last_saved_path = os.path.join(self.out_dir, name)
            if name not in self.received_files:
                self.received_files.append(name)
        self._set_status(line)
        self.stats_label.config(text=self.stats.text())

    def _on_finished(self, returncode, error):
        if error is not None:
            self._set_status(f"Failed to start croc: {error}", error=True)
            self.app.set_statusbar("Receive failed to start.", "error")
        elif self.cancelled:
            self._set_status("Cancelled.")
            self.app.set_statusbar("Receive cancelled.", "error")
        elif returncode == 0:
            self.progress_var.set(100)
            if len(self.received_files) > 1:
                what = f"{len(self.received_files)} files"
            else:
                what = os.path.basename(self.last_saved_path) if self.last_saved_path else "file"
            self._set_status(f"Done — saved to {self.out_dir}")
            self.app.set_statusbar(f"✓ Received: {what}", "ok")
            self.stats_label.config(text=self.stats.text(final=True))
            if self.last_saved_path and os.path.exists(self.last_saved_path):
                self.show_btn.config(state="normal")
            self.code_entry.delete(0, "end")
        else:
            detail = f": {self.last_line}" if self.last_line else ""
            self._set_status(f"croc exited (code {returncode}){detail}", error=True)
            self.app.set_statusbar("Receive failed.", "error")
        self._reset_idle()

    def _cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self._set_status("Cancelling…")
        self.cancel_btn.config(state="disabled")

    def _reset_idle(self):
        self.busy = False
        self.proc = None
        self.receive_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")

    def _show_in_folder(self):
        if self.last_saved_path and os.path.exists(self.last_saved_path):
            subprocess.Popen(["explorer", "/select,", self.last_saved_path])

    def _set_status(self, text, error=False):
        self.status_label.config(text=text, fg=ERROR if error else MUTED)

    def shutdown(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass


class RunningTab(tk.Frame):
    """Lists every croc.exe / croc-v10.exe process on the system, however it
    was launched -- our own tabs, a right-click send, or a bare terminal
    command -- so nothing can be silently running out of view."""

    def __init__(self, master, app):
        super().__init__(master, bg=BG)
        self.app = app
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(header, text="Running croc processes", bg=BG, fg=FG, font=("Segoe UI", 11)).pack(side="left")
        tk.Button(header, text="Refresh now", command=self._refresh).pack(side="right")

        tk.Label(
            self, text="Updates automatically every couple of seconds.",
            bg=BG, fg=MUTED, font=("Segoe UI", 9),
        ).pack(anchor="w", padx=20)

        self.list_frame = tk.Frame(self, bg=BG)
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=(8, 16))

    @staticmethod
    def _describe(parts):
        if not parts:
            return "croc"
        if len(parts) > 1 and parts[1] == "relay":
            return "Relay server"
        if "send" in parts:
            for part in reversed(parts):
                if not part.startswith("-") and part != "send" and ":" not in part:
                    return f"Sending {os.path.basename(part)}"
            return "Sending"
        return f"Receiving (code: {parts[-1]})" if parts[-1] else "Receiving"

    def _refresh(self):
        for child in self.list_frame.winfo_children():
            child.destroy()

        rows = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                name = (proc.info.get("name") or "").lower()
                if name in ("croc.exe", "croc-v10.exe"):
                    rows.append((proc.info["pid"], proc.info.get("cmdline") or []))
        except Exception:
            pass

        if not rows:
            tk.Label(
                self.list_frame, text="No croc processes running.",
                bg=BG, fg=MUTED, font=("Segoe UI", 10),
            ).pack(pady=20)
        else:
            for pid, parts in rows:
                row = tk.Frame(self.list_frame, bg=BG_DROP)
                row.pack(fill="x", pady=(0, 6))
                tk.Label(
                    row, text=f"PID {pid}   ·   {self._describe(parts)}",
                    bg=BG_DROP, fg=FG, font=("Segoe UI", 9), anchor="w",
                ).pack(side="left", fill="x", expand=True, padx=10, pady=8)
                tk.Button(row, text="Kill", command=lambda p=pid: self._kill(p)).pack(side="right", padx=8)

        self.after(2000, self._refresh)

    def _kill(self, pid):
        try:
            psutil.Process(pid).terminate()
        except Exception:
            pass
        self._refresh()


class CrocApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("croc")
        self.geometry("460x630")
        self.minsize(420, 540)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_DROP, foreground=FG, padding=(16, 8), borderwidth=0)
        style.map(
            "TNotebook.Tab",
            background=[("selected", BG_DROP_ACTIVE)],
            foreground=[("selected", ACCENT)],
        )
        style.configure(
            "Croc.Horizontal.TProgressbar",
            troughcolor=BG_DROP, background=ACCENT, bordercolor=BG_DROP,
            lightcolor=ACCENT, darkcolor=ACCENT, thickness=8,
        )

        self.statusbar = tk.Label(
            self, text="Idle", font=("Segoe UI", 9), bg=STATUSBAR_IDLE_BG, fg=MUTED,
            anchor="w", padx=10, pady=5,
        )
        self.statusbar.pack(fill="x", side="bottom")

        self.settings = load_settings()
        self.relay_var = tk.StringVar(value=self.settings.get("relay", ""))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.send_tab = SendTab(self.notebook, self)
        self.receive_tab = ReceiveTab(self.notebook, self)
        self.running_tab = RunningTab(self.notebook, self)
        self.notebook.add(self.send_tab, text="Send")
        self.notebook.add(self.receive_tab, text="Receive")
        self.notebook.add(self.running_tab, text="Running")

        if CROC_PATH is None:
            self.set_statusbar(NOT_FOUND_MSG, "error")

        self._handle_launch_args()

    def _handle_launch_args(self):
        """Support being launched by the OS: a croc://<code> link (URL protocol
        handler) or one/more file paths ("Send with croc" context menu)."""
        launch_args = sys.argv[1:]
        if not launch_args:
            return
        if launch_args[0].startswith("croc://"):
            code = launch_args[0][len("croc://"):].strip("/")
            if code:
                self.notebook.select(self.receive_tab)
                self.receive_tab.code_entry.delete(0, "end")
                self.receive_tab.code_entry.insert(0, code)
                self.receive_tab._start_receive()
            return
        paths = [a for a in launch_args if os.path.exists(a)]
        if paths:
            self.notebook.select(self.send_tab)
            self.send_tab._start_send(paths)

    def set_statusbar(self, text, kind="idle"):
        bg = {"ok": STATUSBAR_OK_BG, "error": STATUSBAR_ERROR_BG}.get(kind, STATUSBAR_IDLE_BG)
        fg = ACCENT if kind == "ok" else (ERROR if kind == "error" else MUTED)
        stamp = time.strftime("%I:%M %p").lstrip("0")
        self.statusbar.config(text=f"{text}   ·   {stamp}", bg=bg, fg=fg)

    def _on_close(self):
        try:
            save_settings({"relay": self.relay_var.get().strip()})
            self.send_tab.shutdown()
            self.receive_tab.shutdown()
            self.destroy()
        finally:
            # Guarantee this process ends here even if something above hangs
            # or throws, and even if launched through an intermediary (e.g.
            # a launcher shim) that doesn't reliably exit when we do.
            os._exit(0)


if __name__ == "__main__":
    CrocApp().mainloop()
