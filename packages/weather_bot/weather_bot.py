"""Weather bot: answers weather commands in the channels you pick (default #weather), like the MeshCore weather bots.
Off until you switch it on in Options.  Every answer is rate-limited; nothing is sent unless somebody asks (rain warnings are a separate opt-in)."""
import os
import time
import tkinter as tk

from gui_addons import AddonBase, BASE_DIR
import meshbot_common as mc
import wxbot_sky as sky
import wxbot_sources as ws

COMMANDS = {        # command: (what it does, needs a place)
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
    "channels": "where this bot answers and what it knows",
    "status": "is the bot running",
    "contact": "who runs this bot",
}
ALIASES = {"solarforecast": "sf", "overhead": "airplanes"}
VERSION = "1.0.13"


def first_hop(packet_log, heard_at, hops):
    """The first repeater (key prefix) of the channel packet that brought a message: the newest one heard just before it with that many
    hops.  None if the packet wasn't heard (Bluetooth can't hear packets)."""
    for p in reversed(packet_log):
        if p.get("type") != "GRP_TXT" or not heard_at - 20 <= p.get("t", 0) <= heard_at: continue
        n = 2 * max(1, int(p.get("size") or 1))
        path = (p.get("path") or "").upper()
        if path and len(path) // n == hops: return path[:n]
    return None


