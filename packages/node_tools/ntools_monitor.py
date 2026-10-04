"""Tools 6-8: live packet monitor, radio health graphs, coverage.

6. Packet monitor - every packet the radio hears (mcIRC's listener reports its kind, route and signal, never its content).
7. Radio health - the node's own counters (noise floor, signal, battery, airtime, errors) sampled every few minutes, drawn as small graphs.
8. Coverage - which repeaters your node hears directly and how well (from the last hop of every heard packet): a map layer, plus a CSV log
   with your position at the time (the position from Options > Node, or the node's own GPS position when it has one)."""
import csv
import datetime as dt
import os
import time
import tkinter as tk
from tkinter import filedialog, ttk

import gui_signals
from ntools_common import BG, ToolWindow, first, run

KEEP_SAMPLES = 24 * 12                 # a day of 5-minute samples


# ---- 6. packet monitor --------------------------------------------------------------------------------------------------------------------
class MonitorWindow(ToolWindow):
    COLS = (("time", 70), ("kind", 90), ("route", 70), ("hops", 45), ("path", 160), ("snr", 50), ("rssi", 50), ("bytes", 50))

    def __init__(self, api):
        super().__init__(api, "Packet monitor", "720x460", choose_node=False)
        self.t = ttk.Treeview(self, columns=[c for c, _ in self.COLS], show="headings")
        for c, w in self.COLS:
            self.t.heading(c, text=c)
            self.t.column(c, width=w, anchor="w")
        self.t.pack(fill="both", expand=True, padx=6, pady=6)
        self.counts = tk.Label(self, bg=BG, anchor="w", justify="left")
        self.counts.pack(fill="x", padx=6)
        self.shown = 0
        self.say("Packets appear while mcIRC listens between polls (Options > Connect: 'Listen for adverts between polls'). "
                 "Only kind, route and signal are shown - never content.")
        self.tick()

    def tick(self):
        if not self.winfo_exists(): return
        log = self.api.packet_log
        for p in log[self.shown:] if self.shown <= len(log) else log:
            hops = len(gui_signals.split_path(p.get("path", ""), p.get("size", 1)))
            self.t.insert("", 0, values=(dt.datetime.fromtimestamp(p["t"]).strftime("%H:%M:%S"), p.get("type", ""), p.get("route", ""), hops,
                                         p.get("path", ""), p.get("snr", ""), p.get("rssi", ""), p.get("length", "")))
        self.shown = len(log)
        for item in self.t.get_children()[500:]: self.t.delete(item)
        kinds = {}
        for p in log: kinds[p.get("type") or "?"] = kinds.get(p.get("type") or "?", 0) + 1
        self.counts.config(text=f"{len(log)} packets heard this session: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])))
        self.after(1000, self.tick)


# ---- 7. radio health ------------------------------------------------------------------------------------------------------------------------
def sample():
    """One reading of the node's counters."""
    out = run(".get", "stats_core", ".get", "stats_radio", ".get", "stats_packets")
    s = {"t": time.time()}
    from ntools_common import docs
    for d in docs(out):
        if isinstance(d, dict): s.update(d)
    return s


SERIES = (("noise_floor", "Noise floor (dBm)"), ("last_rssi", "Last signal (dBm)"), ("last_snr", "Last SNR (dB)"),
          ("battery_v", "Battery (V)"), ("airtime_pct", "Airtime used (%)"), ("errors_new", "New errors"))


def derived(samples):
    """Adds battery_v, airtime_pct (tx+rx airtime per interval) and errors_new (errors + receive errors since the previous sample)."""
    out, prev = [], None
    for s in samples:
        d = dict(s)
        if s.get("battery_mv"): d["battery_v"] = s["battery_mv"] / 1000
        if prev is not None and s["t"] > prev["t"]:
            span = s["t"] - prev["t"]
            air = (s.get("tx_air_secs", 0) + s.get("rx_air_secs", 0)) - (prev.get("tx_air_secs", 0) + prev.get("rx_air_secs", 0))
            if air >= 0: d["airtime_pct"] = round(100 * air / span, 2)
            err = (s.get("errors", 0) + s.get("recv_errors", 0)) - (prev.get("errors", 0) + prev.get("recv_errors", 0))
            if err >= 0: d["errors_new"] = err
        out.append(d)
        prev = s
    return out


class HealthWindow(ToolWindow):
    def __init__(self, api, addon):
        super().__init__(api, "Radio health", "760x560", choose_node=False)
        self.addon = addon
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Button(top, text="Read now", command=self.read_now).pack(side="left")
        tk.Label(top, text=f"  Sampled every {addon.sample_minutes()} min while connected (Tools > Addons > double-click MeshCore tools).", bg=BG, fg="#555").pack(side="left")
        self.c = tk.Canvas(self, bg="white", highlightthickness=0)
        self.c.pack(fill="both", expand=True, padx=6, pady=4)
        self.c.bind("<Configure>", lambda e: self.draw())
        self.draw()

    def read_now(self):
        self.job("Reading the node's counters", sample, lambda s: (self.addon.add_sample(s), self.draw()))

    def draw(self):
        c = self.c
        c.delete("all")
        data = derived(self.addon.samples)
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 300)
        rows = len(SERIES)
        for i, (key, title) in enumerate(SERIES):
            y0, y1 = i * h / rows + 18, (i + 1) * h / rows - 6
            pts = [(d["t"], d[key]) for d in data if isinstance(d.get(key), (int, float))]
            c.create_text(8, y0 - 10, anchor="w", text=title + (f":  {pts[-1][1]}" if pts else ":  no data yet"), font=("Segoe UI", 9, "bold"))
            c.create_rectangle(60, y0, w - 10, y1, outline="#ccc")
            if len(pts) < 2: continue
            t0, t1 = pts[0][0], pts[-1][0] or 1
            lo, hi = min(v for _, v in pts), max(v for _, v in pts)
            if hi == lo: hi, lo = hi + 1, lo - 1
            xy = [v for t, val in pts for v in (60 + (t - t0) / max(t1 - t0, 1) * (w - 70), y1 - (val - lo) / (hi - lo) * (y1 - y0))]
            c.create_line(*xy, fill="#1a5fb4", width=2)
            c.create_text(56, y0, anchor="ne", text=f"{hi:g}", font=("Segoe UI", 7))
            c.create_text(56, y1, anchor="se", text=f"{lo:g}", font=("Segoe UI", 7))
        if data:
            span = dt.datetime.fromtimestamp(data[0]["t"]).strftime("%H:%M") + " - " + dt.datetime.fromtimestamp(data[-1]["t"]).strftime("%H:%M")
            self.say(f"{len(data)} samples, {span}.  Last: noise {data[-1].get('noise_floor')} dBm, uptime {int(data[-1].get('uptime_secs', 0)) // 3600} h.")


