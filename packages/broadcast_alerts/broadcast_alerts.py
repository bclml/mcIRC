"""Traffic, transit and weather addon: DriveBC, BC Ferries, BC Transit, TransLink, weather, earthquake and tsunami feeds
broadcast to the mesh, plus the weekly reminder.  Has a master mute and a switch per source.
The chat GUI works fine with this addon disabled (Tools > Addons)."""
import gui_platform
import asyncio, logging, os, re, threading, time
import tkinter as tk
from tkinter import ttk

import emergency_agent as ea
import meshcore_io as io
from gui_addons import AddonBase


CHANNEL_KINDS = ("DriveBC", "BC Ferries", "BC Transit", "TransLink", "Weather")
ROUTE_WORDS = ("route", "directions", "gps")                 # 'route <address>' by private message
ROUTE_EVERY = 120                                            # seconds between two route answers to the same person
TOMTOM_SIGNUP = "https://my.tomtom.com/"   # free key for live traffic on routes (optional)
ADDRESSED = re.compile(r"^@\[[^\]]*\]\s*[:,]?\s*|^@\S+[:,]\s*")


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
    replies = True                         # ('route' answers people: the settings window offers the answer wait)
    version = "1.6.4"
    author = "built in"
    description = ("Traffic / ferry / transit / weather / earthquake / tsunami alerts. Keeps the map's DriveBC and earthquake layers up to date; "
                   "broadcasting them to the mesh is OFF until you switch it on.")

    def on_load(self):
        self.route_last = {}
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.route_help)
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

    # ---- 'route <address>': directions with DriveBC closures, incidents and roadwork on the way - by private message only ----
    def route_help(self, channel, dm=False):
        return ["route <address> (private message)"] if self.api.get("route_on", False) else []

    def _route_words(self, text):
        t = ADDRESSED.sub("", (text or "").strip(), count=1)
        if t[:1] in "!/.": t = t[1:]
        word, _, rest = t.partition(" ")
        return (word.lower(), rest.strip()) if word.lower() in ROUTE_WORDS else (None, "")

    def on_message(self, msg):
        if not self.api.get("route_on", False): return
        word, where = self._route_words(msg.get("text"))
        if not word: return
        who, now = msg.get("nick", "?"), time.time()
        if not msg.get("dm"):                   # never answer a destination in a channel - nor repeat it: only how to ask privately
            if where and now - self.route_last.get(("hint", who), 0) > ROUTE_EVERY:
                self.route_last[("hint", who)] = now
                self.api.reply(msg, f"Send it to me by private message instead: {word} <address> - so your destination stays private.", private=True)
            return
        if not where:
            return self.api.reply(msg, f"Directions with DriveBC closures and roadwork on the way: {word} <address>  (or: {word} <from> to <to>)", private=True)
        if now - self.route_last.get(who, 0) < ROUTE_EVERY:
            return self.api.reply(msg, "One route every 2 minutes, please - try again shortly.", private=True)
        self.route_last[who] = now
        pos = self._position(msg)
        origin, age = (pos[:2], pos[2]) if pos else (None, None)

        def work():
            import traffic_route
            return traffic_route.answer(origin, where, known=self._known_events, origin_age=age, tomtom_key=self.api.get("tomtom_key", ""))

        def done(r):
            if isinstance(r, Exception):           # (never the address in the log: only what kind of failure)
                logging.warning(f"route: the lookup failed ({type(r).__name__})")
                r = ["Couldn't work out the route just now - please try again in a minute."]
            get = getattr(self.api, "reply_delays", None)
            first, gap = get(node=msg.get("node")) if get else (5.0, 9.0)
            for i, part in enumerate(r[:12]):         # route, via, everything on the way, start
                self.api.after(int((first + i * gap) * 1000), lambda p=part: self.api.reply(msg, p, private=True))
        self.api.run_background(work, done)

    def _known_events(self):
        """The DriveBC events the traffic check is tracking (its areas), for a route when DriveBC doesn't answer the route's own request."""
        out = []
        for k, val in list(ea.active_traffic_alerts.items()):
            loc = ea.ALERT_LOCATIONS.get(k)
            src, title = val if isinstance(val, tuple) and len(val) == 2 else ("", str(val))
            if not loc or src != "DriveBC": continue
            text = str(title)
            what = "CLOSED" if re.search(r"closed|closure", text, re.I) else "Roadwork" if re.search(r"construction|roadwork", text, re.I) else "Incident"
            road = re.sub(r"^(?:INCIDENT|CONSTRUCTION|ROAD_CONDITION|SPECIAL_EVENT)\s*-\s*", "", text, flags=re.I)[:30]
            out.append({"id": str(k), "what": what, "road": road, "place": "", "points": [(loc[0], loc[1])]})
        return out

    def _position(self, msg):
        """(lat, lon, seconds since that advert or None) of the asker's node from its advert (mcIRC's node memory), or None.  The age
        goes by lastmod - stamped by YOUR node's clock when it heard the advert (the advert's own time is often wrong)."""
        raw = msg.get("raw") if isinstance(msg.get("raw"), dict) else {}
        key = raw.get("pubkey_prefix") or ""
        row = (self.api.nodes.find_by_prefix(key) if key else None) or self.api.nodes.find_by_name((msg.get("nick") or "").lstrip("@"))
        if row and (row.get("lat") or row.get("lon")):
            heard = row.get("lastmod") or row.get("last_seen") or 0
            age = time.time() - heard if 0 < heard <= time.time() + 300 else None
            return float(row["lat"]), float(row["lon"]), age
        return None

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
        was_used = any(g(k, None) is not None for k in ("sources", "muted", "weather_areas", "weekly_opt_in", "translink_key"))   # (before anything is saved below)
        ea.TX["muted"] = g("muted", True)         # broadcasting is OFF unless the user turned it on (an existing "muted" setting is kept)
        saved = g("sources", {})
        if not g("weekly_opt_in", False) and saved.get("Weekly reminder", True):      # the Sunday reminder on Public is opt-in now (it was on by default)
            saved = dict(saved, **{"Weekly reminder": False})
            self.api.set("sources", saved)
            self.api.set("weekly_opt_in", True)
        for k in self.SOURCES: ea.TX["sources"][k] = saved.get(k, k != "Weekly reminder")
        ea.USE_SCOPES = g("use_scopes", False)
        ea.REGION_SCOPES = {"Lower Mainland": g("scope_lm", ""), "Vancouver Island": g("scope_vi", ""), "Sunshine Coast": g("scope_sc", "")}
        if hasattr(ea, "CHANNEL_LISTS"):                          # the channels per kind (Channels tab); blank = not sent
            lists = g("channel_lists", None)
            if not g("channels_v2", False):                       # 1.4 and older: built-in channels, only changes saved - an install that was
                used = was_used                                   # in use
                old = dict(lists or {})                           # keeps them; a new one starts blank (each station chooses its own)
                lists = {k: old.get(k) or (("#" + (ea.WEATHER_CHANNEL_NAME if k == "Weather" else ea.CHANNEL_NAMES[k])) if used else "")
                         for k in CHANNEL_KINDS}
                self.api.set("channel_lists", lists)
                self.api.set("channels_v2", True)
            lists = lists or {}
            ea.CHANNEL_LISTS = {k: split_channels(lists.get(k, "")) for k in CHANNEL_KINDS}
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
        alerts, areas, chans, route, accounts = (tk.Frame(nb, bg=bg, padx=8, pady=6) for _ in range(5))
        nb.add(alerts, text="Alerts")
        nb.add(areas, text="Weather areas")
        nb.add(chans, text="Channels")
        nb.add(route, text="Route")
        nb.add(accounts, text="Accounts & scopes")
        self._areas_page(areas, bg)
        self._channels_page(chans, bg)
        self.route_var = tk.BooleanVar(value=bool(self.api.get("route_on", False)))
        tk.Checkbutton(route, text="Answer 'route <address>' by private message", variable=self.route_var, bg=bg,
                       font=(gui_platform.UI_FONT_NAME, gui_platform.UI_FONT_SIZE, "bold")).pack(anchor="w")
        tk.Label(route, bg=bg, fg="#555", justify="left", wraplength=420, text=(
            "Someone sends the bot a private message 'route 1234 Main St, Town' (also 'directions' / 'gps'). The bot finds the address, "
            "drives the route from the position their node advertises (or 'route <from> to <to>'), checks DriveBC's closures, incidents and "
            "roadwork on the way (British Columbia), and answers privately: distance, time, main roads and what is on the way.\n\n"
            "The quickest route is taken; when routes take about as long, the one with fewer incidents and roadwork. A road closed on the "
            "way is avoided while another route is open. Times are without live congestion - unless you add a TomTom key below.\n\n"
            "Private only: asked in a channel, the bot never repeats the address - it only says to ask by private message. Addresses are "
            "never written to the logs. One route per person every 2 minutes. Free services, no key: OpenStreetMap (addresses) and OSRM "
            "(routes).")).pack(anchor="w", pady=(4, 0))
        box = tk.LabelFrame(route, text="Live traffic (optional): a free TomTom key", bg=bg, padx=6, pady=4)
        box.pack(fill="x", pady=(8, 0))
        tk.Label(box, bg=bg, fg="#8a4b00", justify="left", wraplength=400, text=(
            "With a key, each route's time includes the slow traffic on it now ('~30 min (+5 min traffic now)'), a jam can make another "
            "route the quickest, and the jams on the way are named ('Slow Hwy 1 near Langley 4 km +6 min') - outside BC too. The free "
            "plan allows 2,500 lookups a day; each route uses one.\n"
            "1. Open the sign-up page and register a free account (no credit card).  2. Open your app and copy its API key (not the App ID with dashes).  3. Paste it here, OK.\n"
            "The start and destination are then also sent to TomTom. Leave it empty to stay with the free services above.")).pack(anchor="w")
        row = tk.Frame(box, bg=bg); row.pack(anchor="w", pady=(4, 0))
        self.tomtom_var = tk.StringVar(value=self.api.get("tomtom_key", ""))
        tk.Label(row, text="TomTom key:", bg=bg).pack(side="left")
        tk.Entry(row, textvariable=self.tomtom_var, width=36, show="*").pack(side="left", padx=4)
        import webbrowser
        ttk.Button(row, text="Open the sign-up page", command=lambda: webbrowser.open(TOMTOM_SIGNUP)).pack(side="left")

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
        saved = self.api.get("channel_lists", {}) or {}
        self.chan_vars = {}
        tk.Label(page, bg=bg, fg="#555", justify="left", wraplength=420, text=(
            "The channels each kind of alert goes to. Blank: that kind is not broadcast. Choose channels your own group uses - if every "
            "station sent to the same channel, the same alert would go out many times. More than one: separate them with commas, e.g. "
            "'#traffic-mygroup, #mcirc' (each is one more transmission). Never Public. A channel your node doesn't have is added to it "
            "when broadcasting.")).pack(anchor="w")
        grid = tk.Frame(page, bg=bg); grid.pack(anchor="w", pady=6)
        for i, kind in enumerate(CHANNEL_KINDS):
            self.chan_vars[kind] = tk.StringVar(value=saved.get(kind, ""))
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
            lists = {kind: ", ".join("#" + n for n in split_channels(var.get())) for kind, var in self.chan_vars.items()}
            self.api.set("channel_lists", lists)
            self.api.set("channels_v2", True)
            if self.broadcast.get() and not any(lists.values()) and hasattr(self.api, "notice"):
                self.api.notice("Traffic, transit and weather: broadcasting is on, but no channel is chosen (Settings > Channels) - nothing "
                                "will be sent until you choose one.", "warn")
        if getattr(self, "route_var", None) is not None: self.api.set("route_on", bool(self.route_var.get()))
        if getattr(self, "tomtom_var", None) is not None:
            key = self.tomtom_var.get().strip()
            self.api.set("tomtom_key", key)
            if re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", key) and hasattr(self.api, "notice"):
                self.api.notice("Traffic, transit and weather: that TomTom key looks like the App ID (with dashes). Paste the app's API key "
                                "instead (letters and digits, no dashes) - TomTom refuses the App ID.", "warn")
        self.api.set("muted", not self.broadcast.get())
        self.api.set("sources", {k: var.get() for k, var in self.src.items()})
        self.apply_settings()
        self._mode_changed()
        self._refresh_button()
