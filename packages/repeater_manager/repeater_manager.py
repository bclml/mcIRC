"""Repeater manager: your repeaters and room servers on one page.  For each: log in (the password stays in memory only - never saved or
logged), status (battery, uptime, noise floor, signal, packets, airtime), neighbours, telemetry, and a remote command line; the status
answers are kept, so battery, noise floor and traffic are drawn over time.

Every button sends a request over the air to that repeater (one at a time, never retried by itself).  Commands that change or stop a
repeater (reboot, set ..., password ...) ask first.  Checking the status on a timer is off until you set it (30 minutes at the least),
one repeater at a time.  Addons menu > Repeater manager..."""
import os
import time
import tkinter as tk

from gui_addons import AddonBase, BASE_DIR
import rptmgr_core as core

HISTORY = os.path.join(BASE_DIR, "logs", "repeater_manager.json")
BG = "#d4d0c8"
TYPE_NAMES = {2: "Repeater", 3: "Room server"}
MIN_POLL = 30                      # minutes: the shortest timer for automatic status checks
POLL_GAP = 120                     # seconds between two automatic requests (to different repeaters)


class Addon(AddonBase):
    title = "Repeater manager"
    version = "1.0.0"
    author = "mcIRC"
    description = ("Your repeaters and room servers on one page: log in, status, neighbours, telemetry and a remote command line, with graphs "
                   "of battery, noise floor and traffic over time. Each request goes over the air, one at a time; status on a timer is off until you set it.")
    tick_seconds = 15

    def on_load(self):
        self.pw, self.queue, self.busy, self.win, self.last_auto = {}, [], False, None, 0.0
        self.hist = core.History(HISTORY)
        try: self.hist.load()
        except (OSError, ValueError) as e: self.api.log(f"couldn't read {HISTORY} ({e}) - starting a new history", "warn")
        self.api.add_menu_item("Repeater manager...", self.open)

    def on_unload(self):
        self.queue.clear()
        if self.win is not None and self.win.winfo_exists(): self.win.destroy()
        if self.hist.dirty:
            try: self.hist.save()
            except OSError as e: self.api.log(f"couldn't save the repeater history: {e}", "warn")

    # ---- which repeaters ----
    def keys(self): return list(self.api.get("repeaters", []))

    def add(self, keys):
        have = self.keys()
        self.api.set("repeaters", have + [k for k in dict.fromkeys(keys) if k not in have])

    def remove(self, keys):
        gone = set(keys)
        self.api.set("repeaters", [k for k in self.keys() if k not in gone])
        for k in gone:
            self.hist.forget(k)
            self.pw.pop(k, None)

    def node(self, key): return next((n for n in self.api.nodes.all() if n["public_key"] == key), None)

    def name(self, key):
        n = self.node(key)
        return (n or {}).get("name") or key[:8]

    def poll_minutes(self):
        try: m = int(self.api.get("poll_minutes", 0))
        except (TypeError, ValueError): return 0
        return 0 if m <= 0 else max(MIN_POLL, m)

    # ---- requests (one at a time) ----
    def request(self, key, what, text=None, auto=False):
        """Queue one request; it goes out when the one before it has finished."""
        if not self.api.connected:
            return self.show(key, "Not connected to your node.", "error")
        self.queue.append((key, what, text, auto))
        self.next()

    def next(self):
        if self.busy or not self.queue: return
        key, what, text, auto = self.queue.pop(0)
        self.busy = True
        if not auto: self.show(key, {"login": "logging in...", "status": "asking for its status...", "neighbours": "asking for its neighbours...",
                                     "telemetry": "asking for its telemetry...", "cmd": f"> {text}"}[what], "info")
        self.api.run_background(lambda: self.run(key, what, text), lambda r: self.done(key, what, text, auto, r))

    def run(self, key, what, text):
        """In the background: meshcli on your node, once (never retried - each try is a transmission)."""
        import meshcore_io as io
        if not io.node_args(): raise RuntimeError("not connected")
        if io.HEALTH.is_down: raise RuntimeError("your radio is not answering")
        args = core.request_args(key, what, self.pw.get(key), text)
        r = io.execute_mesh_command(io.node_args() + args, timeout=60, retries=0)
        out = f"{r.stdout}\n{r.stderr}"
        if core.unknown_contact(out):
            n = self.node(key) or {}
            r = io.execute_mesh_command(io.node_args() + core.readd_args(key, n.get("type"), n.get("name"), args), timeout=75, retries=0)
            out = f"{r.stdout}\n{r.stderr}"
        return out

    def done(self, key, what, text, auto, out):
        self.busy = False
        try:
            if isinstance(out, Exception): return self.show(key, f"failed: {out}", "error") if not auto else None
            if what == "cmd":
                lines = [l for l in core.clean_lines(out) if not l.startswith("{")]
                return self.show(key, "\n".join(lines) or "no reply within 8 seconds (out of range, not logged in, or no reply for that command)",
                                 "text" if lines else "warn")
            res = core.parse(out)
            if res["login"] is False and what == "login": self.pw.pop(key, None)
            if what == "login": return self.show(key, "logged in" if res["login"] else f"login failed: {res['error'] or 'no reply'}", "info" if res["login"] else "error")
            if res["status"]:
                self.hist.add(key, time.time(), res["status"])
                return self.show(key, core.status_text(res["status"]), "text") if not auto else self.refresh()
            if res["neighbours"]:
                names = {n["public_key"]: n.get("name") or n["public_key"][:8] for n in self.api.nodes.all()}
                return self.show(key, "neighbours: " + core.neighbours_text(res["neighbours"], names), "text")
            if res["telemetry"] is not None: return self.show(key, "telemetry: " + core.telemetry_text(res["telemetry"]), "text")
            if not auto: self.show(key, res["error"] or "no reply (out of range, or it wants a login)", "warn")
        finally:
            self.next()

    def show(self, key, text, level="text"):
        """A result: in the window when it is open, else in the 'Repeaters' window."""
        line = f"{time.strftime('%H:%M:%S')} {self.name(key)}: {text}"
        if self.win is not None and self.win.winfo_exists(): self.win.output(line, level)
        else: self.api.write("Repeaters", line, level if level in ("info", "warn", "error") else "text")
        self.refresh()

    def refresh(self):
        if self.win is not None and self.win.winfo_exists(): self.win.fill()

    # ---- status on a timer ----
    def on_tick(self):
        mins, now = self.poll_minutes(), time.time()
        if self.hist.dirty and not self.busy:
            try: self.hist.save()
            except OSError: pass
        if not mins or not self.api.connected or self.busy or self.queue or now - self.last_auto < POLL_GAP: return
        due = [(((self.hist.last(k) or [0])[0]), k) for k in self.keys() if now - ((self.hist.last(k) or [0])[0]) >= mins * 60]
        if due:
            self.last_auto = now
            self.request(min(due)[1], "status", auto=True)

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify(); self.win.lift()
            return
        import rptmgr_window
        self.win = rptmgr_window.Window(self)

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_poll = tk.StringVar(value=str(self.poll_minutes()))
        r = tk.Frame(f, bg=bg)
        r.pack(anchor="w")
        tk.Label(r, text=f"Ask each repeater for its status every (minutes, 0 = never, at least {MIN_POLL}):", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_poll, width=5).pack(side="left", padx=4)
        tk.Label(f, bg=bg, fg="#555", justify="left", wraplength=480, text=(
            "Each status request is a transmission: one repeater at a time, at least 2 minutes apart, never retried by itself. Passwords "
            "stay in memory until mcIRC closes - never saved or logged. Addons menu > Repeater manager...")).pack(anchor="w", pady=(4, 0))
        return f

    def apply_options(self):
        try: m = int(self.v_poll.get())
        except ValueError: return
        self.api.set("poll_minutes", 0 if m <= 0 else max(MIN_POLL, m))
