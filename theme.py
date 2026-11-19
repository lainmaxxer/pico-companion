"""Look & feel for Pico Companion, modeled on the aic_pico web configurator
(blue-purple gradient backdrop, rounded cards, flat colored buttons, status pill) with light and dark modes.

Colors live in module globals that set_mode() swaps, so widgets created after a mode change pick them up.
The chosen mode is stored in a small settings file and restored on the next start.
"""
import json
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from shapes import pill_shape, round_rect  # noqa: F401  (anti-aliased shapes)

PALETTES = {
    "light": dict(
        BG_TOP=(0x66, 0x7E, 0xEA), BG_BOTTOM=(0x76, 0x4B, 0xA2),
        CARD="#ffffff", TEXT="#2c3e50", MUTED="#7f8c8d", LINE="#e3e8ee",
        FIELD="#ffffff", FIELD_BORDER="#cfd8e3", TRACK="#dfe6ee", SW_OFF="#bdc3c7",
        TAB_BG="#ecf0f1", TAB_HOVER="#dde5ea",
        PILL_ON_BG="#d5f4e6", PILL_ON_FG="#27ae60", PILL_OFF_BG="#fadbd8", PILL_OFF_FG="#e74c3c",
        CONSOLE_BG="#1e2433", CONSOLE_FG="#d7e0ee",
        SECONDARY="#95a5a6", SECONDARY_H="#7f8c8d"),
    "dark": dict(
        BG_TOP=(0x24, 0x28, 0x5C), BG_BOTTOM=(0x34, 0x1E, 0x52),
        CARD="#1f2535", TEXT="#e4e9f1", MUTED="#8e9bb0", LINE="#343d54",
        FIELD="#161b29", FIELD_BORDER="#3a4560", TRACK="#38425a", SW_OFF="#4d5970",
        TAB_BG="#171c2a", TAB_HOVER="#2a3248",
        PILL_ON_BG="#1b4332", PILL_ON_FG="#58d68d", PILL_OFF_BG="#4a2323", PILL_OFF_FG="#ff8a80",
        CONSOLE_BG="#11151f", CONSOLE_FG="#cfd8e6",
        SECONDARY="#566379", SECONDARY_H="#6a7890"),
}
MODE = "light"
globals().update(PALETTES["light"])

PRIMARY, PRIMARY_H = "#3498db", "#2980b9"
SUCCESS, SUCCESS_H = "#27ae60", "#1e8449"
DANGER, DANGER_H = "#e74c3c", "#c0392b"
WARN, WARN_H = "#e67e22", "#d35400"
FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
FONT_H1 = ("Segoe UI", 18, "bold")
MONO = ("Consolas", 10)


# ------------------------------------------------------------ persistence
def _settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PicoCompanion", "settings.json")


def load_mode():
    """Restore the saved mode (light if there is no usable settings file)."""
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            set_mode(json.load(f).get("mode", "light"))
    except (OSError, ValueError):
        set_mode("light")


def save_mode():
    try:
        path = _settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mode": MODE}, f)
    except OSError:
        pass  # not being able to remember the choice must never break the app


def set_mode(name):
    global MODE
    MODE = name if name in PALETTES else "light"
    globals().update(PALETTES[MODE])


def kinds():
    return {"primary": (PRIMARY, PRIMARY_H), "secondary": (SECONDARY, SECONDARY_H),
            "success": (SUCCESS, SUCCESS_H), "danger": (DANGER, DANGER_H), "warn": (WARN, WARN_H)}


def _kind_for(text):
    t = text.lower()
    if t.startswith("save"):
        return "success"
    if "factory" in t:
        return "danger"
    if "update" in t:
        return "warn"
    if t in ("connect", "send", "apply") or t.startswith("calibrate"):
        return "primary"
    return "secondary"


def _parent_bg(parent):
    try:
        return parent.cget("bg")
    except tk.TclError:
        return CARD


