#!/usr/bin/env python3
"""Windows system tray indicator for Claude Code usage."""
import ctypes
import os
import sys
import threading
import time
from urllib.error import HTTPError, URLError

# Single-instance guard: exit silently if already running.
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_MUTEX = _KERNEL32.CreateMutexW(None, False, "Local\\ClausageTray")
if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
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

# The usage endpoint rate limits aggressive callers, and a 5h/7d window does not move
# fast enough to justify polling every minute. On failure the poll loop backs off
# exponentially up to POLL_MAX_INTERVAL so a transient 429 cannot become permanent.
POLL_INTERVAL = 300
POLL_MAX_INTERVAL = 3600

REASON_LABEL = {
    "auth": "AUTH EXPIRED",
    "network": "OFFLINE",
    "rate": "RATE LIMITED",
    "api": "API ERROR",
}

_refresh_lock = threading.Lock()
_state = dict(
    session_pct=None, weekly_pct=None,
    remaining="--", status="LOADING", severity="normal",
)
_panel_ref = [None]  # current popup panel, if open


# ---------------------------------------------------------------------------
# Icon drawing
# ---------------------------------------------------------------------------

STALE_RING = (150, 150, 150, 255)


def _ring_color(pct, severity):
    if severity in ("error", "critical") or pct > 85:
        return (240, 69, 69, 255)
    if pct >= 50:
        return (242, 196, 15, 255)
    return (54, 199, 120, 255)


def _make_icon(pct=0, severity="normal", fresh=True):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    r, lw = size // 2 - 5, 7
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(180, 180, 180, 90), width=lw)
    if pct > 0:
        draw.arc([cx - r, cy - r, cx + r, cy + r],
                 start=-90, end=-90 + 360 * pct / 100,
                 fill=_ring_color(pct, severity) if fresh else STALE_RING,
                 width=lw)
    return img


# ---------------------------------------------------------------------------
# Usage bar (matches extension.js usageBar exactly)
# ---------------------------------------------------------------------------

def _bar(pct):
    """Block bar for a percentage; pct=None renders an empty "unknown" bar."""
    label = " --%" if pct is None else f" {pct}%"
    slots = 21 - len(label)
    filled = 0 if pct is None else min(slots, round(pct / 5))
    return f"[{'█' * filled}{'░' * (slots - filled)}{label}]"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _degraded(reason, retry_after=None):
    """Fall back to the cache, tagged with why live data is unavailable."""
    data = _u.load_cache()
    if data:
        data.update(state="stale", fresh=False, reason=reason)
        data = _u.normalize(data)
    else:
        data = dict(state=reason, fresh=False, reason=reason)
    if retry_after:
        data["retry_after"] = retry_after
    return data


def _fetch():
    token = _u.load_token()
    if not token:
        return _degraded("auth")

    try:
        raw = _u.fetch_usage(token)
    except HTTPError as exc:
        if exc.code in (401, 403):
            return _degraded("auth")
        if exc.code == 429:
            return _degraded("rate", _u.retry_after(exc))
        return _degraded("api")
    except (URLError, TimeoutError, OSError):
        return _degraded("network")
    except (UnicodeDecodeError, ValueError):  # includes JSONDecodeError
        return _degraded("api")

    if not isinstance(raw, dict) or raw.get("error"):
        return _degraded("api")

    raw.update(state="ok", fresh=True, fetched_at=int(time.time()))
    raw = _u.normalize(raw)
    _u.save(raw)
    return raw


def _reason_label(reason):
    return REASON_LABEL.get(reason, (reason or "ERROR").upper())


def _age(fetched_at):
    """Human-readable age of a cached reading, e.g. "3h old"."""
    try:
        seconds = max(0, int(time.time() - fetched_at))
    except (TypeError, ValueError):
        return "?"
    if seconds < 3600:
        return f"{seconds // 60}m old"
    if seconds < 86400:
        return f"{seconds // 3600}h old"
    return f"{seconds // 86400}d old"


def _reading(window, available, fresh):
    """A window's percentage, or None when we cannot vouch for it.

    A cached reading is void once its window has reset: usage returns to zero at
    rollover, so the stored number is known to be wrong rather than merely old.
    """
    if not available or (not fresh and window.get("expired")):
        return None
    return window.get("percent", 0)


def _apply(raw, icon):
    available = raw.get("state") in ("ok", "stale")
    session = raw.get("session") or {}
    weekly = raw.get("weekly") or {}
    fresh = bool(raw.get("fresh"))
    pct = _reading(session, available, fresh)
    severity = session.get("severity", "normal") if available else "normal"

    reason = raw.get("reason")
    if fresh:
        status = "LIVE"
    elif raw.get("state") == "stale":
        # Say how old the cache is: a frozen number should never read as live.
        status = f"CACHE {_age(raw.get('fetched_at'))} / {_reason_label(reason)}"
    else:
        status = _reason_label(raw.get("state"))

    _state.update(
        session_pct=pct,
        weekly_pct=_reading(weekly, available, fresh),
        # A window that has already rolled over has no meaningful countdown.
        remaining="--" if pct is None else session.get("remaining", "--"),
        status=status, severity=severity,
    )
    icon.icon = _make_icon(pct or 0, severity, fresh)
    shown = "—" if pct is None else f"{pct}%"
    icon.title = f"Claude Code  {shown}" + ("" if fresh else f"  ({status})")


def _refresh(icon):
    """Fetch and apply once. Returns the reading, or None if one was already in flight."""
    if not _refresh_lock.acquire(blocking=False):
        return None
    try:
        raw = _fetch()
        _apply(raw, icon)
        return raw
    finally:
        _refresh_lock.release()


def _poll(icon):
    delay = POLL_INTERVAL
    while True:
        time.sleep(delay)
        try:
            raw = _refresh(icon)
        except Exception:
            # Never let one bad reading kill the poll thread: that freezes the
            # indicator for the rest of the session with no way to recover.
            raw = {}
        if raw is None:
            continue
        if raw.get("fresh"):
            delay = POLL_INTERVAL
        else:
            delay = min(max(raw.get("retry_after") or delay * 2, POLL_INTERVAL),
                        POLL_MAX_INTERVAL)


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
        self._labels["5h"].config(text=f"5H: {_bar(s['session_pct'])}")
        self._labels["reset"].config(text=f"Resets in: {s['remaining']}")
        self._labels["7d"].config(text=f"7D: {_bar(s['weekly_pct'])}")
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
