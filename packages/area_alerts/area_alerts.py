"""Area alerts: natural disasters, earthquakes, tsunamis, official weather warnings, public transit service alerts and road closures for
the areas you choose - anywhere in the world (country, then region, then area).

Sources: GDACS, USGS, NOAA tsunami centres, Environment Canada, the US National Weather Service, MeteoAlarm (no key); the transit agencies
of the Mobility Database (most open, some need a free key); DriveBC (no key) and 20 other 511 road sites (free developer key each).

Off until switched on.  Switched on, alerts show in the 'Area alerts' window on this PC; they are broadcast to the mesh only with 'Broadcast
to the mesh' ticked - each alert once, at most one every 30 seconds and 10 an hour, each kind to its own channel (added to the node when
missing; never Public).  The first check after switching on only shows what is already in force.  Keys stay in this PC's settings and
never appear in messages or logs."""
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

from gui_addons import AddonBase
import aa_places as places
import aa_sources as src
import aa_traffic as traffic
import aa_transit as transit

KINDS = {"disasters": ("Natural disasters (GDACS: earthquakes, cyclones, floods, volcanoes, droughts, wildfires)", "#alerts"),
         "quakes": ("Earthquakes (USGS)", "#alerts"),
         "tsunami": ("Tsunami warnings (NOAA tsunami centres)", "#alerts"),
         "weather": ("Weather warnings (Environment Canada, US NWS, MeteoAlarm Europe)", "#weather"),
         "transit": ("Public transit: service stops and big delays (the agencies ticked on the Public transit tab)", "#transit"),
         "traffic": ("Roads: closures and incidents (DriveBC, 511 sites - see the Traffic tab)", "#traffic")}
DEFAULT_ON = ("disasters", "weather")
CHECK_EVERY = 300            # seconds between checks
GAP, PER_HOUR = 30, 10       # broadcasting limits
MAX_WAITING = 30             # alerts waiting to be broadcast; the oldest are dropped past this
WINDOW = "Area alerts"


