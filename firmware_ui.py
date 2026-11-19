"""Firmware update screen and the drop / browse / flash workflow, as a mixin for the main window.

The host class (PicoApp) provides: `nb`, `dev`, `dev_port`, `prof`, `status`, `help`, `disp_text`, `cfg_raw`,
`run_bg()`, `rescan()`, `devices`, `port_box` and `connect()`.
"""
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import filedrop
import firmware_check
import firmware_update as fw
import theme

MAX_RECONNECT_TRIES = 12


class FirmwareUpdates:
    def init_firmware_updates(self):
        self._fw_log = []
        self._fw_text = None
        self._fw_busy = False
        self._fw_checking = False
        self._fw_target = None          # (prompt name, port) of the controller being flashed, to reconnect to it
        self._fw_tries = 0
        self._fw_expect_build = False
        # The native window only exists once Tk has shown it, so hook the drop a moment after start-up.
        self.after(300, self._hook_file_drop)

    def _hook_file_drop(self):
        try:
            filedrop.enable_file_drop(self, self.on_files_dropped)
        except Exception as e:          # dropping is a convenience; Browse still works
            self.fw_log(f"Dropping files is unavailable ({e}). Use Browse on the Firmware tab instead.")

    # ------------------------------------------------------------ screen ---
    def tab_firmware(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="Firmware")
        ttk.Label(f, text="Update the firmware", font=theme.FONT_B).pack(anchor="w")
        ttk.Label(f, style="Hint.TLabel", wraplength=760, justify="left",
                  text="Drop a .uf2 firmware file anywhere in this window, or browse for one. The controller "
                       "restarts into update mode, the file is copied, and the app reconnects. Your settings are "
                       "saved to a text file first.").pack(anchor="w", pady=(2, 10))

        w, h = 640, 96
        zone = tk.Canvas(f, width=w, height=h, bg=theme.CARD, highlightthickness=0, bd=0, cursor="hand2")
        zone.pack(anchor="w")
        theme.round_rect(zone, 0, 0, w, h, 14, fill=theme.LINE)
        theme.round_rect(zone, 2, 2, w - 2, h - 2, 12, fill=theme.TAB_BG)
        zone.create_text(w / 2, h / 2 - 12, text="Drop a .uf2 firmware file here", fill=theme.TEXT,
                         font=theme.FONT_B)
        zone.create_text(w / 2, h / 2 + 12, text="or click to browse", fill=theme.MUTED, font=("Segoe UI", 9))
        zone.bind("<Button-1>", lambda e: self.browse_firmware())

        row = ttk.Frame(f)
        row.pack(anchor="w", pady=10)
        theme.Button(row, text="Browse...", command=self.browse_firmware, kind="primary").pack(side="left")
        theme.Button(row, text="Check for updates", command=self.check_firmware_updates,
                     kind="primary").pack(side="left", padx=8)
        theme.Button(row, text="Open backups folder", command=self.open_backups).pack(side="left")

        text = tk.Text(f, height=8, font=theme.MONO, bg=theme.CONSOLE_BG, fg=theme.CONSOLE_FG, relief="flat",
                       padx=10, pady=8)
        text.pack(fill="both", expand=True)
        for line in self._fw_log:
            text.insert("end", line + "\n")
        text.see("end")
        self._fw_text = text

    def fw_log(self, msg):
        self._fw_log.append(msg)
        try:
            if self._fw_text is not None and self._fw_text.winfo_exists():
                self._fw_text.insert("end", msg + "\n")
                self._fw_text.see("end")
        except tk.TclError:
            pass
        self.status.set(msg)

    def _post(self, fn):
        """Run fn on the Tk thread (worker threads must not touch Tk)."""
        self.run_bg(lambda: None, lambda _r: fn())

    def open_backups(self):
        folder = fw.backup_dir()
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)

    def browse_firmware(self):
        path = filedialog.askopenfilename(title="Choose a firmware file",
                                          filetypes=[("UF2 firmware", "*.uf2"), ("All files", "*.*")])
        if path:
            self.flash_firmware(os.path.normpath(path))

    def on_files_dropped(self, paths):
        uf2 = [p for p in paths if p.lower().endswith(".uf2")]
        if not uf2:
            messagebox.showerror("Cannot use this file", "Drop a .uf2 firmware file.")
            return
        for t in self.nb.tabs():            # show the Firmware tab so the progress is visible
            if self.nb.tab(t, "text") == "Firmware":
                self.nb.select(t)
        if len(uf2) > 1:
            self.fw_log(f"{len(uf2)} files dropped; using the first one.")
        self.flash_firmware(uf2[0])

    # ------------------------------------------------- check for updates ---
    def check_firmware_updates(self):
        """Compare the connected controller's firmware with the one in its original project repository."""
        if self._fw_busy or self._fw_checking:
            return
        if self.dev is None:
            messagebox.showinfo("No controller", "Connect a controller first.")
            return
        built = re.search(r"Built: (.+)", "\n".join(self.help))
        chip = re.search(r"Processor: (RP\d+)", self.disp_text)
        prof, built_text = self.prof, built.group(1) if built else ""
        chip_name = chip.group(1) if chip else "RP2040"
        self._fw_checking = True
        self.fw_log(f"Checking github.com/whowechina/{prof} for newer firmware ...")
        def work():
            try:
                return firmware_check.check_for_update(prof, built_text, chip_name)
            except Exception as e:      # never leave the button stuck on an unexpected error
                return firmware_check.UpdateResult("error", f"Unexpected error: {e}")
        self.run_bg(work, lambda r: self._update_check_done(prof, r))

    def _update_check_done(self, prof, r):
        self._fw_checking = False
        if r is None:
            return

        def fmt(t):
            return t.strftime("%b %d %Y %H:%M") if t else "unknown"

        if r.status == "error":
            self.fw_log(f"Update check failed: {r.message}")
            messagebox.showerror("Update check failed", r.message)
        elif r.status == "no_firmware":
            self.fw_log(r.message)
            messagebox.showinfo("No published firmware", r.message)
        elif r.status == "current":
            self.fw_log(f"{prof} is up to date (built {fmt(r.device_build)}).")
            messagebox.showinfo("Up to date", f"{prof} already has the published firmware "
                                              f"(built {fmt(r.device_build)}).")
        elif r.status == "older":
            self.fw_log(f"{prof} has a newer or custom build ({fmt(r.device_build)}); published: "
                        f"{fmt(r.repo_build)}.")
            messagebox.showinfo("Nothing newer", f"Your controller is running a build from {fmt(r.device_build)}, "
                                                 f"which is newer than the published one ({fmt(r.repo_build)}). "
                                                 "It may be a custom build.")
        else:   # newer, or unknown (cannot compare): let the user decide
            newer = r.status == "newer"
            self.fw_log(f"{'Newer firmware' if newer else 'Firmware'} published for {prof}: {r.name} "
                        f"(built {fmt(r.repo_build)}); yours is built {fmt(r.device_build)}.")
            notes = []
            if prof == "iidx_pico":
                if getattr(self, "full", False):
                    notes.append("Your IIDX runs a patched build with the extra configuration commands this app "
                                 "uses. The published firmware does not have them, so afterwards the app will "
                                 "only offer limited settings.")
                notes.append("Newer IIDX firmware may need a Raspberry Pi Pico W. If your board is a plain Pico, "
                             "check the project page first.")
            head = ("Newer firmware is available" if newer else
                    "Published firmware found (cannot tell whether it is newer)")
            text = f"{head} for {prof}.\n\nPublished: {r.name}, built {fmt(r.repo_build)}\n"
            text += f"Yours: built {fmt(r.device_build)}\n"
            if r.commit_message:
                text += f"Latest change ({r.commit_date}): {r.commit_message}\n"
            if notes:
                text += "\n" + "\n\n".join(notes) + "\n"
            text += "\nUpdate now? You will be asked to confirm again before anything is written."
            if messagebox.askyesno("Firmware update available", text, icon="warning" if notes else "question"):
                self.flash_firmware(r.file)

    # ------------------------------------------------------------- flash ---
    def _settings_backup_text(self):
        parts = list(self.help[:6]) + [""]
        parts += self.disp_text.splitlines()
        if getattr(self, "cfg_raw", None):
            parts += [""] + list(self.cfg_raw)
        return "\n".join(parts) + "\n"

    def flash_firmware(self, path):
        if self._fw_busy:
            messagebox.showinfo("Please wait", "A firmware update is already running.")
            return
        info = fw.check_uf2(path)
        if not info.ok:
            messagebox.showerror("Cannot use this file", info.error)
            return
        drive = fw.find_boot_drive()
        dev = self.dev
        via_cli = dev is not None and drive is None      # connected controller we must reboot into update mode
        if dev is None and drive is None:
            messagebox.showinfo("No controller", "Connect a controller (or put one in update mode with "
                                                 "BOOTSEL) first, then drop the file again.")
            return
        if drive and drive[1] != info.chip:
            messagebox.showerror("Wrong chip", f"The controller in update mode is an {drive[1]}, but this "
                                               f"firmware is for an {info.chip}.")
            return
        if via_cli:
            if info.prompts and self.prof not in info.prompts:
                if not messagebox.askyesno(
                        "This looks like the wrong firmware",
                        f"This file looks like firmware for {', '.join(info.prompts)}, but the connected "
                        f"controller is {self.prof}.\n\nFlash it anyway?", icon="warning", default="no"):
                    return
            elif not info.prompts:
                if not messagebox.askyesno(
                        "Cannot tell which controller this is for",
                        f"I can't tell which controller this firmware is for, so I can't check it matches "
                        f"{self.prof}.\n\nFlash it anyway?", icon="warning", default="no"):
                    return
        name = os.path.basename(path)
        target = f"the controller in update mode (drive {drive[0]})" if drive else \
            f"the connected {self.prof}"
        if not messagebox.askokcancel(
                "Flash firmware",
                f"Flash {name} ({info.size // 1024} KB) to {target}?\n\n"
                "- The controller restarts and is unavailable for a few seconds.\n"
                "- Do not unplug it while this runs.\n"
                + ("- Your current settings are saved to a text file first.\n" if via_cli else "")
                + "- Some firmware versions reset the settings to defaults."):
            return

        if via_cli:
            try:
                sn = re.search(r"SN: (\w+)", " ".join(self.help))
                backup = fw.write_backup(self.prof, sn.group(1) if sn else "", self._settings_backup_text())
                self.fw_log(f"Settings saved to {backup}")
            except OSError as e:
                if not messagebox.askyesno("Backup failed", f"Could not save the settings backup ({e}).\n\n"
                                                           "Flash without a backup?", icon="warning",
                                           default="no"):
                    return

        self._fw_busy = True
        self._fw_target = (self.prof, self.dev_port) if via_cli else None
        send_update = None
        if via_cli:
            self.dev, self.dev_port = None, None      # the worker thread owns the connection from here
            send_update = lambda: dev.ask("update", timeout=2)  # noqa: E731
        self.fw_log(f"Flashing {name} ...")

        def work():
            try:
                ok, msg = fw.flash(path, send_update, lambda m: self._post(lambda: self.fw_log(m)))
            finally:
                if via_cli:
                    try:
                        dev.close()
                    except Exception:
                        pass
            self._post(lambda: self._flash_done(ok, msg))
        threading.Thread(target=work, daemon=True).start()

    def _flash_done(self, ok, msg):
        self._fw_busy = False
        self.fw_log(msg)
        if not ok:
            messagebox.showerror("Firmware update failed", msg)
            self._fw_target = None
        self._fw_tries = 0
        self._fw_expect_build = ok and self._fw_target is not None
        self.after(3500 if ok else 1500, self.rescan)

    # -------------------------------------------------- reconnecting after ---
    def fw_reconnect_index(self, found):
        """Index in `found` of the controller we just flashed, or None if it is not (clearly) back yet.

        Same prompt on the same port wins; otherwise a single controller with that prompt. If several
        controllers share the prompt (for example two AIC units) we do not guess: the user picks one."""
        if not self._fw_target:
            return None
        prof, port = self._fw_target
        same = [i for i, (n, _p) in enumerate(found) if n == prof]
        for i in same:
            if found[i][1] == port:
                return i
        if len(same) == 1:
            return same[0]
        if len(same) > 1:
            self.fw_log(f"Several {prof} controllers are connected. Pick the one you updated from the list "
                        "and press Connect.")
            self._fw_target = None
            self._fw_expect_build = False
        return None

    def fw_wait_for_return(self):
        """Called from rescan when the flashed controller is not listed yet; returns True if still waiting."""
        if not self._fw_target:
            return False
        self._fw_tries += 1
        if self._fw_tries >= MAX_RECONNECT_TRIES:
            self.fw_log("The controller did not come back. Unplug and replug it, then press Scan.")
            self._fw_target = None
            self._fw_expect_build = False
            return False
        self.after(2500, self.rescan)
        return True

    def fw_after_load(self, prof, built):
        if self._fw_expect_build:
            self._fw_expect_build = False
            self.fw_log(f"Reconnected: {prof} is now running firmware built {built}.")
