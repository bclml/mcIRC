"""Options > More nodes: the extra radios mcIRC connects to together with the main one (Connect / Disconnect)."""
import re
import tkinter as tk
from tkinter import messagebox, ttk

from gui_common import BG

MODES = {"usb": "USB", "tcp": "Wi-Fi", "ble": "Bluetooth"}
LABEL_RE = re.compile(r"[A-Za-z0-9._-](?:[A-Za-z0-9._ -]{0,10}[A-Za-z0-9._-])?")      # '915', 'wifi 1'


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
        for text, cmd in (("Add...", self.add), ("Edit...", self.edit), ("Radio settings...", self.radio), ("On / off", self.toggle), ("Remove", self.remove)):
            ttk.Button(b, text=text, command=cmd).pack(side="left", padx=2)
        self.fill()

    def items(self): return [dict(c) for c in self.items_]

    def main_cfg(self):
        """The main node as a row (it is set on the Connect page)."""
        v = lambda k: self.dlg.vars[k].get() if k in getattr(self.dlg, "vars", {}) else self.dlg.app.settings.get(k, "")
        mode = {"bluetooth": "ble"}.get(v("mode"), v("mode"))
        return {"label": "main", "mode": mode, "port": v("port"), "host": v("tcp_host"), "ble": v("ble_target")}

    def fill(self):
        self.t.delete(*self.t.get_children())
        self.t.insert("", "end", iid="main", values=("main", describe(self.main_cfg()) + "  (Connect page)", "yes"))
        for i, c in enumerate(self.items_):
            self.t.insert("", "end", iid=str(i), values=(c["label"], describe(c), "yes" if c.get("enabled", True) else "no"))

    def sel(self):
        """Index of the chosen extra node; None for nothing or the main node (which is set on the Connect page)."""
        s = self.t.selection()
        if s and s[0] == "main":
            messagebox.showinfo("More nodes", "The main node is set on the Connect page (and its radio on 'Node: radio').", parent=self.dlg)
            return None
        return int(s[0]) if s else None

    def go(self, page):
        if hasattr(self.dlg, "tree") and self.dlg.tree.exists(page): self.dlg.tree.selection_set(page)

    def add(self):
        c = NodeEditor(self.dlg, {"label": "", "mode": "usb", "port": "", "host": "", "tcp_port": 5000, "ble": "", "enabled": True},
                       taken={x["label"] for x in self.items_}).result
        if c: self.items_.append(c); self.fill()

    def edit(self):
        if self.t.selection() == ("main",): return self.go("Connect")
        i = self.sel()
        if i is None: return
        c = NodeEditor(self.dlg, self.items_[i], taken={x["label"] for j, x in enumerate(self.items_) if j != i}).result
        if c: self.items_[i] = c; self.fill()

    def radio(self):
        if self.t.selection() == ("main",):
            self.go("Node: radio")
            np = getattr(self.dlg, "node_pages", None)
            if np is not None and np.node_key != "main":
                np._fill_nodes()
                np.node_var.set(np.choices[0][1])
                np._node_picked()
            return
        i = self.sel()
        if i is None: return
        RadioDialog(self.dlg, self.dlg.app, self.items_[i])

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
        if not LABEL_RE.fullmatch(c["label"]): return messagebox.showerror("Node", "The label: 1-12 letters, digits, spaces, . _ or -", parent=self)
        if c["label"] in self.taken: return messagebox.showerror("Node", "Another node already has that label.", parent=self)
        need = {"usb": "port", "tcp": "host", "ble": "ble"}[c["mode"]]
        if not c[need]: return messagebox.showerror("Node", f"Fill in the {need.replace('ble', 'Bluetooth name')}.", parent=self)
        try: c["tcp_port"] = int(c["tcp_port"] or 5000)
        except ValueError: return messagebox.showerror("Node", "The Wi-Fi port is a number.", parent=self)
        c["enabled"] = True
        self.result = c
        self.destroy()


