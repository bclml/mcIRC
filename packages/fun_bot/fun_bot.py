"""Fun bot: dice, roll, magic8, joke, dadjoke, hacker, catfact and wc (World Cup scores / tables), each switched on per channel.
Off until you switch it on in Options; every answer is rate-limited and only sent when somebody asks."""
import random
import re
import time
import tkinter as tk

from gui_addons import AddonBase
import funbot_data as data
import meshbot_common as mc

COMMANDS = {
    "dice": "roll dice: dice d20, dice 3d6",
    "roll": "a number: roll (1-100), roll 50, roll 2d8",
    "magic8": "ask the Magic 8-Ball a yes/no question",
    "joke": "a random joke",
    "dadjoke": "a clean, corny dad joke",
    "hacker": "movie-style hacker jargon",
    "catfact": "a fact about cats",
    "wc": "World Cup: wc (latest scores), wc A (group A table)",
}
DICE = re.compile(r"^(\d{0,2})d(\d{1,4})$", re.IGNORECASE)
ESPN = "https://site.api.espn.com/apis"


def roll_dice(spec, rng=random):
    """'3d6' -> '3d6: 4+2+6 = 12'.  Up to 20 dice of up to 1000 sides."""
    m = DICE.match((spec or "d6").strip().replace(" ", ""))
    if not m: raise ValueError("use e.g. dice d20 or dice 3d6")
    n, sides = int(m.group(1) or 1), int(m.group(2))
    if not (1 <= n <= 20 and 2 <= sides <= 1000): raise ValueError("1-20 dice with 2-1000 sides")
    rolls = [rng.randint(1, sides) for _ in range(n)]
    return f"\U0001F3B2 {n}d{sides}: " + (f"{'+'.join(map(str, rolls))} = {sum(rolls)}" if n > 1 else str(rolls[0]))


def roll(arg, rng=random):
    a = (arg or "").strip()
    if "d" in a.lower(): return roll_dice(a, rng)
    top = int(a) if a.isdigit() and int(a) >= 2 else 100
    return f"\U0001F3B2 {rng.randint(1, min(top, 1_000_000))} (1-{min(top, 1_000_000)})"


def world_cup(arg, get=mc.http_json):
    a = (arg or "").strip().upper().replace("GROUP", "").strip()
    if a and len(a) == 1 and a.isalpha():
        s = get(f"{ESPN}/v2/sports/soccer/fifa.world/standings")
        grp = next((c for c in s.get("children", []) if c.get("name", "").upper().endswith(" " + a)), None)
        if not grp: raise ValueError(f"no group {a}")
        stat = lambda e, k: next((x.get("displayValue") for x in e["stats"] if x["name"] == k), "?")
        rows = sorted(grp["standings"]["entries"], key=lambda e: int(stat(e, "rank") or 99))
        return f"WC {grp['name']}: " + ", ".join(f"{stat(e, 'rank')}.{e['team']['abbreviation']} {stat(e, 'points')}pts ({stat(e, 'pointDifferential')})" for e in rows)
    d = get(f"{ESPN}/site/v2/sports/soccer/fifa.world/scoreboard")
    games = []
    for e in d.get("events", [])[:4]:
        c = e["competitions"][0]
        teams = sorted(c["competitors"], key=lambda t: t.get("homeAway") != "home")
        status = c["status"]["type"]
        when = status.get("shortDetail", "")
        score = f"{teams[0]['team']['abbreviation']} {teams[0].get('score', '')}-{teams[1].get('score', '')} {teams[1]['team']['abbreviation']}"
        games.append(f"{score} ({when})" if status.get("state") != "pre" else f"{teams[0]['team']['abbreviation']} v {teams[1]['team']['abbreviation']} {when}")
    season = (d.get("leagues") or [{}])[0].get("season", {})
    stage = (season.get("type") or {}).get("name", "")
    return ("WC " + (stage + ": " if stage else "") + "; ".join(games)) if games else "WC: no World Cup games on the schedule right now"


