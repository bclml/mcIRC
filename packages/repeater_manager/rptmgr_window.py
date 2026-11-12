"""Repeater manager - the window: your repeaters in a table, the buttons for the one picked, the answers, and its graphs."""
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import rptmgr_core as core

BG = "#d4d0c8"
TYPE_NAMES = {2: "Repeater", 3: "Room server"}
LEVEL_COLOURS = {"info": "#1a5fb4", "warn": "#c64600", "error": "#c01c28", "text": "black"}


def ago(t, now):
    if not t: return "never"
    s = max(0, now - t)
    return f"{int(s // 60)} min ago" if s < 5400 else f"{int(s // 3600)} h ago" if s < 172800 else f"{int(s // 86400)} days ago"


class Window(tk.Toplevel):
    COLS = (("name", 170), ("type", 85), ("status read", 85), ("battery", 65), ("up", 75), ("noise", 60), ("login", 55))

    def __init__(self, addon):
        super().__init__(addon.api.ui()["root"], bg=BG)
        self.addon = addon
        self.title("Repeater manager")
        self.geometry("1100x640")
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Button(top, text="Add repeaters...", command=lambda: AddDialog(self)).pack(side="left")
        ttk.Button(top, text="Remove", command=self.remove).pack(side="left", padx=4)
        self.poll = tk.Label(top, bg=BG, fg="#555")
        self.poll.pack(side="left", padx=8)
        pane = tk.PanedWindow(self, orient="horizontal", bg=BG, sashwidth=5)
        pane.pack(fill="both", expand=True, padx=6)
        self.t = ttk.Treeview(pane, columns=[c for c, _ in self.COLS], show="headings", selectmode="browse")
        for c, w in self.COLS:
            self.t.heading(c, text=c)
            self.t.column(c, width=w, anchor="w", stretch=c == "name")
        self.t.bind("<<TreeviewSelect>>", lambda e: self.draw())
        right = tk.Frame(pane, bg=BG)
        pane.add(self.t, minsize=360, width=600)
        pane.add(right, minsize=380)
        btns = tk.Frame(right, bg=BG)
        btns.pack(fill="x")
        for text, what in (("Log in...", "login"), ("Status", "status"), ("Neighbours", "neighbours"), ("Telemetry", "telemetry")):
            ttk.Button(btns, text=text, command=lambda w=what: self.act(w)).pack(side="left", padx=(0, 4))
        cli = tk.Frame(right, bg=BG)
        cli.pack(fill="x", pady=4)
        tk.Label(cli, text="Command:", bg=BG).pack(side="left")
        self.cmd = tk.StringVar()
        e = tk.Entry(cli, textvariable=self.cmd)
        e.pack(side="left", fill="x", expand=True, padx=4)
        e.bind("<Return>", lambda ev: self.send_cmd())
        ttk.Button(cli, text="Send", command=self.send_cmd).pack(side="left")
        self.out = tk.Text(right, height=9, wrap="word", font=("Consolas", 9), state="disabled")
        for lvl, col in LEVEL_COLOURS.items(): self.out.tag_configure(lvl, foreground=col)
        self.out.pack(fill="x", pady=(0, 4))
        self.c = tk.Canvas(right, bg="white", highlightthickness=0)
        self.c.pack(fill="both", expand=True)
        self.c.bind("<Configure>", lambda e: self.draw())
        tk.Label(self, bg=BG, fg="#555", anchor="w", justify="left", wraplength=1080, text=(
            "Every button sends a request over the air to the repeater picked - one at a time, never retried by itself. A password stays in memory "
            "until mcIRC closes. Commands that change or stop a repeater ask first. Remote commands: 'ver', 'clock', 'neighbors', 'get <param>' "
            "(type /help in a repeater's window for the list).")).pack(fill="x", padx=6, pady=4)
        self.fill()

    def selected(self):
        sel = self.t.selection()
        return sel[0] if sel and sel[0] in self.addon.keys() else None

    def output(self, line, level="text"):
        self.out.config(state="normal")
        self.out.insert("end", line + "\n", level)
        self.out.see("end")
        self.out.config(state="disabled")

    def act(self, what):
        key = self.selected()
        if not key: return self.output("Pick a repeater in the table first.", "warn")
        if what == "login":
            pw = simpledialog.askstring("Log in", f"Password for {self.addon.name(key)}\n(kept in memory only, never saved or logged):", show="*", parent=self)
            if not pw: return
            self.addon.pw[key] = pw
        self.addon.request(key, what)

    def send_cmd(self):
        key, text = self.selected(), self.cmd.get().strip()
        if not key: return self.output("Pick a repeater in the table first.", "warn")
        if not text: return
        if core.dangerous(text) and not messagebox.askyesno("Repeater manager", f"Send '{text}' to {self.addon.name(key)}?\n"
                                                            "This changes or stops the repeater.", parent=self): return
        self.cmd.set("")
        self.addon.request(key, "cmd", text)

    def remove(self):
        key = self.selected()
        if not key: return
        if messagebox.askyesno("Repeater manager", f"Remove {self.addon.name(key)} from the repeater manager?\nIts status history here is deleted "
                               "too (the repeater itself and mcIRC's node list are not touched).", parent=self):
            self.addon.remove([key])
            self.fill()

    def fill(self):
        a, now = self.addon, time.time()
        keep = self.selected()
        self.t.delete(*self.t.get_children())
        for k in a.keys():
            n, last = a.node(k) or {}, a.hist.last(k)
            vals = (a.name(k), TYPE_NAMES.get(n.get("type"), "?"), ago(last[0], now) if last else "never",
                    f"{last[1] / 1000:.2f} V" if last and last[1] else "", core.duration(last[8]) if last and last[8] else "",
                    f"{last[2]} dBm" if last and last[2] is not None else "", "yes" if k in a.pw else "")
            self.t.insert("", "end", iid=k, values=vals)
        if keep and self.t.exists(keep): self.t.selection_set(keep)
        m = a.poll_minutes()
        self.poll.config(text=f"Status on a timer: every {m} min" if m else "Status on a timer: off (Tools > Addons > Repeater manager)")
        self.draw()

    def draw(self):
        c = self.c
        c.delete("all")
        key, a = self.selected(), self.addon
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 200)
        if not key:
            c.create_text(w / 2, h / 2, fill="#777", text="Pick a repeater: its battery, noise floor and traffic\nare drawn from the status answers it gave.", justify="center")
            return
        since = time.time() - 7 * 86400
        graphs = (("Battery (V)", [(t, v / 1000) for t, v in a.hist.series(key, 1, since)], "#26a269"),
                  ("Noise floor (dBm)", a.hist.series(key, 2, since), "#1a5fb4"),
                  ("Packets received per hour", a.hist.per_hour(key, 5, since), "#813d9c"))
        rows, x0, x1 = len(graphs), 50, w - 10
        for i, (title, pts, colour) in enumerate(graphs):
            y0, y1 = i * h / rows + 18, (i + 1) * h / rows - 8
            c.create_text(8, y0 - 9, anchor="w", font=("Segoe UI", 9, "bold"), text=title + (f":  {pts[-1][1]:.2f}".rstrip("0").rstrip(".") if pts else ":  no readings yet"))
            c.create_rectangle(x0, y0, x1, y1, outline="#ccc")
            if not pts: continue
            t0, t1 = pts[0][0], max(pts[-1][0], pts[0][0] + 1)
            lo, hi = min(v for _, v in pts), max(v for _, v in pts)
            if hi == lo: lo, hi = lo - 1, hi + 1
            xy = [v for t, val in pts for v in (x0 + (t - t0) / (t1 - t0) * (x1 - x0), y1 - (val - lo) / (hi - lo) * (y1 - y0))]
            if len(xy) >= 4: c.create_line(*xy, fill=colour, width=2)
            for j in range(0, len(xy), 2): c.create_oval(xy[j] - 2, xy[j + 1] - 2, xy[j] + 2, xy[j + 1] + 2, fill=colour, outline="")
            c.create_text(x0 - 4, y0, anchor="ne", text=f"{hi:.1f}", font=("Segoe UI", 7))
            c.create_text(x0 - 4, y1, anchor="se", text=f"{lo:.1f}", font=("Segoe UI", 7))


