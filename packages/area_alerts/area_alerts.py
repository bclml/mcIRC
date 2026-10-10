"""Area alerts: natural disasters, earthquakes, tsunamis and official weather warnings for the areas you choose - anywhere in the world
(country, then region, then area).  Sources: GDACS, USGS, NOAA tsunami centres, Environment Canada, the US National Weather Service and
MeteoAlarm - free, no key.

Off until switched on.  Switched on, alerts show in the 'Area alerts' window on this PC; they are broadcast to the mesh only with 'Broadcast
to the mesh' ticked - each alert once, at most one every 30 seconds and 10 an hour, each kind to its own channel (added to the node when
missing; never Public).  The first check after switching on only shows what is already in force."""
import time
import tkinter as tk
from tkinter import ttk

from gui_addons import AddonBase
import aa_places as places
import aa_sources as src

KINDS = {"disasters": ("Natural disasters (GDACS: earthquakes, cyclones, floods, volcanoes, droughts, wildfires)", "#alerts"),
         "quakes": ("Earthquakes (USGS)", "#alerts"),
         "tsunami": ("Tsunami warnings (NOAA tsunami centres)", "#alerts"),
         "weather": ("Weather warnings (Environment Canada, US NWS, MeteoAlarm Europe)", "#weather")}
CHECK_EVERY = 300            # seconds between checks
GAP, PER_HOUR = 30, 10       # broadcasting limits
WINDOW = "Area alerts"


