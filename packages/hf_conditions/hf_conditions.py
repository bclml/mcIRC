"""HF conditions bot, for amateur radio operators: someone types 'hf' (or your own trigger words) and gets the HF band conditions right now -
solar flux, sunspots, A / K index, X-rays, noise, and Good / Fair / Poor for each band group by day and night.  Data: hamqsl.com (N0NBH),
free, no key; fetched at most every 30 minutes (it changes every few hours).  Only in the channels you choose - never in Public - and
in private messages if you allow it.  Off until you switch it on; one answer per person a minute."""
import time
import tkinter as tk
import xml.etree.ElementTree as ET

from gui_addons import AddonBase
import meshbot_common as mc

URL = "https://www.hamqsl.com/solarxml.php"
DEFAULT_TRIGGERS = "hf, condx, bands, propagation"
CACHE = 1800                       # seconds a fetched report is reused
DEFAULT_COOLDOWN = 60


def is_public(name): return mc.norm_channel(name or "") in ("public", "#public", "")


def norm_text(text):
    """What was typed, as a trigger is matched: no '@[bot]' in front, no '!' / '/' / '.', lower case, single spaces."""
    t = mc.ADDRESSED.sub("", (text or "").strip(), count=1)
    if t[:1] in mc.CALL_MARKS: t = t[1:]
    return " ".join(t.lower().rstrip("?.!").split())


def trigger_list(text):
    """'hf, Condx,  hf conditions' -> ['hf', 'condx', 'hf conditions'] (one or more words each, each once)."""
    out = []
    for part in (text or "").split(","):
        t = norm_text(part)
        if t and t not in out: out.append(t)
    return out


def asked(text, triggers):
    """The message is a trigger, alone or followed by more words ('hf', 'hf please', '@[Bot] !condx')."""
    t = norm_text(text)
    return any(t == trig or t.startswith(trig + " ") for trig in triggers)


def k_word(k):
    return "quiet" if k < 4 else "active" if k < 5 else f"storm G{min(5, k - 4)}"


def report(xml_text):
    """hamqsl's solarxml -> one answer; ' | ' marks where it may be split into mesh-sized parts."""
    sd = ET.fromstring(xml_text).find("solardata")
    if sd is None: raise ValueError("no solar data in the answer")
    val = lambda tag: (sd.findtext(tag) or "").strip()
    when = val("updated").split()
    stamp = f" {when[3]}Z" if len(when) >= 4 and when[3].isdigit() else ""
    head = [f"SFI {val('solarflux') or '?'}", f"SSN {val('sunspots') or '?'}", f"A {val('aindex') or '?'}"]
    k = val("kindex")
    head.append(f"K {k} ({k_word(int(k))})" if k.isdigit() else f"K {k or '?'}")
    if val("xray"): head.append(f"X-ray {val('xray')}")
    if val("signalnoise"): head.append(f"noise {val('signalnoise')}")
    bands = {"day": [], "night": []}
    for b in sd.iter("band"):
        if b.get("time") in bands: bands[b.get("time")].append(f"{b.get('name', '?')} {(b.text or '?').strip()}")
    parts = [f"HF{stamp}: " + ", ".join(head)]
    for when_, label in (("day", "Day"), ("night", "Night")):
        if bands[when_]: parts.append(f"{label}: " + ", ".join(bands[when_]))
    vhf = [f"{p.get('name')} {p.get('location', '').replace('_', ' ')}".strip() for p in sd.iter("phenomenon")
           if (p.text or "").strip().lower() not in ("band closed", "")]
    if vhf: parts.append("VHF open: " + ", ".join(vhf))
    return " | ".join(parts)


