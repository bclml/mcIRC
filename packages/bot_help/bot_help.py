"""Bot help: answers 'bothelp' with the commands the bots answer in that channel (every bot addon that registers its commands),
and can announce 'Type bothelp for a list of commands.' once a day at a set time.  Off until you switch it on."""
import datetime as dt
import re
import time
import tkinter as tk

from gui_addons import AddonBase

DEFAULT_TEXT = "Type bothelp for a list of commands."
MAX_CHARS = 115


def norm(ch):
    n = re.sub(r"\s*\[[^\]]*\]$", "", (ch or "").strip().lower())      # ('Public [915]' = Public on an extra node)
    if n in ("public", "#public"): return "public"
    return n if n.startswith("#") else "#" + n if n else ""


def channel_set(text): return {norm(x) for x in re.split(r"[,;\s]+", text or "") if x.strip()}


def help_lines(found, limit=MAX_CHARS, max_parts=3):
    """{'Weather bot': ['wx <place>', 'moon'], 'Fun bot': ['joke']} -> mesh-sized messages: 'Weather bot: wx <place>, moon | Fun bot: joke'."""
    parts, cur = [], ""
    for title, cmds in found.items():
        piece = f"{title}: " + ", ".join(cmds)
        for chunk in ([piece] if len(piece) <= limit else _wrap(piece, limit)):
            joined = chunk if not cur else cur + " | " + chunk
            if len(joined) <= limit: cur = joined
            else:
                parts.append(cur)
                cur = chunk
    if cur: parts.append(cur)
    if len(parts) > max_parts: parts = parts[:max_parts - 1] + [parts[max_parts - 1][:limit - 1] + "…"]
    return parts


def _wrap(text, limit):
    out, cur = [], ""
    for word in text.split(" "):
        if len(cur) + len(word) + 1 > limit:
            out.append(cur)
            cur = word
        else: cur = (cur + " " + word).strip()
    return out + ([cur] if cur else [])


