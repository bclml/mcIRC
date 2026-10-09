"""Mesh bot: the commands of agessaman/meshcore-bot that mcIRC's other bots don't have - ping, hello, path, prefix, multitest, stats, sports,
version - and its greeter, each switched on for the channels you choose.  Off until you switch it on; answers only when asked (the greeter:
once per newcomer), rate-limited, and in the channel or privately as you set it."""
import time
import gui_platform
import tkinter as tk

from gui_addons import AddonBase
import meshbot_cmds as cmds
import meshbot_common as mc

COMMANDS = {
    "ping": "Pong! with how your message arrived",
    "hello": "a robot greeting (hi, hello, hey, ...)",
    "path": "the repeaters your message came through; path a1,b2 decodes a path",
    "prefix": "the repeaters using a key prefix: prefix A1, prefix free",
    "multitest": "the different paths your message took (listens 6 s)",
    "stats": "the mesh in the last 24 hours",
    "sports": "scores: sports, sports nhl, sports canucks",
    "version": "which bot this is",
    "firmware": "the newest MeshCore firmware versions (read-only)",
}
ALIASES = {"stat": "stats", "fw": "firmware", "ver": "version"}     # other words people type for the same command
USAGE = {"path": "path [a1,b2]", "prefix": "prefix <A1|free>", "sports": "sports [team|league]"}
GREETING = cmds.DEFAULT_GREETINGS[0]                     # the single greeting of 1.0.x (kept when someone had changed it)


