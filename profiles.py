"""Declarative settings profiles for whowechina "pico" controllers.

Every profile was written from the project's firmware source (commands.c), NOT tested on real hardware
unless noted in VERIFIED. A profile is a function (display_text, probes) -> list of control specs.
A control is only produced when its value can be found in the device's own `display` output, so older
firmware that lacks a setting simply doesn't show it.

Control specs (dicts):
  slider  : label, val, lo, hi, cmd(int) -> str
  check   : label, val(bool), cmd(bool) -> str
  choice  : label, options(list[str]), cur(str|None), cmd(str) -> str
  buttons : label, buttons=[(text, command)], reload(bool)
  info    : text
"""
import re

# Devices whose profile has been run against real hardware (everything else is source-only).
VERIFIED = {"musec_pico", "aic_pico", "iidx_pico"}

# Commands run (read-only: they only print usage) when connecting, to adapt to the firmware version.
PROBES = {
    "bishi_pico": ["spin"],
    "voltex_pico": ["knob"],
    "aic_pico": ["lcd"],
}


def grab(t, pattern, cast=str, default=None, flags=re.I):
    m = re.search(pattern, t, flags)
    return cast(m.group(1)) if m else default


def onoff(v, on="on", off="off"):
    return on if v else off


def slider(label, val, lo, hi, cmd):
    return dict(kind="slider", label=label, val=val, lo=lo, hi=hi, cmd=cmd) if val is not None else None


def check(label, val, cmd):
    return dict(kind="check", label=label, val=val, cmd=cmd) if val is not None else None


def choice(label, options, cur, cmd):
    return dict(kind="choice", label=label, options=options, cur=cur, cmd=cmd)


def buttons(label, btns, reload=True):
    return dict(kind="buttons", label=label, buttons=btns, reload=reload)


def level(t, cmd="level {}", pattern=r"Level: (\d+)", label="LED brightness"):
    return slider(label, grab(t, pattern, int), 0, 255, lambda v: cmd.format(v))


def bool_text(t, pattern):
    v = grab(t, pattern)
    return None if v is None else v.lower() in ("on", "yes", "true")


def hid_choice(t, joy_pat, other_pat, other_word, label="HID mode"):
    """Choice among joy / <other> / both, from two on/off values in the display text."""
    joy, other = bool_text(t, joy_pat), bool_text(t, other_pat)
    if joy is None or other is None:
        return None
    cur = "both" if joy and other else "joy" if joy else other_word if other else None
    return choice(label, ["joy", other_word, "both"], cur, lambda o: f"hid {o}")


def filter_and_debounce(t):
    out = []
    f = re.search(r"Filter: (\d+), (\d+), (\d+)", t)
    if f:
        st = [int(f[1]), int(f[2]), int(f[3])]

        def mk(i):
            def cmd(v):
                st[i] = v
                return f"filter {st[0]} {st[1]} {st[2]}"
            return cmd
        out += [slider("Filter: first iterations", st[0], 0, 3, mk(0)),
                slider("Filter: second iterations", st[1], 0, 3, mk(1)),
                slider("Filter: sample interval", st[2], 0, 7, mk(2))]
    d = re.search(r"Debounce \(touch, release\): (\d+), (\d+)", t)
    if d:
        db = [int(d[1]), int(d[2])]

        def mkd(i):
            def cmd(v):
                db[i] = v
                return f"debounce {db[0]} {db[1]}"
            return cmd
        out += [slider("Debounce: touch", db[0], 0, 7, mkd(0)), slider("Debounce: release", db[1], 0, 7, mkd(1))]
    g = re.search(r"global: ([+-]?\d+)", t)
    if g:
        out.append(buttons(f"Global touch sensitivity (now {g[1]})",
                           [("Less (-)", "sense -"), ("Reset (0)", "sense 0"), ("More (+)", "sense +")]))
    return out


def aime(t):
    out = []
    v = bool_text(t, r"Virtual AIC: (\w+)")
    out.append(check("Virtual AIC card", v, lambda b: f"aime virtual {onoff(b)}"))
    m = grab(t, r"(?:Protocol )?Mode: (\d+)", int)
    if m is not None:
        out.append(choice("Aime protocol mode", ["0", "1"], str(m), lambda o: f"aime mode {o}"))
    return out


# ------------------------------------------------------------------ profiles
def popn(t, p):
    return [level(t)]


def dance(t, p):
    deg = grab(t, r"Rotate: (\d+) degree", int)
    cur = None if deg is None else str(deg)
    return [level(t), choice("Rotation (degrees)", ["0", "90", "180", "270"], cur,
                             lambda o: f"rotate {int(o) // 90}") if deg is not None else None]


def rock(t, p):
    out = [level(t)]
    inp = grab(t, r"Input: (Tip|Ring)")
    if inp:
        st = {"mode": inp.lower(), "invert": bool_text(t, r"Invert: (\w+)") or False}

        def send():
            return f"pedal {st['mode']}" + (" invert" if st["invert"] else "")

        def set_mode(o):
            st["mode"] = o
            return send()

        def set_inv(b):
            st["invert"] = b
            return send()
        out += [choice("Pedal input", ["tip", "ring"], st["mode"], set_mode),
                check("Invert pedal", st["invert"], set_inv)]
    out.append(hid_choice(t, r"Joy: (\w+)\.", r"Keyboard: (\w+)\.", "keyboard"))
    return out


