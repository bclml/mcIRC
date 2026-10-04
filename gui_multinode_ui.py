"""Options > More nodes: the extra radios mcIRC connects to together with the main one (Connect / Disconnect)."""
import re
import tkinter as tk
from tkinter import messagebox, ttk

from gui_common import BG

MODES = {"usb": "USB", "tcp": "Wi-Fi", "ble": "Bluetooth"}


def describe(c):
    where = c.get("port") if c.get("mode", "usb") == "usb" else c.get("host") if c.get("mode") == "tcp" else c.get("ble")
    return f"{MODES.get(c.get('mode', 'usb'), '?')} {where or '?'}"


class NodesPage:
    """The page itself; OptionsDialog.apply() stores items() as settings['extra_nodes']."""
    def __init__(self, dlg, f):
        self.dlg, self.items_ = dlg, [dict(c) for c in dlg.app.settings.get("extra_nodes", [])]
        tk.Label(f, text="More nodes", bg=BG, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        tk.Label(f, bg=BG, fg="#555", justify="left", wraplength=440, text=(
            "Connect more radios at the same time - for example a second node on another frequency - and chat on all of them here. "
            "Each one gets its own Status window and channel windows, named with its label (Public [915]). Private chats stay on the top bar. "
            "They connect and disconnect together with the main node (Connect / Disconnect).")).pack(anchor="w", pady=(0, 6))
        self.t = ttk.Treeview(f, columns=("label", "connection", "on"), show="headings", height=6, selectmode="browse")
        for c, w in (("label", 90), ("connection", 230), ("on", 50)):
            self.t.heading(c, text=c.capitalize())
            self.t.column(c, width=w, anchor="w")
        self.t.pack(fill="x")
        self.t.bind("<Double-1>", lambda e: self.edit())
        b = tk.Frame(f, bg=BG)
        b.pack(fill="x", pady=4)
        for text, cmd in (("Add...", self.add), ("Edit...", self.edit), ("On / off", self.toggle), ("Remove", self.remove)):
            ttk.Button(b, text=text, command=cmd).pack(side="left", padx=2)
        self.fill()

    def items(self): return [dict(c) for c in self.items_]

    def fill(self):
        self.t.delete(*self.t.get_children())
        for i, c in enumerate(self.items_):
            self.t.insert("", "end", iid=str(i), values=(c["label"], describe(c), "yes" if c.get("enabled", True) else "no"))

    def sel(self):
        s = self.t.selection()
        return int(s[0]) if s else None

    def add(self):
        c = NodeEditor(self.dlg, {"label": "", "mode": "usb", "port": "", "host": "", "tcp_port": 5000, "ble": "", "enabled": True},
                       taken={x["label"] for x in self.items_}).result
        if c: self.items_.append(c); self.fill()

    def edit(self):
        i = self.sel()
        if i is None: return
        c = NodeEditor(self.dlg, self.items_[i], taken={x["label"] for j, x in enumerate(self.items_) if j != i}).result
        if c: self.items_[i] = c; self.fill()

    def toggle(self):
        i = self.sel()
        if i is None: return
        self.items_[i]["enabled"] = not self.items_[i].get("enabled", True)
        self.fill()

    def remove(self):
        i = self.sel()
        if i is not None and messagebox.askyesno("More nodes", f"Remove node '{self.items_[i]['label']}'?", parent=self.dlg):
            del self.items_[i]
            self.fill()


class NodeEditor(tk.Toplevel):
    def __init__(self, parent, cfg, taken=()):
        super().__init__(parent, bg=BG)
        self.title("Node")
        self.transient(parent)
        self.result, self.taken = None, set(taken)
        self.v = {k: tk.StringVar(value=str(cfg.get(k, ""))) for k in ("label", "mode", "port", "host", "tcp_port", "ble")}
        self.v["mode"].set(cfg.get("mode", "usb"))
        g = tk.Frame(self, bg=BG)
        g.pack(padx=12, pady=10)
        rows = (("Label (short, e.g. 915):", "label"), ("USB port (e.g. COM10):", "port"), ("Wi-Fi host:", "host"), ("Wi-Fi port:", "tcp_port"),
                ("Bluetooth name or address:", "ble"))
        tk.Label(g, text="Connection:", bg=BG).grid(row=0, column=0, sticky="w")
        m = tk.Frame(g, bg=BG)
        m.grid(row=0, column=1, sticky="w")
        for key, label in MODES.items(): tk.Radiobutton(m, text=label, value=key, variable=self.v["mode"], bg=BG).pack(side="left")
        for r, (label, key) in enumerate(rows, start=1):
            tk.Label(g, text=label, bg=BG).grid(row=r, column=0, sticky="w", pady=2)
            tk.Entry(g, textvariable=self.v[key], width=26).grid(row=r, column=1, sticky="w", pady=2)
        try:
            import serial.tools.list_ports as lp
            ports = ", ".join(p.device for p in lp.comports())
        except Exception:
            ports = ""
        if ports: tk.Label(self, text=f"USB ports on this PC: {ports}", bg=BG, fg="#555").pack(anchor="w", padx=12)
        b = tk.Frame(self, bg=BG)
        b.pack(fill="x", padx=12, pady=8)
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="OK", command=self.ok).pack(side="right", padx=4)
        self.grab_set()
        self.wait_window()

    def ok(self):
        c = {k: v.get().strip() for k, v in self.v.items()}
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,12}", c["label"]): return messagebox.showerror("Node", "The label: 1-12 letters, digits, . _ or -", parent=self)
        if c["label"] in self.taken: return messagebox.showerror("Node", "Another node already has that label.", parent=self)
        need = {"usb": "port", "tcp": "host", "ble": "ble"}[c["mode"]]
        if not c[need]: return messagebox.showerror("Node", f"Fill in the {need.replace('ble', 'Bluetooth name')}.", parent=self)
        try: c["tcp_port"] = int(c["tcp_port"] or 5000)
        except ValueError: return messagebox.showerror("Node", "The Wi-Fi port is a number.", parent=self)
        c["enabled"] = True
        self.result = c
        self.destroy()