class Addon(AddonBase):
    title = "Mesh bot"
    version = "1.2.3"
    author = "mcIRC (commands after agessaman/meshcore-bot, MIT)"
    description = ("ping, hello, path, prefix, multitest, stats, sports and version - the meshcore-bot commands mcIRC's other bots don't have - "
                   "plus its greeter for newcomers (a random greeting from your list), each switched on for the channels you choose. Off until you switch it on.")
    tick_seconds = 0
    switch = "enabled"           # its ON/OFF switch on the toolbar
    replies = True

    def on_load(self):
        self.limiter = mc.Limiter(per_user=int(self.api.get("cooldown", 20)), gap=5)
        self.counts = {}
        self.loaded_at = time.time()
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.help_for)

    def on_unload(self): pass

    def where(self, cmd): return mc.channel_list(self.api.get("channels", {}).get(cmd, ""))

    def help_for(self, channel, dm=False):
        if not self.api.get("enabled", False) or (dm and not self.api.get("answer_dm", True)): return []
        p = self.api.get("prefix", "")
        return [p + USAGE.get(c, c) for c in COMMANDS if self.where(c) and (dm or mc.channel_ok(channel, self.where(c)))]

    def bot_name(self): return self.api.node_position()[2] or "a bot"

    def on_message(self, msg):
        ch = msg.get("channel", "")
        if not msg.get("dm"): self.counts[ch] = self.counts.get(ch, 0) + 1
        if not self.api.get("enabled", False): return
        self.greet(msg)
        text = msg.get("text", "")
        hit = ("hello", "") if cmds.is_greeting(text) else mc.parse_command(text, (set(COMMANDS) | set(ALIASES)) - {"hello"}, self.api.get("prefix", ""))
        if not hit: return
        cmd, arg = ALIASES.get(hit[0], hit[0]), hit[1]
        if msg.get("dm"):
            if not (self.api.get("answer_dm", True) and self.where(cmd)): return
        elif not mc.channel_ok(ch, self.where(cmd)): return
        if not self.limiter.allow(msg.get("nick", "?")): return
        now = time.time()
        if cmd == "multitest":                                   # wait for the copies of the message to arrive first
            return self.api.after(7000, lambda: self.send(msg, cmds.multitest_text(cmds.multitest_paths(self.api.packet_log, now))))
        if cmd == "firmware":
            return self.api.run_background(self.firmware, lambda r: self.send(msg, r if not isinstance(r, Exception) else "Couldn't reach GitHub for the firmware versions"))
        if cmd == "sports":
            teams = [t for t in self.api.get("sports_teams", "canucks, whitecaps, seahawks, mariners, kraken").split(",")]
            return self.api.run_background(lambda: cmds.sports_text(arg, mc.http_json, teams), lambda r: self.send(msg, r if not isinstance(r, Exception) else "Error fetching sports data"))
        try: self.send(msg, self.answer(cmd, arg, msg, now))
        except ValueError as e: self.send(msg, f"{cmd}: {e}")

    def answer(self, cmd, arg, msg, now):
        hops = msg.get("hops")
        hops = 0 if hops in (None, 255) else hops
        if cmd == "ping":
            how = "direct" if not hops else f"{hops} hop{'s' if hops > 1 else ''}"
            return "Pong!" + (f" ({how}" + (f", SNR {msg['snr']}" if msg.get("snr") is not None else "") + ")" if not msg.get("dm") else "")
        if cmd == "hello": return cmds.hello(self.bot_name())
        if cmd == "path":
            nodes = self.api.nodes.all()
            if arg.strip(): return cmds.path_text(nodes, cmds.split_hops(arg))
            hopsl = cmds.path_of_message(self.api.packet_log, now, hops)
            if hopsl is None: return "No path information for your message (try: path a1,b2)" if hops else "Direct connection (0 hops)"
            return cmds.path_text(nodes, hopsl)
        if cmd == "prefix": return cmds.prefix_text(self.api.nodes.all(), arg, now)
        if cmd == "stats":
            log = self.api.packet_log
            since = min([self.loaded_at] + [p.get("t", now) for p in log[:1]])
            activity = cmds.channel_activity(getattr(self.api, "log_dir", None) or "logs", now, self.bot_name() if self.bot_name() != "a bot" else "")
            return cmds.stats_text(log, self.api.nodes.all(), activity, now, since)
        if cmd == "version":
            try:
                import gui_update
                v = gui_update.local_version()
            except Exception: v = "?"
            return f"mcIRC {v} - Mesh bot {self.version} (commands after meshcore-bot)"
        raise ValueError("unknown command")

    def firmware(self):
        """The newest MeshCore releases, asked from GitHub at most once an hour."""
        cached = getattr(self, "_fw", None)
        if cached and time.time() - cached[0] < 3600: return cached[1]
        text = cmds.firmware_text(mc.http_json(cmds.RELEASES_URL, headers={"User-Agent": "mcIRC"}))
        self._fw = (time.time(), text)
        return text

    def greet(self, msg):
        """Once per newcomer: someone whose first message this is, and who wasn't in mcIRC's node memory (nodes.db, not the radio's
        contact list) when the greeter was switched on."""
        if msg.get("dm") or not mc.channel_ok(msg.get("channel", ""), mc.channel_list(self.api.get("greet_channels", ""))): return
        nick = (msg.get("nick") or "").strip()
        if not nick or nick == "someone": return
        seen = set(self.api.get("greeted", []))
        if nick in seen: return
        seen.add(nick)
        self.api.set("greeted", sorted(seen)[-5000:])
        line = cmds.pick_greeting(self.greetings(), getattr(self, "_last_greeting", None))
        self._last_greeting = line
        self.send(msg, cmds.greeting_for(nick, line, msg.get("channel", "")))

    def greetings(self):
        """The greetings to pick from: the list from the settings, or 1.0.x's single line if it was changed, else the defaults."""
        saved = self.api.get("greet_lines")
        if saved: return list(saved)
        old = self.api.get("greet_text", GREETING)
        return [old] if old != GREETING else list(cmds.DEFAULT_GREETINGS)

    def send(self, msg, text): mc.send_parts(self.api, msg, text, max_parts=2)

    # ---- settings ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        g = self.api.get
        self.v_on, self.v_dm = tk.BooleanVar(value=g("enabled", False)), tk.BooleanVar(value=g("answer_dm", True))
        self.v_prefix, self.v_cool = tk.StringVar(value=g("prefix", "")), tk.StringVar(value=str(g("cooldown", 20)))
        self.v_teams = tk.StringVar(value=g("sports_teams", "canucks, whitecaps, seahawks, mariners, kraken"))
        self.v_greet_ch = tk.StringVar(value=g("greet_channels", ""))
        tk.Checkbutton(f, text="Answer these commands (sends to the mesh when someone asks)", variable=self.v_on, bg=bg).pack(anchor="w")
        tk.Label(f, text="For each command, the channels it answers in (comma separated, 'all', or blank = off):", bg=bg).pack(anchor="w", pady=(6, 2))
        grid = tk.Frame(f, bg=bg); grid.pack(anchor="w")
        saved = g("channels", {})
        self.v_ch = {}
        for i, (c, what) in enumerate(COMMANDS.items()):
            self.v_ch[c] = tk.StringVar(value=saved.get(c, ""))
            tk.Label(grid, text=c, bg=bg, width=9, anchor="w").grid(row=i, column=0, sticky="w")
            tk.Entry(grid, textvariable=self.v_ch[c], width=22).grid(row=i, column=1, padx=4, pady=1)
            tk.Label(grid, text=what, bg=bg, fg="#555", anchor="w").grid(row=i, column=2, sticky="w")
        r = tk.Frame(f, bg=bg); r.pack(anchor="w", pady=(6, 0))
        tk.Button(r, text="Use #bot-van for all", command=lambda: [v.set("#bot-van") for v in self.v_ch.values()]).pack(side="left")
        tk.Button(r, text="Clear all", command=lambda: [v.set("") for v in self.v_ch.values()]).pack(side="left", padx=4)
        for label, var, width in (("Command prefix (blank: 'ping' and '!ping' both work):", self.v_prefix, 4),
                                  ("Seconds before the same person gets another answer:", self.v_cool, 6),
                                  ("Teams for a plain 'sports':", self.v_teams, 40)):
            r = tk.Frame(f, bg=bg); r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=bg).pack(side="left")
            tk.Entry(r, textvariable=var, width=width).pack(side="left", padx=4)
        tk.Checkbutton(f, text="Also answer private messages (for the commands that are on somewhere)", variable=self.v_dm, bg=bg).pack(anchor="w")
        tk.Label(f, text="Greeter (sends on its own - once per newcomer; blank = off):", bg=bg, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(8, 0))
        r = tk.Frame(f, bg=bg); r.pack(fill="x", pady=1)
        tk.Label(r, text="Greet newcomers in channels:", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_greet_ch, width=22).pack(side="left", padx=4)
        tk.Label(f, bg=bg, text="With one of these, picked at random (one per line; {nick} = their name, {channel} = the channel):").pack(anchor="w")
        self.greet_box = tk.Text(f, height=6, width=70, wrap="none", font=(gui_platform.EDITOR_FONT_NAME, 9))
        self.greet_box.insert("1.0", "\n".join(self.greetings()))
        self.greet_box.pack(anchor="w", fill="x")
        r = tk.Frame(f, bg=bg); r.pack(anchor="w", pady=(2, 0))
        tk.Button(r, text="Back to the default greetings",
                  command=lambda: (self.greet_box.delete("1.0", "end"), self.greet_box.insert("1.0", "\n".join(cmds.DEFAULT_GREETINGS)))).pack(side="left")
        tk.Label(r, bg=bg, fg="#555", text="  Plain text only - the mesh can't carry mIRC colours.").pack(side="left")
        tk.Label(f, bg=bg, fg="#555", wraplength=460, justify="left",
                 text="A newcomer: someone who isn't in mcIRC's own memory of nodes (nodes.db on this PC - not the radio's contact list) when "
                      "you switch the greeter on, speaking for the first time. path and prefix name repeaters from that same memory.").pack(anchor="w")
        return f

    def apply_options(self):
        greet_was = self.api.get("greet_channels", "")
        self.api.set("enabled", self.v_on.get())
        self.api.set("answer_dm", self.v_dm.get())
        self.api.set("prefix", self.v_prefix.get().strip())
        try: cool = max(5, int(self.v_cool.get()))
        except ValueError: cool = 20
        self.api.set("cooldown", cool); self.limiter.per_user = cool
        self.api.set("sports_teams", self.v_teams.get().strip())
        self.api.set("channels", {c: v.get().strip() for c, v in self.v_ch.items() if v.get().strip()})
        greet = self.v_greet_ch.get().strip()
        if greet and not greet_was:                              # greeter switched on: everyone already known is not a newcomer
            self.api.set("greeted", sorted({n["name"] for n in self.api.nodes.all() if n.get("name")})[-5000:])
        self.api.set("greet_channels", greet)
        self.api.set("greet_lines", cmds.greeting_lines(self.greet_box.get("1.0", "end")) or list(cmds.DEFAULT_GREETINGS))
