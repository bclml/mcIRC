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
    "wx": "weather and forecast for a place (NOAA in the US, Open-Meteo elsewhere)",
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
VERSION = "1.0.2"


class Addon(AddonBase):
    title = "Weather bot"
    version = VERSION
    author = "mcIRC"
    description = ("Answers weather commands in the channels you choose (default #weather): wx <place>, gwx, aqi, sun, moon, solar, sf, hfcond, "
                   "satpass, airplanes, rain, aurora, channels, status, contact. Off until you switch it on.")
    tick_seconds = 60

    def on_load(self):
        self.started, self.answers, self._home, self._rain_said = time.time(), 0, None, 0.0
        self.limiter = mc.Limiter(per_user=int(self.api.get("cooldown", 30)), gap=5)
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.help_for)      # (mcIRC 1.5.2 and later)

    USAGE = {"wx": "wx <place>", "gwx": "gwx <place>", "aqi": "aqi <place>", "sf": "sf <place>", "rain": "rain <place>", "satpass": "satpass iss"}

    def help_for(self, channel, dm=False):
        """For 'bothelp': the commands answered in this channel right now."""
        if not self.cfg("enabled", False): return []
        if (dm and not self.cfg("answer_dm", False)) or (not dm and not mc.channel_ok(channel, self.channels())): return []
        p, off = self.cfg("prefix", ""), self.cfg("off", [])
        return [p + self.USAGE.get(c, c) for c in COMMANDS if c not in off]

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
        return (lat, lon, "here") if (lat or lon) else None

    # ---- answering ----
    def on_message(self, msg):
        if not self.cfg("enabled", False): return
        if msg.get("dm"):
            if not self.cfg("answer_dm", False): return
        elif not mc.channel_ok(msg.get("channel", ""), self.channels()):
            return
        cmds = set(COMMANDS) | set(ALIASES)
        hit = mc.parse_command(msg.get("text", ""), cmds, self.cfg("prefix", ""))
        if not hit: return
        cmd, arg = ALIASES.get(hit[0], hit[0]), hit[1]
        if cmd in self.cfg("off", []): return
        if not self.limiter.allow(msg.get("nick", "?")): return
        self.api.run_background(lambda: self.answer(cmd, arg), lambda r: self.send(msg, cmd, r))

    def send(self, msg, cmd, result):
        if isinstance(result, ValueError): text = f"{cmd}: {result}"
        elif isinstance(result, Exception):
            self.api.log(f"{cmd} failed: {result}", "warn")
            text = f"{cmd}: that service is not answering right now, try later"
        else: text = result
        self.answers += 1
        for i, part in enumerate(mc.split_message(text, max_parts=int(self.cfg("max_parts", 3)))):
            self.api.after(i * 3000, lambda p=part: self.api.reply(msg, p))      # a few seconds apart: one message at a time on the mesh

    def place(self, arg):
        home = None
        try: home = self.home()
        except ValueError: pass
        return mc.resolve_place(arg, nodes=self.api.nodes, default=home, near=home)

    def answer(self, cmd, arg):
        units = self.cfg("units", "metric")
        if cmd == "wx":
            lat, lon, label = self.place(arg)
            try: return ws.wx(lat, lon, label)
            except ValueError: return ws.gwx(lat, lon, label, units)       # outside the US NOAA has nothing: same answer from Open-Meteo
        if cmd == "gwx": return ws.gwx(*self.place(arg), units)
        if cmd == "aqi": return ws.aqi(*self.place(arg))
        if cmd == "sun": return ws.sun(*self.place(arg))
        if cmd == "moon": return ws.moon()
        if cmd == "solar": return ws.solar()
        if cmd == "sf": return ws.solar_forecast(*self.place(arg))
        if cmd == "hfcond": return ws.hfcond()
        if cmd == "rain": return ws.rain(*self.place(arg), units)
        if cmd == "aurora": return ws.aurora(*self.place(arg))
        if cmd == "satpass":                                       # satpass [satellite] [place]: 'satpass iss surrey', 'satpass 25544', 'satpass surrey'
            first, _, rest = arg.partition(" ")
            if first.lower() in sky.SATS or first.isdigit(): return sky.satpass(first, *self.place(rest))
            return sky.satpass("iss", *self.place(arg))
        if cmd == "airplanes":                                     # airplanes [miles] [place], in either order
            words = arg.split()
            nums = [w for w in words if w.isdigit()]
            return sky.airplanes(*self.place(" ".join(w for w in words if not w.isdigit())), nm=int(nums[0]) if nums else 25)
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
            with open(os.path.join(BASE_DIR, "VERSION")) as f: return f.read().strip()
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
        self.v = {"enabled": tk.BooleanVar(value=self.cfg("enabled", False)), "answer_dm": tk.BooleanVar(value=self.cfg("answer_dm", False)),
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