class Button(tk.Canvas):
    """Flat rounded button with hover; kind (color) is inferred from its label. Drop-in for ttk.Button."""
    H = 34

    def __init__(self, parent, text="", command=None, kind=None, minw=0, **kw):
        self._minw = minw
        self._bg, self._hover = kinds()[kind or _kind_for(text)]
        self._font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.command = command
        self._label = text.upper()
        w = max(self._font.measure(self._label) + 30, minw)
        super().__init__(parent, width=w, height=self.H, bg=_parent_bg(parent), highlightthickness=0, bd=0,
                         cursor="hand2")
        self._draw(self._bg)
        self.bind("<Enter>", lambda e: self._draw(self._hover))
        self.bind("<Leave>", lambda e: self._draw(self._bg))
        self.bind("<ButtonRelease-1>", self._click)

    def _draw(self, fill):
        self.delete("all")
        w = int(self.cget("width"))
        round_rect(self, 0, 0, w, self.H, 8, fill=fill)
        self.create_text(w / 2, self.H / 2, text=self._label, fill="white", font=self._font)

    def set_text(self, text):
        self._label = text.upper()
        self.config(width=max(self._font.measure(self._label) + 30, self._minw))
        self._draw(self._bg)

    def _click(self, e):
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height() and self.command:
            self.command()


class Pill(tk.Canvas):
    """Fully rounded status badge (green when connected, red otherwise)."""

    def __init__(self, parent):
        self._font = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        super().__init__(parent, width=120, height=26, bg=_parent_bg(parent), highlightthickness=0, bd=0)
        self.set(False)

    def set(self, connected):
        if getattr(self, "_state", None) == connected:
            return
        self._state = connected
        text, bg, fg = (("CONNECTED", PILL_ON_BG, PILL_ON_FG) if connected
                        else ("DISCONNECTED", PILL_OFF_BG, PILL_OFF_FG))
        w = self._font.measure(text) + 28
        self.config(width=w)
        self.delete("all")
        pill_shape(self, 0, 0, w, 26, bg)
        self.create_text(w / 2, 13, text=text, fill=fg, font=self._font)


