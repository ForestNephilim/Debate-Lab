"""
DebateLab Auto-Deploy — System Tray Edition
- Watches for DebateLab-index.html in Downloads (including files already there on start)
- Renames to index.html, moves into repo, commits and pushes
- Retry Push button in case of timeout/auth delay

Requirements:  pip install watchdog pystray pillow
"""

import os
import shutil
import subprocess
import threading
import sys
import time
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import json

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_OK = True
except ImportError:
    WATCHDOG_OK = False

try:
    import pystray
    from pystray import MenuItem, Menu
    from PIL import Image, ImageDraw
    TRAY_OK = True
except ImportError:
    TRAY_OK = False

WATCH_FOR   = "DebateLab-index.html"
RENAME_TO   = "index.html"
BRANCH      = "main"
CONFIG_FILE = Path.home() / ".debatelab_watcher.json"
GIT_TIMEOUT = 180   # 3 minutes — plenty of time for credential popups


# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}

def save_config(data):
    try:
        CONFIG_FILE.write_text(json.dumps(data))
    except Exception:
        pass


# ── Git ───────────────────────────────────────────────────────────────────────

def git(args, cwd, timeout=30):
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, (r.stdout + "\n" + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"Command {['git'] + args} timed out after {timeout} seconds"
    except FileNotFoundError:
        return -1, "ERROR: git not found. Is Git installed?"
    except Exception as e:
        return -1, str(e)


def do_push(repo, log_fn, notify_fn):
    """Just the push step — used by both deploy() and retry."""
    log_fn(f"Running: git push origin {BRANCH}  (timeout: {GIT_TIMEOUT}s)…")
    code, out = git(["push", "origin", BRANCH], repo, timeout=GIT_TIMEOUT)
    log_fn(out or "(no output)")
    if code == 0:
        log_fn("✔ SUCCESS — GitHub Pages updating in ~30 seconds.")
        log_fn("─" * 40)
        log_fn(f"Still watching for {WATCH_FOR} …")
        notify_fn("DebateLab Deployed ✔", "Pushed to GitHub! Pages updating in ~30s.")
        return True
    else:
        log_fn("git push FAILED.")
        log_fn("─" * 40)
        log_fn("Tip: make sure you're signed in to GitHub Desktop,")
        log_fn("then click  ↺ Retry Push  to try again without re-downloading.")
        log_fn("─" * 40)
        log_fn(f"Still watching for {WATCH_FOR} …")
        notify_fn("DebateLab FAILED", "git push failed — open app and click Retry Push")
        return False


def deploy(src: Path, repo: str, log_fn, notify_fn):
    log_fn("─" * 40)
    log_fn(f"File detected: {src.name}")

    # Wait for file to finish writing
    log_fn("Waiting for file to finish writing…")
    prev_size = -1
    for _ in range(20):
        time.sleep(0.5)
        try:
            curr_size = src.stat().st_size
        except FileNotFoundError:
            log_fn("File disappeared before we could move it.")
            return
        if curr_size == prev_size and curr_size > 0:
            break
        prev_size = curr_size

    # Move / overwrite
    dest = Path(repo) / RENAME_TO
    log_fn(f"Moving → {dest}")
    try:
        shutil.move(str(src), str(dest))
    except Exception as e:
        log_fn(f"ERROR moving file: {e}")
        notify_fn("DebateLab FAILED", f"Could not move file: {e}")
        return

    # git add
    log_fn("Running: git add index.html")
    code, out = git(["add", RENAME_TO], repo)
    log_fn(out or "(no output)")
    if code != 0:
        log_fn("git add FAILED — stopping.")
        notify_fn("DebateLab FAILED", "git add failed — open app to see log")
        return

    # git commit
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"DebateLab update - {ts}"
    log_fn(f"Running: git commit -m \"{msg}\"")
    code, out = git(["commit", "-m", msg], repo)
    log_fn(out or "(no output)")
    if code != 0:
        log_fn("git commit FAILED — stopping.")
        notify_fn("DebateLab FAILED", "git commit failed — open app to see log")
        return

    # git push
    do_push(repo, log_fn, notify_fn)


# ── Watchdog ──────────────────────────────────────────────────────────────────

class Handler(FileSystemEventHandler):
    def __init__(self, repo, log_fn, notify_fn):
        super().__init__()
        self.repo      = repo
        self.log_fn    = log_fn
        self.notify_fn = notify_fn
        self._seen     = set()
        self._lock     = threading.Lock()

    def _queue(self, src: Path):
        with self._lock:
            if src.name in self._seen:
                return
            self._seen.add(src.name)

        def run():
            deploy(src, self.repo, self.log_fn, self.notify_fn)
            with self._lock:
                self._seen.discard(src.name)

        t = threading.Timer(1.0, run)
        t.daemon = True
        t.start()

    def on_created(self, event):
        if not event.is_directory:
            src = Path(event.src_path)
            if src.name == WATCH_FOR:
                self._queue(src)

    def on_moved(self, event):
        if not event.is_directory:
            dest = Path(event.dest_path)
            if dest.name == WATCH_FOR:
                self._queue(dest)

    def on_modified(self, event):
        if not event.is_directory:
            src = Path(event.src_path)
            if src.name == WATCH_FOR:
                self._queue(src)


# ── Tray icon ─────────────────────────────────────────────────────────────────

def make_icon(active=False):
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (76, 222, 128) if active else (107, 107, 133)
    draw.ellipse([4, 4, 60, 60], fill=(26, 26, 40))
    pts = [32,10, 20,36, 30,36, 28,54, 44,28, 34,28, 38,10]
    draw.polygon(pts, fill=color)
    return img


# ── Settings window ───────────────────────────────────────────────────────────

class SettingsWindow(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("DebateLab Auto-Deploy")
        self.geometry("620x540")
        self.minsize(560, 480)
        self.configure(bg="#0f0f18")
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self._build()
        self._load()

    def _build(self):
        BG     = "#0f0f18"
        CARD   = "#1a1a28"
        PANEL  = "#14141f"
        TEXT   = "#e8e8f0"
        MUTED  = "#6b6b85"
        TEAL   = "#4fd1c5"
        ACCENT = "#7c6af7"
        ORANGE = "#fb923c"
        self._c = dict(BG=BG, CARD=CARD, PANEL=PANEL, TEXT=TEXT,
                       MUTED=MUTED, TEAL=TEAL, ACCENT=ACCENT, ORANGE=ORANGE)

        # Header
        hdr = tk.Frame(self, bg=CARD, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚡  DebateLab Auto-Deploy",
                 bg=CARD, fg=TEXT,
                 font=("Segoe UI Semibold", 13)).pack(side="left", padx=18, pady=12)
        self._status_lbl = tk.Label(hdr, text="● Idle", bg=CARD, fg=MUTED,
                                    font=("Segoe UI", 9))
        self._status_lbl.pack(side="right", padx=18)

        # Paths
        pnl = tk.Frame(self, bg=PANEL, pady=10)
        pnl.pack(fill="x", padx=14, pady=10)
        self._dl   = tk.StringVar(value=str(Path.home() / "Downloads"))
        self._repo = tk.StringVar()
        self._path_row(pnl, 0, "Downloads folder:", self._dl,
                       lambda: self._browse(self._dl))
        self._path_row(pnl, 1, "Repo folder:",      self._repo,
                       lambda: self._browse(self._repo))
        tk.Label(pnl,
                 text=f"  Watches for:  {WATCH_FOR}  →  renames to {RENAME_TO}  →  pushes to origin/{BRANCH}",
                 bg=PANEL, fg=TEAL, font=("Consolas", 8)
                 ).grid(row=2, column=0, columnspan=3, sticky="w", padx=14, pady=(4,2))
        pnl.columnconfigure(1, weight=1)

        # Buttons row
        bf = tk.Frame(self, bg=BG)
        bf.pack(fill="x", padx=14, pady=4)

        self._toggle_btn = tk.Button(
            bf, text="▶  Start Watching",
            bg=ACCENT, fg=TEXT,
            activebackground="#6558d4", activeforeground=TEXT,
            relief="flat", bd=0, cursor="hand2",
            font=("Segoe UI Semibold", 11), padx=20, pady=9,
            command=self.app.toggle)
        self._toggle_btn.pack(side="left")

        tk.Button(
            bf, text="↺  Retry Push",
            bg=ORANGE, fg=TEXT,
            activebackground="#ea7a2a", activeforeground=TEXT,
            relief="flat", bd=0, cursor="hand2",
            font=("Segoe UI Semibold", 11), padx=16, pady=9,
            command=self.app.retry_push
        ).pack(side="left", padx=8)

        tk.Button(
            bf, text="🔧 Test Git",
            bg=CARD, fg=TEXT,
            activebackground="#2a2a3a", activeforeground=TEXT,
            relief="flat", bd=0, cursor="hand2",
            font=("Segoe UI", 10), padx=14, pady=9,
            command=self.app.test_git
        ).pack(side="left")

        # Log
        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=14, pady=(8,12))
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
        self._log.pack(fill="both", expand=True, pady=(4,0))
        self._log.configure(state="disabled")

    def _path_row(self, parent, row, label, var, cmd):
        c = self._c
        tk.Label(parent, text=label, bg=c["PANEL"], fg=c["MUTED"],
                 font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w",
                                             padx=14, pady=5)
        tk.Entry(parent, textvariable=var, bg=c["CARD"], fg=c["TEXT"],
                 insertbackground=c["TEXT"], relief="flat", bd=4,
                 font=("Segoe UI", 10)).grid(row=row, column=1, sticky="ew",
                                              padx=4, pady=5)
        tk.Button(parent, text="Browse…", bg=c["CARD"], fg=c["MUTED"],
                  relief="flat", bd=0, cursor="hand2",
                  font=("Segoe UI", 8), padx=6, pady=3,
                  command=cmd).grid(row=row, column=2, padx=6, pady=5)

    def _browse(self, var):
        d = filedialog.askdirectory(parent=self)
        if d:
            var.set(d)

    def _load(self):
        cfg = load_config()
        if "repo"      in cfg: self._repo.set(cfg["repo"])
        if "downloads" in cfg: self._dl.set(cfg["downloads"])

    def save(self):
        save_config({"repo": self._repo.get(), "downloads": self._dl.get()})

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

    def set_watching(self, watching):
        if watching:
            self._toggle_btn.configure(text="■  Stop Watching", bg="#f87171")
            self._status_lbl.configure(text="● Watching", fg="#4ade80")
        else:
            self._toggle_btn.configure(text="▶  Start Watching", bg="#7c6af7")
            self._status_lbl.configure(text="● Idle", fg="#6b6b85")


# ── Main app ──────────────────────────────────────────────────────────────────

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self._observer = None
        self._watching = False
        self._win      = SettingsWindow(self.root, self)

        if not WATCHDOG_OK or not TRAY_OK:
            missing = []
            if not WATCHDOG_OK: missing.append("watchdog")
            if not TRAY_OK:     missing.extend(["pystray", "pillow"])
            messagebox.showwarning("Missing packages",
                f"Run this in a terminal then restart:\n\n"
                f"    pip install {' '.join(missing)}")

        self._tray = self._make_tray()
        threading.Thread(target=self._tray.run, daemon=True).start()
        self.root.mainloop()

    def _make_tray(self):
        return pystray.Icon(
            "debatelab", make_icon(False), "DebateLab Auto-Deploy",
            menu=Menu(
                MenuItem("Open / Settings", self._show_window, default=True),
                MenuItem("Start Watching",  self._tray_start,
                         visible=lambda item: not self._watching),
                MenuItem("Stop Watching",   self._tray_stop,
                         visible=lambda item: self._watching),
                Menu.SEPARATOR,
                MenuItem("Quit", self._quit),
            )
        )

    def _tray_start(self, icon, item): self.root.after(0, self.toggle)
    def _tray_stop(self,  icon, item): self.root.after(0, self.toggle)

    def _show_window(self, icon=None, item=None):
        self.root.after(0, self._do_show)

    def _do_show(self):
        self._win.deiconify()
        self._win.lift()
        self._win.focus_force()

    def _quit(self, icon=None, item=None):
        self._stop()
        self._tray.stop()
        self.root.after(0, self.root.destroy)

    def _set_tray_icon(self, active):
        try:
            self._tray.icon  = make_icon(active)
            self._tray.title = ("DebateLab — Watching" if active
                                else "DebateLab Auto-Deploy")
        except Exception:
            pass

    def notify(self, title, msg):
        try:
            self._tray.notify(msg, title)
        except Exception:
            self.root.after(0, lambda: messagebox.showinfo(title, msg))

    def toggle(self):
        if self._watching: self._stop()
        else:              self._start()

    def retry_push(self):
        """Push whatever is already committed, without needing a new file."""
        repo = self._win._repo.get().strip()
        if not repo or not Path(repo).is_dir():
            messagebox.showwarning("No repo set", "Set your repo folder first.")
            self._show_window()
            return
        self._show_window()
        self._win.log("─" * 40)
        self._win.log("Retrying push…")
        threading.Thread(
            target=do_push,
            args=(repo, self._win.log, self.notify),
            daemon=True
        ).start()

    def test_git(self):
        repo = self._win._repo.get().strip()
        if not repo or not Path(repo).is_dir():
            messagebox.showwarning("No repo set", "Set your repo folder first.")
            self._show_window()
            return
        self._show_window()
        self._win.log("─── Git Test ───")
        _, out = git(["remote", "-v"], repo)
        self._win.log(f"Remote: {out or '(none)'}")
        _, out = git(["status"], repo)
        self._win.log(out or "(no output)")
        _, out = git(["log", "--oneline", "-3"], repo)
        self._win.log(f"Last 3 commits:\n{out or '(none)'}")
        self._win.log("─── End Test ───")

    def _check_existing_file(self, dl, repo):
        """If WATCH_FOR is already sitting in Downloads when we start, process it."""
        src = Path(dl) / WATCH_FOR
        if src.exists():
            self._win.log(f"Found existing file in Downloads: {WATCH_FOR}")
            self._win.log("Processing it now…")
            t = threading.Thread(
                target=deploy,
                args=(src, repo, self._win.log, self.notify),
                daemon=True
            )
            t.start()

    def _start(self):
        if not WATCHDOG_OK or not TRAY_OK:
            messagebox.showerror("Missing packages",
                "pip install watchdog pystray pillow  then restart.")
            return

        dl   = self._win._dl.get().strip()
        repo = self._win._repo.get().strip()

        if not dl or not Path(dl).is_dir():
            messagebox.showwarning("Invalid", "Set a valid Downloads folder.")
            self._show_window(); return
        if not repo or not Path(repo).is_dir():
            messagebox.showwarning("Invalid", "Set your local repo folder.")
            self._show_window(); return

        code, _ = git(["rev-parse", "--git-dir"], repo)
        if code != 0:
            messagebox.showwarning("Not a repo",
                "That folder doesn't seem to be a Git repo.\n"
                "Make sure you've opened it in GitHub Desktop first.")
            self._show_window(); return

        self._win.save()

        handler = Handler(repo=repo, log_fn=self._win.log, notify_fn=self.notify)
        self._observer = Observer()
        self._observer.schedule(handler, dl, recursive=False)
        self._observer.start()
        self._watching = True

        self._win.log("─" * 40)
        self._win.log(f"Watching:  {dl}")
        self._win.log(f"Repo:      {repo}")
        self._win.log(f"Waiting for {WATCH_FOR} …")
        self._win.set_watching(True)
        self._set_tray_icon(True)
        self.notify("DebateLab Auto-Deploy", "Watching your Downloads folder.")

        # Handle file already present in Downloads
        self._check_existing_file(dl, repo)

    def _stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        self._watching = False
        self._win.set_watching(False)
        self._set_tray_icon(False)
        self._win.log("Stopped.")


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(
            ctypes.windll.kernel32.GetConsoleWindow(), 0)
    App()
