#!/usr/bin/env python3
"""Windows system tray indicator for Claude Code usage."""
import ctypes
import os
import sys
import threading
import time
from urllib.error import HTTPError, URLError

# Single-instance guard: exit silently if already running.
_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ClausageTray_PedroElizalde01")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PIL import Image, ImageDraw
    import pystray
except ImportError as _err:
    import tkinter.messagebox as _mb
    _mb.showerror("Clausage", f"Missing dependency: {_err}\nRun install_windows.bat first.")
    sys.exit(1)

import tkinter as tk
import usage as _u

POLL_INTERVAL = 60

_refresh_lock = threading.Lock()
_state = dict(
    available=False, session_pct=0, weekly_pct=0,
    remaining="--", status="LOADING", severity="normal",
)
_panel_ref = [None]  # current popup panel, if open


# ---------------------------------------------------------------------------
# Icon drawing
# ---------------------------------------------------------------------------

def _ring_color(pct, severity):
    if severity in ("error", "critical") or pct > 85:
        return (240, 69, 69, 255)
    if pct >= 50:
        return (242, 196, 15, 255)
    return (54, 199, 120, 255)


def _make_icon(pct=0, severity="normal"):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    r, lw = size // 2 - 5, 7
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(180, 180, 180, 90), width=lw)
    if pct > 0:
        draw.arc([cx - r, cy - r, cx + r, cy + r],
                 start=-90, end=-90 + 360 * pct / 100,
                 fill=_ring_color(pct, severity), width=lw)
    return img


# ---------------------------------------------------------------------------
# Usage bar (matches extension.js usageBar exactly)
# ---------------------------------------------------------------------------

def _bar(pct):
    label = f" {pct}%"
    slots = 21 - len(label)
    filled = min(slots, round(pct / 5))
    return f"[{'█' * filled}{'░' * (slots - filled)}{label}]"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch():
    token = _u.load_token()
    if not token:
        cached = _u.load_cache()
        if cached:
            cached.update(state="stale", fresh=False, reason="auth")
            return _u.normalize(cached)
        return dict(state="auth", fresh=False, reason="auth")

    try:
        raw = _u.fetch_usage(token)
    except HTTPError as exc:
        reason = "auth" if exc.code in (401, 403) else "network"
        cached = _u.load_cache()
        if cached:
            cached.update(state="stale", fresh=False, reason=reason)
            return _u.normalize(cached)
        return dict(state=reason, fresh=False, reason=reason)
    except (URLError, TimeoutError, OSError):
        cached = _u.load_cache()
        if cached:
            cached.update(state="stale", fresh=False, reason="network")
            return _u.normalize(cached)
        return dict(state="network", fresh=False, reason="network")

    if not isinstance(raw, dict) or raw.get("error"):
        cached = _u.load_cache()
        if cached:
            cached.update(state="stale", fresh=False, reason="api")
            return _u.normalize(cached)
        return dict(state="api", fresh=False)

    raw.update(state="ok", fresh=True, fetched_at=int(time.time()))
    raw = _u.normalize(raw)
    _u.save(raw)
    return raw


def _apply(raw, icon):
    available = raw.get("state") in ("ok", "stale")
    session = raw.get("session") or {}
    weekly = raw.get("weekly") or {}
    pct = session.get("percent", 0) if available else 0
    severity = session.get("severity", "normal") if available else "normal"

    if raw.get("fresh"):
        status = "LIVE"
    elif raw.get("state") == "stale":
        status = f"CACHE / {(raw.get('reason') or 'OFFLINE').upper()}"
    else:
        status = (raw.get("state") or "ERROR").upper()

    _state.update(
        available=available, session_pct=pct,
        weekly_pct=weekly.get("percent", 0) if available else 0,
        remaining=session.get("remaining", "--") if available else "--",
        status=status, severity=severity,
    )
    icon.icon = _make_icon(pct, severity)
    icon.title = f"Claude Code  {pct}%" if available else "Claude Code  —"


def _refresh(icon):
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        _apply(_fetch(), icon)
    finally:
        _refresh_lock.release()


def _poll(icon):
    while True:
        time.sleep(POLL_INTERVAL)
        _refresh(icon)


# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------

class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _cursor_pos():
    pt = _POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _work_area_bottom():
    """Y coordinate of the bottom edge of the desktop work area (above taskbar)."""
    r = _RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r.bottom


# ---------------------------------------------------------------------------
# Popup panel (replaces native context menu so Refresh can stay open)
# ---------------------------------------------------------------------------

