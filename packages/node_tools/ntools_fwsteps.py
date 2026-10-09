"""The Firmware builder's over-the-air options: install the OTAFIX bootloader first (nRF52), or update over Wi-Fi instead of USB (ESP32).
Each box is only offered where it makes sense: OTAFIX for nRF52 boards that don't have it yet, Wi-Fi for ESP32 firmware with 'start ota'."""
import subprocess
import time
import tkinter as tk
from tkinter import messagebox

import meshcore_io as io
import ntools_fwbuild as fb
import ntools_ota as ota
from ntools_common import BG, diag


class OtaSteps:
    """Mixed into FirmwareBuilderWindow (needs: self.v, self.boards, self.write, self.job, self.pio, self.tag, source_dir)."""

    def ota_widgets(self, f, r):
        tk.Label(f, text="Over the air:", bg=BG).grid(row=r, column=0, sticky="nw", pady=2)
        of = tk.Frame(f, bg=BG); of.grid(row=r, column=1, columnspan=3, sticky="w")
        self.otafix, self.wifi_ota = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        self.otafix_check = tk.Checkbutton(of, variable=self.otafix, bg=BG, command=self.update_fields,
                                           text="Install the OTAFIX bootloader first (nRF52: faster Bluetooth updates; a failed update can be retried)")
        self.otafix_check.pack(anchor="w")
        self.wifi_ota_check = tk.Checkbutton(of, variable=self.wifi_ota, bg=BG, command=self.update_fields,
                                             text="Update over Wi-Fi instead of USB (ESP32 already running MeshCore: 'start ota')")
        self.wifi_ota_check.pack(anchor="w")
        self.ota_note = tk.Label(of, bg=BG, fg="#555", justify="left", wraplength=560)
        self.ota_note.pack(anchor="w")
        self._uf2_info = None
        self.after(500, self._watch_uf2)

    def setup_widgets(self, f, r):
        """First setup after flashing: name, admin password (repeater types), position - with the radio fields above."""
        tk.Label(f, text="After flashing:", bg=BG).grid(row=r, column=0, sticky="nw", pady=2)
        sf = tk.Frame(f, bg=BG); sf.grid(row=r, column=1, columnspan=3, sticky="w")
        self.setup_on = tk.BooleanVar(value=True)
        self.setup_check = tk.Checkbutton(sf, variable=self.setup_on, bg=BG, command=self.update_fields,
                                          text="Set the node up: name, admin password, position and the radio above")
        self.setup_check.pack(anchor="w")
        row = tk.Frame(sf, bg=BG); row.pack(anchor="w")
        self.setup_vars = {k: tk.StringVar() for k in ("name", "admin", "lat", "lon")}
        self.setup_entries = {}
        for label, key, width, show in (("Name", "name", 18, ""), ("Admin password", "admin", 12, "*"), ("Lat", "lat", 9, ""), ("Lon", "lon", 10, "")):
            tk.Label(row, text=label, bg=BG).pack(side="left", padx=(0, 2))
            self.setup_entries[key] = tk.Entry(row, textvariable=self.setup_vars[key], width=width, show=show)
            self.setup_entries[key].pack(side="left", padx=(0, 8))

    def update_setup_fields(self, kind):
        cli = kind in ota.CLI_KINDS
        ok = (cli or kind == "companion") and not self.wifi_ota.get()      # over Wi-Fi the node keeps its settings
        self.setup_check.config(state="normal" if ok else "disabled")
        on = ok and self.setup_on.get()
        for key, e in self.setup_entries.items():
            e.config(state="normal" if on and (cli or key != "admin") else "disabled")

    def setup_values(self, kind):
        """-> (name, admin password, lat, lon) when the setup box is ticked (checked), else None."""
        if str(self.setup_check.cget("state")) == "disabled" or not self.setup_on.get(): return None
        v = {k: x.get() for k, x in self.setup_vars.items()}
        return ota.check_setup(v["name"], v["admin"] if kind in ota.CLI_KINDS else "", v["lat"], v["lon"], cli=kind in ota.CLI_KINDS)

    def _watch_uf2(self):
        """A board in its UF2 bootloader (double-press reset) shows as a drive: is OTAFIX already on it?"""
        if not self.winfo_exists(): return
        drives = ota.uf2_drives()
        info = None
        if drives:
            try: info = ota.read_info(drives[0])
            except OSError: info = None
        if info != self._uf2_info:
            self._uf2_info = info
            self.update_fields()
        self.after(2000, self._watch_uf2)

    def update_ota_fields(self, envs, kind):
        arch = fb.arch(envs) if envs else "other"
        info, note = self._uf2_info, ""
        already = bool(info) and ota.has_otafix(info)
        fix_ok = arch == "nrf52" and not already
        if already:
            note = f"This board already has the OTAFIX bootloader ({info['bootloader'].split(' lib')[0]})."
        elif arch == "nrf52" and info and ota.otafix_file(info["board_id"]) is None:
            fix_ok, note = False, f"OTAFIX has no bootloader for this board ({info['model'] or info['board_id']})."
        self.otafix_check.config(state="normal" if fix_ok else "disabled")
        if not fix_ok: self.otafix.set(False)
        wifi_ok = bool(envs) and fb.wifi_ota_ok(envs, kind)
        self.wifi_ota_check.config(state="normal" if wifi_ok else "disabled")
        if not wifi_ok: self.wifi_ota.set(False)
        if self.otafix.get(): note = "Before flashing, double-press the board's reset button so it shows up as a drive; mcIRC copies the bootloader to it."
        if self.wifi_ota.get(): note = (f"No USB needed: the node opens the Wi-Fi '{ota.OTA_SSID}' when you send it 'start ota' (log in to it in its "
                                        "private window and type /start ota). This PC joins that Wi-Fi for the upload.")
        self.ota_note.config(text=note)
        self.entries["port"].config(state="disabled" if self.wifi_ota.get() else "normal")
        if hasattr(self, "setup_check"): self.update_setup_fields(kind)

    # ---- OTAFIX, before a USB flash ----
    def install_otafix_step(self):
        """In the background, before the firmware upload: waits for the UF2 drive, then installs OTAFIX (unless it is already there)."""
        self.write("\n== OTAFIX bootloader\nWaiting for the board's UF2 drive (double-press its reset button)...\n")
        t0 = time.time()
        while not ota.uf2_drives():
            if time.time() - t0 > 60: raise RuntimeError("no UF2 drive appeared - double-press the board's reset button and try again")
            time.sleep(1)
        info = ota.read_info(ota.uf2_drives()[0])
        diag(f"OTAFIX: UF2 drive found - {info.get('model') or '?'} / {info.get('board_id') or '?'} / {info.get('bootloader', '')[:60]}")
        result = ota.install_otafix(ota.uf2_drives()[0], log=self.write)
        diag(f"OTAFIX: {result}")
        if result == "installed":
            self.write("Bootloader installed. Waiting for the board to restart...\n")
            time.sleep(10)

    # ---- Wi-Fi OTA instead of USB ----
    def go_wifi_ota(self, env, ini_path, make, board, kind):
        what = fb.TYPE_TITLES[kind].split(" (")[0].split(":")[0]
        if not messagebox.askyesno("Firmware builder", f"Build {what} for {board} and send it to the node over Wi-Fi?\n\n"
                                   "First it is built here (several minutes the first time). Then mcIRC tells you when to put the node in "
                                   "update mode and join its Wi-Fi.", parent=self): return
        src = self.source()

        def build():
            with open(ini_path, encoding="utf-8") as f: original = f.read()
            try:
                with open(ini_path, "w", encoding="utf-8") as f: f.write(make(original))
                self.write(f"\n== pio run -e {env}\n")
                p = subprocess.Popen(self.pio + ["run", "-e", env], cwd=src, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, errors="replace", creationflags=io.NO_WINDOW)
                tail = []
                for line in p.stdout:
                    self.write(line)
                    tail = (tail + [line.rstrip()])[-25:]
                if p.wait() != 0:
                    diag(f"PlatformIO build of {env} (for Wi-Fi OTA) failed (exit {p.returncode}); its last lines:%s" % "".join(chr(10) + l for l in tail))
                    raise RuntimeError("PlatformIO stopped - see above")
            finally:
                with open(ini_path, "w", encoding="utf-8") as f: f.write(original)
            return ota.firmware_bin(src, env)

        self.job("Building (several minutes the first time)", build, lambda path: self.after(0, lambda: self._ask_upload(path, kind)), need_radio=False)

    def _ask_upload(self, path, kind):
        self.write(f"\nBuilt: {path}\n")
        if not messagebox.askokcancel("Firmware builder - update over Wi-Fi",
                                      "Now:\n\n1. In mcIRC, open the private window with that node, log in (/login) and type   /start ota\n"
                                      f"   (it answers 'Started: http://{ota.OTA_HOST}/update').\n"
                                      f"2. Connect this PC's Wi-Fi to '{ota.OTA_SSID}' (no password). This PC is off your own network until step 4.\n"
                                      "3. Press OK.\n4. When it is done, put this PC back on your own Wi-Fi.", parent=self): return
        self.job("Looking for the node in update mode", ota.ota_identity, lambda ident: self._confirm_upload(path, ident, kind), need_radio=False)

    def _confirm_upload(self, path, ident, kind):
        diag(f"Wi-Fi OTA: node in update mode: {ident.get('hardware', '?')}, {kind}")
        if not messagebox.askyesno("Firmware builder", f"The node in update mode is:\n\n    {ident.get('id', '?')}\n\nSend the new firmware to it?", parent=self):
            return
        last = [0]

        def progress(done, total):
            pct = int(done * 100 / total)
            if pct >= last[0] + 10: last[0] = pct; self.write(f"  {pct}%\n")

        def done(answer):
            diag(f"Wi-Fi OTA: the node answered '{str(answer)[:40]}'")
            self.write(f"\nThe node answered '{answer}' and restarts with the new firmware. Put this PC back on your own Wi-Fi.\n"
                       "Then log in to the node again, check 'clock' (and 'clock sync' if it's wrong) and 'ver'.\n")
            if kind in fb.AFTER: self.write(fb.AFTER[kind] + "\n")
        self.write("\n== Uploading over Wi-Fi\n")
        self.job("Uploading the firmware over Wi-Fi", lambda: ota.ota_upload(path, progress=progress), done, need_radio=False)