class Addon(AddonBase):
    title = "Bot help"
    version = "1.0.5"
    author = "mcIRC"
    description = ("Answers 'bothelp' with the bot commands that work in that channel (Weather bot, Fun bot, Auto reply, ...), and can announce "
                   "'Type bothelp for a list of commands.' once a day at a set time. Off until you switch it on.")
    tick_seconds = 30
    switch = "enabled"           # its ON/OFF switch on the toolbar

    def on_load(self):
        self.last_any, self.last_by = 0.0, {}

    def on_unload(self): pass

    def found(self, channel, dm=False):
        if not hasattr(self.api, "bot_commands"): return {}
        hidden = set(self.api.get("hidden", []))                 # bots switched off in Options: not listed, not announced for
        return {t: c for t, c in self.api.bot_commands(channel, dm).items() if t != self.title and t not in hidden}

    # ---- answering 'bothelp' ----
    def on_message(self, msg):
        if not self.api.get("enabled", False): return
        text = (msg.get("text") or "").strip().lower()
        if text not in ("bothelp", "!bothelp", "bothelp?", "!bothelp?"): return
        if msg.get("dm") and not self.api.get("answer_dm", True): return
        now, who = time.time(), msg.get("nick", "?")
        if now - self.last_any < 5 or now - self.last_by.get(who, 0) < 60: return       # one answer per person per minute
        found = self.found(msg.get("channel", ""), bool(msg.get("dm")))
        if not found: return                                     # no bot answers here: stay quiet
        self.last_any = self.last_by[who] = now
        for i, part in enumerate(help_lines(found)):
            self.api.after(5000 + i * 9000, lambda p=part: self.api.reply(msg, p))      # wait for the repeats of the question to die down first

    # ---- the daily announcement ----
    def announce_channels(self):
        chosen = channel_set(self.api.get("announce_channels", ""))
        if chosen: return sorted(chosen)
        return sorted(norm(c) for c in self.api.channels() if self.found(c))      # blank = every channel where a bot answers

    def on_tick(self, now=None):
        if not (self.api.get("enabled", False) and self.api.get("announce", False) and self.api.connected): return
        now = now or dt.datetime.now()
        try: hh, mm = (int(x) for x in str(self.api.get("announce_time", "19:00")).split(":"))
        except ValueError: return
        due = now.replace(hour=hh % 24, minute=mm % 60, second=0, microsecond=0)
        today = now.date().isoformat()
        if self.api.get("announced_on", "") == today or not (due <= now < due + dt.timedelta(minutes=10)): return
        self.api.set("announced_on", today)                      # once a day, even across a restart
        text = (self.api.get("announce_text", DEFAULT_TEXT) or DEFAULT_TEXT)[:MAX_CHARS]
        for i, ch in enumerate(self.announce_channels()):
            self.api.after(i * 5000, lambda c=ch: self.api.send("Public" if c == "public" else c, text))

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        g = self.api.get
        self.v = {"enabled": tk.BooleanVar(value=g("enabled", False)), "answer_dm": tk.BooleanVar(value=g("answer_dm", True)),
                  "announce": tk.BooleanVar(value=g("announce", False)), "announce_time": tk.StringVar(value=g("announce_time", "19:00")),
                  "announce_text": tk.StringVar(value=g("announce_text", DEFAULT_TEXT)), "announce_channels": tk.StringVar(value=g("announce_channels", ""))}
        tk.Checkbutton(f, text="Answer 'bothelp' with the bot commands that work in that channel", variable=self.v["enabled"], bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text="Also answer 'bothelp' in private messages", variable=self.v["answer_dm"], bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text="Announce it once a day", variable=self.v["announce"], bg=bg).pack(anchor="w", pady=(8, 0))
        for label, key, width in (("Time (HH:MM, 24-hour):", "announce_time", 6), ("Message:", "announce_text", 44),
                                  ("Channels (blank = every channel where a bot answers):", "announce_channels", 24)):
            r = tk.Frame(f, bg=bg)
            r.pack(fill="x", pady=1, padx=(20, 0))
            tk.Label(r, text=label, bg=bg).pack(side="left")
            tk.Entry(r, textvariable=self.v[key], width=width).pack(side="left", padx=4)
        tk.Label(f, text="List these bots in 'bothelp' (untick to leave one out):", bg=bg).pack(anchor="w", pady=(8, 0))
        names = [n for n in (self.api.bot_names() if hasattr(self.api, "bot_names") else []) if n != self.title]
        hidden = set(self.api.get("hidden", []))
        self.v_bots = {}
        box = tk.Frame(f, bg=bg)
        box.pack(anchor="w", padx=(20, 0))
        for n in names:
            self.v_bots[n] = tk.BooleanVar(value=n not in hidden)
            tk.Checkbutton(box, text=n, variable=self.v_bots[n], bg=bg).pack(anchor="w")
        if not names: tk.Label(box, text="(no bot addons are switched on yet)", bg=bg, fg="#555").pack(anchor="w")
        self.preview = tk.Label(f, bg=bg, fg="#555", justify="left", wraplength=440, anchor="w")
        self.preview.pack(anchor="w", pady=(8, 0))
        tk.Button(f, text="Show what 'bothelp' answers in each channel", command=self.show_preview).pack(anchor="w", pady=2)
        return f

    def show_preview(self):
        lines = []
        for ch in self.api.channels():
            found = self.found(ch)
            lines.append(f"{ch}: " + (" / ".join(help_lines(found)) if found else "(no bot answers here - bothelp stays quiet)"))
        self.preview.config(text="\n".join(lines) or "No channels yet.")

    def apply_options(self):
        t = self.v["announce_time"].get().strip()
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            t = "19:00"
            self.v["announce_time"].set(t)
        keep = set(self.api.get("hidden", [])) - set(self.v_bots)        # bots not loaded right now keep their setting
        self.api.set("hidden", sorted(keep | {n for n, v in self.v_bots.items() if not v.get()}))
        for k, var in self.v.items():
            val = var.get()
            self.api.set(k, t if k == "announce_time" else val.strip() if isinstance(val, str) else val)
