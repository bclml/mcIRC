"""Tool 3 - backup and restore: the node's settings, channels and contacts in one file (optionally its private key = its identity).
Restore writes back only what you tick; settings go through the same code as Options > Node, contacts are added with their key and name."""
import datetime as dt
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import gui_nodecfg as cfg
from gui_addons import BASE_DIR
from ntools_common import BG, ToolWindow, first, run
from ntools_channels import read_channels

BACKUP_DIR = os.path.join(BASE_DIR, "backup", "node")


def make_backup(include_key=False):
    node = cfg.read_node()
    data = {"mcirc_node_backup": 1, "saved": dt.datetime.now().isoformat(timespec="seconds"), "model": node["ver"].get("model"),
            "firmware": node["ver"].get("ver"), "name": node["info"].get("name"), "public_key": node["info"].get("public_key"),
            "settings": cfg.values_from(node), "channels": [{k: c[k] for k in ("channel_idx", "channel_name", "channel_secret")} for c in read_channels()],
            "contacts": [{k: c.get(k) for k in ("public_key", "type", "adv_name", "adv_lat", "adv_lon")} for c in (first(run(".contacts")) or {}).values()]}
    if include_key:
        pk = first(run(".get", "private_key")) or {}
        data["private_key"] = pk.get("private_key") or next(iter(pk.values()), None) if isinstance(pk, dict) else None
    return data


def save(data, folder=BACKUP_DIR):
    os.makedirs(folder, exist_ok=True)
    name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (data.get("name") or "node"))
    path = os.path.join(folder, f"{name}-{dt.datetime.now():%Y%m%d-%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=1, ensure_ascii=False)
    return path


def load(path):
    with open(path, encoding="utf-8") as f: data = json.load(f)
    if data.get("mcirc_node_backup") != 1: raise ValueError("this is not an mcIRC node backup")
    return data


def restore(data, settings=True, channels=True, contacts=True, identity=False):
    """Writes the ticked parts back.  -> list of text lines saying what was done."""
    done = []
    if identity and data.get("private_key"):
        run("set", "private_key", data["private_key"])
        done.append("identity (private key) written")
    if settings and data.get("settings"):
        current = cfg.values_from(cfg.read_node())
        results, _ = cfg.write_node(current, dict(current, **data["settings"]))
        done += [f"setting {label}: {'ok' if ok else 'FAILED - ' + detail}" for label, ok, detail in results] or ["settings: nothing to change"]
    if channels:
        have = {c["channel_idx"]: c for c in read_channels()}
        for c in data.get("channels", []):
            h = have.get(c["channel_idx"])
            if h and h["channel_name"] == c["channel_name"] and h["channel_secret"] == c["channel_secret"]: continue
            run("set_channel", c["channel_idx"], c["channel_name"], c["channel_secret"])
            done.append(f"channel {c['channel_idx']} {c['channel_name']}")
    if contacts:
        on = set((first(run(".contacts")) or {}).keys())
        missing = [c for c in data.get("contacts", []) if c.get("public_key") and c["public_key"] not in on]
        for i in range(0, len(missing), 5):
            args = []
            for c in missing[i:i + 5]:
                name = (c.get("adv_name") or c["public_key"][:8]).strip()
                if name.startswith("-"): name = c["public_key"][:8]
                args += ["add_contact", c["public_key"], str(int(c.get("type") or 1)), name[:31], "reset_path", c["public_key"]]
            run(*args, timeout=120)
        done.append(f"{len(missing)} contact(s) added back" if missing else "contacts: all already on the node")
    return done or ["nothing was restored"]


class BackupWindow(ToolWindow):
    def __init__(self, api):
        super().__init__(api, "Node backup and restore", "560x380")
        tk.Label(self, bg=BG, justify="left", wraplength=520, text=(
            "A backup holds the node's settings, channels (with their keys) and contacts. Use it before a firmware update, a 'rebuild' or "
            "'erase' in the rescue console, or to set up a new board the same way.")).pack(anchor="w", padx=10, pady=(10, 4))
        self.with_key = tk.BooleanVar(value=False)
        tk.Checkbutton(self, bg=BG, variable=self.with_key, justify="left", wraplength=500,
                       text="Include the private key (the node's identity: needed to bring the SAME node back after an erase). "
                            "Anyone with the file can impersonate your node - keep it private.").pack(anchor="w", padx=10)
        ttk.Button(self, text="Back up now", command=self.backup).pack(anchor="w", padx=10, pady=6)
        ttk.Separator(self).pack(fill="x", padx=10, pady=6)
        self.parts = {k: tk.BooleanVar(value=v) for k, v in (("settings", True), ("channels", True), ("contacts", True), ("identity", False))}
        r = tk.Frame(self, bg=BG)
        r.pack(anchor="w", padx=10)
        tk.Label(r, text="Restore:", bg=BG).pack(side="left")
        for k, label in (("settings", "settings"), ("channels", "channels"), ("contacts", "contacts"), ("identity", "identity (private key)")):
            tk.Checkbutton(r, text=label, variable=self.parts[k], bg=BG).pack(side="left")
        ttk.Button(self, text="Restore from a file...", command=self.restore).pack(anchor="w", padx=10, pady=6)
        ttk.Button(self, text="Open the backup folder", command=lambda: (os.makedirs(BACKUP_DIR, exist_ok=True), os.startfile(BACKUP_DIR) if hasattr(os, "startfile") else None)).pack(anchor="w", padx=10)

    def backup(self):
        self.job("Backing up the node", lambda: save(make_backup(self.with_key.get())),
                 lambda path: self.say(f"Saved: {path}"))

    def restore(self):
        path = filedialog.askopenfilename(parent=self, initialdir=BACKUP_DIR, filetypes=[("mcIRC node backup", "*.json")])
        if not path: return
        try: data = load(path)
        except (OSError, ValueError) as e: return messagebox.showerror("Restore", f"Can't use this file: {e}", parent=self)
        parts = {k: v.get() for k, v in self.parts.items()}
        if parts["identity"] and not data.get("private_key"): return messagebox.showerror("Restore", "This backup has no private key.", parent=self)
        what = ", ".join(k for k, v in parts.items() if v)
        warn = "\n\nWriting the identity makes this board BECOME the backed-up node." if parts["identity"] else ""
        if not messagebox.askyesno("Restore", f"Restore {what} from\n{os.path.basename(path)}\n(node '{data.get('name')}', saved {data.get('saved')})?{warn}", parent=self): return
        self.job("Restoring", lambda: restore(data, **parts), lambda lines: messagebox.showinfo("Restore", "\n".join(lines), parent=self))
