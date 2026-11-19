"""IIDX Pico / Jumbo companion app.

Talks to the controller's built-in CLI over USB serial (Windows, stdlib only).
Works in two modes:
  * Full mode  - firmware has the `cfg`/`set`/`pset`/`color` commands (see firmware patch).
  * Legacy mode - stock firmware: Hall trigger distances, calibrate, save, factory reset.
"""
import colorsys
import ctypes
import re
import threading
import time
import tkinter as tk
import theme
from ctypes import wintypes
from tkinter import colorchooser, messagebox, ttk

PROMPT = "iidx_pico>"
VID_PID = "VID_CAFF&PID_002E"
PPR = [200, 128, 64, 32, 256, 160, 96, 48]
TT_STYLES = ["Style 1 (Blade)", "Style 2 (Heatbar)", "Style 3 (Rainbow)", "Style 4"]
LIGHT_MODES = ["Normal", "Mode 1", "Mode 2", "Mode 3"]
KEY_NAMES = [f"Key {i}" for i in range(1, 8)] + [f"E{i}" for i in range(1, 5)]


# ---------------------------------------------------------------- serial ----
class Serial:
    GENERIC_RW = 0xC0000000
    OPEN_EXISTING = 3

    class TIMEOUTS(ctypes.Structure):
        _fields_ = [(n, wintypes.DWORD) for n in (
            "ReadIntervalTimeout", "ReadTotalTimeoutMultiplier", "ReadTotalTimeoutConstant",
            "WriteTotalTimeoutMultiplier", "WriteTotalTimeoutConstant")]

    def __init__(self, port):
        k = ctypes.windll.kernel32
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k.WriteFile.argtypes = k.ReadFile.argtypes
        k.SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(self.TIMEOUTS)]
        k.EscapeCommFunction.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k = k
        h = k.CreateFileW("\\\\.\\" + port, self.GENERIC_RW, 0, None, self.OPEN_EXISTING, 0, None)
        if h in (None, wintypes.HANDLE(-1).value):
            raise OSError(f"Cannot open {port} (in use by another program?)")
        self.h = h
        # Non-blocking reads: return immediately with whatever is buffered.
        k.SetCommTimeouts(h, ctypes.byref(self.TIMEOUTS(0xFFFFFFFF, 0, 0, 0, 0)))
        k.EscapeCommFunction(h, 5)  # SETDTR - firmware only talks when DTR is up

    def read(self):
        buf = ctypes.create_string_buffer(4096)
        n = wintypes.DWORD(0)
        self.k.ReadFile(self.h, buf, 4096, ctypes.byref(n), None)
        return buf.raw[:n.value].decode("utf-8", "replace")

    def write(self, text):
        data = text.encode()
        n = wintypes.DWORD(0)
        self.k.WriteFile(self.h, data, len(data), ctypes.byref(n), None)

    def close(self):
        self.k.CloseHandle(self.h)


def find_ports():
    """Return (preferred_port, all_ports) using the registry (no extra packages)."""
    import winreg
    ports = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
            for i in range(winreg.QueryInfoKey(k)[1]):
                ports.append(winreg.EnumValue(k, i)[1])
    except OSError:
        pass
    preferred = None
    try:
        base = r"SYSTEM\CurrentControlSet\Enum\USB\\" + VID_PID + "&MI_01"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                with winreg.OpenKey(k, winreg.EnumKey(k, i) + r"\Device Parameters") as d:
                    name = winreg.QueryValueEx(d, "PortName")[0]
                    if name in ports:
                        preferred = name
    except OSError:
        pass
    return preferred, sorted(set(ports), key=lambda p: int(re.sub(r"\D", "", p) or 0))


class Device:
    """Thread-safe request/response wrapper over the CLI."""

    def __init__(self, port, prompt=PROMPT):
        self.prompt = prompt
        self.ser = Serial(port)
        self.lock = threading.Lock()
        time.sleep(0.5)          # firmware prints a banner ~200 ms after DTR
        self.ser.read()
        self.ask("")             # sync to a fresh prompt

    def ask(self, cmd, timeout=3.0):
        with self.lock:
            self.ser.read()
            self.ser.write(cmd + "\r")
            out, end = "", time.time() + timeout
            while time.time() < end:
                time.sleep(0.02)
                out += self.ser.read()
                if out.rstrip().endswith(self.prompt):
                    break
            lines = [l.strip() for l in out.replace("\r", "\n").split("\n")]
            lines = [l for l in lines if l and l != cmd and not l.startswith(self.prompt)
                     and not l.startswith("Save requested") and not l.startswith("Program Flash")]
            return lines

    def close(self):
        self.ser.close()