class UsagePanel(tk.Toplevel):
    BG = "#1e1e1e"
    FG = "#cccccc"
    DIM = "#777777"
    BORDER = "#3c3c3c"
    BTN_BG = "#2c2c2c"
    BTN_ACT = "#3c3c3c"

    def __init__(self, master, icon, cx, quit_cb):
        super().__init__(master)
        self._icon = icon
        self._quit_cb = quit_cb
        self._refreshing = False
        self._labels = {}

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.BORDER)

        self._build()
        self.update_idletasks()

        sw = self.winfo_screenwidth()
        w = self.winfo_reqwidth() + 2   # +2 for 1px border each side
        h = self.winfo_reqheight() + 2
        x = max(4, min(cx - w // 2, sw - w - 4))
        y = _work_area_bottom() - h - 6

        self.geometry(f"{w}x{h}+{x}+{y}")
        self.lift()
        self.focus_force()
        self.bind("<FocusOut>", self._on_focus_out)
        _panel_ref[0] = self

    def _build(self):
        f = tk.Frame(self, bg=self.BG, padx=14, pady=10)
        f.pack(fill="both", expand=True, padx=1, pady=1)

        tk.Label(f, text="CLAUDE / USAGE", bg=self.BG, fg=self.DIM,
                 font=("Consolas", 8), anchor="w").pack(fill="x")
        tk.Frame(f, bg=self.BORDER, height=1).pack(fill="x", pady=(4, 8))

        for key in ("5h", "reset", "7d"):
            lbl = tk.Label(f, text="", bg=self.BG, fg=self.FG,
                           font=("Consolas", 9), anchor="w")
            lbl.pack(fill="x")
            self._labels[key] = lbl

        tk.Frame(f, bg=self.BORDER, height=1).pack(fill="x", pady=(8, 6))

        self._labels["status"] = tk.Label(f, text="", bg=self.BG, fg=self.DIM,
                                          font=("Consolas", 8), anchor="w")
        self._labels["status"].pack(fill="x")

        tk.Frame(f, bg=self.BORDER, height=1).pack(fill="x", pady=(6, 8))

        self._btn = tk.Button(
            f, text="[ REFRESH NOW ]",
            bg=self.BTN_BG, fg=self.FG, font=("Consolas", 9),
            relief="flat", bd=0, pady=4, cursor="hand2",
            activebackground=self.BTN_ACT, activeforeground=self.FG,
            takefocus=False, command=self._on_refresh,
        )
        self._btn.pack(fill="x")

        quit_lbl = tk.Label(f, text="Quit", bg=self.BG, fg=self.DIM,
                            font=("Segoe UI", 8), cursor="hand2", anchor="e")
        quit_lbl.pack(fill="x", pady=(8, 0))
        quit_lbl.bind("<Button-1>", lambda _e: (self._close(), self._quit_cb()))

        self._refresh_labels()

    def _refresh_labels(self):
        s = _state
        if s["available"]:
            self._labels["5h"].config(text=f"5H: {_bar(s['session_pct'])}")
            self._labels["reset"].config(text=f"Resets in: {s['remaining']}")
            self._labels["7d"].config(text=f"7D: {_bar(s['weekly_pct'])}")
        else:
            self._labels["5h"].config(text="5H: [░░░░░░░░░░░░░░░░░ --%]")
            self._labels["reset"].config(text="Resets in: --")
            self._labels["7d"].config(text="7D: [░░░░░░░░░░░░░░░░░ --%]")
        self._labels["status"].config(text=f"STATUS  {s['status']}")
        if not self._refreshing:
            self._btn.config(text="[ REFRESH NOW ]", state="normal")

    def _on_refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        self._btn.config(text="[ REFRESHING… ]", state="disabled")

        def worker():
            _refresh(self._icon)
            self._refreshing = False
            if self.winfo_exists():
                self.after(0, self._refresh_labels)

        threading.Thread(target=worker, daemon=True).start()

    def _on_focus_out(self, _event):
        # Delay so focus can settle into a child widget (e.g. the Refresh button).
        # If focus_get() is None after settling, focus left the app entirely.
        self.after(50, self._maybe_close)

    def _maybe_close(self):
        if self.winfo_exists() and self.focus_get() is None:
            self._close()

    def _close(self):
        _panel_ref[0] = None
        if self.winfo_exists():
            self.destroy()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    root.withdraw()

    icon_ref = [None]

    def quit_all():
        if icon_ref[0]:
            icon_ref[0].stop()
        root.quit()

    def toggle_panel():
        panel = _panel_ref[0]
        if panel and panel.winfo_exists():
            panel._close()
            return
        cx, _cy = _cursor_pos()
        UsagePanel(root, icon_ref[0], cx, quit_all)

    def on_left_click(icon, item):
        # Called from pystray's thread; schedule panel toggle on tkinter's thread.
        root.after(0, toggle_panel)

    menu = pystray.Menu(
        pystray.MenuItem("Open", on_left_click, default=True, visible=False),
        pystray.MenuItem("Quit", lambda icon, item: root.after(0, quit_all)),
    )

    icon = pystray.Icon("clausage", _make_icon(), "Claude Code", menu)
    icon_ref[0] = icon

    # pystray runs its own Win32 message pump in a background thread.
    tray_thread = threading.Thread(target=icon.run, daemon=True)
    tray_thread.start()

    def startup():
        _refresh(icon)
        threading.Thread(target=_poll, args=(icon,), daemon=True).start()

    threading.Thread(target=startup, daemon=True).start()

    root.mainloop()
    icon.stop()


if __name__ == "__main__":
    main()
