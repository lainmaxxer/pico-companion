"""IIDX Pico settings screens, plus the Hall-key screen that every Hall-effect controller shares.

`IidxScreens` is a mixin for the main window (`PicoApp`). The host class has to provide: `nb` (the ttk.Notebook),
`dev`, `status`, `cfg`, `hall`, `full`, `scale()`, `send()`, `run_bg()`, `load()` and `tab_raw()`.

Two modes, depending on the firmware:
  * Full mode   - firmware has the `cfg` / `set` / `pset` / `color` commands (see the firmware patch).
  * Legacy mode - stock firmware: Hall trigger distances, calibrate, save, factory reset.
"""
import colorsys
import re
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

import theme

PPR = [200, 128, 64, 32, 256, 160, 96, 48]
TT_STYLES = ["Style 1 (Blade)", "Style 2 (Heatbar)", "Style 3 (Rainbow)", "Style 4"]
LIGHT_MODES = ["Normal", "Mode 1", "Mode 2", "Mode 3"]
KEY_NAMES = [f"Key {i}" for i in range(1, 8)] + [f"E{i}" for i in range(1, 5)]


# ------------------------------------------------------------------ parse ---
def parse_cfg(lines):
    """Parse the output of the patched firmware's `cfg` command."""
    cfg = {"globals": {}, "profiles": [dict(vals={}, on=[], off=[]) for _ in range(4)],
           "meta": {}}
    for l in lines:
        t = l.split()
        if not t:
            continue
        if t[0] == "CFG" and len(t) >= 7:
            cfg["meta"] = dict(version=int(t[2]), keys=int(t[4]), profile=int(t[6]))
        elif t[0] == "G" and len(t) == 4:
            cfg["globals"][t[1]] = (int(t[2]), int(t[3]))
        elif t[0] == "P" and len(t) == 5:
            cfg["profiles"][int(t[1])]["vals"][t[2]] = (int(t[3]), int(t[4]))
        elif t[0] in ("CON", "COFF") and len(t) == 13:
            cols = [tuple(int(x) for x in c.split(",")) for c in t[2:]]
            cfg["profiles"][int(t[1])]["on" if t[0] == "CON" else "off"] = cols
    return cfg


def parse_hall(lines):
    """Hall-effect key trigger settings from a `display` listing ("Key 1: 3706->1914, On: 16, Off: 21.")."""
    keys = []
    for l in lines:
        m = re.search(r"Key\s+(\d+): +(\d+)->\s*(\d+), On: +(\d+), Off: +(\d+)", l)
        if m:
            keys.append(dict(key=int(m[1]), on=int(m[4]), off=int(m[5])))
    return keys


def hsv_hex(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h / 255, s / 255, max(v, 0) / 255)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def hex_hsv(hexc):
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return round(h * 255), round(s * 255), round(v * 255)


