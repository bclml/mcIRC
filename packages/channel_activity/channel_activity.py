"""Channel activity: how busy your frequency is - packets per minute, how much of the airtime they use, which kinds, the noise floor
and how far signals stand above it - live, with graphs for the last hour, 6 hours or day.  From the packets mcIRC's listener hears
(Options > Connect: 'Listen between polls') and, every few minutes, your node's own noise floor and airtime counters (a local read
of the node; nothing goes over the air).  Addons menu > Channel activity..."""
import time
import tkinter as tk
from tkinter import ttk

from gui_addons import AddonBase
import chact_core as core

BG = "#d4d0c8"
DEFAULTS = {"sf": 7, "bw": 62.5, "cr": 5}                          # MeshCore's common narrow preset, until the node says otherwise
RANGES = (("Last hour", 60, 1), ("6 hours", 360, 6), ("Day", 1440, 24))


class Addon(AddonBase):
    title = "Channel activity"
    version = "1.0.0"
    author = "mcIRC"
    description = ("How busy your frequency is: packets per minute, airtime used, which kinds, the noise floor and the signal margin - live, "
                   "with graphs for the last hour, 6 hours or day. Never transmits.")
    tick_seconds = 10

    def on_load(self):
        self.act, self.win, self.busy, self.last_noise = core.Activity(), None, False, 0.0
        self.radio = dict(DEFAULTS)
        self.radio_from = "defaults (until the node is read)"
        self.act.last_t = time.time()                               # only what is heard from now on
        self.api.add_menu_item("Channel activity...", self.open)
        if self.api.connected: self.on_connect()

    def on_unload(self):
        if self.win is not None and self.win.winfo_exists(): self.win.destroy()

    def noise_minutes(self):
        try: return max(0, int(self.api.get("noise_minutes", 5)))
        except (TypeError, ValueError): return 5

    # ---- the radio's settings (for the airtime estimate) ----
    def on_connect(self):
        """Read the node's radio settings once (spreading factor, bandwidth, coding rate): the airtime estimate needs them."""
        def read():
            import gui_nodecfg
            return gui_nodecfg.read_node()
        def done(r):
            if isinstance(r, Exception) or not isinstance(r, dict): return
            i = r.get("info", {})
            try:
                self.radio = {"sf": int(i["radio_sf"]), "bw": float(i["radio_bw"]), "cr": int(i["radio_cr"])}
                self.radio_from = f"your node ({i.get('radio_freq')} MHz)"
            except (KeyError, TypeError, ValueError):
                pass
            st = r.get("radio", {})
            if st: self.act.add_noise(time.time(), st)
        self.api.run_background(read, done)

    # ---- collecting ----
    def on_tick(self):
        self.act.add_packets(self.api.packet_log, self.radio["sf"], self.radio["bw"], self.radio["cr"])
        now = time.time()
        self.act.trim(now)
        mins = self.noise_minutes()
        if mins and self.api.connected and not self.busy and now - self.last_noise >= mins * 60:
            self.busy, self.last_noise = True, now
            self.api.run_background(self.read_noise, self.got_noise)

    def read_noise(self):
        """The node's radio counters (noise floor, rx / tx airtime) - a local read over USB / Wi-Fi / Bluetooth, nothing transmitted."""
        import meshcore_io as io
        if not io.node_args(): raise RuntimeError("not connected")
        r = io.execute_mesh_command(io.node_args() + [".get", "stats_radio"], timeout=30, retries=0)
        return core.parse_stats(f"{r.stdout}\n{r.stderr}")

    def got_noise(self, r):
        self.busy = False
        if isinstance(r, dict) and r: self.act.add_noise(time.time(), r)

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify(); self.win.lift()
            return
        self.win = ActivityWindow(self)

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_noise = tk.StringVar(value=str(self.noise_minutes()))
        r = tk.Frame(f, bg=bg)
        r.pack(anchor="w")
        tk.Label(r, text="Read the node's noise floor and airtime every (minutes, 0 = never):", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_noise, width=5).pack(side="left", padx=4)
        tk.Label(f, bg=bg, fg="#555", justify="left", wraplength=480, text=(
            "That is a local read of your node over its cable / Wi-Fi / Bluetooth - nothing goes over the air. Packets are counted from "
            "what mcIRC's listener hears (Options > Connect: 'Listen between polls'; not over Bluetooth). Addons menu > Channel activity...")).pack(anchor="w", pady=(4, 0))
        return f

    def apply_options(self):
        try: self.api.set("noise_minutes", max(0, int(self.v_noise.get())))
        except ValueError: pass


