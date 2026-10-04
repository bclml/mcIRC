"""Tool 2 - channel manager: the node's channel slots - add (a #hashtag channel gets its key from its name, a private one needs the key),
rename, change the key, remove, and copy a channel's key to share it.  Duplicate channels are pointed out."""
import re
import secrets
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ntools_common import BG, ToolWindow, docs, run

HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


def read_channels():
    """[{channel_idx, channel_name, channel_secret, channel_hash}] for the used slots."""
    out = []
    for d in docs(run(".get_channels")):
        rows = d if isinstance(d, list) else [d]
        out += [c for c in rows if isinstance(c, dict) and c.get("channel_name")]
    return sorted(out, key=lambda c: c["channel_idx"])


def duplicates(chs):
    seen, dup = {}, set()
    for c in chs:
        key = (c["channel_name"].lower().lstrip("#"), c.get("channel_secret"))
        if key in seen: dup.add(c["channel_idx"])
        seen.setdefault(key, c["channel_idx"])
    return dup


def check_key(key):
    key = (key or "").strip().replace(" ", "")
    if key and not HEX32.match(key): raise ValueError("a channel key is 32 hex characters (16 bytes)")
    return key


class ChannelsWindow(ToolWindow):
    COLS = (("slot", 50), ("name", 170), ("hash", 50), ("key", 280))

    def __init__(self, api):
        super().__init__(api, "Node channels", "700x420")
        self.t = ttk.Treeview(self, columns=[c for c, _ in self.COLS], show="headings", selectmode="browse")
        for c, w in self.COLS:
            self.t.heading(c, text=c.capitalize())
            self.t.column(c, width=w, anchor="w")
        self.t.pack(fill="both", expand=True, padx=6, pady=6)
        self.t.tag_configure("dup", foreground="#c00000")
        b = tk.Frame(self, bg=BG)
        b.pack(fill="x", padx=6)
        for text, cmd in (("Refresh", self.read), ("Add...", self.add), ("Rename...", self.rename), ("Change key...", self.rekey),
                          ("Remove", self.remove), ("Copy key", self.copy_key)):
            ttk.Button(b, text=text, command=cmd).pack(side="left", padx=2)
        tk.Label(self, bg=BG, fg="#555", justify="left", wraplength=660,
                 text="A name starting with # is a public hashtag channel: everyone who adds the same name can read it (its key comes from the name). "
                      "For a private channel give it a 32-character key and share that key only with the people who should read it.").pack(anchor="w", padx=6)
        self.chs = []
        self.read()

    def selected(self):
        sel = self.t.selection()
        return next((c for c in self.chs if str(c["channel_idx"]) == sel[0]), None) if sel else None

    def on_node_change(self): self.read()

    def read(self):
        def show(chs):
            self.chs, dup = chs, duplicates(chs)
            self.t.delete(*self.t.get_children())
            for c in chs:
                self.t.insert("", "end", iid=str(c["channel_idx"]), values=(c["channel_idx"], c["channel_name"], c.get("channel_hash", ""), c.get("channel_secret", "")),
                              tags=("dup",) if c["channel_idx"] in dup else ())
            self.say(f"{len(chs)} channel(s)." + (f" Red = the same channel twice (slot {', '.join(map(str, sorted(dup)))}); you can remove the copy." if dup else ""))
        self.job("Reading the node's channels", read_channels, show)

    def _then_refresh(self, label, fn):
        def work():
            fn()
            if self.node_key == "main": self.api.refresh_channels()      # the channel windows in mcIRC follow (an extra node re-reads its own)
            return read_channels()
        self.job(label, work, lambda chs: (setattr(self, "chs", chs), self.read()))

    def add(self):
        name = simpledialog.askstring("Add channel", "Channel name (#name = public hashtag channel):", parent=self)
        if not name or not name.strip(): return
        name = name.strip()
        key = "" if name.startswith("#") else simpledialog.askstring("Add channel", "Key (32 hex characters), or leave empty to make a new random one:", parent=self) or ""
        try: key = check_key(key)
        except ValueError as e: return messagebox.showerror("Add channel", str(e), parent=self)
        if not name.startswith("#") and not key: key = secrets.token_hex(16)     # a private channel gets a random key (meshcli would derive it from the name)
        self._then_refresh(f"Adding {name}", lambda: run("add_channel", name, *([key] if key else [])))

    def rename(self):
        c = self.selected()
        if not c: return self.say("Select a channel first.")
        name = simpledialog.askstring("Rename channel", "New name:", initialvalue=c["channel_name"], parent=self)
        if not name or name.strip() == c["channel_name"]: return
        self._then_refresh(f"Renaming slot {c['channel_idx']}", lambda: run("set_channel", c["channel_idx"], name.strip(), c["channel_secret"]))

    def rekey(self):
        c = self.selected()
        if not c: return self.say("Select a channel first.")
        key = simpledialog.askstring("Change key", "New key (32 hex characters). Everyone on this channel needs the same key:", parent=self)
        try: key = check_key(key)
        except ValueError as e: return messagebox.showerror("Change key", str(e), parent=self)
        if not key: return
        self._then_refresh(f"Changing the key of {c['channel_name']}", lambda: run("set_channel", c["channel_idx"], c["channel_name"], key))

    def remove(self):
        c = self.selected()
        if not c: return self.say("Select a channel first.")
        if c["channel_idx"] == 0: return messagebox.showinfo("Remove channel", "Public (slot 0) can't be removed.", parent=self)
        if not messagebox.askyesno("Remove channel", f"Remove {c['channel_name']} (slot {c['channel_idx']}) from the node?", parent=self): return
        self._then_refresh(f"Removing {c['channel_name']}", lambda: run("remove_channel", c["channel_idx"]))

    def copy_key(self):
        c = self.selected()
        if not c: return self.say("Select a channel first.")
        self.clipboard_clear()
        self.clipboard_append(c.get("channel_secret", ""))
        self.say(f"Key of {c['channel_name']} copied.")
