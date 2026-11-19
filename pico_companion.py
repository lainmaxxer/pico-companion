"""Pico Companion - settings app for whowechina "pico" controllers.

Scans serial ports, identifies each controller by the prompt its CLI prints
(for example "iidx_pico>" or "musec_pico>") and shows a settings screen for it.
Supported: IIDX Pico (full with the extended firmware, limited on stock),
Musec Pico (stock firmware). Any other *_pico device gets a generic screen
(LED level + raw console).
"""
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import iidx_companion as ic
import profiles
import theme
from iidx_companion import Device, Serial, find_ports

__version__ = "1.0.0"
PROMPT_RE = re.compile(r"(\w+_pico)>\s*$")
DANGEROUS = ("update", "factory")


def probe(port):
    """Return the CLI prompt name (e.g. 'musec_pico') if a pico CLI answers on this port."""
    try:
        s = Serial(port)
    except OSError:
        return None
    try:
        time.sleep(0.4)
        s.read()
        s.write("\r")
        out, end = "", time.time() + 1.5
        while time.time() < end:
            time.sleep(0.05)
            out += s.read()
            m = PROMPT_RE.search(out.replace("\r", "\n").strip())
            if m:
                return m.group(1)
    finally:
        s.close()
    return None


def scan(skip=()):
    """Probe every serial port except those in `skip` (ports we already hold open)."""
    _, ports = find_ports()
    found = []
    for p in dict.fromkeys(ports):  # unique, keep order
        if p in skip:
            continue
        name = probe(p)
        if name:
            found.append((name, p))
    return found


def kv(lines, pattern, cast=str):
    for l in lines:
        m = re.search(pattern, l)
        if m:
            return cast(m.group(1))
    return None


