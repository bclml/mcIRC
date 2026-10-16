"""Area alerts: the parts that came over from the Traffic, transit and weather addon - the 'route <address>' command (by private message),
the map's 'DriveBC incidents' and 'Earthquakes' layers, the daily forecast posts, the weekly reminder, mute / unmute, and moving that
addon's settings over when it is replaced.  A mixin of the Addon class (area_alerts.py)."""
import datetime
import logging
import re
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

import aa_more as more
import aa_places as places
import aa_sources as src
import aa_traffic as traffic

ROUTE_WORDS = ("route", "directions", "gps")
ROUTE_EVERY = 120                       # seconds between two routes for the same person
TOMTOM_SIGNUP = "https://my.tomtom.com/"
ADDRESSED = re.compile(r"^@\[[^\]]*\]\s*[:,]?\s*|^@\S+[:,]\s*")
OLD = "broadcast_alerts"                # Traffic, transit and weather


class Extras:
    # ---- start: the map layers, menus, and taking over from Traffic, transit and weather ----
    def extras_load(self):
        self.route_last = {}
        self.api.add_menu_item("Mute / unmute broadcasting", self.toggle_broadcast)
        self.api.add_map_layer("DriveBC incidents", self._incidents, "#d32f2f")
        self.api.add_map_layer("Earthquakes", self._quakes, "#ef6c00")
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.route_help)
        if hasattr(self.api, "addon_settings") and not self.api.get("ttw_moved", False): self.api.after(500, self.take_over)

    def take_over(self):
        """Traffic, transit and weather was used here: its settings are added to Area alerts' (once) and it is switched off."""
        old = self.api.addon_settings(OLD)
        if self.api.addon_installed(OLD) and any(k in old for k in ("sources", "channel_lists", "muted", "weather_areas", "route_on")):
            new = more.move_settings(old, self.api.get, src_default_on(self), lambda k: self.KINDS[k][1], _make_area)
            for k, v in new.items(): self.api.set(k, v)
            self.api.set("enabled", True)
            if self.api.addon_enabled(OLD): self.api.set_addon_enabled(OLD, False)
            self.quiet_next, self.last_check = True, 0.0
            self.api.log("Traffic, transit and weather is now part of Area alerts: its settings were added here (areas, alert types, channels, "
                         "keys, route) and it was switched off. Area alerts > Settings to see them.", "info")
        self.api.set("ttw_moved", True)

    def toggle_broadcast(self):
        on = not self.api.get("broadcast", False)
        self.api.set("broadcast", on)
        self.api.log(f"Area alerts: broadcasting to the mesh {'ON' if on else 'OFF (still checking, shown on this PC)'}.", "info")

    def _incidents(self):
        now = time.time()
        return [(lat, lon, label, detail) for lat, lon, label, detail, t in list(traffic.INCIDENTS_SEEN.values()) if now - t < 1800]

    def _quakes(self): return [(lat, lon, f"M{mag:.1f} {place}") for lat, lon, mag, place in list(src.QUAKES_SEEN.values())]

    # ---- daily forecast posts and the weekly reminder (every tick) ----
    def extras_tick(self):
        now = datetime.datetime.now()
        if self.api.get("forecast_on", False):                     # its own switch on the first tab (not tied to Weather warnings)
            sent = dict(self.api.get("forecast_sent", {}))
            due = more.due_posts(now, sent)
            if due:
                for h in due: sent[str(h)] = now.date().isoformat()
                self.api.set("forecast_sent", sent)
                areas = list(self.api.get("areas", []))
                self.api.run_background(lambda: [p for h in due for a in areas for p in [_try(lambda: more.forecast(a, h, places.label(a)))] if p],
                                        self._queue_posts)
        if self.api.get("weekly_on", False) and self.api.get("broadcast", False) and self.api.connected:
            go, week = more.weekly_due(now, self.api.get("weekly_sent", ""))
            if go:
                self.api.set("weekly_sent", week)
                chans = sorted({c for c in self.channels_used()}, key=str.lower)
                for i, text in enumerate(more.weekly_texts(chans)):
                    self.api.after(i * 9000, lambda t=text: self.api.send(self.api.get("weekly_channel", "Public") or "Public", t))

    def _queue_posts(self, posts):
        if isinstance(posts, Exception) or not posts: return
        for p in posts: self.api.write(self.WINDOW, p.text)
        if self.api.get("broadcast", False): self.queue.extend(posts)
        self.drain()

    # ---- 'route <address>' by private message ----
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
            return self.api.reply(msg, f"Directions with road closures and roadwork on the way: {word} <address>  (or: {word} <from> to <to>)", private=True)
        if now - self.route_last.get(who, 0) < ROUTE_EVERY:
            return self.api.reply(msg, "One route every 2 minutes, please - try again shortly.", private=True)
        self.route_last[who] = now
        pos = self._position(msg)
        origin, age = (pos[:2], pos[2]) if pos else (None, None)
        key = self.api.get("tomtom_key", "")

        def work():
            import aa_route
            return aa_route.answer(origin, where, known=self._known_events, origin_age=age, tomtom_key=key)

        def done(r):
            if isinstance(r, Exception):           # (never the address in the log: only what kind of failure)
                logging.warning(f"route: the lookup failed ({type(r).__name__})")
                r = ["Couldn't work out the route just now - please try again in a minute."]
            get = getattr(self.api, "reply_delays", None)
            first, gap = get(node=msg.get("node")) if get else (5.0, 9.0)
            for i, part in enumerate(r[:12]):
                self.api.after(int((first + i * gap) * 1000), lambda p=part: self.api.reply(msg, p, private=True))
        self.api.run_background(work, done)

    def _known_events(self):
        """DriveBC's events from the last checks, for a route when DriveBC doesn't answer the route's own request."""
        now = time.time()
        return [{"id": str(i), "what": "CLOSED" if label.startswith("CLOSED") else "Roadwork" if label.startswith("Roadwork") else "Incident",
                 "road": label.split(": ", 1)[-1], "place": "", "points": [(lat, lon)]}
                for i, (lat, lon, label, _d, t) in list(traffic.INCIDENTS_SEEN.items()) if now - t < 1800]

    def _position(self, msg):
        """(lat, lon, seconds since that advert or None) of the asker's node (mcIRC's node memory), or None."""
        raw = msg.get("raw") if isinstance(msg.get("raw"), dict) else {}
        key = raw.get("pubkey_prefix") or ""
        row = (self.api.nodes.find_by_prefix(key) if key else None) or self.api.nodes.find_by_name((msg.get("nick") or "").lstrip("@"))
        if row and (row.get("lat") or row.get("lon")):
            heard = row.get("lastmod") or row.get("last_seen") or 0
            age = time.time() - heard if 0 < heard <= time.time() + 300 else None
            return float(row["lat"]), float(row["lon"]), age
        return None

    # ---- settings: the 'Route and more' tab ----
    def extras_page(self, page, bg):
        g = self.api.get
        self.v_route, self.v_tomtom = tk.BooleanVar(value=g("route_on", False)), tk.StringVar(value=g("tomtom_key", ""))
        self.v_week = tk.BooleanVar(value=g("weekly_on", False))
        self.v_week_ch, self.v_hour = tk.StringVar(value=g("weekly_channel", "Public")), tk.StringVar(value=str(g("per_hour", 10)))
        self.v_prefix = tk.StringVar(value=g("prefix", ""))
        tk.Checkbutton(page, text="Answer 'route <address>' by private message", variable=self.v_route, bg=bg, font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        tk.Label(page, bg=bg, fg="#555", justify="left", wraplength=560, text=(
            "Someone sends the bot a private message 'route 1234 Main St, Town' (also 'directions' / 'gps', or 'route <from> to <to>'). It answers "
            "privately: distance, time, the roads in order, and what is on the way - DriveBC closures, incidents and roadwork with their cross "
            "streets or exits (British Columbia). Asked in a channel, it never repeats the address. One route per person every 2 minutes. Free: "
            "OpenStreetMap, OSRM.")).pack(anchor="w", padx=18)
        row = tk.Frame(page, bg=bg); row.pack(anchor="w", padx=18, pady=(2, 6))
        tk.Label(row, text="TomTom key (optional, live traffic):", bg=bg).pack(side="left")
        tk.Entry(row, textvariable=self.v_tomtom, width=34, show="*").pack(side="left", padx=4)
        ttk.Button(row, text="Open the sign-up page", command=lambda: webbrowser.open(TOMTOM_SIGNUP)).pack(side="left")
        row = tk.Frame(page, bg=bg); row.pack(anchor="w", pady=(4, 0))
        tk.Checkbutton(row, text="Weekly reminder on Sundays around noon (which channels carry the alerts), in:", variable=self.v_week, bg=bg).pack(side="left")
        try:
            from gui_chanbox import channel_box
            channel_box(row, self.v_week_ch, max_items=1, empty="(Public)").pack(side="left", padx=4)
        except ImportError: tk.Entry(row, textvariable=self.v_week_ch, width=12).pack(side="left", padx=4)
        tk.Label(page, bg=bg, fg="#555", text="(Public only when Options > Display lets bots post in Public.)").pack(anchor="w", padx=18)
        row = tk.Frame(page, bg=bg); row.pack(anchor="w", pady=(6, 0))
        tk.Label(row, text="At most", bg=bg).pack(side="left")
        tk.Entry(row, textvariable=self.v_hour, width=4).pack(side="left", padx=4)
        tk.Label(row, text="messages an hour (each channel an alert goes to counts; 10 by default)", bg=bg).pack(side="left")
        row = tk.Frame(page, bg=bg); row.pack(anchor="w", pady=(6, 0))
        tk.Label(row, text="Start every alert with (optional, e.g. your group's region code '[on]'):", bg=bg).pack(side="left")
        tk.Entry(row, textvariable=self.v_prefix, width=10).pack(side="left", padx=4)

    def extras_apply(self):
        self.api.set("route_on", bool(self.v_route.get()))
        self.api.set("tomtom_key", self.v_tomtom.get().strip())
        if hasattr(self, "v_fc"): self.api.set("forecast_on", bool(self.v_fc.get()))         # (on the 'Areas and alerts' tab)
        self.api.set("weekly_on", bool(self.v_week.get()))
        self.api.set("weekly_channel", self.v_week_ch.get().strip() or "Public")
        self.api.set("prefix", self.v_prefix.get().strip()[:12])
        try: self.api.set("per_hour", max(1, min(60, int(self.v_hour.get()))))
        except ValueError: pass


def src_default_on(addon): return addon.DEFAULT_ON


def _make_area(name):
    """A Canadian area by its name (the three BC regions, or an Environment Canada weather area in any province)."""
    a = places.make("CA", "British Columbia", name)
    if a: return a
    try:
        import ec_areas
        for prov, rows in ec_areas.AREAS.items():
            if any(r[0] == name for r in rows): return places.make("CA", prov, name)
    except Exception: pass
    return None


def _try(fn):
    try: return fn()
    except Exception: return None