class Addon(AddonBase):
    title = "Area alerts"
    version = "1.1.0"
    author = "mcIRC"
    description = ("Natural disasters, earthquakes, tsunamis, weather warnings, public transit alerts and road closures for the areas you "
                   "choose anywhere in the world (country, region, area). Shown on this PC; broadcast to the mesh only if you tick it. "
                   "Off until you switch it on.")
    tick_seconds = 60
    switch = "enabled"

    def on_load(self):
        self.busy, self.last_check, self.queue, self.sent_times = False, 0.0, [], []
        self.current = []                                   # [(where, Alert)] from the last check
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
        g = self.api.get
        opts = {"min_level": g("min_level", "orange"), "min_mag": float(g("min_mag", 5.0)), "radius": int(g("quake_radius", 300)),
                "keys": dict(g("keys", {})), "feeds": list(g("transit_feeds", [])), "all": bool(g("transit_all", False)),
                "road_km": int(g("traffic_km", traffic.DEFAULT_KM)), "roadwork": bool(g("roadwork", False))}

        def add(found, where, got):
            texts = {al.text for w, al in found if w == where}
            for al in got:                          # the same warning for neighbouring districts: once per place
                if al.text not in texts: found.append((where, al)); texts.add(al.text)

        def work():
            found, errors = [], []
            for a in areas:
                for kind in on:
                    if kind == "transit": continue
                    try:
                        if kind == "disasters": got = src.gdacs(a, opts["min_level"])
                        elif kind == "quakes": got = src.usgs(a, opts["min_mag"], opts["radius"])
                        elif kind == "traffic":
                            site = traffic.site_for(a)
                            got = traffic.traffic(a, opts["keys"].get(f"511:{site[0]}", "") if site else "", opts["road_km"], opts["roadwork"])
                        else: got = src.SOURCES[kind](a)
                        add(found, places.label(a), got)
                    except Exception as e:
                        errors.append(f"{kind} for {a.get('name')}: {e}")
            if "transit" in on:
                by_id = {f["id"]: f for f in transit.feeds()}
                for fid in opts["feeds"]:
                    f = by_id.get(fid)
                    if not f: continue
                    key = opts["keys"].get(f"transit:{fid}", "")
                    if f["auth"] and not key: continue
                    try: add(found, transit.label(f), transit.alerts(f, key, opts["all"]))
                    except Exception as e: errors.append(f"transit alerts of {f['provider']}: {e}")
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
        del self.queue[:-MAX_WAITING]
        self.api.set("seen", (list(seen) + [al.id for _, al in new])[-5000:])
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
        return [k for k in KINDS if saved.get(k, k in DEFAULT_ON)]

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
        tk.Label(f, bg=bg, fg="#555", wraplength=560, justify="left", text=(
            "Each alert once, at most one every 30 seconds and 10 an hour, never in Public. A channel your node doesn't have is added to it. "
            "The first check only shows what is already in force.")).pack(anchor="w", padx=18)
        self.keys = dict(g("keys", {}))
        self.key_vars = {}
        tabs = ttk.Notebook(f); tabs.pack(fill="both", expand=True, pady=4)
        pages = {}
        for name in ("Areas and alerts", "Public transit", "Traffic"):
            pages[name] = tk.Frame(tabs, bg=bg); tabs.add(pages[name], text=name)
        self._areas_page(pages["Areas and alerts"], bg)
        self.transit_page, self.traffic_page = pages["Public transit"], pages["Traffic"]
        self.feed_vars = {fid: tk.BooleanVar(value=True) for fid in g("transit_feeds", [])}
        self.v_all = tk.BooleanVar(value=g("transit_all", False))
        self.v_km, self.v_roadwork = tk.StringVar(value=str(g("traffic_km", traffic.DEFAULT_KM))), tk.BooleanVar(value=g("roadwork", False))
        self._fill_transit(); self._fill_traffic()
        return f

    def _areas_page(self, page, bg):
        g = self.api.get
        box = tk.LabelFrame(page, text="Your areas", bg=bg); box.pack(fill="x", pady=4)
        row = tk.Frame(box, bg=bg); row.pack(fill="x", padx=4, pady=2)
        self._countries = places.countries()
        self.c_box = ttk.Combobox(row, values=[n for n, _ in self._countries], state="readonly", width=22)
        self.r_box = ttk.Combobox(row, state="readonly", width=22)
        self.a_box = ttk.Combobox(row, state="readonly", width=26)
        for w, lab in ((self.c_box, "Country"), (self.r_box, "Region"), (self.a_box, "Area")):
            tk.Label(row, text=lab + ":", bg=bg).pack(side="left"); w.pack(side="left", padx=(2, 8))
        self.c_box.bind("<<ComboboxSelected>>", lambda e: self._fill_regions())
        self.r_box.bind("<<ComboboxSelected>>", lambda e: self._fill_areas())
        row2 = tk.Frame(box, bg=bg); row2.pack(fill="x", padx=4, pady=2)
        self.chosen = list(g("areas", []))
        self.lst = tk.Listbox(row2, height=4, width=70)
        self.lst.pack(side="left", fill="x", expand=True)
        b = tk.Frame(row2, bg=bg); b.pack(side="left", padx=4)
        ttk.Button(b, text="Add area", command=self._add).pack(fill="x")
        ttk.Button(b, text="Remove", command=self._remove).pack(fill="x", pady=2)
        self._fill_list()

        kinds = tk.LabelFrame(page, text="Alert kinds, and the channel each goes to", bg=bg); kinds.pack(fill="x", pady=4)
        saved, chans = g("kinds", {}), g("channels", {})
        self.k_vars, self.ch_vars = {}, {}
        for i, (k, (title, default_ch)) in enumerate(KINDS.items()):
            self.k_vars[k] = tk.BooleanVar(value=saved.get(k, k in DEFAULT_ON))
            self.ch_vars[k] = tk.StringVar(value=chans.get(k, default_ch))
            tk.Checkbutton(kinds, text=title, variable=self.k_vars[k], bg=bg, anchor="w").grid(row=i, column=0, sticky="w")
            tk.Entry(kinds, textvariable=self.ch_vars[k], width=12).grid(row=i, column=1, padx=4)
        opt = tk.Frame(page, bg=bg); opt.pack(fill="x", pady=2)
        self.v_level = tk.StringVar(value=g("min_level", "orange"))
        self.v_mag, self.v_rad = tk.StringVar(value=str(g("min_mag", 5.0))), tk.StringVar(value=str(g("quake_radius", 300)))
        tk.Label(opt, text="GDACS from level:", bg=bg).pack(side="left")
        ttk.Combobox(opt, textvariable=self.v_level, values=src.LEVELS, state="readonly", width=7).pack(side="left", padx=(2, 10))
        tk.Label(opt, text="Earthquakes from magnitude", bg=bg).pack(side="left")
        tk.Entry(opt, textvariable=self.v_mag, width=4).pack(side="left", padx=2)
        tk.Label(opt, text="within km", bg=bg).pack(side="left")
        tk.Entry(opt, textvariable=self.v_rad, width=5).pack(side="left", padx=2)
        tk.Label(page, bg=bg, fg="#555", wraplength=560, justify="left", text=(
            "Sources (free, no key): GDACS (UN / EU JRC), USGS, NOAA tsunami warning centres, Environment Canada, the US National Weather "
            "Service, MeteoAlarm. Places: GeoNames (CC BY 4.0). Official weather warnings are available for Canada, the US and 38 European "
            "countries; natural disasters and earthquakes everywhere.")).pack(anchor="w", pady=(4, 0))

    def _key_row(self, parent, bg, slot, help_text, url):
        """'How to get a free key' in plain words, a button opening the sign-up page, and the box for the key."""
        tk.Label(parent, text=help_text, bg=bg, fg="#8a4b00", wraplength=520, justify="left").pack(anchor="w", padx=22)
        row = tk.Frame(parent, bg=bg); row.pack(anchor="w", padx=22, pady=(0, 4))
        var = self.key_vars.get(slot) or tk.StringVar(value=self.keys.get(slot, ""))
        self.key_vars[slot] = var
        tk.Label(row, text="Free key:", bg=bg).pack(side="left")
        tk.Entry(row, textvariable=var, width=40, show="*").pack(side="left", padx=4)
        if url: ttk.Button(row, text="Open the sign-up page", command=lambda: webbrowser.open(url)).pack(side="left")

    def _scrolled(self, page, bg):
        for w in page.winfo_children(): w.destroy()
        canvas = tk.Canvas(page, bg=bg, highlightthickness=0, height=300)
        bar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=bg)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw"); canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True); bar.pack(side="right", fill="y")
        return inner

    def _fill_transit(self):
        bg = self.transit_page["bg"]
        inner = self._scrolled(self.transit_page, bg)
        tk.Label(inner, bg=bg, wraplength=560, justify="left", text=(
            "The transit agencies serving your areas (from the Mobility Database). Tick the ones to follow. Alerts in force now; by default "
            "only service stops and big delays.")).pack(anchor="w")
        tk.Checkbutton(inner, text="All their alerts (detours, stop changes, lifts out of service ... - many)", variable=self.v_all, bg=bg).pack(anchor="w")
        seen = set()
        for a in self.chosen:
            feeds = [f for f in transit.feeds_for(a) if f["id"] not in seen]
            if not feeds: continue
            tk.Label(inner, text=places.label(a), bg=bg, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(6, 0))
            for f in feeds:
                seen.add(f["id"])
                var = self.feed_vars.setdefault(f["id"], tk.BooleanVar(value=False))
                tk.Checkbutton(inner, text=transit.label(f) + ("   (free key needed)" if f["auth"] else ""), variable=var, bg=bg).pack(anchor="w", padx=10)
                if f["auth"]: self._key_row(inner, bg, f"transit:{f['id']}", transit.key_help(f), f["info"])
        if not seen:
            tk.Label(inner, bg=bg, fg="#555", wraplength=560, justify="left", text=(
                "No transit alert feed is known for your areas yet (add areas on the first tab). The Mobility Database lists the agencies "
                "that publish one: mobilitydatabase.org.")).pack(anchor="w", pady=6)

    def _fill_traffic(self):
        bg = self.traffic_page["bg"]
        inner = self._scrolled(self.traffic_page, bg)
        tk.Label(inner, bg=bg, wraplength=560, justify="left", text=(
            "Road closures, crashes and incidents near your areas. British Columbia: DriveBC, no key. 20 other provinces, territories and "
            "US states: their 511 site, each needs a free developer key.")).pack(anchor="w")
        row = tk.Frame(inner, bg=bg); row.pack(anchor="w", pady=2)
        tk.Label(row, text="Within km of each area:", bg=bg).pack(side="left")
        tk.Entry(row, textvariable=self.v_km, width=5).pack(side="left", padx=4)
        tk.Checkbutton(inner, text="Roadwork too (only full closures otherwise)", variable=self.v_roadwork, bg=bg).pack(anchor="w")
        sites = set()
        for a in self.chosen:
            tk.Label(inner, text=f"{places.label(a)}: {traffic.available(a)}", bg=bg, anchor="w").pack(anchor="w", pady=(6, 0))
            site = traffic.site_for(a)
            if site and site[0] not in sites:
                sites.add(site[0])
                self._key_row(inner, bg, f"511:{site[0]}", traffic.key_help(site),
                              f"https://{site[0]}{site[2]}" if site[2] else f"https://{site[0]}/my511/register")
        if not self.chosen: tk.Label(inner, text="Add areas on the first tab.", bg=bg, fg="#555").pack(anchor="w", pady=6)

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
            self.chosen.append(a); self._areas_changed()

    def _remove(self):
        for i in reversed(self.lst.curselection()): del self.chosen[i]
        self._areas_changed()

    def _areas_changed(self):
        self._fill_list()
        if hasattr(self, "transit_page"): self._fill_transit(); self._fill_traffic()

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
        self.api.set("transit_feeds", [fid for fid, v in self.feed_vars.items() if v.get()])
        self.api.set("transit_all", bool(self.v_all.get()))
        try: self.api.set("traffic_km", max(5, min(300, int(self.v_km.get()))))
        except ValueError: pass
        self.api.set("roadwork", bool(self.v_roadwork.get()))
        keys = dict(self.keys)
        keys.update({slot: v.get().strip() for slot, v in self.key_vars.items()})
        self.api.set("keys", {k: v for k, v in keys.items() if v})
        if self.v_on.get() and not was_on: self.api.set("checked_once", False)      # switched on: the first check only shows what is in force
        self.last_check = 0.0
