"""Tool 4 - firmware: compare the node's companion firmware with the newest MeshCore release and, for ESP32 boards on a USB bridge chip
(Heltec V3, LilyGo T3-S3, ...), update it from mcIRC.  Only the application is written (at 0x10000), so settings, contacts, channels and the
node's identity stay; a backup is made first anyway.  Other boards (nRF52: RAK4631, T-Echo, ...) get the download link instead."""
import json
import os
import re
import subprocess
import sys
import tempfile
import tkinter as tk
import urllib.request
from tkinter import messagebox, ttk

import gui_health
import gui_nodecfg as cfg
import meshcore_io as io
from ntools_common import BG, MONO, ToolWindow

RELEASES = "https://api.github.com/repos/meshcore-dev/MeshCore/releases"
APP_OFFSET = "0x10000"
UA = {"User-Agent": "mcIRC (https://github.com/bclml/mcIRC)", "Accept": "application/vnd.github+json"}


def vkey(v): return tuple(int(x) for x in re.findall(r"\d+", (v or "").split("-")[0])[:3])


def companion_releases(get=None):
    """Every 'companion-vX.Y.Z' release, newest first: [(version, html_url, [assets])].  New releases show up here by themselves."""
    if get is None:
        def get(url):
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r: return json.loads(r.read().decode("utf-8"))
    rels = [r for r in get(RELEASES + "?per_page=60") if str(r.get("tag_name", "")).startswith("companion-") and not r.get("prerelease")]
    if not rels: raise RuntimeError("no companion firmware release found")
    rels.sort(key=lambda r: vkey(r["tag_name"].split("-", 1)[1]), reverse=True)
    return [(r["tag_name"].split("-", 1)[1], r.get("html_url", ""), r.get("assets", [])) for r in rels]


def latest_companion(get=None):
    """The newest companion release: (version, html_url, [assets])."""
    return companion_releases(get)[0]


def board_key(model):
    """'Heltec V3' -> 'heltec_v3': how the board is spelled in MeshCore's file names."""
    return re.sub(r"[^a-z0-9]+", "_", (model or "").lower()).strip("_")


def pick_asset(assets, model, connection="usb"):
    """The application image (not the -merged one) of the companion firmware for this board and connection type."""
    key, out = board_key(model), []
    for a in assets:
        n = a["name"].lower()
        if not n.endswith(".bin") or "merged" in n or f"companion_radio_{connection}" not in n: continue
        if n.startswith(key + "_companion"): out.insert(0, a)
        elif key and key.replace("_", "") in n.replace("_", ""): out.append(a)
    return out[0] if out else None


def download(url, path):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]}), timeout=120) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk: break
            f.write(chunk)
    return path


def esptool_available():
    try:
        import importlib.util
        return importlib.util.find_spec("esptool") is not None
    except Exception:
        return False