# --------------------------------------------------------------------- UI ---
class IidxScreens:
    def build_iidx_tabs(self):
        if self.full:
            self.tab_general()
            for p in range(4):
                self.tab_profile(p)
        self.tab_hall()
        self.tab_raw()

    def tab_general(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="General")
        g = self.cfg["globals"]
        r = 0
        ttk.Label(f, text=f"Firmware config v{self.cfg['meta']['version']} - active profile:").grid(
            row=r, column=0, sticky="w")
        pv = tk.IntVar(value=self.cfg["meta"]["profile"] + 1)
        cb = ttk.Combobox(f, values=[1, 2, 3, 4], textvariable=pv, width=4, state="readonly")
        cb.grid(row=r, column=1, sticky="w", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self.send(f"profile {pv.get() - 1}"))
        r += 1

        def check(label, name):
            nonlocal r
            v = tk.BooleanVar(value=bool(g[name][0]))
            theme.Switch(f, text=label, variable=v,
                         command=lambda: self.send(f"set {name} {int(v.get())}", name, 0)).grid(
                row=r, column=0, columnspan=3, sticky="w", pady=2)
            r += 1

        check("Konami spoof mode (needs replug)", "konami")
        check("Turntable direction reversed", "sensor_rev")
        check("Binary / LR2 turntable mode", "binary")
        check("Turntable LEDs wired in reverse", "tt_rev")
        check("Key LEDs use RGB order (instead of GRB)", "rgb_main")
        check("Turntable LEDs use RGB order", "rgb_tt")
        check("Effect LEDs use RGB order", "rgb_fx")

        ttk.Label(f, text="Turntable resolution (PPR):").grid(row=r, column=0, sticky="w", pady=6)
        pp = tk.StringVar(value=str(PPR[g["ppr"][0] & 7]))
        pc = ttk.Combobox(f, values=[str(x) for x in PPR], textvariable=pp, width=6, state="readonly")
        pc.grid(row=r, column=1, sticky="w", padx=8)
        pc.bind("<<ComboboxSelected>>", lambda e: self.send(f"set ppr {PPR.index(int(pp.get()))}"))
        r += 1
        self.scale(f, "Turntable first LED", "tt_start", g["tt_start"][0], 8,
                   lambda v: self.send(f"set tt_start {v}"), r); r += 1
        self.scale(f, "Turntable LED count", "tt_num", g["tt_num"][0], 128,
                   lambda v: self.send(f"set tt_num {max(v, 1)}"), r, vmin=1); r += 1

    def tab_profile(self, p):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text=f"Profile {p + 1}")
        pr = self.cfg["profiles"][p]["vals"]
        self.scale(f, "Key LED brightness", "", pr["lvl_keys"][0], 255,
                   lambda v: self.send(f"pset {p} lvl_keys {v}"), 0)
        self.scale(f, "Turntable LED brightness", "", pr["lvl_tt"][0], 255,
                   lambda v: self.send(f"pset {p} lvl_tt {v}"), 1)
        self.scale(f, "Turntable effect parameter", "", pr["param"][0], 255,
                   lambda v: self.send(f"pset {p} param {v}"), 2)

        ttk.Label(f, text="Turntable effect").grid(row=3, column=0, sticky="w", pady=6)
        sv = tk.StringVar(value=TT_STYLES[pr["style"][0] % 4])
        sc = ttk.Combobox(f, values=TT_STYLES, textvariable=sv, state="readonly", width=22)
        sc.grid(row=3, column=1, sticky="w", padx=8)
        sc.bind("<<ComboboxSelected>>", lambda e: self.send(f"pset {p} style {TT_STYLES.index(sv.get())}"))
        ttk.Label(f, text="Hall key light mode").grid(row=4, column=0, sticky="w", pady=6)
        lv = tk.StringVar(value=LIGHT_MODES[pr["lmode"][0] % 4])
        lc = ttk.Combobox(f, values=LIGHT_MODES, textvariable=lv, state="readonly", width=22)
        lc.grid(row=4, column=1, sticky="w", padx=8)
        lc.bind("<<ComboboxSelected>>", lambda e: self.send(f"pset {p} lmode {LIGHT_MODES.index(lv.get())}"))

        box = ttk.LabelFrame(f, text="Key colors (click a swatch)  -  top: pressed, bottom: released", padding=8)
        box.grid(row=5, column=0, columnspan=3, sticky="we", pady=14)
        for i in range(11):
            ttk.Label(box, text=KEY_NAMES[i]).grid(row=0, column=i, padx=4)
            for row, state in ((1, "on"), (2, "off")):
                col = self.cfg["profiles"][p][state][i]
                b = tk.Button(box, width=5, height=2, bg=hsv_hex(*col), relief="raised",
                              activebackground=hsv_hex(*col))
                b.grid(row=row, column=i, padx=3, pady=3)
                b.config(command=lambda b=b, i=i, state=state: self.pick(b, p, state, i))

    def pick(self, btn, p, state, i):
        rgb, hexc = colorchooser.askcolor(color=btn.cget("bg"), title="Pick color")
        if not hexc:
            return
        h, s, v = hex_hsv(hexc)
        btn.config(bg=hexc, activebackground=hexc)
        self.send(f"color {p} {state} {i} {h} {s} {v}", f"c{p}{state}{i}", 0)

    def tab_hall(self):
        """Hall-effect key trigger distances (used by every controller that has Hall keys)."""
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Hall keys")
        if not self.hall:
            ttk.Label(f, text="No Hall-effect keys reported by this device.").pack()
            return
        ttk.Label(f, text="Actuation (ON) and reset (OFF) distance, 1-36 (applies to the active profile).").pack(
            anchor="w")
        grid = ttk.Frame(f)
        grid.pack(anchor="w", pady=8)
        self.hall_vars = []
        for r, k in enumerate(self.hall):
            ttk.Label(grid, text=f"Key {k['key']}").grid(row=r, column=0, padx=6, pady=3)
            on, off = tk.IntVar(value=k["on"]), tk.IntVar(value=k["off"])
            for c, (lab, var) in enumerate((("ON", on), ("OFF", off))):
                ttk.Label(grid, text=lab).grid(row=r, column=1 + c * 3)
                ttk.Spinbox(grid, from_=1, to=36, width=4, textvariable=var,
                            command=lambda n=k["key"], o=on, x=off: self.send(
                                f"trigger {n} {o.get()} {x.get()}", f"trig{n}", 300)).grid(
                    row=r, column=2 + c * 3, padx=4)
            self.hall_vars.append((k["key"], on, off))
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=8)
        ttk.Label(row, text="Set all keys:").pack(side="left")
        a_on, a_off = tk.IntVar(value=self.hall[0]["on"]), tk.IntVar(value=self.hall[0]["off"])
        ttk.Spinbox(row, from_=1, to=36, width=4, textvariable=a_on).pack(side="left", padx=4)
        ttk.Spinbox(row, from_=1, to=36, width=4, textvariable=a_off).pack(side="left", padx=4)

        def apply_all():
            self.send(f"trigger all {a_on.get()} {a_off.get()}", "trigall", 0)
            for _, o, x in self.hall_vars:
                o.set(a_on.get())
                x.set(a_off.get())
        theme.Button(row, text="Apply", command=apply_all).pack(side="left")
        ttk.Separator(f).pack(fill="x", pady=10)
        theme.Button(f, text="Calibrate...", command=self.calibrate).pack(anchor="w")

    def calibrate(self):
        if not messagebox.askokcancel(
                "Calibrate", "1. Keep your hands OFF the keys when you press OK.\n"
                "2. After about 2 seconds the device says to press the keys: press all 7 keys fully, "
                "a few times each, for 10 seconds.\n\nThe result is saved automatically if it succeeds."):
            return
        self.status.set("Calibrating - press all keys for 10 seconds...")
        self.run_bg(lambda: self.dev.ask("calibrate", timeout=20),
                    lambda r: (messagebox.showinfo("Calibration", "\n".join(r)), self.load()))