class RadioDialog(tk.Toplevel):
    """Name, frequency, bandwidth, spreading factor, coding rate and TX power of an extra node - read from it and written to it."""
    FIELDS = (("Name", "name"), ("Frequency (MHz)", "radio_freq"), ("Bandwidth (kHz)", "radio_bw"), ("Spreading factor (5-12)", "radio_sf"),
              ("Coding rate (5-8)", "radio_cr"), ("TX power (dBm)", "tx_power"))

    def __init__(self, parent, app, cfg):
        super().__init__(parent, bg=BG)
        self.app, self.cfg = app, cfg
        self.title(f"Radio settings - node {cfg['label']}")
        self.transient(parent)
        self.v, self.old = {k: tk.StringVar() for _, k in self.FIELDS}, {}
        g = tk.Frame(self, bg=BG)
        g.pack(padx=12, pady=10)
        for r, (label, key) in enumerate(self.FIELDS):
            tk.Label(g, text=label + ":", bg=BG).grid(row=r, column=0, sticky="w", pady=2)
            tk.Entry(g, textvariable=self.v[key], width=24).grid(row=r, column=1, sticky="w", pady=2)
        self.status = tk.Label(self, bg=BG, fg="#555", wraplength=360, justify="left")
        self.status.pack(fill="x", padx=12)
        b = tk.Frame(self, bg=BG)
        b.pack(fill="x", padx=12, pady=8)
        ttk.Button(b, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Write to the node", command=self.write).pack(side="right", padx=4)
        ttk.Button(b, text="Read from the node", command=self.read).pack(side="left")
        self.read()

    def _run(self, *args, timeout=40):
        import gui_multinode
        import meshcore_io as io
        n = self.app.extra_nodes.get(self.cfg["label"])
        lock, health = (n.lock, n.health) if n else (io._MeshLock(), io.RadioHealth())
        return io.execute_mesh_command(gui_multinode.conn_args(self.cfg) + [str(a) for a in args], timeout=timeout, retries=1, lock=lock, health=health)

    def _bg(self, label, fn, done):
        self.status.config(text=label + "...")
        def finished(r):
            if not self.winfo_exists(): return
            if isinstance(r, Exception):
                import meshcore_io as io
                return self.status.config(text=f"{label} failed: {io.explain_failure(str(r))}")
            done(r)
        self.app.bg(fn, finished)

    def read(self):
        import meshcore_io as io
        def work():
            res = self._run(".infos")
            return next((d for d in io.json_docs(res.stdout) if isinstance(d, dict)), {})
        def done(info):
            self.old = {k: info.get(k) for _, k in self.FIELDS}
            for _, k in self.FIELDS: self.v[k].set("" if info.get(k) is None else f"{info.get(k):g}" if isinstance(info.get(k), float) else str(info.get(k)))
            self.status.config(text="Read from the node.")
        self._bg("Reading", work, done)

    def write(self):
        new = {k: self.v[k].get().strip() for _, k in self.FIELDS}
        try:
            radio = [float(new["radio_freq"]), float(new["radio_bw"]), int(new["radio_sf"]), int(new["radio_cr"])]
            tx = int(new["tx_power"])
        except ValueError:
            return messagebox.showerror("Radio settings", "Frequency and bandwidth are numbers; SF, CR and TX power are whole numbers.", parent=self)
        if not (5 <= radio[2] <= 12 and 5 <= radio[3] <= 8): return messagebox.showerror("Radio settings", "SF must be 5-12 and CR 5-8.", parent=self)
        def num(v):
            try: return float(v)
            except (TypeError, ValueError): return None
        changed_radio = [num(self.old.get(k)) for k in ("radio_freq", "radio_bw", "radio_sf", "radio_cr")] != [float(x) for x in radio]      # (915.0 from the node = 915 typed)
        def work():
            done = []
            if new["name"] and new["name"] != self.old.get("name"):
                self._run("set", "name", new["name"]); done.append("name")
            if str(tx) != str(self.old.get("tx_power")):
                self._run("set", "tx", tx); done.append("TX power")
            if changed_radio:
                self._run("set", "radio", f"{radio[0]:g},{radio[1]:g},{radio[2]},{radio[3]}"); done.append("radio")
                self._run("reboot", timeout=20)                        # new radio settings take effect after a restart
            return done
        def finished(done):
            self.status.config(text=("Written: " + ", ".join(done) + (". The node restarts for the new radio settings." if "radio" in done else ".")) if done else "Nothing changed.")
        if changed_radio and not messagebox.askyesno("Radio settings", "Change this node's radio settings and restart it?\nAll nodes it should hear must use the same settings.", parent=self): return
        self._bg("Writing", work, finished)
