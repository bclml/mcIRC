"""Channel spotter: catches every #channel name people mention in messages and logs it in its own 'Channels spotted' window -
who mentioned it first, in which channel, when, and how often.  /spotted lists them.  Listens only, never transmits.
Off until you switch it on."""
import re
import time
import tkinter as tk

from gui_addons import AddonBase

NAME_RE = re.compile(r"(?<![\w#])#([a-z0-9][a-z0-9_-]{0,29})(?![\w-])", re.IGNORECASE)
MAX_KEPT = 500                     # the log keeps at most this many names (the least recently heard go first)
WINDOW = "Channels spotted"


def find_channels(text):
    """'join #Weather and #bot-van, not #1' -> ['#weather', '#bot-van'] (a name needs a letter; '#public' is Public, not a channel)."""
    out = []
    for m in NAME_RE.finditer(text or ""):
        name = "#" + m.group(1).lower()
        if re.search(r"[a-z]", name) and name != "#public" and name not in out: out.append(name)
    return out


def stamp(t): return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


class Addon(AddonBase):
    title = "Channel spotter"
    version = "1.0.0"
    author = "mcIRC"
    description = ("Logs every #channel name people mention in messages (who said it first, where, how often) in its own window; "
                   "/spotted lists them. Never transmits. Off until you switch it on.")
    tick_seconds = 60              # saves the log once a minute when something changed
    switch = "enabled"             # its ON/OFF switch on the toolbar

    def on_load(self):
        self.seen = dict(self.api.get("seen", {}))
        self.dirty = False
        self.api.add_command("spotted", self.cmd_spotted, "list the #channels people have mentioned (/spotted new: only ones your node lacks)")
        self.api.add_menu_item("Show spotted channels", lambda: self.cmd_spotted(""))

    def on_unload(self): self.save()
    def on_tick(self): self.save()

    def save(self):
        if self.dirty:
            self.api.set("seen", self.seen)
            self.dirty = False

    def mine(self):
        """The channels the node already has, lower case."""
        try: return {c.lower() for c in self.api.channels()}
        except Exception: return set()

    def on_message(self, msg):
        if not self.api.get("enabled", False): return
        if msg.get("dm") and not self.api.get("include_dm", False): return
        names = find_channels(msg.get("text"))
        if not names: return
        now, nick, where = time.time(), msg.get("nick", "?"), msg.get("channel", "?")
        here = (where or "").lower()
        mine = self.mine()
        for name in names:
            if name == here: continue                      # '#weather' said in #weather isn't news
            e = self.seen.get(name)
            if e:
                e["count"] += 1
                e["last"] = now
                if self.api.get("log_repeats", False): self.api.write(WINDOW, f"{name} again ({e['count']}x) - {nick} in {where}", "meta")
            else:
                self.seen[name] = {"first": now, "last": now, "count": 1, "by": nick, "where": where}
                note = "" if name not in mine else " (your node has it)"
                self.api.write(WINDOW, f"NEW {name} - mentioned by {nick} in {where}{note}", "info")
            self.dirty = True
        if len(self.seen) > MAX_KEPT:
            for name in sorted(self.seen, key=lambda n: self.seen[n]["last"])[:len(self.seen) - MAX_KEPT]: del self.seen[name]

    def cmd_spotted(self, arg):
        only_new = (arg or "").strip().lower() == "new"
        mine = self.mine()
        names = sorted(self.seen, key=lambda n: -self.seen[n]["count"])
        if only_new: names = [n for n in names if n not in mine]
        if not names:
            self.api.write(WINDOW, "Nothing your node lacks." if only_new and self.seen else "No channels spotted yet.", "meta")
            if not self.api.get("enabled", False): self.api.write(WINDOW, "Channel spotter is off - switch it on to start logging.", "meta")
            return
        self.api.write(WINDOW, f"--- {len(names)} channel(s) spotted, most mentioned first ---", "info")
        for n in names:
            e = self.seen[n]
            flag = " [on your node]" if n in mine else ""
            self.api.write(WINDOW, f"{n}{flag}: {e['count']}x, first {stamp(e['first'])} by {e['by']} in {e['where']}, last {stamp(e['last'])}", "text")

    def on_demo(self):
        for nick, chan, text in (("Demo Alice", "Public", "anyone on #demo-weather? also try #demo-bots"),
                                 ("Demo Bob", "#demo-bots", "#demo-weather has the forecast"),
                                 ("Demo Carol", "Public", "We're #1! join #demo-net")):
            self.on_message({"channel": chan, "channel_idx": 0, "nick": nick, "text": text, "snr": 0, "hops": 0, "raw": None})

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        g = self.api.get
        self.v = {"enabled": tk.BooleanVar(value=g("enabled", False)), "include_dm": tk.BooleanVar(value=g("include_dm", False)),
                  "log_repeats": tk.BooleanVar(value=g("log_repeats", False))}
        tk.Checkbutton(f, text="Log #channel names people mention", variable=self.v["enabled"], bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text="Also look in private messages", variable=self.v["include_dm"], bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text="Write a line every time a known name comes up again (not only new ones)", variable=self.v["log_repeats"], bg=bg).pack(anchor="w")
        tk.Label(f, text=f"It only listens - nothing is ever sent. Keeps up to {MAX_KEPT} names; /spotted lists them.", bg=bg, fg="#555").pack(anchor="w", pady=(6, 0))
        tk.Button(f, text="Clear the log", command=self.clear).pack(anchor="w", pady=(6, 0))
        return f

    def clear(self):
        self.seen = {}
        self.api.set("seen", {})
        self.dirty = False
        self.api.write(WINDOW, "Log cleared.", "meta")

    def apply_options(self):
        for k, var in self.v.items(): self.api.set(k, var.get())
