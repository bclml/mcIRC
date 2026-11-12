"""Wardrive map: where each repeater can hear you - drive or walk around with mcIRC listening, and every packet a repeater sends straight to
your radio is noted with your position at that moment and how strong it was.  The map gets three layers (Wardrive: strong / fair /
weak), and a window lists each repeater: how often it was heard, its best signal and where, and the farthest spot it reached you.

Your position is your node's (Options > Node, or what a GPS node advertises), so it only moves when that does.  Recording is off until
you switch it on; it only listens - nothing is sent.  The records stay on this PC (logs/wardrive_map.json)."""
import csv
import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from gui_addons import AddonBase, BASE_DIR
import wdmap_core as core

LOG_PATH = os.path.join(BASE_DIR, "logs", "wardrive_map.json")
BG = "#d4d0c8"
SAVE_EVERY = 60
ALL = "All repeaters"


class Addon(AddonBase):
    title = "Wardrive map"
    version = "1.0.0"
    author = "mcIRC"
    description = ("Where each repeater can hear you: while recording, every packet a repeater sends straight to your radio is noted with your "
                   "position and its signal, shown on the map in three layers (strong / fair / weak) and listed per repeater. Never transmits.")
    tick_seconds = 10
    switch = "recording"           # its ON/OFF switch on the toolbar

    def on_load(self):
        self.log, self.win, self.only, self.last_save = core.Log(LOG_PATH), None, None, time.time()
        try: self.log.load()
        except (OSError, ValueError) as e: self.api.log(f"couldn't read {LOG_PATH} ({e}) - starting a new wardrive log", "warn")
        self.seen_t = time.time()                                   # only packets heard from now on
        for kind, colour in (("strong", "#26a269"), ("fair", "#e5a50a"), ("weak", "#c01c28")):
            self.api.add_map_layer(f"Wardrive: {kind}", lambda k=kind: self.points(k), colour)
        self.api.add_menu_item("Wardrive map...", self.open)

    def on_unload(self):
        if self.win is not None and self.win.winfo_exists(): self.win.destroy()
        if self.log.dirty:
            try: self.log.save()
            except OSError as e: self.api.log(f"couldn't save the wardrive log: {e}", "warn")

    def recording(self): return bool(self.api.get("recording", False))

    def here(self):
        lat, lon, _ = self.api.node_position()
        return (lat, lon) if (lat or lon) else None

    # ---- listening ----
    def on_tick(self):
        self.collect()
        if self.log.dirty and time.time() - self.last_save >= SAVE_EVERY:
            self.last_save = time.time()
            data_rows = [list(r) for r in self.log.rows]
            self.log.dirty = False
            def write():
                tmp = core.Log(LOG_PATH); tmp.rows = data_rows; tmp.save()
            self.api.run_background(write, lambda r: isinstance(r, Exception) and self.api.log(f"couldn't save the wardrive log: {r}", "warn"))

    def collect(self):
        """Packets heard since the last look: the last hop of each is the repeater that sent it straight to you."""
        log = [p for p in self.api.packet_log if p.get("t", 0) > self.seen_t]
        if not log: return 0
        self.seen_t = max(p["t"] for p in log)
        me = self.here()
        if not self.recording() or not me: return 0
        relays = [n["public_key"] for n in self.api.nodes.all() if n.get("type") in core.RELAY_TYPES]
        added = 0
        for p in log:
            hops = core.split_path(p.get("path"), p.get("size", 1))
            if not hops or not isinstance(p.get("snr"), (int, float)): continue
            key = core.relay_owner(hops[-1], relays)
            if key: added += self.log.add(p["t"], me[0], me[1], key, p["snr"], p.get("rssi"))
        return added

    def on_packet(self, pkt):
        """A repeater's own advert heard with no hops: that repeater itself reached you."""
        if not self.recording() or pkt.get("type") != "ADVERT" or pkt.get("path") or not isinstance(pkt.get("snr"), (int, float)): return
        key, me = core.advert_key(pkt.get("packet")), self.here()
        if not key or not me: return
        node = next((n for n in self.api.nodes.all() if n["public_key"] == key), None)
        if node and node.get("type") in core.RELAY_TYPES: self.log.add(pkt.get("t") or time.time(), me[0], me[1], key, pkt["snr"], pkt.get("rssi"))

    # ---- the map ----
    def names(self): return {n["public_key"]: n.get("name") or n["public_key"][:8] for n in self.api.nodes.all()}

    def points(self, kind):
        return core.layer(self.log.spots(self.only), self.names(), kind)

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify(); self.win.lift()
            return
        self.win = WardriveWindow(self)

    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_rec = tk.BooleanVar(value=self.recording())
        tk.Checkbutton(f, text="Record where repeaters hear me (listens only)", variable=self.v_rec, bg=bg).pack(anchor="w")
        tk.Label(f, bg=bg, fg="#555", justify="left", wraplength=480, text=(
            "Your position is your node's (Options > Node, or what a GPS node advertises). mcIRC must be listening for packets (Options > "
            "Connect: 'Listen between polls'; USB or Wi-Fi). On the map: Layers > Wardrive: strong / fair / weak. Addons menu > Wardrive map... "
            "lists each repeater.")).pack(anchor="w", pady=(4, 0))
        return f

    def apply_options(self): self.api.set("recording", self.v_rec.get())