class AddDialog(tk.Toplevel):
    """The repeaters and room servers mcIRC knows that aren't on the page yet."""
    def __init__(self, win):
        super().__init__(win, bg=BG)
        self.win, self.items = win, []
        self.title("Add repeaters")
        self.geometry("460x420")
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=8, pady=8)
        tk.Label(row, text="Search:", bg=BG).pack(side="left")
        self.q = tk.StringVar()
        tk.Entry(row, textvariable=self.q, width=26).pack(side="left", padx=4)
        self.lb = tk.Listbox(self, selectmode="extended", activestyle="none")
        self.lb.pack(fill="both", expand=True, padx=8)
        self.lb.bind("<Double-Button-1>", lambda e: self.add())
        bot = tk.Frame(self, bg=BG)
        bot.pack(fill="x", padx=8, pady=8)
        ttk.Button(bot, text="Add selected", command=self.add).pack(side="left")
        ttk.Button(bot, text="Close", command=self.destroy).pack(side="left", padx=4)
        self.q.trace_add("write", lambda *a: self.fill())
        self.fill()

    def fill(self):
        have, q = set(self.win.addon.keys()), self.q.get().strip().lower()
        self.items = [n for n in self.win.addon.api.nodes.all() if n.get("type") in TYPE_NAMES and n["public_key"] not in have
                      and (not q or q in (n.get("name") or "").lower())]
        self.lb.delete(0, "end")
        for n in self.items: self.lb.insert("end", f"{n.get('name') or n['public_key'][:8]}   [{TYPE_NAMES[n['type']]}]")
        if not self.items: self.lb.insert("end", "(no other repeaters or room servers known yet)" if not q else "(no match)")

    def add(self):
        keys = [self.items[i]["public_key"] for i in self.lb.curselection() if i < len(self.items)]
        if not keys: return
        self.win.addon.add(keys)
        self.fill()
        self.win.fill()