class Addon(AddonBase):
    title = "Fun bot"
    version = "1.0.5"
    author = "mcIRC"
    description = ("dice, roll, magic8, joke, dadjoke, hacker, catfact and wc (World Cup scores and tables) - each switched on for the channels you "
                   "choose. Off until you switch it on.")
    tick_seconds = 0
    switch = "enabled"           # its ON/OFF switch on the toolbar

    def on_load(self):
        self.limiter = mc.Limiter(per_user=int(self.api.get("cooldown", 20)), gap=5)
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.help_for)      # (mcIRC 1.5.2 and later)

    USAGE = {"dice": "dice 3d6", "magic8": "magic8 <question>", "wc": "wc [group]"}

    def help_for(self, channel, dm=False):
        """For 'bothelp': the commands answered in this channel right now."""
        if not self.api.get("enabled", False) or (dm and not self.api.get("answer_dm", False)): return []
        p = self.api.get("prefix", "")
        return [p + self.USAGE.get(c, c) for c in COMMANDS if self.where(c) and (dm or mc.channel_ok(channel, self.where(c)))]

    def on_unload(self): pass

    def where(self, cmd):
        """Channels a command answers in: {'#bot-van', 'public'} / {'*'}; empty = switched off."""
        return mc.channel_list(self.api.get("channels", {}).get(cmd, ""))

    def on_message(self, msg):
        if not self.api.get("enabled", False): return
        hit = mc.parse_command(msg.get("text", ""), set(COMMANDS), self.api.get("prefix", ""))
        if not hit: return
        cmd, arg = hit
        if msg.get("dm"):
            if not (self.api.get("answer_dm", False) and self.where(cmd)): return
        elif not mc.channel_ok(msg.get("channel", ""), self.where(cmd)):
            return
        if not self.limiter.allow(msg.get("nick", "?")): return
        if cmd == "wc": self.api.run_background(lambda: world_cup(arg), lambda r: self.send(msg, cmd, r))
        else:
            try: self.send(msg, cmd, self.answer(cmd, arg))
            except ValueError as e: self.send(msg, cmd, e)

    def answer(self, cmd, arg):
        if cmd == "dice": return roll_dice(arg or "d6")
        if cmd == "roll": return roll(arg)
        if cmd == "magic8": return "\U0001F3B1 " + random.choice(data.MAGIC8)
        if cmd == "joke": return random.choice(data.JOKES)
        if cmd == "dadjoke": return random.choice(data.DADJOKES)
        if cmd == "hacker": return data.hacker()
        if cmd == "catfact": return "\U0001F431 " + random.choice(data.CATFACTS)
        raise ValueError("unknown command")

    def send(self, msg, cmd, result):
        if isinstance(result, ValueError): text = f"{cmd}: {result}"
        elif isinstance(result, Exception):
            self.api.log(f"{cmd} failed: {result}", "warn")
            text = f"{cmd}: not reachable right now, try later"
        else: text = result
        mc.send_parts(self.api, msg, text, max_parts=2)

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_on = tk.BooleanVar(value=self.api.get("enabled", False))
        self.v_dm = tk.BooleanVar(value=self.api.get("answer_dm", False))
        self.v_prefix = tk.StringVar(value=self.api.get("prefix", ""))
        self.v_cool = tk.StringVar(value=str(self.api.get("cooldown", 20)))
        tk.Checkbutton(f, text="Answer fun commands (sends to the mesh when someone asks)", variable=self.v_on, bg=bg).pack(anchor="w")
        tk.Label(f, text="For each command, the channels it answers in (comma separated, 'all', or blank = off):", bg=bg).pack(anchor="w", pady=(6, 2))
        grid = tk.Frame(f, bg=bg)
        grid.pack(anchor="w")
        saved = self.api.get("channels", {})
        self.v_ch = {}
        for i, (c, what) in enumerate(COMMANDS.items()):
            self.v_ch[c] = tk.StringVar(value=saved.get(c, ""))
            tk.Label(grid, text=c, bg=bg, width=8, anchor="w").grid(row=i, column=0, sticky="w")
            tk.Entry(grid, textvariable=self.v_ch[c], width=24).grid(row=i, column=1, padx=4, pady=1)
            tk.Label(grid, text=what, bg=bg, fg="#555", anchor="w").grid(row=i, column=2, sticky="w")
        r = tk.Frame(f, bg=bg)
        r.pack(anchor="w", pady=(6, 0))
        tk.Button(r, text="Use #bot-van for all", command=lambda: [v.set("#bot-van") for v in self.v_ch.values()]).pack(side="left")
        tk.Button(r, text="Clear all", command=lambda: [v.set("") for v in self.v_ch.values()]).pack(side="left", padx=4)
        for label, var, width in (("Command prefix (blank: 'joke' and '!joke' both work; '!' = only '!joke'):", self.v_prefix, 4),
                                  ("Seconds before the same person gets another answer:", self.v_cool, 6)):
            r = tk.Frame(f, bg=bg)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=bg).pack(side="left")
            tk.Entry(r, textvariable=var, width=width).pack(side="left", padx=4)
        tk.Checkbutton(f, text="Also answer private messages (for the commands that are on somewhere)", variable=self.v_dm, bg=bg).pack(anchor="w")
        return f

    def apply_options(self):
        self.api.set("enabled", self.v_on.get())
        self.api.set("answer_dm", self.v_dm.get())
        self.api.set("prefix", self.v_prefix.get().strip())
        try: cool = max(5, int(self.v_cool.get()))
        except ValueError: cool = 20
        self.api.set("cooldown", cool)
        self.limiter.per_user = cool
        self.api.set("channels", {c: v.get().strip() for c, v in self.v_ch.items() if v.get().strip()})
