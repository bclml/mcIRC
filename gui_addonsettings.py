"""An addon's settings in a window of their own: Tools > Addons, double-click the addon (or select it and press Settings...).
The addon builds the page itself (build_options); OK / Apply call its apply_options.  Long pages scroll.

With more than one node connected the window has a tab per node besides 'All nodes': every setting can be made for one node only (what a
node doesn't set comes from 'All nodes'), and the addon then answers each node with that node's settings."""
import contextlib
import tkinter as tk
from tkinter import messagebox, ttk

import gui_platform
from gui_common import BG

ALL = ""                     # the 'All nodes' tab: the defaults



def _num(v):
    """5.0 -> '5', 2.5 -> '2.5' (for the boxes)."""
    try: v = float(v)
    except (TypeError, ValueError): return str(v)
    return str(int(v)) if v == int(v) else str(v)

class AddonSettingsWindow(tk.Toplevel):
    def __init__(self, app, name, parent=None):
        super().__init__(parent or app.root, bg=BG)
        self.app, self.name = app, name
        self.inst, self.api = app.addons.loaded[name]
        title, ver, author, desc = app.addons.info(name)
        self.title(f"{title} - settings")
        self.geometry("720x600")
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(head, text=f"{title}  {ver}", bg=BG, font=(gui_platform.UI_FONT_NAME, 11, "bold"), anchor="w").pack(anchor="w")
        if desc: tk.Label(head, text=desc, bg=BG, fg="#555", wraplength=680, justify="left", anchor="w").pack(anchor="w")
        self.extra = [c["label"] for c in app.settings.get("extra_nodes", []) if c.get("label")]
        if not hasattr(self.api, "own_settings"): self.extra = []      # mcIRC not restarted since an update: no node tabs, the rest works
        self.tab = ALL
        self.tab_var = tk.StringVar(value=ALL)
        if self.extra:                                          # one tab per node, besides the defaults for all of them
            tabs = tk.Frame(self, bg=BG)
            tabs.pack(fill="x", padx=10, pady=(6, 0))
            tk.Label(tabs, text="Settings for:", bg=BG).pack(side="left", padx=(0, 6))
            self.tab_buttons = {}
            for node in [ALL, "main"] + self.extra:
                b = ttk.Radiobutton(tabs, text=self._tab_text(node), value=node, variable=self.tab_var, style="Toolbutton",
                                    command=lambda: self.switch(self.tab_var.get()))
                b.pack(side="left", padx=1)
                self.tab_buttons[node] = b
        buttons = tk.Frame(self, bg=BG)
        buttons.pack(side="bottom", fill="x", padx=10, pady=8)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply", command=self.apply).pack(side="right", padx=4)
        ttk.Button(buttons, text="OK", command=lambda: self.apply() and self.destroy()).pack(side="right")
        self.reset_btn = ttk.Button(buttons, text="Use 'All nodes' settings for this node", command=self.reset_node)
        self.top = tk.Frame(self, bg=BG)                        # the general switches (they depend on the tab)
        self.top.pack(fill="x", padx=10, pady=(4, 0))
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=4)
        self.canvas = canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(body, command=canvas.yview)
        canvas.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.holder = holder = tk.Frame(canvas, bg=BG)
        canvas.create_window(0, 0, window=holder, anchor="nw")
        holder.bind("<Configure>", lambda e: canvas.config(scrollregion=canvas.bbox("all")))
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._build()
        self.transient(parent or app.root)

    # ---- tabs ----
    def _tab_text(self, node):
        if node == ALL: return "All nodes"
        name = "main node" if node == "main" else node
        return name + (" *" if self.api.own_settings(node) else "")          # * = has settings of its own

    def _ctx(self):
        """The settings the page reads and writes: the defaults, or the open node's own (with=own: saving makes them that node's)."""
        if not hasattr(self.api, "for_node"): return contextlib.nullcontext()
        return self.api.for_node(self.tab or None, own=bool(self.tab))

    def switch(self, node):
        if node == self.tab: return
        if not self.apply(): return self.tab_var.set(self.tab)   # what was changed on this tab is kept before showing the next one
        self.tab = node
        self._build()

    def _build(self):
        for w in list(self.top.winfo_children()) + list(self.holder.winfo_children()): w.destroy()
        self.reset_btn.pack_forget()
        node = self.tab
        if node:
            who = "the main node" if node == "main" else f"'{node}'"
            tk.Label(self.top, bg=BG, fg="#555", justify="left", wraplength=680, anchor="w",
                     text=f"These settings are for {who} only. What you don't change here comes from 'All nodes'.").pack(anchor="w")
            if self.api.own_settings(node): self.reset_btn.pack(side="left")
        self.node_vars, self.private_var, self.toolbar_var, self.delay_vars = {}, None, None, None
        if not node and self.extra:                             # which nodes this addon works on at all
            row = tk.Frame(self.top, bg=BG); row.pack(fill="x")
            tk.Label(row, text="Use on these nodes:", bg=BG).pack(side="left")
            on = set(self.app.addons.nodes_for(self.name))
            for label in ["main"] + self.extra:
                self.node_vars[label] = tk.BooleanVar(value=label in on)
                tk.Checkbutton(row, text="main node" if label == "main" else label, variable=self.node_vars[label], bg=BG).pack(side="left")
        if self._is_bot(self.inst):                             # an addon that answers people: in the channel or privately (per node too)
            with self._ctx(): self.private_var = tk.BooleanVar(value=bool(self.api.get("_reply_private", False)))
            tk.Checkbutton(self.top, text="Send answers by private message instead of in the channel (to whoever asked)", variable=self.private_var,
                           bg=BG, anchor="w").pack(fill="x")
            first, gap = getattr(self.inst, "reply_delay", 5), getattr(self.inst, "part_gap", 9)
            with self._ctx(): self.delay_vars = (tk.StringVar(value=_num(self.api.get("_reply_delay", first))), tk.StringVar(value=_num(self.api.get("_part_gap", gap))))
            row = tk.Frame(self.top, bg=BG); row.pack(fill="x")
            tk.Label(row, text="Wait", bg=BG).pack(side="left")
            tk.Spinbox(row, from_=0, to=120, increment=1, width=4, textvariable=self.delay_vars[0]).pack(side="left", padx=3)
            tk.Label(row, text="seconds before answering, then", bg=BG).pack(side="left")
            tk.Spinbox(row, from_=3, to=120, increment=1, width=4, textvariable=self.delay_vars[1]).pack(side="left", padx=3)
            tk.Label(row, text=f"seconds between parts of a long answer  (default {first} and {gap}: repeaters are still repeating the question "
                               "for a few seconds)", bg=BG, fg="#555").pack(side="left")
            if getattr(self.inst, "command_words", None):
                row = tk.Frame(self.top, bg=BG); row.pack(fill="x", pady=(2, 0))
                ttk.Button(row, text="Command names...", command=self.edit_names).pack(side="left")
                tk.Label(row, text="other words for its commands ('p' for 'path'), or only your own", bg=BG, fg="#555").pack(side="left", padx=6)
        if not node and getattr(self.inst, "switch", None):     # its ON/OFF switch on the toolbar: shown or not
            self.toolbar_var = tk.BooleanVar(value=bool(self.api.get("_toolbar", True)))
            tk.Checkbutton(self.top, text="Show its ON/OFF switch on the toolbar", variable=self.toolbar_var, bg=BG, anchor="w").pack(fill="x")
        self.page = None
        self.inherited = {}                                     # what this tab showed from 'All nodes' (see _prune)
        if hasattr(self.api, "_ctx"): self.api._ctx.seen = self.inherited
        try:
            with self._ctx(): self.page = self.inst.build_options(self.holder)
        except Exception as e:
            tk.Label(self.holder, text=f"This addon's settings page failed to open:\n{e}", bg=BG, fg="#c00000", justify="left").pack(anchor="w")
        finally:
            if hasattr(self.api, "_ctx"): self.api._ctx.seen = None
        if self.page is not None: self.page.pack(fill="both", expand=True)
        elif not self.holder.winfo_children():
            tk.Label(self.holder, text="This addon has no settings.", bg=BG).pack(anchor="w")
        self.canvas.yview_moveto(0)

    def edit_names(self):
        """'Command names...': for each command, other words people can type, and whether its own word still works.  Saved at once
        (for the node of the tab that is open)."""
        words = list(self.inst.command_words)
        with self._ctx(): saved = dict(self.api.get("_names", {}) or {})
        win = tk.Toplevel(self.top); win.title(f"{self.api.display} - command names"); win.configure(bg=BG); win.transient(self.top.winfo_toplevel())
        tk.Label(win, bg=BG, fg="#555", justify="left", wraplength=520, text=(
            "Other words people can type for each command, separated by commas (e.g. 'p' for 'path'). Both work - or tick the box and only "
            "your words work. A word that is already another command is ignored. The call marks (! / .) and the prefix still apply.")).pack(
            anchor="w", padx=10, pady=(8, 4))
        grid = tk.Frame(win, bg=BG); grid.pack(fill="both", expand=True, padx=10)
        tk.Label(grid, text="Command", bg=BG, font=(gui_platform.UI_FONT_NAME, 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(grid, text="Also answers to", bg=BG, font=(gui_platform.UI_FONT_NAME, 9, "bold")).grid(row=0, column=1, sticky="w")
        rows = {}
        for i, cmd in enumerate(words, start=1):
            cfg = saved.get(cmd) if isinstance(saved.get(cmd), dict) else {}
            also, only = tk.StringVar(value=", ".join(cfg.get("also", []))), tk.BooleanVar(value=bool(cfg.get("only")))
            tk.Label(grid, text=cmd, bg=BG).grid(row=i, column=0, sticky="w", padx=(0, 8))
            tk.Entry(grid, textvariable=also, width=24).grid(row=i, column=1, sticky="w", pady=1)
            tk.Checkbutton(grid, text=f"not to '{cmd}' itself", variable=only, bg=BG).grid(row=i, column=2, sticky="w", padx=6)
            rows[cmd] = (also, only)

        def save():
            out = {}
            for cmd, (also, only) in rows.items():
                ws = []
                for w in also.get().replace(";", ",").split(","):
                    w = w.strip().lower().lstrip("!/.@").rstrip("?.,!")
                    if w and " " not in w and w not in words and w not in ws: ws.append(w)
                if ws: out[cmd] = {"also": ws, "only": bool(only.get())}
            with self._ctx(): self.api.set("_names", out)
            if hasattr(self.app, "save"): self.app.save()
            win.destroy()
        bar = tk.Frame(win, bg=BG); bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="OK", command=save).pack(side="right")
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=6)
        self.names_win = win
        return win

    def _is_bot(self, inst):
        """Answers people: it lists bot commands for 'bothelp', or says so (replies = True)."""
        return getattr(inst, "replies", False) or any(getattr(api, "name", None) == self.name for api, _ in getattr(self.app, "bot_helps", []))

    def reset_node(self):
        if not self.tab: return
        self.api.clear_own_settings(self.tab)
        self._refresh_tabs()
        self._build()

    def _refresh_tabs(self):
        for node, b in getattr(self, "tab_buttons", {}).items(): b.config(text=self._tab_text(node))

    # ---- saving ----
    def apply(self):
        store = self.app.settings.setdefault("addons", {}).setdefault(self.name, {})
        if self.private_var is not None:
            with self._ctx(): self.api.set("_reply_private", bool(self.private_var.get()))
        if self.delay_vars is not None:
            for key, var, lo in (("_reply_delay", self.delay_vars[0], 0), ("_part_gap", self.delay_vars[1], 3)):
                try: value = max(lo, min(120, float(var.get().replace(",", "."))))
                except ValueError: continue
                with self._ctx(): self.api.set(key, int(value) if value == int(value) else value)
        if self.node_vars: store["_nodes"] = [k for k, v in self.node_vars.items() if v.get()]
        if self.toolbar_var is not None and self.name in self.app.addons.loaded:
            store["_toolbar"] = bool(self.toolbar_var.get())
            self.api._draw_switch()
        if self.page is not None:
            try:
                with self._ctx(): self.inst.apply_options()
            except Exception as e:
                messagebox.showerror("Settings", f"Could not save: {e}", parent=self)
                return False
        if self.tab: self._prune(self.tab)
        self.app.save()
        self._refresh_tabs()
        self.app.addons.ensure_channels()                    # a channel typed in that the node doesn't have yet: added to it
        return True

    def _prune(self, node):
        """A node keeps only what was really changed on its tab: a value that is still what it inherited from 'All nodes' when the tab
        opened (or equals 'All nodes' now) is dropped - it keeps following the defaults when they change later."""
        store = self.app.settings["addons"][self.name]
        own = store.get("_per_node", {}).get(node)
        if not own: return
        for k in [k for k, v in own.items() if (k in self.inherited and self.inherited[k] == v) or (k in store and store[k] == v)]: del own[k]
        if not own: store["_per_node"].pop(node, None)


def open_settings(app, name, parent=None):
    """Opens the settings window of an addon; an addon that is switched off is switched on first (after asking)."""
    if name not in app.addons.loaded:
        if not messagebox.askyesno("Addon settings", f"'{name}' is switched off. Switch it on to change its settings?", parent=parent): return None
        app.addons.set_enabled(name, True)
        if name not in app.addons.loaded:
            messagebox.showerror("Addon settings", f"'{name}' could not be switched on:\n{app.addons.errors.get(name, '')[-400:]}", parent=parent)
            return None
    return AddonSettingsWindow(app, name, parent)