class PicoApp(ic.App):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title(f"Pico Companion {__version__}")
        self.geometry("980x720")
        self.minsize(820, 560)
        theme.load_mode()          # restores light/dark from the last run
        theme.setup(self)
        self.dev = None
        self.cfg = None
        self.full = False
        self.hall = []
        self.disp_text = ""
        self.pending = {}
        self.prof = None
        self.dev_port = None
        self.devices = []
        self.status = tk.StringVar(value="Scanning...")
        self._auto_done = False
        self._build_ui()
        self.after(100, self.rescan)
        self._snapshot = None
        self.after(2000, self._watch_ports)

    def _build_ui(self):
        # Gradient backdrop with two rounded cards on top, like the web configurator.
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        head = tk.Frame(self.canvas, bg=theme.CARD)
        main = tk.Frame(self.canvas, bg=theme.CARD)
        self._head_win = self.canvas.create_window(0, 0, anchor="nw", window=head)
        self._main_win = self.canvas.create_window(0, 0, anchor="nw", window=main)
        self._head, self._main = head, main

        left = tk.Frame(head, bg=theme.CARD)
        left.pack(side="left")
        tk.Label(left, text="Pico Companion", bg=theme.CARD, fg=theme.TEXT, font=theme.FONT_H1).pack(anchor="w")
        self.subtitle = tk.Label(left, text="whowechina pico controllers", bg=theme.CARD, fg=theme.MUTED,
                                 font=("Segoe UI", 9))
        self.subtitle.pack(anchor="w")
        self._dark_var = tk.BooleanVar(value=theme.MODE == "dark")
        theme.Switch(left, text="Dark mode", variable=self._dark_var, command=self.toggle_dark).pack(
            anchor="w", pady=(8, 0))
        right = tk.Frame(head, bg=theme.CARD)
        right.pack(side="right")
        self.pill = theme.Pill(right)
        self.pill.grid(row=0, column=0, padx=(0, 12))
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(right, textvariable=self.port_var, width=28, state="readonly")
        self.port_box.grid(row=0, column=1, padx=(0, 8))
        self.port_box.bind("<<ComboboxSelected>>", lambda e: self.connect())
        bw = 128  # equal button widths so the two rows line up
        theme.Button(right, text="Scan", command=self.rescan, minw=bw).grid(row=0, column=2, padx=3)
        self.conn_btn = theme.Button(right, text="Connect", command=self.toggle_connection, kind="primary", minw=bw)
        self.conn_btn.grid(row=0, column=3, padx=3)
        self._conn_label = None
        theme.Button(right, text="Refresh", command=self.load, minw=bw).grid(row=1, column=2, padx=3, pady=(10, 0))
        theme.Button(right, text="Save to flash", command=self.save_now, minw=bw).grid(
            row=1, column=3, padx=3, pady=(10, 0))

        tk.Label(main, textvariable=self.status, bg=theme.CARD, fg=theme.MUTED, anchor="w", padx=6, pady=4,
                 font=("Segoe UI", 9)).pack(fill="x", side="bottom")
        self.nb = ttk.Notebook(main)
        self.nb.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._layout)

    def toggle_dark(self):
        """Switch light/dark, remember it for the next start, and rebuild the window contents."""
        theme.set_mode("dark" if self._dark_var.get() else "light")
        theme.save_mode()
        selected = self.port_box.current()
        self.canvas.destroy()
        theme.setup(self)
        self._build_ui()
        labels = [f"{n} ({p})" for n, p in self.devices]
        self.port_box["values"] = labels
        if 0 <= selected < len(labels):
            self.port_box.current(selected)
        if self.dev:
            self.load()      # re-reads the connected device and rebuilds its tabs in the new colors

    CARD_R, CARD_PAD, MARGIN = 16, 22, 24

    def _layout(self, e):
        w, h = e.width, e.height
        c, m, pad = self.canvas, self.MARGIN, self.CARD_PAD
        theme.paint_gradient(c, w, h)
        c.delete("card")
        c.itemconfig(self._head_win, width=w - 2 * m - 2 * pad)
        self.update_idletasks()
        hh = self._head.winfo_reqheight() + 2 * pad
        theme.round_rect(c, m, m, w - m, m + hh, self.CARD_R, fill=theme.CARD, tags="card")
        c.coords(self._head_win, m + pad, m + pad)
        top = m + hh + 18
        bottom = max(h - m, top + 120)
        theme.round_rect(c, m, top, w - m, bottom, self.CARD_R, fill=theme.CARD, tags="card")
        inset = 12
        c.coords(self._main_win, m + inset, top + inset)
        c.itemconfig(self._main_win, width=w - 2 * m - 2 * inset, height=bottom - top - 2 * inset)
        c.tag_lower("card")
        c.tag_lower("grad")

    def toggle_connection(self):
        if self.dev:
            self.disconnect()
        else:
            self.connect()

    def disconnect(self):
        dev, self.dev, self.dev_port = self.dev, None, None
        try:
            dev.close()
        except Exception:
            pass
        for t in self.nb.tabs():
            w = self.nb.nametowidget(t)
            self.nb.forget(t)
            w.destroy()
        self.status.set("Disconnected")

    # -- thread-safe background jobs: workers queue results, the Tk thread delivers them
    def run_bg(self, fn, then=None):
        if not hasattr(self, "_q"):
            import queue
            self._q = queue.Queue()
            self._poll()

        def worker():
            try:
                res = fn()
            except Exception as e:  # keep the UI alive on serial errors
                res, then_ = None, (lambda _r, e=e: self.status.set(f"Error: {e}"))
                self._q.put((then_, res))
                return
            self._q.put((then, res))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        import queue
        while True:
            try:
                then, res = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                if then:
                    then(res)
            except Exception as e:
                self.status.set(f"UI error: {e}")
        self.pill.set(self.dev is not None)
        want = "Disconnect" if self.dev else "Connect"
        if getattr(self, "_conn_label", None) != want:
            self._conn_label = want
            self.conn_btn.set_text(want)
        self.after(50, self._poll)

    # -- discovery / connection
    def _watch_ports(self):
        """Rescan automatically when a serial port appears or disappears (plug / unplug)."""
        try:
            ports = frozenset(find_ports()[1])
            if self._snapshot is not None and ports != self._snapshot and not getattr(self, "_scanning", False):
                self.rescan()
            self._snapshot = ports
        except Exception:
            pass
        self.after(2000, self._watch_ports)

    def rescan(self):
        self.status.set("Scanning serial ports...")
        self._scanning = True
        held = self.dev_port
        skip = (held,) if held and self.dev else ()

        def done(found):
            self._scanning = False
            if skip:  # the connected device keeps its port open, so it can't be probed: keep it listed
                found = sorted(found + [(self.prof, held)], key=lambda x: int(re.sub(r"\D", "", x[1]) or 0))
            self.devices = found
            labels = [f"{n} ({p})" for n, p in found]
            self.port_box["values"] = labels
            if labels:
                keep = [i for i, d in enumerate(found) if d[1] == held] if skip else []
                self.port_box.current(keep[0] if keep else 0)
                self.status.set(f"Found {len(labels)} device(s)")
                if self.dev is None and not self._auto_done:
                    self._auto_done = True
                    self.connect()
            else:
                self.status.set("No pico controller found - plug one in")
        self.run_bg(lambda: scan(skip), done)

    def connect(self):
        sel = self.port_box.current()
        if sel < 0:
            return
        name, port = self.devices[sel]
        try:
            if self.dev:
                self.dev.close()
                self.dev = None
            self.dev = Device(port, prompt=name + ">")
            self.dev_port = port
        except OSError as e:
            messagebox.showerror("Connect failed", str(e))
            return
        self.prof = name
        self.load()

    def load(self):
        if not self.dev:
            return
        self.status.set("Reading device...")
        prof = self.prof

        def job():
            d = self.dev
            r = {}
            r["help"] = d.ask("?")
            if prof == "iidx_pico":
                cfg_lines = d.ask("cfg")
                r["full"] = any(l.startswith("CFG-BEGIN") for l in cfg_lines)
                r["cfg"] = cfg_lines
            r["disp"] = d.ask("display")
            if prof == "musec_pico":
                r["spin_usage"] = " ".join(d.ask("spin"))
            r["probes"] = {c: d.ask(c) for c in profiles.PROBES.get(prof, [])}
            return r

        def done(r):
            self.help = r["help"]
            self.disp = r["disp"]
            self.disp_text = "\n".join(r["disp"])
            if prof == "iidx_pico":
                self.full = r["full"]
                self.cfg = ic.parse_cfg(r["cfg"]) if self.full else None
                self.hall = ic.parse_hall(r["disp"])
            elif prof == "musec_pico":
                self.spin_usage = r["spin_usage"]
            self.probes = r["probes"]
            self.build_tabs()
            sn = kv(self.help, r"SN: (\w+)") or "?"
            built = kv(self.help, r"Built: (.+)") or "?"
            extra = ""
            if prof == "iidx_pico" and not self.full:
                extra = " - stock firmware: limited settings"
            self.status.set(f"{prof} SN {sn}, built {built}{extra}")
        self.run_bg(job, done)

    # -- sending (response check differs from the IIDX-only app)
    def _fire(self, key, cmd):
        self.pending.pop(key, None)
        if not self.dev:
            return
        self.status.set("Sending...")

        def shown(r):
            bad = [l for l in r if l.startswith(("Usage", "ERR", "Unknown"))]
            self.status.set(f"Device: {bad[0]}" if bad else
                            "Applied. Auto-saves to flash in a few seconds (or press Save now).")
        self.run_bg(lambda: self.dev.ask(cmd), shown)

    # -- tabs
    def build_tabs(self):
        for t in self.nb.tabs():
            w = self.nb.nametowidget(t)
            self.nb.forget(t)
            w.destroy()  # forget() alone leaks the old tab's widgets
        if self.prof == "iidx_pico":
            ic.App.build_tabs(self)
        elif self.prof == "musec_pico":
            self.tab_musec()
            self.tab_raw()
        elif self.prof == "aic_pico":
            self.tab_aic()
            self.tab_raw()
        elif self.prof in profiles.PROFILES:
            self.tab_declared()
            self.hall = ic.parse_hall(self.disp)
            if self.hall:
                self.tab_hall()
            self.tab_raw()
        else:
            self.tab_generic()
            self.tab_raw()

    def level_row(self, parent, row, cmd="level"):
        lvl = kv(self.disp, r"Level: (\d+)", int)
        if lvl is None:
            return
        self.scale(parent, "LED brightness", "", lvl, 255, lambda v: self.send(f"{cmd} {v}"), row)

    def tab_generic(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="General")
        ttk.Label(f, text=f"{self.prof}: no dedicated screen yet. Use the console tab.").grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.level_row(f, 1)

    def tab_declared(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Settings")
        if self.prof not in profiles.VERIFIED:
            ttk.Label(f, foreground=theme.WARN, wraplength=700, justify="left",
                      text="Written from the firmware source and not yet tested on this device model. "
                           "Controls only appear for settings the device reports. If something looks wrong, "
                           "use the Device / CLI tab.").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        specs = profiles.build(self.prof, self.disp_text, self.probes)
        r = 1
        for s in specs:
            k, lab = s["kind"], s.get("label", "")
            key = f"{self.prof}:{lab}"
            if k == "slider":
                self.scale(f, lab, "", s["val"], s["hi"], lambda v, s=s, key=key: self.send(s["cmd"](v), key),
                           r, vmin=s["lo"])
            elif k == "check":
                v = tk.BooleanVar(value=s["val"])
                theme.Switch(f, text=lab, variable=v,
                                command=lambda s=s, v=v, key=key: self.send(s["cmd"](v.get()), key, 0)
                                ).grid(row=r, column=0, columnspan=3, sticky="w", pady=4)
            elif k == "choice":
                ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", pady=5)
                var = tk.StringVar(value=s["cur"] or "")
                cb = ttk.Combobox(f, values=s["options"], textvariable=var, width=14, state="readonly")
                cb.grid(row=r, column=1, sticky="w", padx=8)
                cb.bind("<<ComboboxSelected>>",
                        lambda e, s=s, var=var, key=key: self.send(s["cmd"](var.get()), key, 0))
            elif k == "buttons":
                ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", pady=5)
                bf = ttk.Frame(f)
                bf.grid(row=r, column=1, columnspan=2, sticky="w")
                for text, cmd in s["buttons"]:
                    theme.Button(bf, text=text, command=lambda c=cmd, s=s: (
                        self.send(c, c, 0), s["reload"] and self.after(900, self.load))).pack(side="left", padx=3)
            elif k == "info":
                ttk.Label(f, text=s["text"], wraplength=700, justify="left").grid(
                    row=r, column=0, columnspan=3, sticky="w", pady=8)
            r += 1
        if not specs:
            ttk.Label(f, text="No known settings reported by this device. Use the Device / CLI tab.").grid(row=r, column=0)

    def combo(self, parent, row, label, values, current, cmd_fmt, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        var = tk.StringVar(value=current if current in values else values[0])
        cb = ttk.Combobox(parent, values=values, textvariable=var, width=14, state="readonly")
        cb.grid(row=row, column=1, sticky="w", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self.send(cmd_fmt.format(var.get()), key, 0))
        return var

    def tab_aic(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="AIC")
        d, txt = self.disp, self.disp_text
        m = re.search(r"RGB-(ON|OFF)(?: \((\w+)\))?, LED-(ON|OFF)", txt)
        rgb_on, order, led_on = (m[1] == "ON", (m[2] or "grb").lower(), m[3] == "ON") if m else (True, "grb", True)
        helptxt = " ".join(self.help)
        lcd_usage = " ".join(self.probes.get("lcd", []))
        light = "both" if rgb_on and led_on else "rgb" if rgb_on else "led" if led_on else "off"
        r = 0
        self.combo(f, r, "Lights", ["rgb", "led", "both", "off"], light, "light {}", "light"); r += 1
        if "rgb-order" in helptxt:  # older firmware has no RGB order setting
            self.combo(f, r, "RGB color order", ["grb", "brg", "rgb", "rbg"], order, "rgb-order {}", "order"); r += 1
        lv = re.search(r"Level: Idle-(\d+), Active-(\d+)", txt)
        if lv:
            st = {"i": int(lv[1]), "a": int(lv[2])}

            def lvl(k, v):
                st[k] = v
                self.send(f"level {st['i']} {st['a']}", "level")
            self.scale(f, "Light level (idle)", "", st["i"], 255, lambda v: lvl("i", v), r); r += 1
            self.scale(f, "Light level (active)", "", st["a"], 255, lambda v: lvl("a", v), r); r += 1
        bl = kv(d, r"Backlight: (\d+)", int)
        if bl is not None:
            bl_cmd = "lcd backlight {}" if "lcd backlight" in lcd_usage else "lcd {}"  # older firmware: "lcd <n>"
            self.scale(f, "LCD backlight", "", bl, 255, lambda v: self.send(bl_cmd.format(v), "lcdbl"), r); r += 1
            orient = kv(d, r"Orientation: (\w+)")
            if orient and "orientation" in lcd_usage:
                self.combo(f, r, "LCD orientation", ["auto", "up", "down"], orient.lower(), "lcd orientation {}", "orient"); r += 1
        mode = (kv(d, r"Mode: (\w+)") or "auto").lower()
        self.combo(f, r, "Reader mode", ["auto", "aime0", "aime1", "bana"], mode, "mode {}", "mode"); r += 1
        v = tk.BooleanVar(value=kv(d, r"Virtual AIC: (ON|OFF)") == "ON")
        theme.Switch(f, text="Virtual AIC card", variable=v,
                        command=lambda: self.send(f"virtual {'on' if v.get() else 'off'}", "virtual", 0)
                        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=5); r += 1
        info = ttk.LabelFrame(f, text="Device info (read-only)", padding=8)
        info.grid(row=r, column=0, columnspan=3, sticky="we", pady=12)
        nfc = next((l for i, l in enumerate(d) if l.startswith("[NFC Module]")), None)
        lines = [f"NFC module: {d[d.index('[NFC Module]') + 1]}" if "[NFC Module]" in d else "",
                 f"Detected card protocol: {kv(d, r'Detected: (\w+)') or '-'}",
                 f"Accelerometer (LIS3DH): {kv(d, r'LIS3DH: (.+)') or '-'}",
                 f"Auto PIN-entry: {kv(d, r'Status: (ON|OFF)') or '-'} (slots are managed in the CLI tab)"]
        ttk.Label(info, text="\n".join(l for l in lines if l), justify="left").pack(anchor="w")

    def tab_musec(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Musec Pico")
        d = self.disp
        self.level_row(f, 0)
        upt = kv(d, r"Units Per Turn: (\d+)", int)
        r = 1
        if upt is not None:
            self.scale(f, "Spin units per turn", "", upt, 255, lambda v: self.send(f"spin rate {max(v, 20)}"),
                       r, vmin=20)
            r += 1
        thr = kv(d, r"Suppress Threshold: (\d+)", int)
        if thr is not None:
            decay = kv(d, r"Suppress Decay: (\d+)", int) or 1
            state = {"t": thr, "d": decay}

            def sup(k, v):
                state[k] = v
                self.send(f"spin suppress {state['t']} {max(1, state['d'])}", "suppress")
            self.scale(f, "Spin suppress threshold (0 = off)", "", thr, 255, lambda v: sup("t", v), r)
            self.scale(f, "Spin suppress decay", "", decay, 32, lambda v: sup("d", v), r + 1, vmin=1)
            r += 2
        fast = kv(d, r"Fast I2C: (ON|OFF)")
        if fast is not None:
            v = tk.BooleanVar(value=fast == "ON")
            theme.Switch(f, text="Fast I2C", variable=v,
                            command=lambda: self.send(f"spin fast_i2c {'on' if v.get() else 'off'}", "i2c", 0)
                            ).grid(row=r, column=0, columnspan=3, sticky="w", pady=4)
            r += 1

        # Direction words differ between firmware versions (normal|reverse vs forward|reversed).
        words = ("forward", "reversed") if "forward" in self.spin_usage else ("normal", "reverse")
        box = ttk.LabelFrame(f, text="Spinners (red = sensor not responding)", padding=8)
        box.grid(row=r, column=0, columnspan=3, sticky="we", pady=10)
        for i in range(1, 6):
            m = re.search(rf"Spinner {i}: (\w+), (\w+)", self.disp_text)
            ok, direction = (m[1], m[2].lower()) if m else ("?", words[0])
            ttk.Label(box, text=f"Spinner {i}", foreground=theme.DANGER if ok != "OK" else theme.TEXT).grid(
                row=0, column=i - 1, padx=8)
            var = tk.StringVar(value=words[1] if direction.startswith("rev") else words[0])
            cb = ttk.Combobox(box, values=list(words), textvariable=var, width=9, state="readonly")
            cb.grid(row=1, column=i - 1, padx=8, pady=3)
            cb.bind("<<ComboboxSelected>>", lambda e, i=i, var=var: self.send(f"spin {i} {var.get()}", f"spin{i}", 0))
            ttk.Label(box, text=ok, foreground=theme.SUCCESS if ok == "OK" else theme.DANGER).grid(row=2, column=i - 1)
        r += 1

        pbox = ttk.LabelFrame(f, text="Pedal", padding=8)
        pbox.grid(row=r, column=0, columnspan=3, sticky="we")
        for c, which in enumerate(("internal", "external")):
            on = (kv(d, rf"{which.capitalize()}: (ON|OFF)") == "ON")
            v = tk.BooleanVar(value=on)
            theme.Switch(pbox, text=f"{which.capitalize()} pedal", variable=v,
                            command=lambda w=which, v=v: self.send(f"pedal {w} {'on' if v.get() else 'off'}", w, 0)
                            ).grid(row=0, column=c, padx=10)

    def tab_raw(self):
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="Device / CLI")
        t = tk.Text(f, height=14, font=theme.MONO, bg=theme.CONSOLE_BG, fg=theme.CONSOLE_FG, insertbackground="#ffffff", relief="flat", padx=10, pady=8)
        t.pack(fill="both", expand=True)
        t.insert("1.0", self.disp_text)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=6)
        e = ttk.Entry(row)
        e.pack(side="left", fill="x", expand=True)

        def run(_=None):
            cmd = e.get().strip()
            if not cmd:
                return
            if cmd.lower().startswith(DANGEROUS) and not messagebox.askyesno(
                    "Confirm", f"'{cmd}' is disruptive. Run it?"):
                return
            e.delete(0, "end")
            self.run_bg(lambda: self.dev.ask(cmd, timeout=15),
                        lambda r: (t.insert("end", f"\n> {cmd}\n" + "\n".join(r) + "\n"), t.see("end")))
        e.bind("<Return>", run)
        theme.Button(row, text="Send", command=run).pack(side="left", padx=4)
        theme.Button(row, text="Firmware update mode...", command=self.update_mode).pack(side="left", padx=(8, 0))
        theme.Button(row, text="Factory reset", command=lambda: (
            messagebox.askyesno("Factory reset", "Erase ALL settings on the device?") and
            self.run_bg(lambda: self.dev.ask("factory"), lambda r: self.load()))).pack(side="left", padx=(6, 0))

    def update_mode(self):
        if not self.dev:
            return
        if not messagebox.askokcancel(
                "Firmware update mode",
                "The controller will reboot into update mode and stop working as a controller.\n"
                "A drive named RPI-RP2 will appear: copy a .uf2 firmware file onto it to flash.\n"
                "Unplug and replug the controller to leave update mode without flashing.\n\nContinue?"):
            return
        dev, self.dev = self.dev, None
        self.run_bg(lambda: dev.ask("update", timeout=2),
                    lambda r: (dev.close(), self.status.set("Update mode: look for the RPI-RP2 drive"),
                               [self.nb.forget(t) for t in self.nb.tabs()]))

    def save_now(self):
        if self.dev:
            self.run_bg(lambda: self.dev.ask("save"), lambda r: self.status.set("Saved to flash"))


if __name__ == "__main__":
    PicoApp().mainloop()
