"""Tool 1 - the node's clock.  MeshCore stamps every message and advert with the node's own time; a node whose clock is far off makes its
messages look old (or from the future) to everyone else.  Read it, compare it with this PC, set it, optionally automatically on connect."""
import datetime as dt
import time
import tkinter as tk
from tkinter import ttk

from ntools_common import BG, ToolWindow, first, run

DRIFT_OK = 60          # seconds of difference that need no action


def node_time():
    """(node epoch, PC epoch) read back to back."""
    d = first(run(".clock")) or {}
    return int(d.get("time", 0)), int(time.time())


def sync():
    """Set the node's clock to this PC's time (meshcli 'clock sync')."""
    run("clock", "sync")
    return node_time()


def describe(node, pc):
    diff = node - pc
    when = dt.datetime.fromtimestamp(node).strftime("%Y-%m-%d %H:%M:%S") if node > 0 else "not set"
    if abs(diff) <= DRIFT_OK: state = "in step with this PC"
    else:
        days, rest = divmod(abs(diff), 86400)
        span = f"{days} days {rest // 3600} h" if days else f"{rest // 3600} h {rest % 3600 // 60} min" if rest >= 3600 else f"{rest // 60} min {rest % 60} s"
        state = f"{span} {'behind' if diff < 0 else 'ahead of'} this PC"
    return f"Node clock: {when}\nThis PC:    {dt.datetime.fromtimestamp(pc).strftime('%Y-%m-%d %H:%M:%S')}\n\nThe node is {state}.", abs(diff) > DRIFT_OK


class ClockWindow(ToolWindow):
    def __init__(self, api):
        super().__init__(api, "Node clock", "460x260")
        self.info = tk.Label(self, bg=BG, justify="left", anchor="w", font=("Courier New", 10))
        self.info.pack(fill="x", padx=10, pady=10)
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=10)
        ttk.Button(row, text="Read the node's clock", command=self.read).pack(side="left")
        ttk.Button(row, text="Set it to this PC's time", command=self.set_now).pack(side="left", padx=6)
        self.auto = tk.BooleanVar(value=api.get("clock_auto", True))
        tk.Checkbutton(self, text=f"Set it automatically when mcIRC connects and it is more than {DRIFT_OK} s off",
                       variable=self.auto, bg=BG, command=lambda: api.set("clock_auto", self.auto.get())).pack(anchor="w", padx=10, pady=8)
        self.read()

    def on_node_change(self): self.read()

    def read(self):
        self.job("Reading the node's clock", node_time, lambda r: self.info.config(text=describe(*r)[0]))

    def set_now(self):
        self.job("Setting the node's clock", sync, lambda r: self.info.config(text=describe(*r)[0]))