class Addon(AddonBase):
    title = "HF conditions"
    version = "1.0.0"
    author = "mcIRC"
    description = ("For amateur radio operators: 'hf' (your own trigger words) answers with the HF band conditions now - solar flux, sunspots, "
                   "A / K index, noise, and Good / Fair / Poor per band by day and night (hamqsl.com). Only in the channels you choose, never in "
                   "Public. Off until you switch it on.")
    tick_seconds = 0
    switch = "enabled"           # its ON/OFF switch on the toolbar

    def on_load(self):
        self.limiter = mc.Limiter(per_user=self.cooldown(), gap=5)
        self.cached, self.cached_at, self.busy = "", 0.0, False
        self.waiting = []                                   # questions asked while a fetch is running: all answered by it
        if hasattr(self.api, "add_bot_commands"): self.api.add_bot_commands(self.help_for)

    def on_unload(self): self.waiting = []

    def cooldown(self):
        try: return max(10, int(self.api.get("cooldown", DEFAULT_COOLDOWN)))
        except (TypeError, ValueError): return DEFAULT_COOLDOWN

    def triggers(self): return trigger_list(self.api.get("triggers", DEFAULT_TRIGGERS))

    def where(self):
        """The channels it answers in ({'#hf'} / {'*'}); never Public, even when 'All channels' is picked."""
        return {c for c in mc.channel_list(self.api.get("channels", "")) if not is_public(c)}

    def channel_allowed(self, channel):
        return not is_public(channel) and mc.channel_ok(channel, self.where())

    def channels_used(self):
        """Where it answers (mcIRC adds these to the node when it lacks them)."""
        return sorted(c for c in self.where() if c != "*") if self.api.get("enabled", False) else []

    def help_for(self, channel, dm=False):
        """For 'bothelp': its first trigger word, where it answers."""
        if not self.api.get("enabled", False) or not self.triggers(): return []
        if dm: return [self.triggers()[0]] if self.api.get("answer_dm", True) and self.where() else []
        return [self.triggers()[0]] if self.channel_allowed(channel) else []

    def on_message(self, msg):
        if not self.api.get("enabled", False) or not asked(msg.get("text"), self.triggers()): return
        if msg.get("dm"):
            if not (self.api.get("answer_dm", True) and self.where()): return
        elif not self.channel_allowed(msg.get("channel", "")):
            return
        if not self.limiter.allow(msg.get("nick", "?")): return
        if self.cached and time.time() - self.cached_at < CACHE: return self.send(msg, self.cached)
        self.waiting.append(msg)
        if self.busy: return
        self.busy = True
        self.api.run_background(lambda: report(mc.http_get(URL, timeout=15).decode("utf-8", "replace")), self.fetched)

    def fetched(self, result):
        self.busy = False
        waiting, self.waiting = self.waiting, []
        if isinstance(result, Exception):
            self.api.log(f"HF conditions: couldn't read hamqsl.com ({result})", "warn")
            result = "HF conditions: not reachable right now, try later"
        else:
            self.cached, self.cached_at = result, time.time()
        for msg in waiting: self.send(msg, result)

    def send(self, msg, text):
        if not msg.get("dm") and is_public(msg.get("channel", "")): return          # (never in Public, whatever happens)
        mc.send_parts(self.api, msg, text, max_parts=3)

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        g = self.api.get
        self.v_on = tk.BooleanVar(value=g("enabled", False))
        self.v_dm = tk.BooleanVar(value=g("answer_dm", True))
        self.v_trig = tk.StringVar(value=g("triggers", DEFAULT_TRIGGERS))
        self.v_chan = tk.StringVar(value=g("channels", ""))
        self.v_cool = tk.StringVar(value=str(self.cooldown()))
        tk.Checkbutton(f, text="Answer HF condition requests (sends to the mesh when someone asks)", variable=self.v_on, bg=bg).pack(anchor="w")
        r = tk.Frame(f, bg=bg)
        r.pack(fill="x", pady=(6, 1))
        tk.Label(r, text="Trigger words (comma separated; one or more words each):", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_trig, width=32).pack(side="left", padx=4)
        tk.Button(r, text="Default", command=lambda: self.v_trig.set(DEFAULT_TRIGGERS)).pack(side="left")
        tk.Label(f, text="Answers 'hf', '!hf', '@[bot] hf' and 'hf please' alike. (Area alerts' weather commands answer 'hfcond' - "
                         "leave that word out here if both are on.)", bg=bg, fg="#555", wraplength=520, justify="left").pack(anchor="w", padx=20)
        r = tk.Frame(f, bg=bg)
        r.pack(fill="x", pady=(6, 1))
        tk.Label(r, text="Answer in these channels (Add, or x to remove; never Public):", bg=bg).pack(side="left", anchor="n")
        mc.chan_field(r, self.v_chan, 24, all_option=True, public=False, empty="(none - add one)").pack(side="left", padx=4)
        tk.Checkbutton(f, text="Also answer private messages", variable=self.v_dm, bg=bg).pack(anchor="w")
        r = tk.Frame(f, bg=bg)
        r.pack(fill="x", pady=1)
        tk.Label(r, text="Seconds before the same person gets another answer:", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_cool, width=6).pack(side="left", padx=4)
        self.preview = tk.Label(f, bg=bg, fg="#555", wraplength=520, justify="left", anchor="w",
                                text="The answer looks like: HF 1500Z: SFI 145, SSN 120, A 8, K 2 (quiet), X-ray C1.2, noise S2-S3 | "
                                     "Day: 80m-40m Good, 30m-20m Good, 17m-15m Fair, 12m-10m Poor | Night: ...")
        self.preview.pack(anchor="w", pady=(6, 0))
        tk.Label(f, text="Data: hamqsl.com (N0NBH), free; read at most every 30 minutes.", bg=bg, fg="#555").pack(anchor="w")
        return f

    def apply_options(self):
        self.api.set("enabled", self.v_on.get())
        self.api.set("answer_dm", self.v_dm.get())
        self.api.set("triggers", ", ".join(trigger_list(self.v_trig.get())) or DEFAULT_TRIGGERS)
        chans = [c.strip() for c in self.v_chan.get().replace(";", ",").split(",") if c.strip() and not is_public(c)]
        self.api.set("channels", ", ".join(chans))
        try: cool = max(10, int(self.v_cool.get()))
        except ValueError: cool = DEFAULT_COOLDOWN
        self.api.set("cooldown", cool)
        self.limiter.per_user = cool
