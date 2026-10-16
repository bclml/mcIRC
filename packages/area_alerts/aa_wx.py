"""Area alerts: the weather commands that came over from the Weather bot (2026.10.16) - wx <place>, gwx, aqi, sun, moon, solar, sf, hfcond,
satpass, airplanes, rain, aurora, channels, status, contact - answered in the channels you choose, and the optional rain warning.  Its
settings are 'wx_...' (they don't mix with the alerts' own 'enabled' / 'channels'); the Weather bot's are added here once (take_over_wx).
A mixin of the Addon class (area_alerts.py).  Off until 'Answer weather commands' is ticked; every answer is rate-limited, nothing is sent
unless somebody asks (the rain warning is a separate opt-in)."""
import os
import time
import tkinter as tk

from gui_addons import BASE_DIR
import meshbot_common as mc
import wxbot_sky as sky
import wxbot_sources as ws

COMMANDS = {        # command: what it does
    "wx": "weather and forecast for a place, or where you are (NOAA in the US, Open-Meteo elsewhere)",
    "gwx": "weather for a place from Open-Meteo",
    "aqi": "air quality for a place",
    "sun": "sunrise / sunset here (or for a place)",
    "moon": "moon phase",
    "solar": "space weather: solar flux, Kp, solar wind, X-rays",
    "sf": "solar panel output forecast for a place (also: solarforecast)",
    "hfcond": "HF radio band conditions",
    "satpass": "next satellite pass (satpass iss / hubble / <NORAD number> [place])",
    "airplanes": "aircraft overhead (airplanes [miles] [place]; also: overhead)",
    "rain": "rain in the next 2 hours for a place",
    "aurora": "aurora chances and geomagnetic activity (for a place)",
    "channels": "where the weather commands are answered and what they know",
    "status": "is the bot running",
    "contact": "who runs this bot",
}
ALIASES = {"solarforecast": "sf", "overhead": "airplanes"}
USAGE = {"wx": "wx <place>", "gwx": "gwx <place>", "aqi": "aqi <place>", "sf": "sf <place>", "rain": "rain <place>", "satpass": "satpass iss"}
OLD_WX = "weather_bot"
MOVED = {"enabled": "wx_on", "channels": "wx_channels", "home": "wx_home", "prefix": "wx_prefix", "cooldown": "wx_cooldown", "units": "wx_units",
         "contact": "wx_contact", "answer_dm": "wx_answer_dm", "off": "wx_off", "max_parts": "wx_max_parts", "rain_alerts": "wx_rain",
         "_names": "_names", "_reply_delay": "_reply_delay", "_part_gap": "_part_gap", "_reply_private": "_reply_private"}


def first_hop(packet_log, heard_at, hops):
    """The first repeater (key prefix) of the channel packet that brought a message: the newest one heard just before it with that many
    hops.  None if the packet wasn't heard (Bluetooth can't hear packets)."""
    for p in reversed(packet_log):
        if p.get("type") != "GRP_TXT" or not heard_at - 20 <= p.get("t", 0) <= heard_at: continue
        n = 2 * max(1, int(p.get("size") or 1))
        path = (p.get("path") or "").upper()
        if path and len(path) // n == hops: return path[:n]
    return None


def moved_settings(old, have):
    """The Weather bot's settings (one node's, or its defaults) -> {Area alerts key: value}, only what Area alerts doesn't have yet."""
    return {new: old[k] for k, new in MOVED.items() if k in old and new not in have}