class FirmwareWindow(ToolWindow):
    def __init__(self, api):
        super().__init__(api, "Node firmware", "640x460")
        self.info = tk.Label(self, bg=BG, justify="left", anchor="w", font=MONO)
        self.info.pack(fill="x", padx=10, pady=8)
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=10)
        ttk.Button(row, text="Check for a newer version", command=self.check).pack(side="left")
        tk.Label(row, text="  Version:", bg=BG).pack(side="left")
        self.ver = tk.StringVar()
        self.ver_box = ttk.Combobox(row, textvariable=self.ver, width=12, state="readonly")
        self.ver_box.pack(side="left")
        self.ver_box.bind("<<ComboboxSelected>>", lambda e: self.show())
        self.flash_btn = ttk.Button(row, text="Update the node...", command=self.flash, state="disabled")
        self.flash_btn.pack(side="left", padx=6)
        self.log = tk.Text(self, height=14, font=MONO, bg="#101010", fg="#d0ffd0")
        self.log.pack(fill="both", expand=True, padx=10, pady=8)
        self.node = self.asset = self.latest = None
        self.releases = []
        self.check()

    def write(self, text):
        if self.winfo_exists():
            self.log.insert("end", text)
            self.log.see("end")

    def check(self):
        def work():
            return cfg.read_node(), companion_releases()
        def done(r):
            self.node, self.releases = r
            self.ver_box.config(values=[v for v, _, _ in self.releases])
            self.ver.set(self.releases[0][0])                                  # the newest is preselected
            self.show()
        self.job("Checking the firmware", work, done)

    def on_node_change(self):
        self.node = None
        self.flash_btn.config(state="disabled")
        self.check()

    def show(self):
        """The chosen version against the installed one."""
        if not self.node or not self.releases: return
        ver, url, assets = next((r for r in self.releases if r[0] == self.ver.get()), self.releases[0])
        self.latest = (ver, url, assets)
        have, model = self.node["ver"].get("ver", "?"), self.node["ver"].get("model", "?")
        args = self.node_args() or [""]
        conn = {"-s": "usb", "-t": "wifi"}.get(args[0], "ble")
        self.asset = pick_asset(assets, model, conn)
        newest = self.releases[0][0]
        rel = "newer" if vkey(ver) > vkey(have) else "older" if vkey(ver) < vkey(have) else "installed"
        ok, why = gui_health.reset_allowed(args)
        lines = [f"Board:      {model}", f"Installed:  {have}", f"Newest:     {newest}" + ("   (you are up to date)" if vkey(newest) <= vkey(have) else "   <- newer"),
                 f"Chosen:     {ver}   ({rel})", f"File:       {self.asset['name'] if self.asset else 'no matching file for this board'}"]
        if not ok: lines.append("Updating from mcIRC: not on this board - " + why)
        elif not esptool_available(): lines.append("Updating from mcIRC needs: pip install esptool   (then restart mcIRC)")
        lines.append(f"Release:    {url}")
        self.info.config(text="\n".join(lines))
        can = bool(rel != "installed" and self.asset and ok and esptool_available())
        self.flash_btn.config(state="normal" if can else "disabled")

    def flash(self):
        ver, url, _ = self.latest
        model = self.node["ver"].get("model", "?")
        if not messagebox.askyesno("Update the node", f"Update {model} from {self.node['ver'].get('ver')} to {ver}?\n\nFile: {self.asset['name']}\n"
                                   "Only the application is replaced: settings, contacts, channels and identity stay.\n"
                                   "A backup is made first. mcIRC disconnects during the update (about a minute).\n\nDon't unplug the board.", parent=self): return
        port, main = self.node_args()[1], self.node_key == "main"
        import ntools_backup
        def work():
            log = []
            path = ntools_backup.save(ntools_backup.make_backup(False))
            log.append(f"Backup saved: {path}\n")
            self.api.ui()["root"].after(0, lambda: self.write(log[-1]))
            img = download(self.asset["browser_download_url"], os.path.join(tempfile.gettempdir(), self.asset["name"]))
            self.api.ui()["root"].after(0, lambda: self.write(f"Downloaded {os.path.getsize(img)} bytes\nDisconnecting and flashing...\n"))
            if main: self.api.disconnect()                                     # let go of the port (an extra node: its lock below keeps it quiet)
            import time
            time.sleep(6)
            with io.node_lock():
                p = subprocess.run([sys.executable, "-m", "esptool", "--port", port, "--baud", "460800", "--before", "default-reset", "--after", "hard-reset",
                                    "write-flash", APP_OFFSET, img], capture_output=True, text=True, timeout=600, creationflags=io.NO_WINDOW)
            return p.returncode, p.stdout[-3000:] + p.stderr[-2000:]
        def done(r):
            code, out = r
            self.write(out + ("\nUpdate finished. Press Connect - the node starts with the new firmware.\n" if code == 0 else
                              "\nThe update did NOT finish. The node may need to be put into download mode by hand (hold BOOT, press RESET) - "
                              "then try again. Your backup is in backup/node.\n"))
            self.say("Updated." if code == 0 else "Update failed - see above.", error=code != 0)
        self.job(f"Updating to {ver}", work, done)
