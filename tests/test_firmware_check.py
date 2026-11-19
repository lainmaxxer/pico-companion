"""Tests for firmware_check.py with fake GitHub answers (no network).

Run:  python tests/test_firmware_check.py
"""
import datetime
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import firmware_check as fc  # noqa: E402
from test_firmware_update import make_uf2  # noqa: E402

OLD, SAME, NEW = "Apr 18 2026 09:53:48", "Oct  5 2026 12:55:09", "Nov 17 2026 21:25:40"


def tree(*paths):
    return {"tree": [{"path": p, "type": "blob"} for p in paths] + [{"path": "Production", "type": "tree"}]}


def fake_fetchers(files, paths, commit=("Fix calibration issue", "2026-11-17")):
    """files: {repo path -> bytes}. Returns (fetch_json, fetch_bytes) that behave like GitHub."""
    calls = []

    def fetch_json(url):
        calls.append("tree" if "/git/trees/" in url else "commits")
        if "/git/trees/" in url:
            return tree(*paths)
        if "/commits?" in url:
            return [{"commit": {"message": commit[0] + "\n\nbody", "committer": {"date": commit[1] + "T10:00:00Z"}}}]
        raise AssertionError(url)

    def fetch_bytes(url):
        for path, data in files.items():
            if url.endswith(path.replace(" ", "%20")):
                return data
        raise fc.NotFound("Not found on GitHub.")
    fetch_json.calls = calls
    return fetch_json, fetch_bytes


def uf2_bytes(directory, text):
    p = os.path.join(directory, "tmp.uf2")
    make_uf2(p, text.encode())
    with open(p, "rb") as f:
        return f.read()


class Parse(unittest.TestCase):
    def test_build_time(self):
        self.assertEqual(fc.parse_build_time("Oct  5 2026 12:55:09"), datetime.datetime(2026, 10, 5, 12, 55, 9))
        self.assertEqual(fc.parse_build_time("built May 17 2025 22:27:54."), datetime.datetime(2025, 5, 17, 22, 27, 54))
        self.assertIsNone(fc.parse_build_time("no date here"))
        self.assertIsNone(fc.parse_build_time(""))
        self.assertIsNone(fc.parse_build_time(None))

    def test_uf2_build_time_uses_newest(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.uf2")
            make_uf2(p, b"Apr 18 2026 09:53:48 ... Oct  5 2026 12:55:09 aic_pico>")
            self.assertEqual(fc.uf2_build_time(p), datetime.datetime(2026, 10, 5, 12, 55, 9))
            q = os.path.join(d, "b.uf2")
            make_uf2(q, b"no timestamp")
            self.assertIsNone(fc.uf2_build_time(q))


class Find(unittest.TestCase):
    def find(self, paths, chip="RP2040", repo="aic_pico"):
        return fc.find_firmware(repo, chip, lambda url: tree(*paths))

    def test_picks_production_file_and_skips_tests(self):
        self.assertEqual(self.find(["Production/Firmware/chu_pico.uf2", "Production/Firmware/chu_pico_led_test.uf2"],
                                   repo="chu_pico"), "Production/Firmware/chu_pico.uf2")

    def test_chip_variants(self):
        paths = ["Production/Firmware/aic_pico.uf2", "Production/Firmware/aic_pico_rp2350.uf2"]
        self.assertEqual(self.find(paths), "Production/Firmware/aic_pico.uf2")
        self.assertEqual(self.find(paths, "RP2350"), "Production/Firmware/aic_pico_rp2350.uf2")

    def test_lowercase_folder_and_odd_name(self):
        self.assertEqual(self.find(["Production/firmware/mai_pico.uf2"], repo="mai_pico"),
                         "Production/firmware/mai_pico.uf2")
        self.assertEqual(self.find(["Production/Firmware/popn_pico2.uf2"], repo="popn_pico"),
                         "Production/Firmware/popn_pico2.uf2")

    def test_prefers_production_over_other_folders(self):
        self.assertEqual(self.find(["build/aic_pico.uf2", "Production/Firmware/aic_pico.uf2"]),
                         "Production/Firmware/aic_pico.uf2")

    def test_none_published(self):
        self.assertIsNone(self.find(["README.md", "firmware/src/main.c"]))
        self.assertIsNone(self.find(["Production/Firmware/aic_pico.uf2"], "RP2350"))


class Check(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.dir.name, "dl")

    def tearDown(self):
        self.dir.cleanup()

    def run_check(self, repo_build, device_build, prompt_in_file="musec_pico", paths=None, **kw):
        data = uf2_bytes(self.dir.name, f"{prompt_in_file}> {repo_build}")
        path = "Production/Firmware/musec_pico.uf2"
        fj, fb = fake_fetchers({path: data}, paths or [path])
        self.calls = fj.calls
        return fc.check_for_update("musec_pico", device_build, "RP2040", fj, fb, self.dest, **kw)

    def test_newer(self):
        r = self.run_check(NEW, OLD)
        self.assertEqual(r.status, "newer")
        self.assertTrue(os.path.exists(r.file))
        self.assertEqual((r.name, r.commit_message, r.commit_date), ("musec_pico.uf2", "Fix calibration issue",
                                                                       "2026-11-17"))

    def test_current_needs_no_api_call(self):
        self.assertEqual(self.run_check(SAME, SAME).status, "current")
        self.assertEqual(self.calls, [])          # found at the usual path, nothing to look up

    def test_newer_fetches_commit_message_only(self):
        self.run_check(NEW, OLD)
        self.assertEqual(self.calls, ["commits"])

    def test_unusual_file_name_falls_back_to_repository_listing(self):
        path = "Production/Firmware/popn_pico2.uf2"
        data = uf2_bytes(self.dir.name, f"popn_pico> {NEW}")
        fj, fb = fake_fetchers({path: data}, [path])
        r = fc.check_for_update("popn_pico", OLD, "RP2040", fj, fb, self.dest)
        self.assertEqual(r.status, "newer")
        self.assertEqual(fj.calls, ["tree", "commits"])

    def test_device_newer_or_custom(self):
        self.assertEqual(self.run_check(OLD, NEW).status, "older")

    def test_unknown_device_build(self):
        self.assertEqual(self.run_check(NEW, "").status, "unknown")

    def test_nothing_published(self):
        fj, fb = fake_fetchers({}, ["README.md", "firmware/src/main.c"])    # no .uf2 anywhere in the repository
        r = fc.check_for_update("arcade_pico", OLD, "RP2040", fj, fb, self.dest)
        self.assertEqual(r.status, "no_firmware")
        self.assertEqual(fj.calls, ["tree"])

    def test_published_file_is_for_another_controller(self):
        self.assertEqual(self.run_check(NEW, OLD, prompt_in_file="aic_pico").status, "error")

    def test_network_error(self):
        def boom(url):
            raise fc.CheckError("Cannot reach GitHub (offline).")
        r = fc.check_for_update("musec_pico", OLD, "RP2040", boom, boom, self.dest)
        self.assertEqual(r.status, "error")
        self.assertIn("offline", r.message)

    def test_garbage_download(self):
        path = "Production/Firmware/musec_pico.uf2"
        fj, fb = fake_fetchers({path: b"<html>rate limited</html>"}, [path])
        r = fc.check_for_update("musec_pico", OLD, "RP2040", fj, fb, self.dest)
        self.assertEqual(r.status, "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