class ActivityWindow(tk.Toplevel):
    def __init__(self, addon):
        super().__init__(addon.api.ui()["root"], bg=BG)
        self.addon = addon
        self.title("Channel activity")
        self.geometry("820x600")
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        self.rng = tk.IntVar(value=0)
        for i, (text, _, _) in enumerate(RANGES):
            tk.Radiobutton(top, text=text, variable=self.rng, value=i, bg=BG, command=self.refresh).pack(side="left")
        self.cards = tk.Frame(self, bg=BG)
        self.cards.pack(fill="x", padx=8)
        self.vals = {}
        for i, key in enumerate(("Packets / min", "Airtime used", "Noise floor", "Signal margin")):
            box = tk.Frame(self.cards, bg="white", bd=1, relief="solid")
            box.grid(row=0, column=i, padx=4, pady=4, sticky="nsew")
            self.cards.columnconfigure(i, weight=1)
            tk.Label(box, text=key, bg="white", fg="#555").pack(anchor="w", padx=6, pady=(4, 0))
            self.vals[key] = tk.Label(box, text="-", bg="white", font=("Segoe UI", 16, "bold"))
            self.vals[key].pack(anchor="w", padx=6)
            self.vals[key + " note"] = tk.Label(box, text="", bg="white", fg="#555", justify="left", wraplength=180)
            self.vals[key + " note"].pack(anchor="w", padx=6, pady=(0, 4))
        self.kinds = tk.Label(self, bg=BG, anchor="w", justify="left", wraplength=800)
        self.kinds.pack(fill="x", padx=8)
        self.c = tk.Canvas(self, bg="white", highlightthickness=0)
        self.c.pack(fill="both", expand=True, padx=8, pady=6)
        self.c.bind("<Configure>", lambda e: self.draw())
        self.note = tk.Label(self, bg=BG, fg="#555", anchor="w", justify="left", wraplength=800)
        self.note.pack(fill="x", padx=8, pady=(0, 6))
        self.tick()

    def tick(self):
        if not self.winfo_exists(): return
        self.addon.act.add_packets(self.addon.api.packet_log, self.addon.radio["sf"], self.addon.radio["bw"], self.addon.radio["cr"])
        self.refresh()
        self.after(5000, self.tick)

    def refresh(self):
        a, now = self.addon, time.time()
        label, minutes, step = RANGES[self.rng.get()]
        s = a.act.summary(now, minutes)
        self.vals["Packets / min"].config(text=f"{s['per_min']:.1f}")
        self.vals["Packets / min note"].config(text=f"{s['packets']} heard, {label.lower()}")
        self.vals["Airtime used"].config(text=f"{s['air_pct']:.1f} %")
        node = a.act.node_airtime_pct()
        self.vals["Airtime used note"].config(text=(f"estimated from heard packets; the node counts {node[0]:.1f} % receiving, {node[1]:.1f} % sending"
                                                    if node else "estimated from heard packets"))
        nf = a.act.noise[-1][1] if a.act.noise else None
        self.vals["Noise floor"].config(text=f"{nf} dBm" if nf is not None else "-")
        self.vals["Noise floor note"].config(text=time.strftime("read %H:%M", time.localtime(a.act.noise[-1][0])) if a.act.noise
                                             else "not read yet" if a.noise_minutes() else "reading switched off")
        if nf is not None and s["rssi"] is not None:
            m = s["rssi"] - nf
            self.vals["Signal margin"].config(text=f"{m:.0f} dB")
            self.vals["Signal margin note"].config(text=f"{core.margin_word(m)}: median signal {s['rssi']:.0f} dBm, SNR {s['snr']:+.1f} dB")
        else:
            self.vals["Signal margin"].config(text="-")
            self.vals["Signal margin note"].config(text="needs packets and a noise reading")
        kinds = ", ".join(f"{k} {v}" for k, v in s["kinds"].items())
        self.kinds.config(text=f"Kinds: {kinds}" if kinds else "Kinds: nothing heard yet")
        try: listening = a.api.listening()
        except Exception: listening = "on"
        warn = {"off": "mcIRC isn't listening for packets (Options > Connect: 'Listen between polls'), so nothing is counted. ",
                "bluetooth": "Over Bluetooth mcIRC can't hear packets, so nothing is counted (USB or Wi-Fi can). ",
                "failed": "mcIRC's packet listener kept failing this session, so the counts may be missing. "}.get(listening, "")
        self.note.config(text=warn + f"Airtime is worked out from each packet's size with SF {a.radio['sf']}, {a.radio['bw']:g} kHz, "
                                     f"CR 4/{a.radio['cr']} ({a.radio_from}). Above about 10 % packets start to collide.")
        self.draw()

    def draw(self):
        c = self.c
        c.delete("all")
        a, now = self.addon, time.time()
        label, minutes, step = RANGES[self.rng.get()]
        rows = a.act.series(now, minutes, step)
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 200)
        x0, x1 = 50, w - 50
        half = (h - 30) / 2
        top_pkt = max([r[1] for r in rows] + [1])
        top_air = max([r[2] for r in rows] + [1])
        bw = (x1 - x0) / len(rows)
        c.create_text(x0, 10, anchor="w", text=f"Packets per minute ({'each minute' if step == 1 else f'per {step} min'})", font=("Segoe UI", 9, "bold"))
        c.create_text(x1, 10, anchor="e", text="airtime used %", fill="#c64600", font=("Segoe UI", 9))
        y0, y1 = 20, 20 + half - 10
        c.create_rectangle(x0, y0, x1, y1, outline="#ccc")
        for i, (_, ppm, _) in enumerate(rows):
            if ppm: c.create_rectangle(x0 + i * bw + 1, y1 - ppm / top_pkt * (y1 - y0), x0 + (i + 1) * bw - 1, y1, fill="#1a5fb4", outline="")
        air = [v for i, r in enumerate(rows) for v in (x0 + (i + 0.5) * bw, y1 - r[2] / top_air * (y1 - y0))]
        if len(air) >= 4: c.create_line(*air, fill="#c64600", width=2)
        c.create_text(x0 - 4, y0, anchor="ne", text=f"{top_pkt:.0f}", font=("Segoe UI", 7))
        c.create_text(x1 + 4, y0, anchor="nw", text=f"{top_air:.1f}%", font=("Segoe UI", 7), fill="#c64600")
        # noise floor
        n0, n1 = y1 + 28, h - 20
        pts = [(t, nf) for t, nf, _, _ in a.act.noise if t >= now - minutes * 60]
        c.create_text(x0, n0 - 10, anchor="w", text="Noise floor (dBm)" + ("" if pts else ": no readings in this time"), font=("Segoe UI", 9, "bold"))
        c.create_rectangle(x0, n0, x1, n1, outline="#ccc")
        if pts:
            lo, hi = min(p[1] for p in pts) - 2, max(p[1] for p in pts) + 2
            xy = [v for t, nf in pts for v in (x0 + (t - (now - minutes * 60)) / (minutes * 60) * (x1 - x0), n1 - (nf - lo) / (hi - lo) * (n1 - n0))]
            if len(xy) >= 4: c.create_line(*xy, fill="#26a269", width=2)
            else: c.create_oval(xy[0] - 3, xy[1] - 3, xy[0] + 3, xy[1] + 3, fill="#26a269", outline="")
            c.create_text(x0 - 4, n0, anchor="ne", text=f"{hi:.0f}", font=("Segoe UI", 7))
            c.create_text(x0 - 4, n1, anchor="se", text=f"{lo:.0f}", font=("Segoe UI", 7))
        fmt = "%H:%M"
        for frac, anchor in ((0, "w"), (0.5, "center"), (1, "e")):
            c.create_text(x0 + frac * (x1 - x0), h - 8, anchor=anchor, font=("Segoe UI", 7),
                          text=time.strftime(fmt, time.localtime(now - minutes * 60 * (1 - frac))))
