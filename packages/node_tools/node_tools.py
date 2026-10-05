"""MeshCore tools: node clock, channel manager, backup & restore, firmware check / update, path tools, packet monitor, radio health, coverage.
Each tool is a window in the Addons menu.  Nothing is sent over the mesh unless you press a button that says so (discover / trace a path)."""
import csv
import os
import time
import tkinter as tk

from gui_addons import AddonBase, BASE_DIR

import ntools_clock
import ntools_monitor

HEALTH_CSV = os.path.join(BASE_DIR, "logs", "radio_health.csv")


class Addon(AddonBase):
    title = "MeshCore tools"
    version = "1.1.1"
    author = "mcIRC"
    description = ("Node clock, channel manager, backup & restore, firmware check / update, Wi-Fi firmware builder, path tools, packet monitor, "
                   "radio health graphs and coverage map - in the Addons menu.")
    tick_seconds = 30

    def on_load(self):
        self.windows, self.samples, self._last_sample = {}, [], 0.0
        for label, key in (("Node clock...", "clock"), ("Channels...", "channels"), ("Backup and restore...", "backup"), ("Firmware...", "firmware"),
                           ("Path tools...", "paths"), ("Packet monitor...", "monitor"), ("Radio health...", "health"), ("Coverage...", "coverage"),
                           ("Wi-Fi firmware...", "wifi")):
            self.api.add_menu_item(label, lambda k=key: self.open(k))
        self.api.add_map_layer("Coverage: strong (SNR >= 5)", lambda: self.coverage(True), "#2e7d32")
        self.api.add_map_layer("Coverage: weak (SNR < 5)", lambda: self.coverage(False), "#ef6c00")

    def on_unload(self):
        for w in list(self.windows.values()):
            try: w.destroy()
            except Exception: pass
        self.windows = {}

    def open(self, key):
        w = self.windows.get(key)
        if w is not None and w.winfo_exists(): return w.lift()
        if key == "clock": w = ntools_clock.ClockWindow(self.api)
        elif key == "channels":
            import ntools_channels
            w = ntools_channels.ChannelsWindow(self.api)
        elif key == "backup":
            import ntools_backup
            w = ntools_backup.BackupWindow(self.api)
        elif key == "firmware":
            import ntools_firmware
            w = ntools_firmware.FirmwareWindow(self.api)
        elif key == "paths":
            import ntools_paths
            w = ntools_paths.PathsWindow(self.api)
        elif key == "monitor": w = ntools_monitor.MonitorWindow(self.api)
        elif key == "health": w = ntools_monitor.HealthWindow(self.api, self)
        elif key == "coverage": w = ntools_monitor.CoverageWindow(self.api, self)
        elif key == "wifi":
            import ntools_wifi
            w = ntools_wifi.WifiFirmwareWindow(self.api)
        self.windows[key] = w

    # ---- the node's clock: checked when mcIRC connects ----
    def on_connect(self):
        if not self.api.get("clock_auto", True): return
        def check():
            node, pc = ntools_clock.node_time()
            if abs(node - pc) > ntools_clock.DRIFT_OK:
                ntools_clock.sync()
                return node - pc
            return None
        def done(r):
            if isinstance(r, (int, float)): self.api.log(f"The node's clock was {abs(r) // 60} min {'behind' if r < 0 else 'ahead'} - set it to this PC's time.")
        self.api.run_background(check, done)

    # ---- radio health: a sample every few minutes while connected ----
    def sample_minutes(self):
        try: return max(1, int(self.api.get("health_minutes", 5)))
        except (TypeError, ValueError): return 5

    def on_tick(self):
        if not self.api.connected or not self.api.get("health_on", True): return
        if time.time() - self._last_sample < self.sample_minutes() * 60: return
        self._last_sample = time.time()
        self.api.run_background(ntools_monitor.sample, lambda s: isinstance(s, dict) and self.add_sample(s))

    def add_sample(self, s):
        self.samples.append(s)
        del self.samples[:-ntools_monitor.KEEP_SAMPLES]
        try:
            os.makedirs(os.path.dirname(HEALTH_CSV), exist_ok=True)
            new = not os.path.exists(HEALTH_CSV)
            keys = ("t", "battery_mv", "uptime_secs", "errors", "queue_len", "noise_floor", "last_rssi", "last_snr", "tx_air_secs", "rx_air_secs",
                    "recv", "sent", "flood_rx", "direct_rx", "recv_errors")
            with open(HEALTH_CSV, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new: w.writerow(keys)
                w.writerow([s.get(k, "") for k in keys])
        except OSError:
            pass
        w = self.windows.get("health")
        if w is not None and w.winfo_exists(): w.draw()

    # ---- coverage map layers ----
    def coverage(self, strong):
        rows = ntools_monitor.heard_repeaters(self.api.packet_log, self.api.nodes.all())
        out = []
        for r in rows.values():
            if (r["best_snr"] >= 5) != strong: continue
            out.append((r["lat"], r["lon"], f"{r['name']} {r['best_snr']:+.1f} dB",
                        f"{r['name']}\nheard directly {r['count']} time(s)\nbest SNR {r['best_snr']} dB\nlast {time.strftime('%H:%M:%S', time.localtime(r['last']))}"))
        return out

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_clock = tk.BooleanVar(value=self.api.get("clock_auto", True))
        self.v_health = tk.BooleanVar(value=self.api.get("health_on", True))
        self.v_minutes = tk.StringVar(value=str(self.sample_minutes()))
        tk.Checkbutton(f, text="Set the node's clock to this PC's time when mcIRC connects and it is more than a minute off", variable=self.v_clock, bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text="Sample the radio's health counters while connected (also saved to logs/radio_health.csv)", variable=self.v_health, bg=bg).pack(anchor="w")
        r = tk.Frame(f, bg=bg)
        r.pack(anchor="w", padx=20)
        tk.Label(r, text="every", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_minutes, width=4).pack(side="left", padx=4)
        tk.Label(r, text="minutes", bg=bg).pack(side="left")
        return f

    def apply_options(self):
        self.api.set("clock_auto", self.v_clock.get())
        self.api.set("health_on", self.v_health.get())
        try: self.api.set("health_minutes", max(1, int(self.v_minutes.get())))
        except ValueError: pass
