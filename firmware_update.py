"""Flash a UF2 firmware file onto a Raspberry Pi Pico (RP2040 / RP2350) controller.

The steps are plain functions so they can be tested without hardware:
  check_uf2()        validate a .uf2 file and find out which chip and which controller it is for
  find_boot_drive()  find a Pico in update (BOOTSEL) mode: a drive labelled RPI-RP2 (RP2350: RP2350)
  flash()            reboot the controller into update mode if needed, copy the file, wait for the restart
  write_backup()     save a settings text backup before flashing
"""
import ctypes
import datetime
import os
import re
import shutil
import struct
import time
from dataclasses import dataclass, field

UF2_MAGIC_START0, UF2_MAGIC_START1, UF2_MAGIC_END = 0x0A324655, 0x9E5D5157, 0x0AB16F30
FLAG_FAMILY_ID = 0x00002000
RP2040_FAMILIES = {0xE48BFF56}
RP2350_FAMILIES = {0xE48BFF59, 0xE48BFF5A, 0xE48BFF5B}   # ARM secure, RISC-V, ARM non-secure
BOOT_LABELS = {"RPI-RP2": "RP2040", "RP2350": "RP2350"}
MAX_UF2_BYTES = 32 * 1024 * 1024
PROMPT_RE = re.compile(rb"\b([a-z0-9]+_pico)>")


@dataclass
class Uf2Info:
    ok: bool
    error: str = ""
    size: int = 0
    blocks: int = 0
    chip: str = ""                       # "RP2040" or "RP2350"
    prompts: list = field(default_factory=list)   # controllers this firmware is for, e.g. ["musec_pico"]


def check_uf2(path):
    """Validate a UF2 file. Never raises; returns Uf2Info(ok=False, error=...) for anything unusable."""
    try:
        size = os.path.getsize(path)
        if not path.lower().endswith(".uf2"):
            return Uf2Info(False, "The file is not a .uf2 firmware file.")
        if size < 512 or size % 512:
            return Uf2Info(False, "Not a valid UF2 file (its size is not a multiple of 512 bytes).", size)
        if size > MAX_UF2_BYTES:
            return Uf2Info(False, "The file is too large to be controller firmware.", size)
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return Uf2Info(False, f"Cannot read the file: {e}")

    families, payload, total = set(), bytearray(), None
    for off in range(0, size, 512):
        m0, m1, flags, _addr, nbytes, _bno, nblocks, fam = struct.unpack_from("<8I", data, off)
        (mend,) = struct.unpack_from("<I", data, off + 508)
        if (m0, m1, mend) != (UF2_MAGIC_START0, UF2_MAGIC_START1, UF2_MAGIC_END):
            return Uf2Info(False, f"Not a valid UF2 file (bad block at offset {off}).", size)
        if nbytes > 476:
            return Uf2Info(False, "Not a valid UF2 file (a block is too large).", size)
        if total is None:
            total = nblocks
        elif nblocks != total:
            return Uf2Info(False, "Not a valid UF2 file (inconsistent block count).", size)
        if flags & FLAG_FAMILY_ID:
            families.add(fam)
        payload += data[off + 32: off + 32 + nbytes]
    if total != size // 512:
        return Uf2Info(False, "The UF2 file is incomplete (blocks are missing).", size, size // 512)
    if families & RP2040_FAMILIES and not families & RP2350_FAMILIES:
        chip = "RP2040"
    elif families & RP2350_FAMILIES and not families & RP2040_FAMILIES:
        chip = "RP2350"
    else:
        return Uf2Info(False, "This UF2 is not for an RP2040 or RP2350 Pico.", size, total)
    prompts = sorted({m.decode() for m in PROMPT_RE.findall(bytes(payload))})
    return Uf2Info(True, "", size, total, chip, prompts)


def find_boot_drive():
    """(drive_root, chip) of a Pico in update mode, or None. Windows only."""
    kernel32 = ctypes.windll.kernel32
    bits = kernel32.GetLogicalDrives()
    for i in range(26):
        if not bits & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        label = ctypes.create_unicode_buffer(261)
        if kernel32.GetVolumeInformationW(root, label, 261, None, None, None, None, 0) and \
                label.value in BOOT_LABELS:
            return root, BOOT_LABELS[label.value]
    return None


def _wait(predicate, timeout, sleep, step=0.25):
    end = time.time() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.time() >= end:
            return None
        sleep(step)


def flash(path, send_update, log, find_drive=None, sleep=time.sleep,
          drive_timeout=20.0, restart_timeout=20.0):
    """Copy `path` to a Pico in update mode. Returns (success, message).

    send_update: callable that tells a connected controller to reboot into update mode (None if there is
                 none; then a controller already in update mode must be present).
    log:         callable(str) for progress messages.
    """
    find_drive = find_drive or find_boot_drive
    drive = find_drive()
    if drive is None:
        if send_update is None:
            return False, "No controller in update mode was found."
        log("Rebooting the controller into update mode...")
        try:
            send_update()
        except Exception as e:  # serial errors etc.
            return False, f"Could not send the update command: {e}"
        log("Waiting for the update drive (RPI-RP2) to appear...")
        drive = _wait(find_drive, drive_timeout, sleep)
        if drive is None:
            return False, ("The update drive did not appear. Unplug the controller, hold BOOTSEL while "
                           "plugging it in, then try again.")
    root, _chip = drive
    log(f"Copying the firmware to {root} ...")
    copy_error = None
    try:
        shutil.copyfile(path, os.path.join(root, os.path.basename(path)))
    except OSError as e:
        copy_error = e     # the drive can vanish as the last block is written, so judge by what happens next
    log("Waiting for the controller to restart...")
    if _wait(lambda: find_drive() is None, restart_timeout, sleep):
        return True, "Firmware written. The controller restarted."
    if copy_error:
        return False, f"Copying failed: {copy_error}"
    return False, "The update drive is still there, so the controller did not restart. Unplug and replug it."


# ------------------------------------------------------------- backups ---
def backup_dir():
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    base = docs if os.path.isdir(docs) else os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PicoCompanion", "Backups")


def write_backup(prompt_name, serial_number, text, directory=None):
    """Save a text backup of the device's settings; returns the file path."""
    directory = directory or backup_dir()
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", f"{prompt_name}_{serial_number or 'unknown'}")
    path = os.path.join(directory, f"{safe}_{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
