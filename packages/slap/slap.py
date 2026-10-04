"""/slap <nick>: the old IRC joke, as a one-line channel message."""
import re
import time
import tkinter as tk

from gui_addons import AddonBase

MIN_GAP = 10          # seconds between two slaps: the mesh is a tiny shared channel


class Addon(AddonBase):
    title = "Slap"
    version = "1.0.2"
    author = "mcIRC"
    description = "/slap Nick slaps Nick around a bit with a large trout (change the fish in Options). Only sends when you type the command."
    tick_seconds = 0

    def on_load(self):
        self._last = 0.0
        self.api.add_command("slap", self.cmd_slap, "/slap <nick>: slap someone around a bit with a large trout")

    def on_unload(self): pass

    def line(self, nick):
        item = (self.api.get("item", "a large trout") or "a large trout").strip()
        return f"slaps @[{nick}] around a bit with {item}"

    def cmd_slap(self, arg):
        nick = re.sub(r"[\[\]@]", "", arg).strip()
        if not nick: return self.api.notice("Usage: /slap <nick>", "warn")
        if time.time() - self._last < MIN_GAP: return self.api.notice(f"Easy there - one slap every {MIN_GAP} seconds.", "warn")
        if not self.api.send_current(self.line(nick[:32])): return self.api.notice("Open a channel or private window first - /slap sends to the window in front.", "warn")
        self._last = time.time()

    def build_options(self, parent):
        self.v_item = tk.StringVar(value=self.api.get("item", "a large trout"))
        f = tk.Frame(parent, bg=parent["bg"])
        tk.Label(f, text="Slap with:", bg=parent["bg"]).pack(side="left")
        tk.Entry(f, textvariable=self.v_item, width=36).pack(side="left", padx=6)
        return f

    def apply_options(self):
        self.api.set("item", self.v_item.get().strip()[:60] or "a large trout")