def nos(t, p):
    out = []
    lv = re.search(r"Brightness: Key - (\d+), Logo - (\d+)", t)
    if lv:
        out += [slider("Key brightness", int(lv[1]), 0, 255, lambda v: f"level key {v}"),
                slider("Logo brightness", int(lv[2]), 0, 255, lambda v: f"level logo {v}")]
    mode = grab(t, r"Key Light Mode: (\w+)")
    if mode:
        out.append(choice("Key light mode", ["off", "switch", "pressure", "velocity"], mode.lower(),
                          lambda o: f"light {o}"))
    h = re.search(r"Button - (\w+), Analog - (\w+), MIDI - (\w+)", t)
    if h:
        for i, name in enumerate(("button", "analog", "midi")):
            out.append(check(f"HID: {name}", h[i + 1].lower() == "on",
                             lambda b, n=name: f"hid {n} {onoff(b)}"))
    return out


def bishi(t, p):
    out = [level(t)]
    usage = " ".join(p.get("spin", []))
    units = grab(t, r"Units Per Turn: (\d+)", int)
    if units is not None:
        tmpl = "spin rate {}" if "spin rate" in usage else "spin {}"
        out.append(slider("Spin units per turn", units, 20, 255, lambda v: tmpl.format(max(v, 20))))
    rev = grab(t, r"Spinner: \w+, (\w+)")
    if rev and "normal" in usage:
        out.append(choice("Spin direction", ["normal", "reversed"],
                          "reversed" if rev.lower().startswith("rev") else "normal",
                          lambda o: f"spin {o}"))
    out.append(choice("Light theme (current value not reported)", [str(i) for i in range(7)], None,
                      lambda o: f"theme {o}"))
    return out


def voltex(t, p):
    out = [level(t)]
    units = grab(t, r"Units Per Turn: (\d+)", int)
    if units is not None:
        out.append(slider("Knob units per turn", units, 20, 255, lambda v: f"knob rate {max(v, 20)}"))
    usage = " ".join(p.get("knob", []))
    m = re.search(r"forward\|(reverse\w*)", usage)
    rev_word = m[1] if m else "reversed"
    for side in ("Left", "Right"):
        d = grab(t, rf"{side} Knob: \w+, (\w+)")
        if d and "left|right" in usage:
            out.append(choice(f"{side} knob direction", ["forward", rev_word],
                              rev_word if d.lower().startswith("rev") else "forward",
                              lambda o, s=side.lower(): f"knob {s} {o}"))
    mode = grab(t, r"Mode: (Spoof|Normal)")
    if mode:
        out.append(choice("HID mode (reboot needed)", ["normal", "spoof"], mode.lower(), lambda o: f"hid {o}"))
    mix = grab(t, r"Mix: (AND|OR)")
    if mix:
        out.append(choice("Start button mix", ["or", "and"], mix.lower(), lambda o: f"start {o}"))
    return out


def arcade(t, p):
    return [level(t)]


def chord(t, p):
    out = []
    k, f = grab(t, r"Key Level: (\d+)", int), grab(t, r"Fader Level: (\d+)", int)
    out += [slider("Key brightness", k, 0, 255, lambda v: f"level key {v}"),
            slider("Fader brightness", f, 0, 255, lambda v: f"level fader {v}"),
            check("Report raw fader", bool_text(t, r"Report Fader Raw: (\w+)"), lambda b: f"raw_fader {onoff(b)}")]
    return out


def groove(t, p):
    out = [level(t)]
    out.append(hid_choice(t, r"Joy: (\w+),", r"NKRO: (\w+)\.", "nkro"))
    out.append(check("Haptics", bool_text(t, r"Enabled: (\w+)\."), lambda b: f"haptics {onoff(b)}"))
    out.append(dict(kind="info", text="Gimbal calibration and LED colors: use the Device / CLI tab "
                                      "(gimbal calibrate, color ...)."))
    return out


def ju(t, p):
    out = [level(t)]
    deg = grab(t, r"Rotate: (\d+) degree", int)
    if deg is not None:
        out.append(choice("Rotation (degrees)", ["0", "90", "180", "270"], str(deg),
                          lambda o: f"rotate {int(o) // 90}"))
    out.append(check("Report rotate", bool_text(t, r"Report Rotate: (\w+)"), lambda b: f"report_rotate {onoff(b)}"))
    return out


