# pico-companion

A small desktop companion app for [whowechina](https://github.com/whowechina)'s "pico" arcade-style controllers.
Change a controller's saved settings from your PC instead of using the buttons on the device.

It talks to the controller's built-in command-line interface over its USB serial port (the same thing the
projects' web configurators and `?` / `display` / `save` commands use), so no drivers and no extra installs are needed.
Windows only, no Python required when you use the release `.exe`.

<p align="center"><i>Light and dark mode, remembered between starts.</i></p>

## Supported devices

The app identifies each controller by the prompt its CLI prints (for example `musec_pico>`) and builds the screen
from what the device itself reports, so older firmware simply shows fewer options.

| Device | Status |
|---|---|
| IIDX Pico (`iidx_pico`) | Tested on hardware. Full settings need the small firmware patch in [`firmware/`](firmware/); on stock firmware you get the Hall-key trigger distances, calibration, save, and the console. |
| Musec Pico (`musec_pico`) | Tested on hardware (stock firmware, older and newer builds). |
| AIC Pico / AIC Touch (`aic_pico`) | Tested on hardware (two units, older and newer firmware). |
| popn, dance, rock, nos, bishi, voltex, arcade, chord, groove, ju, geki, chu, mai, diva, densha | **Written from the projects' firmware source and not tested on real devices.** Screens are marked as such in the app. Please open an issue if one looks wrong. |
| any other `*_pico` | Generic screen: LED brightness (if reported) and a console. |

## Download and use

1. Download `PicoCompanion.exe` from the [latest release](../../releases/latest) and run it.
2. Plug in your controller. It is detected automatically and the app rescans when you plug or unplug something.
3. Change settings. Changes apply immediately and the device writes them to flash after a few seconds
   (or press **Save to flash**).

Notes:
- Only one program can use a serial port at a time. Close the web configurator or any serial terminal that is connected
  to the same controller.
- **Firmware update mode** and **Factory reset** (Device / CLI tab) always ask for confirmation.
- Windows SmartScreen may warn about an unsigned app the first time you run the exe.

## Run from source

Python 3.12+ on Windows, standard library only:

```powershell
python pico_companion.py
```

## Build the exe

```powershell
pip install pyinstaller
./build.ps1
```

The result is `dist/PicoCompanion.exe`.

## Files

| File | Purpose |
|---|---|
| `pico_companion.py` | The app (window, device scan, per-device screens for IIDX, Musec, AIC) |
| `profiles.py` | Table-driven settings for the other devices, written from their firmware |
| `iidx_companion.py` | Serial layer and the IIDX screens |
| `theme.py`, `shapes.py` | Look and feel (light/dark, anti-aliased rounded shapes without Pillow) |
| `tests/test_profiles.py` | Runs every profile against sample `display` output |
| `firmware/` | Patch that adds configuration commands to the IIDX Pico firmware |

## License

The app in this repository is released under the [MIT License](LICENSE).

`firmware/commands_cfg.patch` modifies whowechina's IIDX Pico firmware, which is GPL-3.0, so that patch is under the
[GPL-3.0](firmware/LICENSE) (see [`firmware/README.md`](firmware/README.md)). Third-party components of the release
exe are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

This is an unofficial community tool, not affiliated with or endorsed by whowechina. The upstream hardware and
documentation are CC BY-NC; please respect their terms and support the original author.
