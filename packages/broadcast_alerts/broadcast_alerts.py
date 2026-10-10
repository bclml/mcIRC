"""Traffic, transit and weather addon: DriveBC, BC Ferries, BC Transit, TransLink, weather, earthquake and tsunami feeds
broadcast to the mesh, plus the weekly reminder.  Has a master mute and a switch per source.
The chat GUI works fine with this addon disabled (Tools > Addons)."""
import gui_platform
import asyncio, logging, os, re, threading
import tkinter as tk
from tkinter import ttk

import emergency_agent as ea
import meshcore_io as io
from gui_addons import AddonBase


CHANNEL_KINDS = ("DriveBC", "BC Ferries", "BC Transit", "TransLink", "Weather")


def split_channels(text):
    """'#weather, #mcirc' / 'weather mcirc' -> ['weather', 'mcirc']: each once, never Public."""
    out = []
    for n in re.split(r"[,;\s]+", text or ""):
        n = n.strip().lstrip("#").lower()
        if n and n != "public" and n not in out: out.append(n)
    return out


class Addon(AddonBase):
    # (The "test" auto-reply is its own addon now: Auto reply.)
    SOURCES = [k for k in ea.TX_SOURCES if k != "Test reply"]   # alert types with a switch on the Alerts tab
    title = "Traffic, transit and weather"
    version = "1.4.0"
    author = "built in"
    description = ("Traffic / ferry / transit / weather / earthquake / tsunami alerts. Keeps the map's DriveBC and earthquake layers up to date; "
                   "broadcasting them to the mesh is OFF until you switch it on.")

    def on_load(self):
        self.thread = self.loop = None
        self.tasks = []
        self.apply_settings()
        self.button = self.api.add_toolbar_button("", self.toggle_mute)
        self._refresh_button()
        self.api.add_command("mute", lambda a: self.set_muted(True), "stop ALL transmitting by the broadcast addon, tsunami included")
        self.api.add_command("unmute", lambda a: self.set_muted(False), "resume broadcasting")
        self.api.add_menu_item("Mute / unmute broadcasting", self.toggle_mute)
        self.api.add_menu_item("Active alerts...", self.show_active)
        self.api.add_map_layer("DriveBC incidents", self._incidents, "#d32f2f")
        self.api.add_map_layer("Earthquakes", self._quakes, "#ef6c00")
        if ea.TX["muted"]: self._start_feeds()       # map-only mode needs no radio: read the feeds right away

    def on_unload(self):
        self._stop_feeds()
        for k in ea.TX["sources"]: ea.TX["sources"][k] = True  # leave the console agent defaults behind
        ea.TX["muted"] = False

    def _start_feeds(self):
        if self.thread and self.thread.is_alive(): return
        ea.reload_active_alerts_from_log()
        ea.reload_critical_alert_ids_from_log()
        if hasattr(ea, "reload_weekly_ad_from_log"): ea.reload_weekly_ad_from_log()      # restarts never repeat the weekly reminder
        self._stop_req = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def on_connect(self): self._start_feeds()

    def on_disconnect(self):
        if not ea.TX["muted"]: self._stop_feeds()      # broadcasting needs the radio; map-only mode keeps reading the feeds

    def _mode_changed(self):
        """After broadcasting was switched on or off."""
        if ea.TX["muted"]:
            io.PENDING_SENDS.clear()                  # nothing queued earlier may go out now
            self._start_feeds()
        elif not self.api.connected:
            self._stop_feeds()                        # broadcasting without a radio is pointless

    def on_demo(self):
        ea.active_traffic_alerts.update({"DriveBC|d1": ("DriveBC", "x"), "DriveBC|d2": ("DriveBC", "x")})
        ea.ALERT_LOCATIONS.update({"DriveBC|d1": (49.245, -122.969, "INCIDENT - Highway 1 (Westbound, Burnaby)"),
                                   "DriveBC|d2": (49.139, -122.84, "INCIDENT - Highway 15 (Southbound, Surrey)")})
        ea.EARTHQUAKE_EVENTS.append((48.9, -126.1, 4.8, "130 km W of Tofino, Canada"))
        for idx, text, alert in ((3, "\U0001F6A8 NEW [DriveBC]: INCIDENT - Highway 1 (Westbound, Burnaby) - Kensington Ave. Closed.", "new"),
                                 (3, "\u2705 CLEARED [DriveBC]: INCIDENT - Highway 17 (Northbound, Delta)", "clear"),
                                 (4, "\U0001F6A8 NEW [BC Ferries]: Tsawwassen - Swartz Bay: Queen of Alberni running ~25 min late", "new"),
                                 (0, "\U0001F30E EARTHQUAKE M4.8: 130 km W of Tofino, Canada, 10km deep", "critical")):
            ea._emit("out", idx, text, alert=alert)

    # ---- feeds ----
    def _run(self):
        async def main():
            self.loop = asyncio.get_running_loop()
            if getattr(self, "_stop_req", False): return          # stopped before the feeds even began
            self.tasks = [asyncio.ensure_future(c()) for c in (ea.traffic_loop, ea.weather_loop)]
            await asyncio.gather(*self.tasks, return_exceptions=True)
        try: asyncio.run(main())
        except Exception as e: logging.error(f"Broadcast feeds stopped: {e}")
        self.loop = None

    def _stop_feeds(self):
        self._stop_req = True
        loop = self.loop
        if loop is None: return
        try: loop.call_soon_threadsafe(lambda: [t.cancel() for t in self.tasks])
        except RuntimeError: pass          # the feeds' loop had just finished on its own: nothing left to stop

    # ---- settings / mute ----
    def apply_settings(self):
        g = self.api.get
        ea.TX["muted"] = g("muted", True)         # broadcasting is OFF unless the user turned it on (an existing "muted" setting is kept)
        saved = g("sources", {})
        if not g("weekly_opt_in", False) and saved.get("Weekly reminder", True):      # the Sunday reminder on Public is opt-in now (it was on by default)
            saved = dict(saved, **{"Weekly reminder": False})
            self.api.set("sources", saved)
            self.api.set("weekly_opt_in", True)
        for k in self.SOURCES: ea.TX["sources"][k] = saved.get(k, k != "Weekly reminder")
        ea.USE_SCOPES = g("use_scopes", False)
        ea.REGION_SCOPES = {"Lower Mainland": g("scope_lm", ""), "Vancouver Island": g("scope_vi", ""), "Sunshine Coast": g("scope_sc", "")}
        if hasattr(ea, "CHANNEL_LISTS"):                          # more than one channel per kind (Channels tab)
            ea.CHANNEL_LISTS = {k: split_channels(v) for k, v in g("channel_lists", {}).items() if split_channels(v)}
        ea.TRANSLINK_API_KEY = g("translink_key", "").strip() or os.environ.get("TRANSLINK_API_KEY", "").strip() or None
        if hasattr(ea, "set_weather_areas"):                      # which areas' Environment Canada warnings and forecasts are watched
            import ec_areas
            ea.set_weather_areas(g("weather_areas", list(ec_areas.DEFAULT_AREAS)))

    def set_muted(self, muted):
        self.api.set("muted", muted)
        self.apply_settings()
        self._refresh_button()
        self._mode_changed()
        self.api.log("Broadcasting is OFF - the map keeps updating, nothing is transmitted (tsunami and earthquake included)" if muted else "Broadcasting is ON",
                     "info" if muted else "warn")

    def toggle_mute(self): self.set_muted(not ea.TX["muted"])

    def active_text(self):
        """What the bot counts as active right now (announced and not cleared yet) - after a restart it is read back from its log."""
        lines = [f"[{src}] {title}" for src, title in sorted(set(ea.active_traffic_alerts.values()) | set(ea.active_weather_alerts.values()))]
        state = "map only - nothing is broadcast" if ea.TX["muted"] else "BROADCASTING"
        return (f"Traffic, transit and weather: {state}.  {len(lines)} active alert(s):\n\n" + "\n".join(lines)) if lines else f"Traffic, transit and weather: {state}.  No active alerts."

    def show_active(self):
        show = getattr(self.api, "show_text", None)
        if show: show("Traffic, transit and weather - active alerts", self.active_text)
        else: self.api.notice(self.active_text())

    def _refresh_button(self):
        muted = ea.TX["muted"]
        self.button.config(text="Traffic, transit and weather: map only" if muted else "Traffic, transit and weather: BROADCASTING", fg="#555555" if muted else "#006400")

    # ---- map layers ----
    def _incidents(self):
        out = []
        for k in list(ea.active_traffic_alerts):
            loc = ea.ALERT_LOCATIONS.get(k)
            if not loc: continue
            label, detail = ea.ALERT_MAPINFO.get(k, (loc[2], loc[2]))
            out.append((loc[0], loc[1], label, detail))
        return out

    def _quakes(self): return [(lat, lon, f"M{mag:.1f} {place}") for lat, lon, mag, place in list(ea.EARTHQUAKE_EVENTS)]

    # ---- Options page ----
    def build_options(self, parent):
        g = self.api.get
        f = tk.Frame(parent, bg=parent["bg"])
        self.v = {"translink_key": tk.StringVar(value=g("translink_key", "")),
                  "use_scopes": tk.BooleanVar(value=g("use_scopes", False)),
                  "scope_lm": tk.StringVar(value=g("scope_lm", "")), "scope_vi": tk.StringVar(value=g("scope_vi", "")),
                  "scope_sc": tk.StringVar(value=g("scope_sc", ""))}
        saved = g("sources", {})
        self.src = {k: tk.BooleanVar(value=saved.get(k, k != "Weekly reminder")) for k in self.SOURCES}
        self.broadcast = tk.BooleanVar(value=not g("muted", True))
        bg = parent["bg"]
        tk.Label(f, text="Traffic, transit and weather", bg=bg, font=(gui_platform.DIALOG_FONT_NAME, 9, "bold")).pack(anchor="w")
        nb = ttk.Notebook(f)
        nb.pack(fill="both", expand=True, pady=4)
        alerts, areas, chans, accounts = (tk.Frame(nb, bg=bg, padx=8, pady=6) for _ in range(4))
        nb.add(alerts, text="Alerts")
        nb.add(areas, text="Weather areas")
        nb.add(chans, text="Channels")
        nb.add(accounts, text="Accounts & scopes")
        self._areas_page(areas, bg)
        self._channels_page(chans, bg)

        tk.Checkbutton(alerts, text="Broadcast alerts to the mesh (this transmits on your radio)", variable=self.broadcast, bg=bg, wraplength=400, justify="left", anchor="w",
                       font=(gui_platform.UI_FONT_NAME, gui_platform.UI_FONT_SIZE, "bold")).pack(anchor="w")
        tk.Label(alerts, text="OFF (the default): the addon still reads the feeds and keeps the map's DriveBC incident and earthquake layers up to date - nothing is "
                              "transmitted, tsunami and earthquake included, and no radio is needed.\nTip: if other stations in range broadcast the same alerts, leave this off or untick "
                              "the alert types you do not need, so identical messages do not jam the mesh during an emergency.", bg=bg, fg="#555", justify="left", wraplength=400).pack(anchor="w", padx=18, pady=2)
        box = tk.LabelFrame(alerts, text="Alert types to send (when broadcasting is on)", bg=bg)
        box.pack(fill="x", pady=6)
        for i, k in enumerate(self.SOURCES):
            tk.Checkbutton(box, text=k, variable=self.src[k], bg=bg, anchor="w").grid(row=i // 3, column=i % 3, sticky="w", padx=6)

        def row(parent_, label, key, width, show=""):
            r = tk.Frame(parent_, bg=bg)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=label, bg=bg, width=24, anchor="w").pack(side="left")
            tk.Entry(r, textvariable=self.v[key], show=show, width=width).pack(side="left")

        row(accounts, "TransLink API key:", "translink_key", 26, "*")
        for label, key in (("Scope  Lower Mainland:", "scope_lm"), ("Scope  Vancouver Island:", "scope_vi"), ("Scope  Sunshine Coast:", "scope_sc")): row(accounts, label, key, 10)
        tk.Checkbutton(accounts, text="Prefix alerts with region scope codes", variable=self.v["use_scopes"], bg=bg).pack(anchor="w", pady=4)
        return f

    def _channels_page(self, page, bg):
        """The channels each kind of alert goes to: one or more, separated by commas."""
        saved = self.api.get("channel_lists", {})
        self.chan_vars = {}
        tk.Label(page, bg=bg, fg="#555", justify="left", wraplength=420, text=(
            "Each kind of alert can go to more than one channel - separate them with commas, e.g. '#weather, #mcirc'. The first is its own "
            "channel; every alert is also sent once to the others (one more transmission each). Never Public. A channel your node doesn't "
            "have is added to it when broadcasting.")).pack(anchor="w")
        grid = tk.Frame(page, bg=bg); grid.pack(anchor="w", pady=6)
        for i, kind in enumerate(CHANNEL_KINDS):
            default = "#" + (ea.WEATHER_CHANNEL_NAME if kind == "Weather" else ea.CHANNEL_NAMES[kind])
            self.chan_vars[kind] = tk.StringVar(value=saved.get(kind, default))
            tk.Label(grid, text=kind + ":", bg=bg, width=12, anchor="w").grid(row=i, column=0, sticky="w")
            tk.Entry(grid, textvariable=self.chan_vars[kind], width=36).grid(row=i, column=1, sticky="w", pady=2)

    def _areas_page(self, page, bg):
        """Province / territory, then its areas: the Environment Canada warnings (and daily forecasts) the bot watches."""
        import ec_areas
        self.area_vars = {}
        chosen = set(self.api.get("weather_areas", list(ec_areas.DEFAULT_AREAS)))
        tk.Label(page, bg=bg, fg="#555", justify="left", wraplength=420, text=(
            "Weather warnings (and the 6 AM / 8 AM forecasts) for the areas ticked here go to #weather. Pick a province or territory, then tick "
            "its areas - about the size of the Lower Mainland each. Ticks in other provinces are kept.")).pack(anchor="w")
        top = tk.Frame(page, bg=bg); top.pack(fill="x", pady=4)
        tk.Label(top, text="Province / territory:", bg=bg).pack(side="left")
        prov = ttk.Combobox(top, values=list(ec_areas.AREAS), state="readonly", width=28)
        prov.pack(side="left", padx=4)
        self.areas_count = tk.Label(top, bg=bg, fg="#555")
        self.areas_count.pack(side="left", padx=6)
        box = tk.Frame(page, bg=bg); box.pack(fill="both", expand=True)
        for p, areas in ec_areas.AREAS.items():
            for a in areas: self.area_vars[a[0]] = tk.BooleanVar(value=a[0] in chosen)

        def count():
            n = sum(v.get() for v in self.area_vars.values())
            self.areas_count.config(text=f"{n} area{'s' if n != 1 else ''} ticked in all")

        def show(_=None):
            for w in box.winfo_children(): w.destroy()
            for i, a in enumerate(ec_areas.AREAS[prov.get()]):
                tk.Checkbutton(box, text=a[0], variable=self.area_vars[a[0]], bg=bg, anchor="w", command=count).grid(row=i // 2, column=i % 2, sticky="w", padx=4)
        prov.bind("<<ComboboxSelected>>", show)
        first = next((p for p, areas in ec_areas.AREAS.items() if any(a[0] in chosen for a in areas)), "British Columbia")
        prov.set(first); show(); count()

    def apply_options(self):
        for k, var in self.v.items(): self.api.set(k, var.get())
        if getattr(self, "area_vars", None):
            import ec_areas
            self.api.set("weather_areas", [a[0] for areas in ec_areas.AREAS.values() for a in areas if self.area_vars[a[0]].get()])
        if getattr(self, "chan_vars", None):
            lists = {}
            for kind, var in self.chan_vars.items():
                names = split_channels(var.get())
                default = ea.WEATHER_CHANNEL_NAME if kind == "Weather" else ea.CHANNEL_NAMES[kind]
                if names and names != [default]: lists[kind] = ", ".join("#" + n for n in names)
            self.api.set("channel_lists", lists)
        self.api.set("muted", not self.broadcast.get())
        self.api.set("sources", {k: var.get() for k, var in self.src.items()})
        self.apply_settings()
        self._mode_changed()
        self._refresh_button()