class Addon(AddonBase):
    title = "Weather bot"
    command_words = list(COMMANDS)          # (the settings window's 'Command names...': other names for each command)
    version = VERSION
    author = "mcIRC"
    description = ("Answers weather commands in the channels you choose (default #weather): wx <place>, gwx, aqi, sun, moon, solar, sf, hfcond, "
                   "satpass, airplanes, rain, aurora, channels, status, contact. Off until you switch it on.")
    tick_seconds = 60
    switch = "enabled"           # its ON/OFF switch on the toolbar

    def on_load(self):
        self.started, self.answers, self._home, self._rain_said = time.time(), 0, None, 0.0
        self.limiter = mc.Limiter(per_user=int(self.api.get("cooldown", 30)), gap=5)
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.help_for)      # (mcIRC 1.5.2 and later)

    USAGE = {"wx": "wx <place>", "gwx": "gwx <place>", "aqi": "aqi <place>", "sf": "sf <place>", "rain": "rain <place>", "satpass": "satpass iss"}

    def channels_used(self):
        """Where it answers (mcIRC adds these to the node when it lacks them)."""
        return list(self.channels()) if self.cfg("enabled", False) else []

    def help_for(self, channel, dm=False):
        """For 'bothelp': the commands answered in this channel right now."""
        if not self.cfg("enabled", False): return []
        if (dm and not self.cfg("answer_dm", True)) or (not dm and not mc.channel_ok(channel, self.channels())): return []
        p, off = self.cfg("prefix", ""), self.cfg("off", [])
        names = mc.command_names(self.api, COMMANDS, ALIASES)
        return [p + mc.shown_usage(self.USAGE.get(c, c), c, names, ALIASES) for c in COMMANDS if c not in off]

    def on_unload(self): pass

    # ---- settings ----
    def cfg(self, key, default): return self.api.get(key, default)

    def channels(self): return mc.channel_list(self.cfg("channels", "#weather"))

    def home(self):
        """The bot's own location: the place set in Options, else the node position from Options > Node."""
        place = (self.cfg("home", "") or "").strip()
        if place:
            if not self._home or self._home[0] != place: self._home = (place, mc.resolve_place(place))
            return self._home[1]
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
        first (the one nearest them), else None (then the bot's own location)."""
        raw = msg.get("raw") if isinstance(msg.get("raw"), dict) else {}
        nodes = self.api.nodes
        row = (nodes.find_by_prefix(raw.get("pubkey_prefix") or "") if raw.get("pubkey_prefix") else None)             or nodes.find_by_name((msg.get("nick") or "").lstrip("@"))
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
        if not self.cfg("enabled", False): return
        if msg.get("dm"):
            if not self.cfg("answer_dm", True): return
        elif not mc.channel_ok(msg.get("channel", ""), self.channels()):
            return
        names = mc.command_names(self.api, COMMANDS, ALIASES)      # its words, and the names set in 'Command names...'
        hit = mc.parse_command(msg.get("text", ""), set(names), self.cfg("prefix", ""))
        if not hit: return
        cmd, arg = names[hit[0]], hit[1]
        if cmd in self.cfg("off", []): return
        if not self.limiter.allow(msg.get("nick", "?")): return
        heard_at = time.time()
        self.api.run_background(lambda: self.answer(cmd, arg, msg, heard_at), lambda r: self.send(msg, cmd, r))

    def send(self, msg, cmd, result):
        if isinstance(result, ValueError): text = f"{cmd}: {result}"
        elif isinstance(result, Exception):
            self.api.log(f"{cmd} failed: {result}", "warn")
            text = f"{cmd}: that service is not answering right now, try later"
        else: text = result
        self.answers += 1
        mc.send_parts(self.api, msg, text, max_parts=int(self.cfg("max_parts", 3)), label=True)

    def place(self, arg, msg=None, heard_at=0):
        """A place for an answer: the one asked for, else where the asker is, else the bot's own location."""
        home = None
        try: home = self.home()
        except ValueError: pass
        asker = None
        if not (arg or "").strip() and msg:
            try: asker = self.asker_place(msg, heard_at)
            except Exception as e: self.api.log(f"where the asker is: {e}", "warn")
        return mc.resolve_place(arg, nodes=self.api.nodes, default=asker or home, near=asker or home)

    def answer(self, cmd, arg, msg=None, heard_at=0):
        units = self.cfg("units", "metric")
        if cmd == "wx":
            lat, lon, label = self.place(arg, msg, heard_at)
            try: return ws.wx(lat, lon, label)
            except ValueError: return ws.gwx(lat, lon, label, units)       # outside the US NOAA has nothing: same answer from Open-Meteo
        if cmd == "gwx": return ws.gwx(*self.place(arg, msg, heard_at), units)
        if cmd == "aqi": return ws.aqi(*self.place(arg, msg, heard_at))
        if cmd == "sun": return ws.sun(*self.place(arg, msg, heard_at))
        if cmd == "moon": return ws.moon()
        if cmd == "solar": return ws.solar()
        if cmd == "sf": return ws.solar_forecast(*self.place(arg, msg, heard_at))
        if cmd == "hfcond": return ws.hfcond()
        if cmd == "rain": return ws.rain(*self.place(arg, msg, heard_at), units)
        if cmd == "aurora": return ws.aurora(*self.place(arg, msg, heard_at))
        if cmd == "satpass":                                       # satpass [satellite] [place]: 'satpass iss surrey', 'satpass 25544', 'satpass surrey'
            first, _, rest = arg.partition(" ")
            if first.lower() in sky.SATS or first.isdigit(): return sky.satpass(first, *self.place(rest, msg, heard_at))
            return sky.satpass("iss", *self.place(arg, msg, heard_at))
        if cmd == "airplanes":                                     # airplanes [miles] [place], in either order
            words = arg.split()
            nums = [w for w in words if w.isdigit()]
            return sky.airplanes(*self.place(" ".join(w for w in words if not w.isdigit()), msg, heard_at), nm=int(nums[0]) if nums else 25)
        if cmd == "channels":
            where = ", ".join(sorted("all channels" if c == "*" else c for c in self.channels())) or "no channel"
            on = [c for c in COMMANDS if c not in self.cfg("off", []) and c not in ("channels", "status", "contact")]
            return f"I answer in {where}. Place = city, postal code or node. Try: wx <place>, " + ", ".join(c for c in on if c != "wx")
        if cmd == "status":
            up = int(time.time() - self.started)
            return (f"Weather bot {VERSION} on mcIRC {self._app_version()}: up {up // 3600}h{up % 3600 // 60:02d}m, {self.answers} answers, "
                    f"radio {'connected' if self.api.connected else 'offline'}")
        if cmd == "contact":
            return self.cfg("contact", "") or f"This bot runs on {self.api.node_position()[2] or 'this node'} - send it a private message"
        raise ValueError("unknown command")

    @staticmethod
    def _app_version():
        try:
            with open(os.path.join(BASE_DIR, "VERSION")) as f: v = f.read().strip()
            import gui_platform
            return gui_platform.shown_version(v) if hasattr(gui_platform, "shown_version") else v
        except OSError: return "?"

    # ---- optional rain warning ----
    def on_tick(self):
        if not (self.cfg("enabled", False) and self.cfg("rain_alerts", False) and self.api.connected): return
        if time.time() - self._rain_said < 3 * 3600 or int(time.time() / 60) % 15: return      # look every 15 minutes, say it at most every 3 hours
        chans = [c for c in self.channels() if c != "*"]
        if not chans: return
        def check():
            home = self.home()
            if not home: return None
            steps = ws.rain_steps(home[0], home[1], self.cfg("units", "metric"))
            if steps and steps[0][1] <= 0.05 and any(p >= 0.3 for _, p in steps[1:5]):
                start = next(t for t, p in steps[1:] if p >= 0.3)
                return f"Rain heads-up: rain expected {'here' if home[2] == 'here' else 'at ' + home[2]} from about {start}"
            return None
        def done(r):
            if isinstance(r, str):
                self._rain_said = time.time()
                self.api.send("Public" if chans[0] == "public" else chans[0], r)
        self.api.run_background(check, done)

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v = {"enabled": tk.BooleanVar(value=self.cfg("enabled", False)), "answer_dm": tk.BooleanVar(value=self.cfg("answer_dm", True)),
                  "rain_alerts": tk.BooleanVar(value=self.cfg("rain_alerts", False)), "channels": tk.StringVar(value=self.cfg("channels", "#weather")),
                  "home": tk.StringVar(value=self.cfg("home", "")), "prefix": tk.StringVar(value=self.cfg("prefix", "")),
                  "units": tk.StringVar(value=self.cfg("units", "metric")), "contact": tk.StringVar(value=self.cfg("contact", "")),
                  "cooldown": tk.StringVar(value=str(self.cfg("cooldown", 30)))}
        tk.Checkbutton(f, text="Answer weather commands (sends to the mesh when someone asks)", variable=self.v["enabled"], bg=bg).pack(anchor="w")
        for label, key, width in (("Channels it answers in (comma separated, or 'all'):", "channels", 28),
                                  ("Its own location (blank = the node position from Options > Node):", "home", 28),
                                  ("Command prefix (blank: 'wx Surrey' and '!wx Surrey' both work; '!' = only '!wx'):", "prefix", 4),
                                  ("Seconds before the same person gets another answer:", "cooldown", 6), ("'contact' answer:", "contact", 40)):
            r = tk.Frame(f, bg=bg)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=bg, anchor="w").pack(side="left")
            tk.Entry(r, textvariable=self.v[key], width=width).pack(side="left", padx=4)
        r = tk.Frame(f, bg=bg)
        r.pack(fill="x", pady=1)
        tk.Label(r, text="Units:", bg=bg).pack(side="left")
        for u in ("metric", "imperial"): tk.Radiobutton(r, text=u, value=u, variable=self.v["units"], bg=bg).pack(side="left")
        tk.Checkbutton(f, text="Also answer private messages", variable=self.v["answer_dm"], bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text="Warn the first channel when rain is about to start here (at most every 3 hours)", variable=self.v["rain_alerts"], bg=bg).pack(anchor="w")
        tk.Label(f, text="Commands (untick to switch one off):", bg=bg).pack(anchor="w", pady=(6, 0))
        grid = tk.Frame(f, bg=bg)
        grid.pack(anchor="w")
        off = set(self.cfg("off", []))
        self.cmd_vars = {}
        for i, (c, what) in enumerate(COMMANDS.items()):
            self.cmd_vars[c] = tk.BooleanVar(value=c not in off)
            tk.Checkbutton(grid, text=c, variable=self.cmd_vars[c], bg=bg, width=10, anchor="w").grid(row=i // 5, column=i % 5, sticky="w")
        return f

    def apply_options(self):
        for k, var in self.v.items():
            val = var.get()
            if k == "cooldown":
                try: val = max(5, int(val))
                except ValueError: val = 30
                self.limiter.per_user = val
            self.api.set(k, val.strip() if isinstance(val, str) else val)
        self.api.set("off", [c for c, var in self.cmd_vars.items() if not var.get()])
        self._home = None