def geki(t, p):
    out = []
    lv = re.search(r"Level: (\d+) \(int\), (\d+) \(ext\)", t)
    if lv:
        st = [int(lv[1]), int(lv[2])]

        def mk(i):
            def cmd(v):
                st[i] = v
                return f"level {st[0]} {st[1]}"
            return cmd
        out += [slider("Internal LED brightness", st[0], 0, 255, mk(0)),
                slider("External LED brightness", st[1], 0, 255, mk(1))]
    o = re.search(r"RGB Order: (\w+) \(int\), (\w+) \(ext\)", t)
    if o:
        so = [o[1].lower(), o[2].lower()]

        def mko(i):
            def cmd(v):
                so[i] = v
                return f"rgb_order {so[0]} {so[1]}"
            return cmd
        out += [choice("Internal RGB order", ["rgb", "grb"], so[0], mko(0)),
                choice("External RGB order", ["rgb", "grb"], so[1], mko(1))]
    out.append(slider("Volume", grab(t, r"Volume: (\d+)", int), 0, 255, lambda v: f"volume {v}"))
    io4 = bool_text(t, r"IO4: (\w+)\.")
    if io4 is not None:
        out.append(choice("HID", ["io4", "off"], "io4" if io4 else "off", lambda o: f"hid {o}"))
    out += aime(t)
    out.append(dict(kind="info", text="Lever calibration, ToF mixing and external LED mapping: use the Device / CLI tab."))
    return out


def chu(t, p):
    out = [level(t)]
    out.append(hid_choice(t, r"Joy: (\w+), NKRO", r"NKRO: (\w+)\.", "nkro"))
    tof = re.search(r"Offset: (\d+), Pitch: (\d+)", t)
    if tof:
        st = [int(tof[1]), int(tof[2])]

        def mk(i):
            def cmd(v):
                st[i] = v
                return f"tof {st[0]} {st[1]}"
            return cmd
        out += [slider("ToF offset", st[0], 40, 255, lambda v: mk(0)(max(v, 40))),
                slider("ToF pitch", st[1], 4, 50, lambda v: mk(1)(max(v, 4)))]
    en = bool_text(t, r"Enabled: (\w+)")
    if en is not None and "[IR]" in t:
        out.append(check("IR enabled", en, lambda b: f"ir {'enable' if b else 'disable'}"))
    out += filter_and_debounce(t)
    out += aime(t)
    out.append(check("Skip splitter LED", bool_text(t, r"Skip Splitter LED: (\w+)"),
                     lambda b: f"tweak skip_split {onoff(b)}"))
    return out


def mai(t, p):
    out = [level(t)]
    r = re.search(r"Button: (\d+)\s+LED Number for Cabinet Light: (\d+)\s+LED Number for Banner: (\d+)", t)
    if r:
        st = [int(r[1]), int(r[2]), int(r[3])]

        def mk(i):
            def cmd(v):
                st[i] = v
                return f"rgb {st[0]} {st[1]} {st[2]}"
            return cmd
        out += [slider("LEDs per button", st[0], 0, 15, mk(0)),
                slider("LEDs per cabinet light", st[1], 0, 15, mk(1)),
                slider("LEDs for banner", st[2], 0, 15, mk(2))]
    h = re.search(r"IO4: (\w+), NKRO: (\w+)", t)
    if h:
        cur = "io4" if h[1].lower() == "on" else h[2].lower()
        out.append(choice("HID", ["io4", "key1", "key2", "off"], cur, lambda o: f"hid {o}"))
    out += filter_and_debounce(t)
    out += aime(t)
    out.append(dict(kind="info", text="GPIO and touch key mapping: use the Device / CLI tab (gpio, touch)."))
    return out


def diva(t, p):
    out = []
    out += [slider("Slider brightness", grab(t, r"Slider Level: (\d+)", int), 0, 255, lambda v: f"level slider {v}"),
            slider("Button brightness", grab(t, r"Button Level: (\d+)", int), 0, 255, lambda v: f"level button {v}")]
    km = grab(t, r"Keymap: (\w+)")
    out.append(choice("Keymap", ["switch", "steam", "arcade"],
                      km.lower() if km and km.lower() in ("switch", "steam", "arcade") else None,
                      lambda o: f"keymap {o}"))
    out += filter_and_debounce(t)
    return out


def densha(t, p):
    out = [level(t)]
    out.append(slider("LCD backlight", grab(t, r"Backlight: (\d+)", int), 0, 255, lambda v: f"lcd {v}"))
    h, r = grab(t, r"Hold Current: (\d+)", int), grab(t, r"Run Current: (\d+)", int)
    if h is not None and r is not None:
        st = [h, r]

        def mk(i):
            def cmd(v):
                st[i] = v
                return f"mascon {st[0]} {st[1]}"
            return cmd
        out += [slider("Mascon hold current", h, 0, 31, mk(0)), slider("Mascon run current", r, 0, 31, mk(1))]
    return out


PROFILES = {
    "popn_pico": popn, "dance_pico": dance, "rock_pico": rock, "nos_pico": nos, "bishi_pico": bishi,
    "voltex_pico": voltex, "arcade_pico": arcade, "chord_pico": chord, "groove_pico": groove, "ju_pico": ju,
    "geki_pico": geki, "chu_pico": chu, "mai_pico": mai, "diva_pico": diva, "densha_pico": densha,
}


def build(prof, display_text, probes):
    return [s for s in PROFILES[prof](display_text, probes) if s]
