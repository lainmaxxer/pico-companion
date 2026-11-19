import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import profiles as P
SIM = {
"popn_pico": "[Light]\n  Level: 128.",
"dance_pico": "[Light]\n  Level: 100\n[HID]\n  Rotate: 90 degree",
"rock_pico": "[Light]\n  Level: 60.\n[Pedal]\n  Input: Ring.\n  Invert: Yes.\n[HID]\n  Joy: On.\n  Keyboard: Off.\n  Keycode:",
"nos_pico": "[Light]\n  Brightness: Key - 90, Logo - 40.\n  Key Light Mode: Pressure\n[HID]\n  Button - On, Analog - Off, MIDI - On.",
"bishi_pico": "[Light]\n  Level: 128.\n[Spin]\n  Units Per Turn: 80.\n  Spinner: OK, Reversed.",
"voltex_pico": "[Light]\n  Level: 128.\n[Knob]\n  Units Per Turn: 90.\n  Left Knob: OK, Forward.\n  Right Knob: OK, Reversed.\n[Hall Effect Button]\n  Key 1: 3000->1000, On:  8, Off: 18.\n[HID]\n  Mode: Spoof.\n[Start]\n  Mix: AND.",
"arcade_pico": "[Light]\n  Level: 128.\n[Hall Effect Button]\n  Key  1: 3000->1000, On:  8, Off: 18.",
"chord_pico": "[Light]\n  Key Level: 100.\n  Fader Level: 50.\n[HID]\n  Report Fader Raw: On.",
"groove_pico": "[HID]\n  Joy: on, NKRO: off.\n[Light]\n  Level: 128.\n[Haptics]\n  Enabled: on.",
"ju_pico": "[Light]\n  Level: 128\n[HID]\n  Rotate: 270 degree\n  Report Rotate: off",
"geki_pico": "[Light]\n  Level: 120 (int), 60 (ext).\n  RGB Order: grb (int), rgb (ext).\n[Sound]\n  Volume: 40\n[HID]\n  IO4: ON.\n[AIME]\n   NFC Module: PN532\n  Virtual AIC: ON\n         Mode: 1",
"chu_pico": "[Style]\n  Key: 1, Gap: 2, ToF: 0, Level: 128\n[ToF]\n  Offset: 60, Pitch: 20\n[IR]\n  Enabled: ON\n[Sense]\n  Filter: 1, 2, 3\n  Sensitivity (global: +2):\n  Debounce (touch, release): 1, 2\n[HID]\n  Joy: on, NKRO: on.\n[AIME]\n   NFC Module: PN532\n  Virtual AIC: OFF\n         Mode: 0\n[Tweak]\n  Skip Splitter LED: ON",
"mai_pico": "[RGB]\n  LED Number for Button: 3\n  LED Number for Cabinet Light: 4\n  LED Number for Banner: 5\n  Level: 128\n[Sense]\n  Filter: 1, 2, 3\n  Sensitivity (global: -1):\n  Debounce (touch, release): 0, 1\n[HID]\n  IO4: off, NKRO: key2\n[AIME]\n  NFC Module: PN532\n  Virtual AIC: ON\n  Protocol Mode: 0",
"diva_pico": "[Light]\n  Slider Level: 100\n  Button Level: 90\n[Slider]\n  Filter: 1, 1, 2\n  Sensitivity (global: +0):\n  Debounce (touch, release): 1, 1\n[HID]\n  Keymap: switch",
"densha_pico": "[Light]\n  Level: 128.\n[LCD]\n  Backlight: 200.\n[Mascon]\n  Hold Current: 5\n  Run Current: 20",
}
PROBE = {"bishi_pico": {"spin": ["Usage: spin rate <units_per_turn>", "spin <normal|reverse>"]},
         "voltex_pico": {"knob": ["Usage: knob rate <units_per_turn>", "knob <left|right> <forward|reverse>"]}}
for name, text in SIM.items():
    specs = P.build(name, text, PROBE.get(name, {}))
    print(f"== {name}: {len(specs)} controls")
    for s in specs:
        if s["kind"] == "slider":
            print("   slider", s["label"], s["val"], "->", s["cmd"](min(max(s["val"] + 1, s["lo"]), s["hi"])))
        elif s["kind"] == "check":
            print("   check ", s["label"], s["val"], "->", s["cmd"](not s["val"]))
        elif s["kind"] == "choice":
            print("   choice", s["label"], repr(s["cur"]), "->", s["cmd"](s["options"][-1]))
        elif s["kind"] == "buttons":
            print("   buttons", s["label"], [b[1] for b in s["buttons"]])
        else:
            print("   info")
