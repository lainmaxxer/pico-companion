# IIDX Pico firmware patch

`commands_cfg.patch` adds configuration commands to the [IIDX Pico](https://github.com/whowechina/iidx_pico)
firmware so a PC app can read and change all settings (stock firmware only exposes the Hall-key trigger distances over
the CLI):

| Command | Purpose |
|---|---|
| `cfg` | Machine-readable dump of the whole config (`CFG-BEGIN` ... `CFG-END`) |
| `set <name> <value>` | `konami rgb_main rgb_tt rgb_fx tt_start tt_num tt_rev ppr sensor_rev binary` |
| `pset <profile 0-3> <name> <value>` | `lvl_keys lvl_tt style param lmode` |
| `color <profile> <on\|off> <key 0-10\|all> <h> <s> <v>` | Key on/off colors (HSV) |
| `profile <0-3>` | Select the active profile |

The patch only touches `firmware/src/commands.c`.

## Which upstream version

It applies cleanly to upstream `main` (`de55cd3`) and to the last release commit `314a8b9`.
**Newer upstream source only builds for a Raspberry Pi Pico W** (it assumes the wireless chip). If your board is a plain
Pico, build from `314a8b9` plus this patch.

## Build and flash (summary)

1. Check out upstream (`git checkout 314a8b9` for a plain Pico) and apply the patch: `git apply commands_cfg.patch`.
2. Build with pico-sdk 2.2.0 and the Arm GNU toolchain (see the upstream README), `PICO_BOARD=pico_w`.
3. Put the controller into update mode (the app's **Firmware update mode** button, or hold BOOTSEL while plugging in),
   then copy the `.uf2` to the `RPI-RP2` drive.

Back up your settings first (the console tab's `display` output) and keep the original firmware around so you can
return to it. Flashing is at your own risk.

## License

The firmware is licensed under the GNU GPL v3 (see [`LICENSE`](LICENSE), copied from upstream's `firmware/LICENSE`).
This patch is a modification of that code and is distributed under the same license. Only the patch is provided here,
not a compiled firmware image.