class WardriveWindow(tk.Toplevel):
    COLS = (("repeater", 190), ("heard", 60), ("best snr", 70), ("best at", 150), ("farthest", 80), ("last", 90))

    def __init__(self, addon):
        super().__init__(addon.api.ui()["root"], bg=BG)
        self.addon = addon
        self.title("Wardrive map")
        self.geometry("720x460")
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=6, pady=6)
        self.rec = tk.BooleanVar(value=addon.recording())
        tk.Checkbutton(top, text="Recording", variable=self.rec, bg=BG, command=self.toggle).pack(side="left")
        tk.Label(top, text="Map shows:", bg=BG).pack(side="left", padx=(12, 0))
        self.only = tk.StringVar(value=ALL)
        self.pick = ttk.Combobox(top, textvariable=self.only, state="readonly", width=26)
        self.pick.pack(side="left", padx=4)
        self.pick.bind("<<ComboboxSelected>>", lambda e: self.choose())
        ttk.Button(top, text="Save as CSV...", command=self.export).pack(side="right")
        ttk.Button(top, text="Clear...", command=self.clear).pack(side="right", padx=4)
        self.t = ttk.Treeview(self, columns=[c for c, _ in self.COLS], show="headings")
        for c, w in self.COLS:
            self.t.heading(c, text=c)
            self.t.column(c, width=w, anchor="w", stretch=c == "repeater")
        self.t.pack(fill="both", expand=True, padx=6)
        self.note = tk.Label(self, bg=BG, fg="#555", anchor="w", justify="left", wraplength=700)
        self.note.pack(fill="x", padx=6, pady=4)
        self.tick()

    def toggle(self): self.addon.api.set("recording", self.rec.get())

    def choose(self):
        keys = {v: k for k, v in self.keys.items()}
        self.addon.only = keys.get(self.only.get())

    def tick(self):
        if not self.winfo_exists(): return
        self.fill()
        self.after(5000, self.tick)

    def fill(self):
        a, now = self.addon, time.time()
        self.rec.set(a.recording())
        rows = a.log.per_repeater(a.api.nodes.all())
        self.keys = {k: r["name"] for k, r in rows.items()}
        self.pick.config(values=[ALL] + sorted(self.keys.values(), key=str.lower))
        self.t.delete(*self.t.get_children())
        for k, r in sorted(rows.items(), key=lambda kv: -kv[1]["count"]):
            at = f"{r['best_at'][0]:.4f}, {r['best_at'][1]:.4f}" if r["best_at"] else ""
            far = f"{r['far_km']:.1f} km" if r["far_km"] is not None else "?"
            last = time.strftime("%m-%d %H:%M", time.localtime(r["last"]))
            self.t.insert("", "end", values=(r["name"], r["count"], f"{r['best']:+.1f} dB", at, far, last))
        me = a.here()
        state = ("Recording." if a.recording() else "Not recording (tick Recording to start).") + (
            "" if me else " Your position isn't set (Options > Node), so nothing can be recorded.")
        self.note.config(text=f"{len(a.log.rows)} sightings of {len(rows)} repeaters. {state} On the map: Layers > Wardrive: strong (SNR 5 dB "
                              "or more) / fair / weak (below -5 dB). A spot heard by several repeaters shows the best one.")

    def clear(self):
        if not self.addon.log.rows: return
        if messagebox.askyesno("Wardrive map", f"Delete all {len(self.addon.log.rows)} recorded sightings?\nThis can't be undone "
                               "(Save as CSV first to keep a copy).", parent=self):
            self.addon.log.clear()
            self.addon.log.save()
            self.fill()

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="wardrive.csv")
        if not path: return
        names = self.addon.names()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", "my_lat", "my_lon", "repeater", "repeater_key", "snr", "rssi"])
            for t, lat, lon, k, snr, rssi in self.addon.log.rows:
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)), lat, lon, names.get(k, ""), k, snr, rssi])
        self.note.config(text=f"Saved {len(self.addon.log.rows)} sightings to {path}")