def setup(root):
    """(Re)configure ttk styles and Tk option defaults for the current mode."""
    root.configure(bg=CARD)
    root.option_add("*Font", FONT)
    root.option_add("*TCombobox*Listbox.font", FONT)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", PRIMARY)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=CARD, foreground=TEXT, font=FONT, bordercolor=LINE, focuscolor=CARD)
    s.configure("TFrame", background=CARD)
    s.configure("TLabel", background=CARD, foreground=TEXT, font=FONT)
    s.configure("TLabelframe", background=CARD, bordercolor=LINE, relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=CARD, foreground=PRIMARY, font=FONT_B)
    s.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=PRIMARY,
                bordercolor=FIELD_BORDER, lightcolor=FIELD, darkcolor=FIELD, padding=4)
    s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
          selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)],
          bordercolor=[("focus", PRIMARY)])
    s.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, bordercolor=FIELD_BORDER,
                arrowcolor=PRIMARY, padding=3)
    s.configure("TNotebook", background=CARD, borderwidth=0, tabmargins=(0, 0, 0, 0),
                bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    s.configure("TNotebook.Tab", background=TAB_BG, foreground=MUTED, padding=(20, 9), font=FONT_B,
                borderwidth=0, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    # clam shrinks the selected tab's padding unless it is overridden here
    s.map("TNotebook.Tab", background=[("selected", CARD), ("active", TAB_HOVER)],
          foreground=[("selected", PRIMARY)],
          lightcolor=[("selected", LINE), ("!selected", LINE)], darkcolor=[("selected", LINE), ("!selected", LINE)],
          bordercolor=[("selected", LINE), ("!selected", LINE)],
          padding=[("selected", (20, 9)), ("!selected", (20, 9))],
          expand=[("selected", (0, 0, 0, 0)), ("!selected", (0, 0, 0, 0))])
    s.configure("TSeparator", background=LINE)
    s.configure("Card.TFrame", background=CARD)
    s.configure("Hint.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
    s.configure("Title.TLabel", background=CARD, foreground=TEXT, font=FONT_H1)


def paint_gradient(canvas, w, h):
    canvas.delete("grad")
    step = 4
    for y in range(0, h, step):
        t = y / max(h - 1, 1)
        c = tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        canvas.create_rectangle(0, y, w, y + step, fill="#%02x%02x%02x" % c, outline="", tags="grad")
    canvas.tag_lower("grad")


class Switch(tk.Frame):
    """Toggle switch with a label (replaces Checkbutton). Works with a tk.BooleanVar/IntVar."""
    W, H = 40, 20
    PAD = 2

    def __init__(self, parent, text="", variable=None, command=None, **kw):
        super().__init__(parent, bg=_parent_bg(parent), cursor="hand2")
        bg = _parent_bg(parent)
        self.var = variable or tk.BooleanVar(value=False)
        self.command = command
        self.cv = tk.Canvas(self, width=self.W + 2 * self.PAD, height=self.H + 2 * self.PAD, bg=bg,
                            highlightthickness=0, bd=0)
        self.cv.pack(side="left")
        self.lbl = tk.Label(self, text=text, bg=bg, fg=TEXT, font=FONT, cursor="hand2")
        self.lbl.pack(side="left", padx=(8, 0))
        for w in (self.cv, self.lbl):
            w.bind("<Button-1>", self.toggle)
        self.var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def draw(self):
        on = bool(self.var.get())
        c, W, H, P = self.cv, self.W, self.H, self.PAD
        c.delete("all")
        col = SUCCESS if on else SW_OFF
        pill_shape(c, P, P, P + W, P + H, col)
        x = P + (W - H + 3 if on else 3)
        c.create_oval(x, P + 3, x + H - 6, P + H - 3, fill="white", outline="white")

    def toggle(self, _=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()


class Slider(tk.Frame):
    """Rounded slider with a live value readout (replaces ttk.Scale + separate label)."""

    def __init__(self, parent, lo, hi, value, command=None, length=320):
        bg = _parent_bg(parent)
        super().__init__(parent, bg=bg)
        self.lo, self.hi, self.length, self.command = lo, hi, length, command
        self.value = max(lo, min(hi, int(value)))
        self.cv = tk.Canvas(self, width=length, height=26, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack(side="left")
        self.lbl = tk.Label(self, text=str(self.value), bg=bg, fg=TEXT, font=FONT_B, width=4, anchor="e")
        self.lbl.pack(side="left", padx=(8, 0))
        self.cv.bind("<Button-1>", self._drag)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<MouseWheel>", lambda e: self._set(self.value + (1 if e.delta > 0 else -1), True))
        self.draw()

    def _x(self):
        span = max(self.hi - self.lo, 1)
        return 10 + (self.length - 20) * (self.value - self.lo) / span

    def draw(self):
        c, x = self.cv, self._x()
        c.delete("all")
        # anti-aliased: pill track + pill fill + round solid thumb (like the web configurator)
        round_rect(c, 4, 10, self.length - 4, 16, 3, fill=TRACK)
        round_rect(c, 4, 10, max(x, 10), 16, 3, fill=PRIMARY)
        round_rect(c, x - 10, 3, x + 10, 23, 10, fill=PRIMARY)

    def _set(self, v, notify):
        v = max(self.lo, min(self.hi, int(round(v))))
        if v == self.value:
            return
        self.value = v
        self.lbl.config(text=str(v))
        self.draw()
        if notify and self.command:
            self.command(v)

    def _drag(self, e):
        span = max(self.hi - self.lo, 1)
        self._set(self.lo + span * (e.x - 10) / max(self.length - 20, 1), True)