# ---- 8. coverage ---------------------------------------------------------------------------------------------------------------------------
def heard_repeaters(packets, nodes):
    """{public_key: {name, lat, lon, count, best_snr, last}} for the repeaters heard directly (the last hop of each packet's path)."""
    out = {}
    for p in packets:
        hops = gui_signals.split_path(p.get("path", ""), p.get("size", 1))
        if not hops or p.get("snr") is None: continue
        n = gui_signals.locate(hops[-1], nodes)
        if not n: continue
        r = out.setdefault(n["public_key"], {"name": n["name"], "lat": n["lat"], "lon": n["lon"], "count": 0, "best_snr": -99, "last": 0})
        r["count"] += 1
        r["best_snr"] = max(r["best_snr"], p["snr"])
        r["last"] = max(r["last"], p["t"])
    return out


class CoverageWindow(ToolWindow):
    def __init__(self, api, addon):
        super().__init__(api, "Coverage", "620x420", choose_node=False)
        self.addon = addon
        tk.Label(self, bg=BG, justify="left", wraplength=580, text=(
            "The repeaters your node hears directly, from the last hop of every packet it hears. On the map: tick 'Coverage: strong (SNR >= 5)' and "
            "'Coverage: weak' under Layers. 'Wardrive log' saves every heard packet with your position at that moment - move around (with a "
            "GPS node, or update your position in Options > Node) and the file shows where each repeater reaches you.")).pack(anchor="w", padx=8, pady=6)
        self.t = ttk.Treeview(self, columns=("repeater", "heard", "best snr", "last"), show="headings", height=10)
        for c, wd in (("repeater", 220), ("heard", 60), ("best snr", 70), ("last", 90)):
            self.t.heading(c, text=c)
            self.t.column(c, width=wd, anchor="w")
        self.t.pack(fill="both", expand=True, padx=8)
        r = tk.Frame(self, bg=BG)
        r.pack(fill="x", padx=8, pady=6)
        ttk.Button(r, text="Refresh", command=self.fill).pack(side="left")
        ttk.Button(r, text="Save wardrive log (CSV)...", command=self.save_csv).pack(side="left", padx=6)
        self.fill()

    def fill(self):
        rows = heard_repeaters(self.api.packet_log, self.api.nodes.all())
        self.t.delete(*self.t.get_children())
        for r in sorted(rows.values(), key=lambda r: -r["best_snr"]):
            self.t.insert("", "end", values=(r["name"], r["count"], r["best_snr"], dt.datetime.fromtimestamp(r["last"]).strftime("%H:%M:%S")))
        self.say(f"{len(rows)} repeater(s) heard directly this session.")

    def save_csv(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile=f"wardrive-{dt.datetime.now():%Y%m%d-%H%M}.csv")
        if not path: return
        nodes = self.api.nodes.all()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", "my_lat", "my_lon", "kind", "snr", "rssi", "heard_from", "from_lat", "from_lon", "path"])
            for p in self.api.packet_log:
                hops = gui_signals.split_path(p.get("path", ""), p.get("size", 1))
                n = gui_signals.locate(hops[-1], nodes) if hops else None
                lat, lon = p.get("my_pos") or (None, None)
                w.writerow([dt.datetime.fromtimestamp(p["t"]).isoformat(timespec="seconds"), lat, lon, p.get("type"), p.get("snr"), p.get("rssi"),
                            n["name"] if n else "", n["lat"] if n else "", n["lon"] if n else "", p.get("path", "")])
        self.say(f"Saved {len(self.api.packet_log)} packets to {path}")