class WeatherCmds:
    command_words = list(COMMANDS)          # (the settings window's 'Command names...')

    # ---- start ----
    def wx_load(self):
        self.wx_started, self.wx_answers, self._wx_home, self._rain_said = time.time(), 0, None, 0.0
        self.wx_limiter = mc.Limiter(per_user=int(self.api.get("wx_cooldown", 30)), gap=5)
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.wx_help)
        if hasattr(self.api, "addon_settings") and not self.api.get("wx_moved", False): self.api.after(700, self.take_over_wx)

    def take_over_wx(self):
        """The Weather bot was used here: its settings - every node's - are added to these (once; nothing it had is changed or removed)."""
        if self.api.addon_installed(OLD_WX):
            try: raw = self.api.addon_settings(OLD_WX, raw=True)
            except TypeError: raw = self.api.addon_settings(OLD_WX)          # (an mcIRC without per-node copies: its main settings)
            was_on = self.api.addon_enabled(OLD_WX) or raw.get("handed_over", False)      # (the Weather bot 2.0 notes it before it switches off)
            mine = self.api.addon_settings(self.api.name, raw=True) if hasattr(self.api, "name") else {}
            moved = moved_settings(raw, {k for k in mine if not k.startswith("_per_node")})
            if not was_on: moved.pop("wx_on", None)                              # it was switched off: the commands stay off here too
            for k, v in moved.items(): self.api.set(k, v)
            nodes = list(self.api.get("_nodes", ["main"]))
            for n in raw.get("_nodes", []):
                if n not in nodes: nodes.append(n)
            if nodes != list(self.api.get("_nodes", ["main"])): self.api.set("_nodes", nodes)
            for node, own in (raw.get("_per_node") or {}).items():
                have = (mine.get("_per_node") or {}).get(node, {})
                with self.api.for_node(node, own=True):
                    for k, v in moved_settings(own, have).items(): self.api.set(k, v)
            if moved or raw.get("_per_node"):
                if self.api.addon_enabled(OLD_WX): self.api.set_addon_enabled(OLD_WX, False)
                self.wx_limiter.per_user = int(self.api.get("wx_cooldown", 30))
                self.api.log("The Weather bot is now part of Area alerts: its settings were added here (Settings > Weather commands) and it was "
                             "switched off.", "info")
        self.api.set("wx_moved", True)

    # ---- where it answers ----
    def wx_channels(self): return mc.channel_list(self.api.get("wx_channels", "#weather"))

    def wx_channels_used(self): return [c for c in self.wx_channels() if c != "*"] if self.api.get("wx_on", False) else []

    def wx_help(self, channel, dm=False):
        """For 'bothelp': the weather commands answered in this channel right now."""
        g = self.api.get
        if not g("wx_on", False): return []
        if (dm and not g("wx_answer_dm", True)) or (not dm and not mc.channel_ok(channel, self.wx_channels())): return []
        p, off = g("wx_prefix", ""), g("wx_off", [])
        names = mc.command_names(self.api, COMMANDS, ALIASES)
        return [p + mc.shown_usage(USAGE.get(c, c), c, names, ALIASES) for c in COMMANDS if c not in off]

    def wx_home(self):
        """Its own location: the place set in its settings, else the node position from Options > Node."""
        place = (self.api.get("wx_home", "") or "").strip()
        if place:
            if not self._wx_home or self._wx_home[0] != place: self._wx_home = (place, mc.resolve_place(place))
            return self._wx_home[1]
        lat, lon, _ = self.api.node_position()
        if not (lat or lon): return None
        return lat, lon, self.town(lat, lon) or "here"

    def town(self, lat, lon):
        """The town at a position ('Hope BC'), looked up once per spot (OpenStreetMap allows one lookup a second); None if there is none."""
        key, towns = (round(lat, 2), round(lon, 2)), self.__dict__.setdefault("_towns", {})
        if key not in towns: towns[key] = mc.town_name(lat, lon)
        return towns[key]

    def asker_place(self, msg, heard_at):
        """Where the asker is, for a command without a place: their node's advertised position, else the repeater their message reached
        first (the one nearest them), else None (then its own location)."""
        raw = msg.get("raw") if isinstance(msg.get("raw"), dict) else {}
        nodes = self.api.nodes
        row = (nodes.find_by_prefix(raw.get("pubkey_prefix") or "") if raw.get("pubkey_prefix") else None) \
            or nodes.find_by_name((msg.get("nick") or "").lstrip("@"))
        if row and (row.get("lat") or row.get("lon")):
            lat, lon = float(row["lat"]), float(row["lon"])
            return lat, lon, self.town(lat, lon) or row["name"][:24]
        hops = msg.get("hops")
        if msg.get("dm") or hops in (None, 0, 255): return None
        first = first_hop(self.api.packet_log, heard_at, hops)
        if not first: return None
        reps = sorted((n for n in nodes.all() if n.get("type") in (2, 3) and (n.get("lat") or n.get("lon"))
                       and (n.get("public_key") or "").lower().startswith(first.lower())), key=lambda n: -(n.get("last_seen") or 0))
        if not reps: return None
        lat, lon = float(reps[0]["lat"]), float(reps[0]["lon"])
        return lat, lon, self.town(lat, lon) or reps[0]["name"][:24]

    # ---- answering ----
    def on_message(self, msg):
        self.wx_message(msg)
        super().on_message(msg)             # 'route <address>' (aa_extras)

    def wx_message(self, msg):
        g = self.api.get
        if not g("wx_on", False): return
        if msg.get("dm"):
            if not g("wx_answer_dm", True): return
        elif not mc.channel_ok(msg.get("channel", ""), self.wx_channels()):
            return
        names = mc.command_names(self.api, COMMANDS, ALIASES)      # its words, and the names set in 'Command names...'
        hit = mc.parse_command(msg.get("text", ""), set(names), g("wx_prefix", ""))
        if not hit: return
        cmd, arg = names[hit[0]], hit[1]
        if cmd in g("wx_off", []): return
        if not self.wx_limiter.allow(msg.get("nick", "?")): return
        heard_at, units = time.time(), g("wx_units", "metric")
        self.api.run_background(lambda: self.wx_answer(cmd, arg, msg, heard_at, units), lambda r: self.wx_send(msg, cmd, r))

    def wx_send(self, msg, cmd, result):
        if isinstance(result, ValueError): text = f"{cmd}: {result}"
        elif isinstance(result, Exception):
            self.api.log(f"{cmd} failed: {result}", "warn")
            text = f"{cmd}: that service is not answering right now, try later"
        else: text = result
        self.wx_answers += 1
        with self.api.for_node(msg.get("node") or "main"): parts = int(self.api.get("wx_max_parts", 3))
        mc.send_parts(self.api, msg, text, max_parts=parts, label=True)

    def wx_place(self, arg, msg=None, heard_at=0):
        """A place for an answer: the one asked for, else where the asker is, else its own location."""
        home = None
        try: home = self.wx_home()
        except ValueError: pass
        asker = None
        if not (arg or "").strip() and msg:
            try: asker = self.asker_place(msg, heard_at)
            except Exception as e: self.api.log(f"where the asker is: {e}", "warn")
        return mc.resolve_place(arg, nodes=self.api.nodes, default=asker or home, near=asker or home)

    def wx_answer(self, cmd, arg, msg=None, heard_at=0, units="metric"):
        place = lambda a=arg: self.wx_place(a, msg, heard_at)
        if cmd == "wx":
            lat, lon, label = place()
            try: return ws.wx(lat, lon, label)
            except ValueError: return ws.gwx(lat, lon, label, units)       # outside the US NOAA has nothing: same answer from Open-Meteo
        if cmd == "gwx": return ws.gwx(*place(), units)
        if cmd == "aqi": return ws.aqi(*place())
        if cmd == "sun": return ws.sun(*place())
        if cmd == "moon": return ws.moon()
        if cmd == "solar": return ws.solar()
        if cmd == "sf": return ws.solar_forecast(*place())
        if cmd == "hfcond": return ws.hfcond()
        if cmd == "rain": return ws.rain(*place(), units)
        if cmd == "aurora": return ws.aurora(*place())
        if cmd == "satpass":                                       # satpass [satellite] [place]: 'satpass iss surrey', 'satpass 25544', 'satpass surrey'
            first, _, rest = arg.partition(" ")
            if first.lower() in sky.SATS or first.isdigit(): return sky.satpass(first, *place(rest))
            return sky.satpass("iss", *place())
        if cmd == "airplanes":                                     # airplanes [miles] [place], in either order
            words = arg.split()
            nums = [w for w in words if w.isdigit()]
            return sky.airplanes(*place(" ".join(w for w in words if not w.isdigit())), nm=int(nums[0]) if nums else 25)
        g = self.api.get
        if cmd == "channels":
            where = ", ".join(sorted("all channels" if c == "*" else c for c in self.wx_channels())) or "no channel"
            on = [c for c in COMMANDS if c not in g("wx_off", []) and c not in ("channels", "status", "contact")]
            return f"I answer in {where}. Place = city, postal code or node. Try: wx <place>, " + ", ".join(c for c in on if c != "wx")
        if cmd == "status":
            up = int(time.time() - self.wx_started)
            return (f"Area alerts {self.version} on mcIRC {_app_version()}: up {up // 3600}h{up % 3600 // 60:02d}m, {self.wx_answers} weather answers, "
                    f"radio {'connected' if self.api.connected else 'offline'}")
        if cmd == "contact":
            return g("wx_contact", "") or f"This bot runs on {self.api.node_position()[2] or 'this node'} - send it a private message"
        raise ValueError("unknown command")

    # ---- the optional rain warning (every tick, whether or not alerts are checked) ----
    def wx_tick(self):
        g = self.api.get
        if not (g("wx_on", False) and g("wx_rain", False) and self.api.connected): return
        if time.time() - self._rain_said < 3 * 3600 or int(time.time() / 60) % 15: return      # look every 15 minutes, say it at most every 3 hours
        chans = [c for c in self.wx_channels() if c != "*"]
        if not chans: return
        units = g("wx_units", "metric")

        def check():
            home = self.wx_home()
            if not home: return None
            steps = ws.rain_steps(home[0], home[1], units)
            if steps and steps[0][1] <= 0.05 and any(p >= 0.3 for _, p in steps[1:5]):
                start = next(t for t, p in steps[1:] if p >= 0.3)
                return f"Rain heads-up: rain expected {'here' if home[2] == 'here' else 'at ' + home[2]} from about {start}"
            return None

        def done(r):
            if isinstance(r, str):
                self._rain_said = time.time()
                self.api.send("Public" if chans[0] == "public" else chans[0], r)
        self.api.run_background(check, done)

    # ---- settings: the 'Weather commands' tab ----
    def wx_page(self, page, bg):
        g = self.api.get
        self.wv = {"wx_on": tk.BooleanVar(value=g("wx_on", False)), "wx_answer_dm": tk.BooleanVar(value=g("wx_answer_dm", True)),
                   "wx_rain": tk.BooleanVar(value=g("wx_rain", False)), "wx_channels": tk.StringVar(value=g("wx_channels", "#weather")),
                   "wx_home": tk.StringVar(value=g("wx_home", "")), "wx_prefix": tk.StringVar(value=g("wx_prefix", "")),
                   "wx_units": tk.StringVar(value=g("wx_units", "metric")), "wx_contact": tk.StringVar(value=g("wx_contact", "")),
                   "wx_cooldown": tk.StringVar(value=str(g("wx_cooldown", 30)))}
        tk.Checkbutton(page, text="Answer weather commands (sends to the mesh when someone asks)", variable=self.wv["wx_on"], bg=bg,
                       font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        tk.Label(page, bg=bg, fg="#555", wraplength=560, justify="left", text=(
            "wx <place> (nothing = where the asker's node is, or the repeater nearest them), gwx, aqi, sun, moon, solar, sf, hfcond, satpass, "
            "airplanes, rain, aurora, channels, status, contact. Answers start with '@name:' and are rate-limited. satpass needs "
            "'pip install sgp4'. (These were the Weather bot.)")).pack(anchor="w", padx=18)
        for label, key, width in (("Channels it answers in:", "wx_channels", 28),
                                  ("Its own location (blank = the node position from Options > Node):", "wx_home", 28),
                                  ("Command prefix (blank: 'wx Surrey' and '!wx Surrey' both work; '!' = only '!wx'):", "wx_prefix", 4),
                                  ("Seconds before the same person gets another answer:", "wx_cooldown", 6), ("'contact' answer:", "wx_contact", 40)):
            r = tk.Frame(page, bg=bg)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=bg, anchor="w").pack(side="left")
            if key == "wx_channels": mc.chan_field(r, self.wv[key], width, all_option=True, empty="(off)").pack(side="left", padx=4)
            else: tk.Entry(r, textvariable=self.wv[key], width=width).pack(side="left", padx=4)
        r = tk.Frame(page, bg=bg)
        r.pack(fill="x", pady=1)
        tk.Label(r, text="Units:", bg=bg).pack(side="left")
        for u in ("metric", "imperial"): tk.Radiobutton(r, text=u, value=u, variable=self.wv["wx_units"], bg=bg).pack(side="left")
        tk.Checkbutton(page, text="Also answer private messages", variable=self.wv["wx_answer_dm"], bg=bg).pack(anchor="w")
        tk.Checkbutton(page, text="Warn the first channel when rain is about to start here (at most every 3 hours)", variable=self.wv["wx_rain"], bg=bg).pack(anchor="w")
        tk.Label(page, text="Commands (untick to switch one off):", bg=bg).pack(anchor="w", pady=(6, 0))
        grid = tk.Frame(page, bg=bg)
        grid.pack(anchor="w")
        off = set(g("wx_off", []))
        self.wx_cmd_vars = {}
        for i, c in enumerate(COMMANDS):
            self.wx_cmd_vars[c] = tk.BooleanVar(value=c not in off)
            tk.Checkbutton(grid, text=c, variable=self.wx_cmd_vars[c], bg=bg, width=10, anchor="w").grid(row=i // 5, column=i % 5, sticky="w")

    def wx_apply(self):
        for k, var in self.wv.items():
            val = var.get()
            if k == "wx_cooldown":
                try: val = max(5, int(val))
                except ValueError: val = 30
                self.wx_limiter.per_user = val
            self.api.set(k, val.strip() if isinstance(val, str) else val)
        self.api.set("wx_off", [c for c, var in self.wx_cmd_vars.items() if not var.get()])
        self._wx_home = None


def _app_version():
    try:
        with open(os.path.join(BASE_DIR, "VERSION")) as f: v = f.read().strip()
        import gui_platform
        return gui_platform.shown_version(v) if hasattr(gui_platform, "shown_version") else v
    except OSError: return "?"
