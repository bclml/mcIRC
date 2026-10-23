"""Nodes dashboard - the window: your nodes in a table, graphs of the one you pick (or of all of them), adding and removing nodes."""
import time
import tkinter as tk
from tkinter import messagebox, ttk

import ndash_core as core

BG = "#d4d0c8"
KIND_COLORS = {"advert": "#1a5fb4", "relay": "#813d9c", "msg": "#26a269"}
KIND_LABELS = {"advert": "its adverts", "relay": "relayed to you", "msg": "messages"}
STATUS = {"online": "#26a269", "quiet": "#c64600", "silent": "#c01c28", "never": "#777777"}
STATUS_ORDER = {"online": 0, "quiet": 1, "silent": 2, "never": 3}
BOLD, FONT, SMALL = ("Segoe UI", 9, "bold"), ("Segoe UI", 9), ("Segoe UI", 7)
COLS = (("status", "status", 60), ("name", "name", 170), ("type", "type", 85), ("last heard", "last", 85), ("heard by", "via", 75),
        ("adverts", "adverts", 55), ("relayed", "relays", 60), ("msgs", "msgs", 45), ("snr", "snr", 45), ("best snr", "best", 60), ("hops", "hops", 40))


def ago(t, now):
    if not t: return "never"
    s = max(0, now - t)
    if s < 90: return f"{int(s)} s ago"
    if s < 5400: return f"{int(s // 60)} min ago"
    if s < 172800: return f"{int(s // 3600)} h ago"
    return f"{int(s // 86400)} days ago"


def fmt(v): return "" if v is None else f"{v:+.1f}" if isinstance(v, float) else str(v)


