"""
DebateLab Auto-Deploy
---------------------
Watches Downloads for `DebateLab-index.html`, renames it to `index.html`,
moves it into your local GitHub repo (overwriting the old one), then
commits and pushes to the main branch automatically.

Requirements:  pip install watchdog
"""

import os
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
from pathlib import Path
from datetime import datetime

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_OK = True
except ImportError:
    WATCHDOG_OK = False

WATCH_FOR  = "DebateLab-index.html"
RENAME_TO  = "index.html"
BRANCH     = "main"


# ── Core logic ────────────────────────────────────────────────────────────────

def git(args, cwd):
    """Run a git command, return (returncode, combined output)."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True, timeout=60
        )
        out = (r.stdout + r.stderr).strip()
        return r.returncode, out
    except FileNotFoundError:
        return -1, "ERROR: git not found. Is Git installed?"
    except Exception as e:
        return -1, str(e)


def deploy(src: Path, repo: str, log):
    dest = Path(repo) / RENAME_TO

    # 1. Rename + move (overwrite)
    log(f"Moving  {src.name}  →  {dest}")
    try:
        shutil.move(str(src), str(dest))
    except Exception as e:
        log(f"ERROR moving file: {e}")
        return

    # 2. Stage
    log("Staging changes…")
    code, out = git(["add", RENAME_TO], repo)
    if code != 0:
        log(f"git add failed: {out}")
        return

    # 3. Commit
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"DebateLab update - {ts}"
    log(f"Committing: \"{msg}\"")
    code, out = git(["commit", "-m", msg], repo)
    if code != 0:
        log(f"git commit failed: {out}")
        return

    # 4. Push
    log(f"Pushing to origin/{BRANCH}…")
    code, out = git(["push", "origin", BRANCH], repo)
    if code == 0:
        log("✔  Done! GitHub Pages will update in ~30 seconds.")
    else:
        log(f"git push failed: {out}")


class Handler(FileSystemEventHandler):
    def __init__(self, repo, log):
        super().__init__()
        self.repo = repo
        self.log  = log

    def on_created(self, event):
        if event.is_directory:
            return
        src = Path(event.src_path)
        if src.name == WATCH_FOR:
            self.log(f"Detected: {src.name}")
            # Wait 1.5 s for browser to finish writing the file
            t = threading.Timer(1.5, deploy, args=[src, self.repo, self.log])
            t.daemon = True
            t.start()


# ── GUI ───────────────────────────────────────────────────────────────────────

BG     = "#0f0f18"
CARD   = "#1a1a28"
PANEL  = "#14141f"
ACCENT = "#7c6af7"
TEAL   = "#4fd1c5"
TEXT   = "#e8e8f0"
MUTED  = "#6b6b85"
GREEN  = "#4ade80"
RED    = "#f87171"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DebateLab Auto-Deploy")
        self.geometry("620x460")
        self.minsize(540, 400)
        self.configure(bg=BG)
        self._observer = None
        self._watching = False
        self._build()
        if not WATCHDOG_OK:
            self.after(400, self._warn_watchdog)

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=CARD, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚡  DebateLab Auto-Deploy",
                 bg=CARD, fg=TEXT,
                 font=("Segoe UI Semibold", 13)).pack(side="left", padx=18, pady=12)
        self._status = tk.Label(hdr, text="● Idle", bg=CARD, fg=MUTED,
                                font=("Segoe UI", 9))
        self._status.pack(side="right", padx=18)

        # Settings
        pnl = tk.Frame(self, bg=PANEL, pady=10)
        pnl.pack(fill="x", padx=14, pady=12)

        self._downloads = tk.StringVar(value=str(Path.home() / "Downloads"))
        self._repo      = tk.StringVar()

        self._row(pnl, 0, "Downloads folder:", self._downloads,
                  lambda: self._browse_dir(self._downloads))
        self._row(pnl, 1, "Repo folder:",      self._repo,
                  lambda: self._browse_dir(self._repo))

        # Info line
        info = tk.Frame(pnl, bg=PANEL)
        info.grid(row=2, column=0, columnspan=3, sticky="w", padx=14, pady=(6, 2))
        tk.Label(info, text="Watching for:", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Label(info, text=f"  {WATCH_FOR}  →  {RENAME_TO}  →  pushed to origin/{BRANCH}",
                 bg=PANEL, fg=TEAL,
                 font=("Consolas", 9)).pack(side="left")

        pnl.columnconfigure(1, weight=1)

        # Start/stop button
        bf = tk.Frame(self, bg=BG)
        bf.pack(fill="x", padx=14, pady=4)
        self._btn = tk.Button(bf, text="▶  Start Watching",
                              bg=ACCENT, fg=TEXT,
                              activebackground="#6558d4", activeforeground=TEXT,
                              relief="flat", bd=0, cursor="hand2",
                              font=("Segoe UI Semibold", 11),
                              padx=20, pady=9,
                              command=self._toggle)
        self._btn.pack(side="left")

        # Log
        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=14, pady=(8, 12))
        hrow = tk.Frame(lf, bg=BG)
        hrow.pack(fill="x")
        tk.Label(hrow, text="Log", bg=BG, fg=MUTED,
                 font=("Segoe UI Semibold", 9)).pack(side="left")
        tk.Button(hrow, text="Clear", bg=CARD, fg=MUTED,
                  relief="flat", bd=0, cursor="hand2",
                  font=("Segoe UI", 8), padx=6, pady=2,
                  command=self._clear).pack(side="right")
        self._log = scrolledtext.ScrolledText(
            lf, bg=CARD, fg=TEAL,
            font=("Consolas", 9), relief="flat", bd=0, wrap="word")
        self._log.pack(fill="both", expand=True, pady=(4, 0))
        self._log.configure(state="disabled")

    def _row(self, parent, row, label, var, cmd):
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w",
                                             padx=14, pady=5)
        tk.Entry(parent, textvariable=var, bg=CARD, fg=TEXT,
                 insertbackground=TEXT, relief="flat", bd=4,
                 font=("Segoe UI", 10)).grid(row=row, column=1, sticky="ew",
                                              padx=4, pady=5)
        tk.Button(parent, text="Browse…", bg=CARD, fg=MUTED,
                  relief="flat", bd=0, cursor="hand2",
                  font=("Segoe UI", 8), padx=6, pady=3,
                  command=cmd).grid(row=row, column=2, padx=6, pady=5)

    def _browse_dir(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    # ── Logging ───────────────────────────────────────────────────────────────
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.after(0, self._append, f"[{ts}]  {msg}\n")

    def _append(self, line):
        self._log.configure(state="normal")
        self._log.insert("end", line)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    # ── Watch toggle ──────────────────────────────────────────────────────────
    def _toggle(self):
        if self._watching:
            self._stop()
        else:
            self._start()

    def _start(self):
        if not WATCHDOG_OK:
            messagebox.showerror("Missing package",
                                 "Run this then restart:\n\n    pip install watchdog")
            return

        dl   = self._downloads.get().strip()
        repo = self._repo.get().strip()

        if not dl or not Path(dl).is_dir():
            messagebox.showwarning("Invalid", "Set a valid Downloads folder.")
            return
        if not repo or not Path(repo).is_dir():
            messagebox.showwarning("Invalid", "Set your local repo folder.")
            return

        # Quick git sanity check
        code, out = git(["rev-parse", "--git-dir"], repo)
        if code != 0:
            messagebox.showwarning("Not a repo",
                "That folder doesn't seem to be a Git repo.\n"
                "Make sure you've opened it in GitHub Desktop first.")
            return

        handler = Handler(repo=repo, log=self.log)
        self._observer = Observer()
        self._observer.schedule(handler, dl, recursive=False)
        self._observer.start()
        self._watching = True
        self._btn.configure(text="■  Stop", bg=RED)
        self._status.configure(text=f"● Watching", fg=GREEN)
        self.log(f"Watching:  {dl}")
        self.log(f"Repo:      {repo}")
        self.log(f"Waiting for {WATCH_FOR} …")

    def _stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        self._watching = False
        self._btn.configure(text="▶  Start Watching", bg=ACCENT)
        self._status.configure(text="● Idle", fg=MUTED)
        self.log("Stopped.")

    def _warn_watchdog(self):
        messagebox.showwarning("Missing package",
            "watchdog is not installed.\n\n"
            "Open a terminal and run:\n\n    pip install watchdog\n\nThen restart.")
        self.log("watchdog not installed — run:  pip install watchdog")

    def on_close(self):
        self._stop()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
