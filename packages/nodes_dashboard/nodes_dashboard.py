"""Nodes dashboard: for people with many nodes (companions, repeaters, room servers).  Put the nodes you care about on one window and see
at a glance which are online, quiet or silent, when each was last heard, which of your nodes hears it, and graphs of its signal, activity
and advert hops.  It only listens - no logins, no status requests, nothing is ever sent - so it shows what your radio hears of a node,
not a repeater's own counters (battery, uptime).  The history stays on this PC (logs/nodes_dashboard.json)."""
import os
import time
import tkinter as tk

from gui_addons import AddonBase, BASE_DIR
import ndash_core as core

HISTORY = os.path.join(BASE_DIR, "logs", "nodes_dashboard.json")
SAVE_EVERY = 120                   # seconds between writes of the history (and when switched off)
ADVERT_GAP = 30                    # copies of one advert heard through several repeaters count once


class Addon(AddonBase):
    title = "Nodes dashboard"
    version = "1.0.0"
    author = "mcIRC"
    description = ("One window for all your nodes (companions, repeaters, room servers): online / quiet / silent, last heard, heard by, and "
                   "graphs of signal, activity and hops. Add or remove nodes from the ones mcIRC knows. Listens only, never transmits.")
    tick_seconds = 10

    def on_load(self):
        self.demo, self.demo_keys, self.win, self.last_save = False, [], None, time.time()
        self.hist = core.History(HISTORY)
        try: self.hist.load()
        except (OSError, ValueError) as e: self.api.log(f"couldn't read {HISTORY} ({e}) - starting a new history", "warn")
        self.seen_t = self.hist.newest()
        self.api.add_menu_item("Nodes dashboard...", self.open)
        self.api.add_command("dashboard", lambda arg: self.open(), "open the nodes dashboard")
        if self.api.get("toolbar", False): self.api.add_toolbar_button("Nodes", self.open)

    def on_unload(self):
        if self.win is not None and self.win.winfo_exists(): self.win.destroy()
        if self.hist.dirty and not self.demo:
            try: self.hist.save()
            except OSError as e: self.api.log(f"couldn't save the dashboard history: {e}", "warn")

    # ---- which nodes ----
    def keys(self): return list(self.demo_keys) if self.demo else list(self.api.get("nodes", []))

    def add_nodes(self, keys):
        have = self.keys()
        new = have + [k for k in dict.fromkeys(keys) if k not in have]
        if self.demo: self.demo_keys = new
        else: self.api.set("nodes", new)

    def remove_nodes(self, keys):
        gone = set(keys)
        left = [k for k in self.keys() if k not in gone]
        if self.demo: self.demo_keys = left
        else: self.api.set("nodes", left)
        for k in gone: self.hist.forget(k)

    def rows(self, span):
        known = {n["public_key"]: n for n in self.api.nodes.all()}
        try: heard_by = self.api.nodes.heard_by()
        except AttributeError: heard_by = {}
        return core.node_rows(self.keys(), known, heard_by, self.hist, time.time(), span)

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            return
        import ndash_window
        self.win = ndash_window.Dashboard(self)

    # ---- listening ----
    def on_tick(self):
        self.collect()
        now = time.time()
        if now - self.last_save >= SAVE_EVERY:
            self.last_save = now
            try: days = max(1, min(30, int(self.api.get("days", 7))))
            except (TypeError, ValueError): days = 7
            self.hist.trim(now, days)
            if self.hist.dirty and not self.demo:
                data, self.hist.dirty = self.hist.snapshot(), False
                self.api.run_background(lambda: core.write_json(HISTORY, data),
                                        lambda r: isinstance(r, Exception) and self.api.log(f"couldn't save the dashboard history: {r}", "warn"))

    def collect(self):
        """Packets your radio heard since the last look: the last hop of each is the repeater that sent it to you - if it's on the dashboard,
        that's a 'relay' with the signal of that link."""
        log = [p for p in self.api.packet_log if p.get("t", 0) > self.seen_t]
        if not log: return
        self.seen_t = max(p["t"] for p in log)
        keys = set(self.keys())
        if not keys: return
        relays = [n["public_key"] for n in self.api.nodes.all() if n.get("type") in core.RELAY_TYPES]
        for p in log:
            hops = core.split_path(p.get("path"), p.get("size", 1))
            if not hops or p.get("snr") is None: continue
            owner = core.relay_owner(hops[-1], relays)
            if owner in keys: self.hist.add(owner, p["t"], "relay", p.get("snr"), p.get("rssi"))

    def on_packet(self, pkt):
        if pkt.get("type") != "ADVERT" or not pkt.get("packet"): return
        key = core.advert_key(pkt["packet"])
        if not key or key not in set(self.keys()): return
        last, t = self.hist.last(key, "advert"), pkt.get("t") or time.time()
        if last and t - last[0] < ADVERT_GAP: return
        self.hist.add(key, t, "advert", pkt.get("snr"), pkt.get("rssi"), len(core.split_path(pkt.get("path"), pkt.get("size", 1))))

    def on_message(self, msg):
        nick = (msg.get("nick") or "").strip()
        if not nick: return
        n = self.api.nodes.find_by_name(nick)
        if n and n["public_key"] in set(self.keys()):
            self.hist.add(n["public_key"], time.time(), "msg", msg.get("snr"), None, msg.get("hops"))

    def on_demo(self):
        """Demo mode: the first few demo nodes on the dashboard, with two days of made-up history (nothing is saved)."""
        self.demo = True
        nodes = self.api.nodes.all()
        pick = [n for n in nodes if n.get("type") in core.RELAY_TYPES][:4] + [n for n in nodes if n.get("type") == 1][:3]
        self.demo_keys = [n["public_key"] for n in pick]
        self.hist = core.demo_history([(n["public_key"], n.get("type")) for n in pick], time.time())

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_toolbar = tk.BooleanVar(value=self.api.get("toolbar", False))
        self.v_days = tk.StringVar(value=str(self.api.get("days", 7)))
        tk.Checkbutton(f, text="A 'Nodes' button on the toolbar (from the next start)", variable=self.v_toolbar, bg=bg).pack(anchor="w")
        r = tk.Frame(f, bg=bg)
        r.pack(anchor="w", pady=4)
        tk.Label(r, text="Keep the graph history for (days, 1-30):", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_days, width=4).pack(side="left", padx=4)
        tk.Label(f, bg=bg, fg="#555", justify="left", wraplength=460, text=(
            f"It listens only - nothing is ever sent. {len(self.keys())} node(s) on the dashboard; add or remove them in the dashboard itself "
            "(Addons menu > Nodes dashboard, or /dashboard).")).pack(anchor="w", pady=(4, 0))
        tk.Button(f, text="Open the dashboard", command=self.open).pack(anchor="w", pady=(6, 0))
        return f

    def apply_options(self):
        self.api.set("toolbar", self.v_toolbar.get())
        try: self.api.set("days", max(1, min(30, int(self.v_days.get()))))
        except ValueError: pass
