"""Tests for firmware_update.py. No hardware needed: the update drive is simulated with a temp folder.

Run:  python tests/test_firmware_update.py
"""
import os
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import firmware_update as fw  # noqa: E402

RP2040 = 0xE48BFF56
RP2350_ARM_S = 0xE48BFF59


def make_uf2(path, payload=b"", family=RP2040, blocks=4, corrupt=None):
    data = bytearray()
    for i in range(blocks):
        chunk = (payload if i == 0 else b"").ljust(256, b"\0")
        block = struct.pack("<8I", fw.UF2_MAGIC_START0, fw.UF2_MAGIC_START1, fw.FLAG_FAMILY_ID,
                            0x10000000 + 256 * i, 256, i, blocks, family)
        block += chunk.ljust(476, b"\0") + struct.pack("<I", fw.UF2_MAGIC_END)
        data += block
    if corrupt == "magic":
        data[0] ^= 0xFF
    if corrupt == "truncate":
        data = data[:-512]
    if corrupt == "trailing":
        data += b"\0" * 100
    with open(path, "wb") as f:
        f.write(data)


class CheckUf2(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.p = os.path.join(self.dir.name, "fw.uf2")

    def tearDown(self):
        self.dir.cleanup()

    def test_valid_rp2040_with_prompt(self):
        make_uf2(self.p, b"xx musec_pico> yy")
        info = fw.check_uf2(self.p)
        self.assertTrue(info.ok, info.error)
        self.assertEqual((info.chip, info.blocks, info.prompts), ("RP2040", 4, ["musec_pico"]))

    def test_rp2350_family(self):
        make_uf2(self.p, family=RP2350_ARM_S)
        self.assertEqual(fw.check_uf2(self.p).chip, "RP2350")

    def test_no_prompt_found(self):
        make_uf2(self.p, b"nothing here")
        info = fw.check_uf2(self.p)
        self.assertTrue(info.ok)
        self.assertEqual(info.prompts, [])

    def test_two_prompts(self):
        make_uf2(self.p, b"aic_pico> and iidx_pico>")
        self.assertEqual(fw.check_uf2(self.p).prompts, ["aic_pico", "iidx_pico"])

    def test_bad_magic(self):
        make_uf2(self.p, corrupt="magic")
        self.assertFalse(fw.check_uf2(self.p).ok)

    def test_truncated(self):
        make_uf2(self.p, corrupt="truncate")
        self.assertFalse(fw.check_uf2(self.p).ok)

    def test_size_not_multiple_of_512(self):
        make_uf2(self.p, corrupt="trailing")
        self.assertFalse(fw.check_uf2(self.p).ok)

    def test_unknown_family(self):
        make_uf2(self.p, family=0x12345678)
        self.assertFalse(fw.check_uf2(self.p).ok)

    def test_not_uf2_extension(self):
        other = os.path.join(self.dir.name, "fw.bin")
        make_uf2(other)
        self.assertFalse(fw.check_uf2(other).ok)

    def test_missing_file(self):
        self.assertFalse(fw.check_uf2(os.path.join(self.dir.name, "nope.uf2")).ok)


class Flash(unittest.TestCase):
    """The update drive is a temp folder that 'appears' after the update command and 'vanishes' once the
    firmware has been copied, like a Pico rebooting after a UF2 is written."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.fw = os.path.join(self.dir.name, "fw.uf2")
        make_uf2(self.fw, b"musec_pico>")
        self.drive = os.path.join(self.dir.name, "RPI-RP2")
        self.present = False
        self.log = []

    def tearDown(self):
        self.dir.cleanup()

    def find(self):
        return (self.drive + os.sep, "RP2040") if self.present else None

    def appear(self):
        os.makedirs(self.drive, exist_ok=True)
        self.present = True

    def vanish_when_copied(self):
        def watch():
            dest = os.path.join(self.drive, "fw.uf2")
            for _ in range(200):
                if os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(self.fw):
                    time.sleep(0.05)
                    self.present = False
                    return
                time.sleep(0.02)
        threading.Thread(target=watch, daemon=True).start()

    def run_flash(self, send_update, **kw):
        return fw.flash(self.fw, send_update, self.log.append, find_drive=self.find, sleep=time.sleep,
                        drive_timeout=3, restart_timeout=3, **kw)

    def test_full_sequence_from_connected_device(self):
        sent = []

        def send_update():
            sent.append(True)
            threading.Timer(0.3, self.appear).start()
        self.vanish_when_copied()
        ok, msg = self.run_flash(send_update)
        self.assertTrue(ok, msg)
        self.assertEqual(sent, [True])
        self.assertTrue(any("Copying" in m for m in self.log))

    def test_device_already_in_update_mode(self):
        self.appear()
        self.vanish_when_copied()
        ok, msg = self.run_flash(None)
        self.assertTrue(ok, msg)

    def test_nothing_to_flash(self):
        ok, msg = self.run_flash(None)
        self.assertFalse(ok)
        self.assertIn("No controller", msg)

    def test_drive_never_appears(self):
        ok, msg = self.run_flash(lambda: None)
        self.assertFalse(ok)
        self.assertIn("did not appear", msg)

    def test_update_command_fails(self):
        def boom():
            raise OSError("port closed")
        ok, msg = self.run_flash(boom)
        self.assertFalse(ok)
        self.assertIn("port closed", msg)

    def test_drive_stays_means_failure(self):
        self.appear()
        ok, msg = self.run_flash(None)
        self.assertFalse(ok)
        self.assertIn("did not restart", msg)


class Backup(unittest.TestCase):
    def test_backup_written_with_safe_name(self):
        with tempfile.TemporaryDirectory() as d:
            path = fw.write_backup("musec_pico", "ab/cd:12", "[Light]\nLevel: 128.", directory=d)
            self.assertTrue(os.path.basename(path).startswith("musec_pico_abcd12_"))
            self.assertEqual(open(path, encoding="utf-8").read(), "[Light]\nLevel: 128.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