# ------------------------------------------------------------------ parse ---
def parse_cfg(lines):
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
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("IIDX Pico / Jumbo Companion")
        self.geometry("820x640")
        self.dev = None
        self.cfg = None
        self.full = False
        self.pending = {}
        self.busy = False

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Port:").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(top, textvariable=self.port_var, width=8, state="readonly")
        self.port_box.pack(side="left", padx=4)
        theme.Button(top, text="Connect", command=self.connect).pack(side="left")
        theme.Button(top, text="Refresh", command=self.load).pack(side="left", padx=4)
        theme.Button(top, text="Save to flash now", command=self.save_now).pack(side="left")
        self.status = tk.StringVar(value="Not connected")
        ttk.Label(top, textvariable=self.status).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.after(100, self.initial_connect)

    # -- connection
    def initial_connect(self):
        pref, ports = find_ports()
        self.port_box["values"] = ports
        if pref or ports:
            self.port_var.set(pref or ports[0])
        if pref:
            self.connect()
        else:
            self.status.set("Controller serial port not found - pick a port and press Connect")

    def connect(self):
        try:
            if self.dev:
                self.dev.close()
            self.dev = Device(self.port_var.get())
        except OSError as e:
            messagebox.showerror("Connect failed", str(e))
            self.dev = None
            return
        self.load()

    def run_bg(self, fn, then=None):
        def worker():
            res = fn()
            if then:
                self.after(0, lambda: then(res))
        threading.Thread(target=worker, daemon=True).start()

    def load(self):
        if not self.dev:
            return
        self.status.set("Reading device...")

        def job():
            cfg_lines = self.dev.ask("cfg")
            full = any(l.startswith("CFG-BEGIN") for l in cfg_lines)
            disp = self.dev.ask("display")
            return full, cfg_lines, disp

        def done(res):
            full, cfg_lines, disp = res
            self.full = full
            self.cfg = parse_cfg(cfg_lines) if full else None
            self.hall = parse_hall(disp)
            self.disp_text = "\n".join(disp)
            self.build_tabs()
            self.status.set("Connected (full mode)" if full else
                            "Connected (stock firmware: limited settings)")
        self.run_bg(job, done)

    # -- sending
    def send(self, cmd, key=None, delay=250):
        """Debounced send; the latest command per key wins (so sliders don't flood the device)."""
        key = key or cmd
        if key in self.pending:
            self.after_cancel(self.pending[key])
        self.pending[key] = self.after(delay, lambda: self._fire(key, cmd))

    def _fire(self, key, cmd):
        self.pending.pop(key, None)
        if not self.dev:
            return
        self.status.set("Sending...")
        self.run_bg(lambda: self.dev.ask(cmd),
                    lambda r: self.status.set("Saved to RAM; auto-saves to flash in ~5 s"
                                              if r and r[-1] == "OK" else f"Device: {' '.join(r)}"))

    def save_now(self):
        if self.dev:
            self.run_bg(lambda: self.dev.ask("save"), lambda r: self.status.set("Saved to flash"))

    # -- tabs
    def build_tabs(self):
        for t in self.nb.tabs():
            self.nb.forget(t)
        if self.full:
            self.tab_general()
            for p in range(4):
                self.tab_profile(p)
        self.tab_hall()
        self.tab_raw()

    def scale(self, parent, label, name, val, vmax, cmd, row, vmin=0):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        sl = theme.Slider(parent, vmin, vmax, val, cmd)
        sl.grid(row=row, column=1, columnspan=2, sticky="w", padx=8)
        return sl

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

    def tab_raw(self):
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="Device / CLI")
        t = tk.Text(f, height=14, font=("Consolas", 10))
        t.pack(fill="both", expand=True)
        t.insert("1.0", self.disp_text)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=6)
        e = ttk.Entry(row)
        e.pack(side="left", fill="x", expand=True)

        def run(_=None):
            cmd = e.get().strip()
            if cmd.lower().startswith(("update", "factory")) and not messagebox.askyesno(
                    "Confirm", f"'{cmd}' is disruptive. Run it?"):
                return
            e.delete(0, "end")
            self.run_bg(lambda: self.dev.ask(cmd), lambda r: (t.insert("end", f"\n> {cmd}\n" + "\n".join(r) + "\n"),
                                                               t.see("end")))
        e.bind("<Return>", run)
        theme.Button(row, text="Send", command=run).pack(side="left", padx=4)
        theme.Button(row, text="Factory reset", command=lambda: (
            messagebox.askyesno("Factory reset", "Erase ALL settings on the device?") and
            self.run_bg(lambda: self.dev.ask("factory"), lambda r: self.load()))).pack(side="left")


if __name__ == "__main__":
    App().mainloop()