class Addon(AddonBase):
    title = "Area alerts"
    version = "1.0.0"
    author = "mcIRC"
    description = ("Natural disasters, earthquakes, tsunamis and official weather warnings for the areas you choose anywhere in the world "
                   "(country, region, area). Shown on this PC; broadcast to the mesh only if you tick it. Off until you switch it on.")
    tick_seconds = 60
    switch = "enabled"

    def on_load(self):
        self.busy, self.last_check, self.queue, self.sent_times = False, 0.0, [], []
        self.current = []                                   # [(area label, Alert)] from the last check
        self.api.add_menu_item("Check now", lambda: self.check(force=True))
        self.api.add_menu_item("Alerts in force...", self.show_current)

    def on_unload(self): self.queue.clear()

    # ---- checking ----
    def on_tick(self):
        if not self.api.get("enabled", False): return
        self.drain()
        if time.time() - self.last_check >= CHECK_EVERY: self.check()

    def check(self, force=False):
        if self.busy or not (self.api.get("enabled", False) or force): return
        areas, on = list(self.api.get("areas", [])), self.kinds_on()
        if not areas or not on:
            if force: self.api.notice("Area alerts: choose areas and alert kinds in its settings first.", "warn")
            return
        self.busy, self.last_check = True, time.time()
        opts = {"min_level": self.api.get("min_level", "orange"), "min_mag": float(self.api.get("min_mag", 5.0)),
                "radius": int(self.api.get("quake_radius", 300))}

        def work():
            found, errors = [], []
            for a in areas:
                for kind in on:
                    try:
                        if kind == "disasters": got = src.gdacs(a, opts["min_level"])
                        elif kind == "quakes": got = src.usgs(a, opts["min_mag"], opts["radius"])
                        else: got = src.SOURCES[kind](a)
                        texts = {al.text for _, al in found if _ == places.label(a)}
                        for al in got:                  # the same warning for neighbouring districts: once per area
                            if al.text not in texts: found.append((places.label(a), al)); texts.add(al.text)
                    except Exception as e:
                        errors.append(f"{kind} for {a.get('name')}: {e}")
            return found, errors
        self.api.run_background(work, self._checked)

    def _checked(self, r):
        self.busy = False
        if isinstance(r, Exception): return self.api.log(f"Area alerts: check failed: {r}", "warn")
        found, errors = r
        for e in errors[:3]: self.api.log(f"Area alerts: couldn't read {e}", "warn")
        self.current = found
        seen = set(self.api.get("seen", []))
        first = not self.api.get("checked_once", False)
        new = [(lab, al) for lab, al in found if al.id not in seen]
        for lab, al in new:
            self.api.write(WINDOW, f"{'(in force) ' if first else ''}{al.text}  [{lab}]")
            if not first and self.api.get("broadcast", False): self.queue.append(al)
        self.api.set("seen", (list(seen) + [al.id for _, al in new])[-3000:])
        self.api.set("checked_once", True)
        self.drain()

    def drain(self):
        """Broadcast what is waiting: at most one every GAP seconds and PER_HOUR an hour."""
        if not self.queue or not self.api.get("broadcast", False) or not self.api.connected: return
        now = time.time()
        self.sent_times = [t for t in self.sent_times if now - t < 3600]
        if len(self.sent_times) >= PER_HOUR or (self.sent_times and now - self.sent_times[-1] < GAP): return
        al = self.queue.pop(0)
        self.api.send(self.channel(al.kind), al.text)
        self.sent_times.append(now)
        if self.queue: self.api.after(GAP * 1000 + 500, self.drain)

    def kinds_on(self):
        saved = self.api.get("kinds", {})
        return [k for k in KINDS if saved.get(k, k in ("disasters", "weather"))]

    def channel(self, kind):
        return (self.api.get("channels", {}).get(kind) or KINDS[kind][1]).strip()

    def show_current(self):
        lines = [f"{al.text}  [{lab}]" for lab, al in self.current] or ["Nothing in force for your areas at the last check."]
        text = "\n".join(lines) + f"\n\nLast check: {time.strftime('%H:%M', time.localtime(self.last_check)) if self.last_check else 'not yet'}"
        show = getattr(self.api, "show_text", None)
        if show: show("Area alerts - in force now", text)
        else: self.api.notice(text)

    # ---- settings ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        g = self.api.get
        self.v_on, self.v_bc = tk.BooleanVar(value=g("enabled", False)), tk.BooleanVar(value=g("broadcast", False))
        tk.Checkbutton(f, text="Check for alerts (they show in the 'Area alerts' window on this PC)", variable=self.v_on, bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text="Broadcast to the mesh (this transmits on your radio)", variable=self.v_bc, bg=bg,
                       font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        tk.Label(f, bg=bg, fg="#555", wraplength=520, justify="left", text=(
            "Each alert once, at most one every 30 seconds and 10 an hour, never in Public. A channel your node doesn't have is added to it. "
            "The first check only shows what is already in force.")).pack(anchor="w", padx=18)

        # areas: country -> region -> area
        box = tk.LabelFrame(f, text="Your areas", bg=bg); box.pack(fill="x", pady=6)
        row = tk.Frame(box, bg=bg); row.pack(fill="x", padx=4, pady=2)
        self._countries = places.countries()
        self.c_box = ttk.Combobox(row, values=[n for n, _ in self._countries], state="readonly", width=24)
        self.r_box = ttk.Combobox(row, state="readonly", width=24)
        self.a_box = ttk.Combobox(row, state="readonly", width=28)
        for w, lab in ((self.c_box, "Country"), (self.r_box, "Region"), (self.a_box, "Area")):
            tk.Label(row, text=lab + ":", bg=bg).pack(side="left"); w.pack(side="left", padx=(2, 8))
        self.c_box.bind("<<ComboboxSelected>>", lambda e: self._fill_regions())
        self.r_box.bind("<<ComboboxSelected>>", lambda e: self._fill_areas())
        row2 = tk.Frame(box, bg=bg); row2.pack(fill="x", padx=4, pady=2)
        self.chosen = list(g("areas", []))
        self.lst = tk.Listbox(row2, height=5, width=70)
        self.lst.pack(side="left", fill="x", expand=True)
        b = tk.Frame(row2, bg=bg); b.pack(side="left", padx=4)
        ttk.Button(b, text="Add area", command=self._add).pack(fill="x")
        ttk.Button(b, text="Remove", command=self._remove).pack(fill="x", pady=2)
        self._fill_list()

        kinds = tk.LabelFrame(f, text="Alert kinds, and the channel each goes to", bg=bg); kinds.pack(fill="x", pady=4)
        saved, chans = g("kinds", {}), g("channels", {})
        self.k_vars, self.ch_vars = {}, {}
        for i, (k, (title, default_ch)) in enumerate(KINDS.items()):
            self.k_vars[k] = tk.BooleanVar(value=saved.get(k, k in ("disasters", "weather")))
            self.ch_vars[k] = tk.StringVar(value=chans.get(k, default_ch))
            tk.Checkbutton(kinds, text=title, variable=self.k_vars[k], bg=bg, anchor="w").grid(row=i, column=0, sticky="w")
            tk.Entry(kinds, textvariable=self.ch_vars[k], width=14).grid(row=i, column=1, padx=4)
        opt = tk.Frame(f, bg=bg); opt.pack(fill="x", pady=2)
        self.v_level = tk.StringVar(value=g("min_level", "orange"))
        self.v_mag, self.v_rad = tk.StringVar(value=str(g("min_mag", 5.0))), tk.StringVar(value=str(g("quake_radius", 300)))
        tk.Label(opt, text="GDACS from level:", bg=bg).pack(side="left")
        ttk.Combobox(opt, textvariable=self.v_level, values=src.LEVELS, state="readonly", width=7).pack(side="left", padx=(2, 10))
        tk.Label(opt, text="Earthquakes from magnitude", bg=bg).pack(side="left")
        tk.Entry(opt, textvariable=self.v_mag, width=4).pack(side="left", padx=2)
        tk.Label(opt, text="within km", bg=bg).pack(side="left")
        tk.Entry(opt, textvariable=self.v_rad, width=5).pack(side="left", padx=2)
        tk.Label(f, bg=bg, fg="#555", wraplength=520, justify="left", text=(
            "Sources (free, no key): GDACS (UN / EU JRC), USGS, NOAA tsunami warning centres, Environment Canada, the US National Weather "
            "Service, MeteoAlarm. Places: GeoNames (CC BY 4.0). Official weather warnings are available for Canada, the US and 38 European "
            "countries; natural disasters and earthquakes everywhere.")).pack(anchor="w", pady=(4, 0))
        return f

    def _fill_regions(self):
        cc = dict(self._countries).get(self.c_box.get())
        self.r_box.config(values=places.regions(cc) if cc else []); self.r_box.set(""); self.a_box.config(values=[]); self.a_box.set("")

    def _fill_areas(self):
        cc = dict(self._countries).get(self.c_box.get())
        self.a_box.config(values=[a[0] for a in places.areas(cc, self.r_box.get())]); self.a_box.set("")

    def _add(self):
        cc = dict(self._countries).get(self.c_box.get())
        a = places.make(cc, self.r_box.get(), self.a_box.get()) if cc else None
        if a and not any(places.label(x) == places.label(a) for x in self.chosen):
            self.chosen.append(a); self._fill_list()

    def _remove(self):
        for i in reversed(self.lst.curselection()): del self.chosen[i]
        self._fill_list()

    def _fill_list(self):
        self.lst.delete(0, "end")
        for a in self.chosen: self.lst.insert("end", places.label(a))

    def apply_options(self):
        was_on = self.api.get("enabled", False)
        self.api.set("enabled", bool(self.v_on.get()))
        self.api.set("broadcast", bool(self.v_bc.get()))
        self.api.set("areas", self.chosen)
        self.api.set("kinds", {k: bool(v.get()) for k, v in self.k_vars.items()})
        self.api.set("channels", {k: v.get().strip() or KINDS[k][1] for k, v in self.ch_vars.items()})
        self.api.set("min_level", self.v_level.get() if self.v_level.get() in src.LEVELS else "orange")
        try: self.api.set("min_mag", max(2.5, float(self.v_mag.get())))
        except ValueError: pass
        try: self.api.set("quake_radius", max(10, min(2000, int(self.v_rad.get()))))
        except ValueError: pass
        if self.v_on.get() and not was_on: self.api.set("checked_once", False)      # switched on: the first check only shows what is in force
        self.last_check = 0.0
