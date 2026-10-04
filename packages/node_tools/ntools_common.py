"""Shared bits of the MeshCore tools addon: running meshcli on the connected node, reading its JSON answers, and a simple tool window."""
import json
import tkinter as tk
from tkinter import ttk

import meshcore_io as io

BG = "#d4d0c8"
MONO = ("Courier New", 9)


def run(*args, timeout=40, retries=1):
    """meshcli on the connected node -> its output text (stdout + stderr).  Raises when the node does not answer."""
    if not io.CONNECTION_ARGS: raise RuntimeError("not connected to a node")
    r = io.execute_mesh_command(io.CONNECTION_ARGS + [str(a) for a in args], timeout=timeout, retries=retries)
    return f"{r.stdout}\n{r.stderr}"


def docs(text):
    """Every JSON value in meshcli's output, in order."""
    return list(io.json_docs(text))


def first(text, kind=dict, default=None):
    return next((d for d in docs(text) if isinstance(d, kind)), default)


def plain(text):
    """meshcli's output without its own INFO / DEBUG lines."""
    return "\n".join(l for l in (text or "").splitlines() if l.strip() and not l.startswith(("INFO:", "DEBUG:", "WARNING:meshcore"))).strip()


class ToolWindow(tk.Toplevel):
    """A tool window with a status line and a way to run radio work in the background (one job at a time)."""
    def __init__(self, api, title, size="640x460"):
        super().__init__(api.ui()["root"], bg=BG)
        self.api, self.busy = api, False
        self.title(title)
        self.geometry(size)
        self.status = tk.Label(self, bg=BG, fg="#555", anchor="w", justify="left", wraplength=600)
        self.status.pack(side="bottom", fill="x", padx=6, pady=4)

    def say(self, text, error=False):
        if self.winfo_exists(): self.status.config(text=text, fg="#c00000" if error else "#555")

    def job(self, label, fn, done=None, need_radio=True):
        """Runs fn() in the background; done(result) afterwards on the window.  Exceptions are shown in the status line."""
        if self.busy: return self.say("Still busy with the last request...")
        if need_radio and not self.api.connected: return self.say("Connect to your node first.", error=True)
        self.busy = True
        self.say(label + "...")
        def finished(r):
            self.busy = False
            if not self.winfo_exists(): return
            if isinstance(r, Exception): return self.say(f"{label} failed: {io.explain_failure(str(r))}", error=True)
            self.say(label + " - done.")
            if done: done(r)
        self.api.run_background(fn, finished)


def text_box(parent, height=12):
    frame = tk.Frame(parent, bg=BG)
    t = tk.Text(frame, height=height, font=MONO, wrap="word", bg="white")
    sb = ttk.Scrollbar(frame, command=t.yview)
    t.config(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    t.pack(side="left", fill="both", expand=True)
    return frame, t


def show(t, text):
    t.config(state="normal")
    t.delete("1.0", "end")
    t.insert("end", text)
    t.config(state="disabled")


def pretty(obj): return json.dumps(obj, indent=2, ensure_ascii=False)
