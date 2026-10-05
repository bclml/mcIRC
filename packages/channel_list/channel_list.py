"""Channel list bot: someone types 'channel list' and gets the list of channels you keep (Options: add, remove, rename, reorder).
'channel list add #name' adds a channel to it (can be switched off; checked names only, a size limit, and you see who added what).
Off until you switch it on; one answer per person per minute."""
import re
import time
import tkinter as tk

from gui_addons import AddonBase
import meshbot_common as mc

DEFAULT_CHANNELS = ["Public", "#bc", "#bcferries", "#bctransit", "#drivebc", "#kod-bot", "#news", "#ssi", "#translink", "#vanisle",
                    "#wardrive", "#wardriving", "#weather"]
DEFAULT_TRIGGERS = "channel list, channels list, !channels"
MAX_CHANNELS = 30                                  # 'channel list add' stops here (the answer has to fit a few mesh messages)
ADD_RE = re.compile(r"channel list add(?:\s+(\S+))?\s*", re.IGNORECASE)      # the one way to type it: channel list add #name
NAME_RE = re.compile(r"#[a-z0-9][a-z0-9_-]{0,29}", re.IGNORECASE)
ADD_HOW = "Type it like this: channel list add #name (letters, digits, - or _)"


def norm_text(t): return re.sub(r"[^a-z0-9!#]+", " ", (t or "").lower()).strip()


def answer_text(channels, intro="Channels:"):
    return f"{intro} " + ", ".join(channels)