class Dashboard(tk.Toplevel):
    def __init__(self, addon):
        super().__init__(addon.api.ui()["root"], bg=BG)
        self.addon, self.rows, self.sort_by = addon, {}, ("last", True)
        self.title("Nodes dashboard")
        self.geometry("1250x660")
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Button(top, text="Add nodes...", command=lambda: AddDialog(self)).pack(side="left")
        ttk.Button(top, text="Remove", command=self.remove).pack(side="left", padx=4)
        ttk.Button(top, text="Graph all", command=lambda: self.t.selection_set(())).pack(side="left")
        self.span = tk.IntVar(value=24)
        for text, hours in (("Last 24 h", 24), ("Last 7 days", 168)):
            tk.Radiobutton(top, text=text, variable=self.span, value=hours, bg=BG, command=self.update_rows).pack(side="left", padx=(8, 0))
        self.summary = tk.Label(top, bg=BG, font=BOLD)
        self.summary.pack(side="right")
        pane = tk.PanedWindow(self, orient="horizontal", bg=BG, sashwidth=5)
        pane.pack(fill="both", expand=True, padx=6)
        left = tk.Frame(pane, bg=BG)
        self.t = ttk.Treeview(left, columns=[c for c, _, _ in COLS], show="headings", selectmode="extended")
        for c, field, w in COLS:
            self.t.heading(c, text=c, command=lambda f=field: self.sort(f))
            self.t.column(c, width=w, anchor="w", stretch=c == "name")
        sb = ttk.Scrollbar(left, command=self.t.yview)
        self.t.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.t.pack(fill="both", expand=True)
        for st, col in STATUS.items(): self.t.tag_configure(st, foreground=col)
        self.t.bind("<<TreeviewSelect>>", lambda e: self.draw())
        self.c = tk.Canvas(pane, bg="white", highlightthickness=0)
        self.c.bind("<Configure>", lambda e: self.draw())
        pane.add(left, minsize=380, width=800)
        pane.add(self.c, minsize=300)
        tk.Label(self, bg=BG, fg="#555", anchor="w", justify="left", wraplength=1100, text=(
            "Pick one node for its graphs; none or several for a comparison. Online = heard within an hour, quiet = within a day, silent = longer. "
            "'Relayed' counts packets the node repeated straight to your radio (only when its key's first byte is unique among the repeaters "
            "you know). It only listens: a repeater's own battery and counters need a login, which this never does.")).pack(fill="x", padx=6, pady=4)
        self.tick()

    def tick(self):
        if not self.winfo_exists(): return
        self.update_rows()
        self.after(5000, self.tick)

    def update_rows(self):
        now = time.time()
        rows = {r["key"]: r for r in self.addon.rows(self.span.get() * 3600)}
        for iid in self.t.get_children():
            if iid not in rows: self.t.delete(iid)
        for k, r in rows.items():
            vals = ("● " + r["status"], r["name"], r["type"], ago(r["last"], now), r["via"], r["adverts"], r["relays"], r["msgs"],
                    fmt(r["snr"]), fmt(r["best"]), fmt(r["hops"]))
            if self.t.exists(k): self.t.item(k, values=vals, tags=(r["status"],))
            else: self.t.insert("", "end", iid=k, values=vals, tags=(r["status"],))
        self.rows = rows
        counts = {s: sum(r["status"] == s for r in rows.values()) for s in STATUS}
        self.summary.config(text=f"{len(rows)} nodes:  {counts['online']} online   {counts['quiet']} quiet   {counts['silent'] + counts['never']} silent")
        self.sort(None)
        self.draw()

    def sort(self, field):
        if field: self.sort_by = (field, not self.sort_by[1] if self.sort_by[0] == field else field in ("last", "adverts", "relays", "msgs", "snr", "best"))
        f, rev = self.sort_by
        def val(k):
            v = STATUS_ORDER[self.rows[k]["status"]] if f == "status" else self.rows[k].get(f)
            return v.lower() if isinstance(v, str) else v
        ks = [k for k in self.t.get_children() if k in self.rows]
        order = sorted((k for k in ks if val(k) is not None), key=val, reverse=rev) + [k for k in ks if val(k) is None]     # blanks last
        for i, k in enumerate(order): self.t.move(k, "", i)

    def remove(self):
        keys = [k for k in self.t.selection() if k in self.rows]
        if not keys: return messagebox.showinfo("Nodes dashboard", "Pick the nodes to remove in the table first.", parent=self)
        names = ", ".join(self.rows[k]["name"] for k in keys[:5]) + (f" and {len(keys) - 5} more" if len(keys) > 5 else "")
        if messagebox.askyesno("Nodes dashboard", f"Remove {names} from the dashboard?\nTheir graph history is deleted too "
                               "(the nodes themselves stay in mcIRC's node list).", parent=self):
            self.addon.remove_nodes(keys)
            self.update_rows()

    # ---- graphs ----
    def draw(self):
        c = self.c
        c.delete("all")
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 300)
        sel = [k for k in self.t.selection() if k in self.rows]
        if len(sel) == 1: self.draw_node(self.rows[sel[0]], w, h)
        else: self.draw_overview([self.rows[k] for k in sel] or [self.rows[k] for k in self.t.get_children() if k in self.rows], w, h)

    def draw_overview(self, rows, w, h):
        c, now, span = self.c, time.time(), self.span.get()
        if not rows:
            c.create_text(w / 2, h / 2, text="No nodes on the dashboard yet.\nPress 'Add nodes...' to pick some.", font=FONT, justify="center")
            return
        c.create_text(10, 12, anchor="w", font=BOLD, text=f"Packets heard per node, last {'24 h' if span == 24 else '7 days'}")
        self.legend(w - 10, 12)
        step = max(12, min(26, (h - 40) / len(rows)))
        fits = int((h - 40) // step)
        top = max([r["adverts"] + r["relays"] + r["msgs"] for r in rows] + [1])
        x0, x1 = min(170, w * 0.4), w - 120
        for i, r in enumerate(rows[:fits]):
            y = 34 + i * step
            c.create_text(x0 - 6, y + step / 2, anchor="e", text=r["name"][:24], font=SMALL if step < 18 else FONT, fill=STATUS[r["status"]])
            x = x0
            for kind, n in (("advert", r["adverts"]), ("relay", r["relays"]), ("msg", r["msgs"])):
                if n: c.create_rectangle(x, y + 2, x + (x1 - x0) * n / top, y + step - 2, fill=KIND_COLORS[kind], outline="")
                x += (x1 - x0) * n / top
            c.create_text(x + 4, y + step / 2, anchor="w", font=SMALL, text=f"{r['adverts'] + r['relays'] + r['msgs']}  ·  {ago(r['last'], now)}")
        if len(rows) > fits: c.create_text(10, h - 8, anchor="w", font=SMALL, text=f"+{len(rows) - fits} more - make the window taller")

    def legend(self, x, y):
        for kind in reversed(core.KINDS):
            item = self.c.create_text(x, y, anchor="e", text=KIND_LABELS[kind], font=SMALL)
            x = self.c.bbox(item)[0] - 4
            self.c.create_rectangle(x - 8, y - 4, x, y + 4, fill=KIND_COLORS[kind], outline="")
            x -= 14

    def draw_node(self, r, w, h):
        c, now, span = self.c, time.time(), self.span.get() * 3600
        start = now - span
        pos = f"{r['lat']:.4f}, {r['lon']:.4f}" if r["lat"] or r["lon"] else "no position"
        c.create_text(10, 12, anchor="w", font=BOLD, fill=STATUS[r["status"]], text=f"{r['name']}  ({r['type']}, {r['status']})")
        c.create_text(10, 30, anchor="w", font=SMALL, text=f"key {r['key'][:16]}...   {pos}   first seen "
                      f"{time.strftime('%Y-%m-%d', time.localtime(r['first'])) if r['first'] else '?'}   heard by: {r['via'] or '?'}")
        self.legend(w - 10, 12)
        x0, x1, ev = 50, w - 12, r["events"]
        def xt(t): return x0 + (t - start) / span * (x1 - x0)
        panels = ((62, 0.44), (0.44, 0.73), (0.73, 1.0))
        y = [(p0 if p0 > 1 else p0 * (h - 20) + 22, p1 * (h - 20) - 4) for p0, p1 in panels]
        # 1. signal
        pts = [(e[0], e[2], e[1]) for e in ev if isinstance(e[2], (int, float))]
        self.frame(y[0], x0, x1, "Signal (SNR, dB)" + (f":  last {pts[-1][1]:+.1f}" if pts else ":  nothing heard in this time"))
        if pts:
            lo, hi = min(p[1] for p in pts) - 1, max(p[1] for p in pts) + 1
            ya, yb = y[0]
            def ys(v): return yb - (v - lo) / (hi - lo) * (yb - ya)
            if lo < 0 < hi: c.create_line(x0, ys(0), x1, ys(0), fill="#bbb", dash=(3, 3))
            for t, v, kind in pts:
                c.create_oval(xt(t) - 2, ys(v) - 2, xt(t) + 2, ys(v) + 2, fill=KIND_COLORS[kind], outline="")
            c.create_text(x0 - 4, ya, anchor="ne", font=SMALL, text=f"{hi:.0f}")
            c.create_text(x0 - 4, yb, anchor="se", font=SMALL, text=f"{lo:.0f}")
        # 2. activity
        n = 24 if span <= 86400 else 28
        bk = core.buckets(ev, now, span, n)
        top = max([sum(b.values()) for b in bk] + [1])
        ya, yb = y[1]
        self.frame(y[1], x0, x1, f"Packets per {'hour' if n == 24 else '6 hours'}:  {len(ev)} in all")
        bw = (x1 - x0) / n
        for i, b in enumerate(bk):
            base = yb
            for kind in core.KINDS:
                if b[kind]:
                    hgt = b[kind] / top * (yb - ya)
                    c.create_rectangle(x0 + i * bw + 1, base - hgt, x0 + (i + 1) * bw - 1, base, fill=KIND_COLORS[kind], outline="")
                    base -= hgt
        c.create_text(x0 - 4, ya, anchor="ne", font=SMALL, text=str(top))
        # 3. hops of its adverts
        hp = [(e[0], e[4]) for e in ev if e[1] == "advert" and isinstance(e[4], int)]
        ya, yb = y[2]
        self.frame(y[2], x0, x1, "Hops of its adverts" + (f":  last {hp[-1][1]}" if hp else ":  no advert heard in this time"))
        if hp:
            top = max(max(v for _, v in hp), 1)
            for t, v in hp: c.create_rectangle(xt(t) - 2, yb - v / top * (yb - ya) - 2, xt(t) + 2, yb - v / top * (yb - ya) + 2, fill=KIND_COLORS["advert"], outline="")
            c.create_text(x0 - 4, ya, anchor="ne", font=SMALL, text=str(top))
            c.create_text(x0 - 4, yb, anchor="se", font=SMALL, text="0")
        fmt_t = "%H:%M" if span <= 86400 else "%a %H:%M"
        for frac, anchor in ((0, "w"), (0.5, "center"), (1, "e")):
            c.create_text(x0 + frac * (x1 - x0), h - 6, anchor=anchor, font=SMALL, text=time.strftime(fmt_t, time.localtime(start + frac * span)))

    def frame(self, ys, x0, x1, title):
        self.c.create_text(x0, ys[0] - 8, anchor="w", font=FONT, text=title)
        self.c.create_rectangle(x0, ys[0], x1, ys[1], outline="#ccc")


class AddDialog(tk.Toplevel):
    """Every node mcIRC remembers that isn't on the dashboard yet, with a search box and a type filter."""
    def __init__(self, dash):
        super().__init__(dash, bg=BG)
        self.dash, self.items = dash, []
        self.title("Add nodes to the dashboard")
        self.geometry("540x500")
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=8, pady=8)
        tk.Label(row, text="Search:", bg=BG).pack(side="left")
        self.q = tk.StringVar()
        e = tk.Entry(row, textvariable=self.q, width=24)
        e.pack(side="left", padx=4)
        e.focus_set()
        self.kind = tk.StringVar(value="All")
        cb = ttk.Combobox(row, textvariable=self.kind, values=["All"] + list(core.TYPE_NAMES.values()), state="readonly", width=12)
        cb.pack(side="left", padx=4)
        mid = tk.Frame(self, bg=BG)
        mid.pack(fill="both", expand=True, padx=8)
        self.lb = tk.Listbox(mid, selectmode="extended", font=FONT, activestyle="none")
        sb = ttk.Scrollbar(mid, command=self.lb.yview)
        self.lb.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.lb.pack(fill="both", expand=True)
        self.lb.bind("<Double-Button-1>", lambda ev: self.add())
        bot = tk.Frame(self, bg=BG)
        bot.pack(fill="x", padx=8, pady=8)
        ttk.Button(bot, text="Add selected", command=self.add).pack(side="left")
        ttk.Button(bot, text="Close", command=self.destroy).pack(side="left", padx=4)
        self.hint = tk.Label(bot, bg=BG, fg="#555", text="Ctrl- or Shift-click picks several.")
        self.hint.pack(side="left", padx=8)
        self.q.trace_add("write", lambda *a: self.fill())
        cb.bind("<<ComboboxSelected>>", lambda ev: self.fill())
        self.fill()

    def fill(self):
        have, q, kind, now = set(self.dash.addon.keys()), self.q.get().strip().lower(), self.kind.get(), time.time()
        self.items = [n for n in self.dash.addon.api.nodes.all() if n["public_key"] not in have
                      and (kind == "All" or core.TYPE_NAMES.get(n.get("type")) == kind)
                      and (not q or q in (n.get("name") or "").lower() or n["public_key"].lower().startswith(q))]
        self.lb.delete(0, "end")
        for n in self.items:
            self.lb.insert("end", f"{n.get('name') or n['public_key'][:8]}    [{core.TYPE_NAMES.get(n.get('type'), '?')}, last heard {ago(n.get('last_seen'), now)}]")
        if not self.items: self.lb.insert("end", "(nothing to add - mcIRC hasn't heard any other node yet)" if not q and kind == "All" else "(no match)")

    def add(self):
        keys = [self.items[i]["public_key"] for i in self.lb.curselection() if i < len(self.items)]
        if not keys: return
        self.dash.addon.add_nodes(keys)
        self.hint.config(text=f"Added {len(keys)} node(s).")
        self.fill()
        self.dash.update_rows()