class Addon(AddonBase):
    title = "Channel list"
    version = "1.1.0"
    author = "mcIRC"
    description = ("Answers 'channel list' with the channels you keep in its list (add / remove / rename / reorder them in Options); "
                   "'channel list add #name' adds one from the mesh. Off until you switch it on.")
    tick_seconds = 0

    def on_load(self):
        self.last_any, self.last_by = 0.0, {}
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.help_for)

    def on_unload(self): pass

    def channels(self): return list(self.api.get("list", DEFAULT_CHANNELS))
    def triggers(self): return {norm_text(t) for t in self.api.get("triggers", DEFAULT_TRIGGERS).split(",") if t.strip()}

    def help_for(self, channel, dm=False):
        if not self.api.get("enabled", False): return []
        if (dm and not self.api.get("answer_dm", True)) or (not dm and not mc.channel_ok(channel, mc.channel_list(self.api.get("where", "all")))): return []
        first = next((t.strip() for t in self.api.get("triggers", DEFAULT_TRIGGERS).split(",") if t.strip()), "")
        if not first: return []
        return [first] + (["channel list add #name"] if self.api.get("allow_add", True) else [])

    def add_request(self, text):
        """'channel list add #lse-bot' -> '#lse-bot'; '' when the name is missing or not usable (the answer shows how to type it);
        None when it's not 'channel list add'."""
        m = ADD_RE.fullmatch((text or "").strip())
        if not m: return None
        name = m.group(1) or ""
        if not NAME_RE.fullmatch(name) or name.lower() == "#public": return ""
        return name.lower()

    def handle_add(self, msg, name):
        """Adds the channel and says so (the caller has checked where and how often)."""
        if not name: return ADD_HOW
        chans = self.channels()
        if name.lower() in (c.lower() for c in chans): return f"{name} is already in the channel list."
        if len(chans) >= MAX_CHANNELS: return f"The channel list is full ({MAX_CHANNELS})."
        self.api.set("list", chans + [name])
        self.api.log(f"{msg.get('nick', '?')} added {name} to the channel list (remove it in the Channel list settings if you don't want it).", "info")
        return f"Added {name} to the channel list."

    def on_message(self, msg):
        if not self.api.get("enabled", False): return
        add = self.add_request(msg.get("text")) if self.api.get("allow_add", True) else None
        if add is None and norm_text(msg.get("text")) not in self.triggers(): return
        if msg.get("dm"):
            if not self.api.get("answer_dm", True): return
        elif not mc.channel_ok(msg.get("channel", ""), mc.channel_list(self.api.get("where", "all"))):
            return
        now, who = time.time(), msg.get("nick", "?")
        if now - self.last_any < 5 or now - self.last_by.get(who, 0) < 60: return
        if add is not None:
            self.last_any = self.last_by[who] = now
            return mc.send_parts(self.api, msg, self.handle_add(msg, add), max_parts=1)
        chans = self.channels()
        if not chans: return
        self.last_any = self.last_by[who] = now
        mc.send_parts(self.api, msg, answer_text(chans, self.api.get("intro", "Channels:")), max_parts=3)

    # ---- options: the list itself ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        g = self.api.get
        self.v = {"enabled": tk.BooleanVar(value=g("enabled", False)), "answer_dm": tk.BooleanVar(value=g("answer_dm", True)),
                  "where": tk.StringVar(value=g("where", "all")), "triggers": tk.StringVar(value=g("triggers", DEFAULT_TRIGGERS)),
                  "intro": tk.StringVar(value=g("intro", "Channels:")), "allow_add": tk.BooleanVar(value=g("allow_add", True))}
        tk.Checkbutton(f, text="Answer 'channel list' with the list below", variable=self.v["enabled"], bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text="Also answer private messages", variable=self.v["answer_dm"], bg=bg).pack(anchor="w")
        tk.Checkbutton(f, text=f"Let people add channels: 'channel list add #name' (checked names, at most {MAX_CHANNELS}; you see who added what)",
                       variable=self.v["allow_add"], bg=bg, wraplength=460, justify="left").pack(anchor="w")
        for label, key, width in (("Answer in channels (comma separated, or 'all'):", "where", 24), ("Words that ask for it (comma separated):", "triggers", 30),
                                  ("Answer starts with:", "intro", 20)):
            r = tk.Frame(f, bg=bg)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=bg).pack(side="left")
            tk.Entry(r, textvariable=self.v[key], width=width).pack(side="left", padx=4)
        tk.Label(f, text="The list (in this order):", bg=bg).pack(anchor="w", pady=(6, 0))
        row = tk.Frame(f, bg=bg)
        row.pack(fill="x")
        self.lb = tk.Listbox(row, height=9, width=28, exportselection=False)
        self.lb.pack(side="left")
        for c in self.channels(): self.lb.insert("end", c)
        btns = tk.Frame(row, bg=bg)
        btns.pack(side="left", padx=6, anchor="n")
        self.entry = tk.StringVar()
        tk.Entry(btns, textvariable=self.entry, width=18).pack(anchor="w")
        for text, cmd in (("Add", self.add), ("Rename to this", self.rename), ("Remove", self.remove), ("Move up", lambda: self.move(-1)),
                          ("Move down", lambda: self.move(1)), ("Sort A-Z", self.sort), ("Add my node's channels", self.add_mine)):
            tk.Button(btns, text=text, command=cmd, width=20).pack(anchor="w", pady=1)
        self.lb.bind("<<ListboxSelect>>", lambda e: self.entry.set(self.lb.get(self.lb.curselection()[0]) if self.lb.curselection() else ""))
        self.preview = tk.Label(f, bg=bg, fg="#555", wraplength=440, justify="left", anchor="w")
        self.preview.pack(anchor="w", pady=(6, 0))
        self.show_preview()
        return f

    @staticmethod
    def clean(name):
        n = (name or "").strip()
        if not n: return ""
        return "Public" if n.lower() in ("public", "#public") else (n if n.startswith("#") else "#" + n)

    def items(self): return list(self.lb.get(0, "end"))

    def add(self):
        n = self.clean(self.entry.get())
        if n and n.lower() not in (x.lower() for x in self.items()): self.lb.insert("end", n)
        self.show_preview()

    def rename(self):
        sel, n = self.lb.curselection(), self.clean(self.entry.get())
        if sel and n:
            self.lb.delete(sel[0]); self.lb.insert(sel[0], n); self.lb.selection_set(sel[0])
        self.show_preview()

    def remove(self):
        for i in reversed(self.lb.curselection()): self.lb.delete(i)
        self.show_preview()

    def move(self, step):
        sel = self.lb.curselection()
        if not sel: return
        i, j = sel[0], sel[0] + step
        if 0 <= j < self.lb.size():
            v = self.lb.get(i); self.lb.delete(i); self.lb.insert(j, v); self.lb.selection_set(j)
        self.show_preview()

    def sort(self):
        items = sorted(self.items(), key=lambda c: (c != "Public", c.lower()))
        self.lb.delete(0, "end")
        for c in items: self.lb.insert("end", c)
        self.show_preview()

    def add_mine(self):
        have = {x.lower() for x in self.items()}
        for c in self.api.channels():
            n = self.clean(c)
            if n.lower() not in have: self.lb.insert("end", n); have.add(n.lower())
        self.show_preview()

    def show_preview(self):
        parts = mc.split_message(answer_text(self.items(), self.v["intro"].get() or "Channels:"))
        self.preview.config(text="The answer: " + "  /  ".join(parts) if parts else "The list is empty - nothing is answered.")

    def apply_options(self):
        for k, var in self.v.items():
            val = var.get()
            self.api.set(k, val.strip() if isinstance(val, str) else val)
        self.api.set("list", self.items())
