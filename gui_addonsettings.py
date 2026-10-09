"""An addon's settings in a window of their own: Tools > Addons, double-click the addon (or select it and press Settings...).
The addon builds the page itself (build_options); OK / Apply call its apply_options.  Long pages scroll.

With more than one node connected the window has a tab per node besides 'All nodes': every setting can be made for one node only (what a
node doesn't set comes from 'All nodes'), and the addon then answers each node with that node's settings."""
import tkinter as tk
from tkinter import messagebox, ttk

import gui_platform
from gui_common import BG

ALL = ""                     # the 'All nodes' tab: the defaults


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
        self.node_vars, self.private_var, self.toolbar_var = {}, None, None
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
        if not node and getattr(self.inst, "switch", None):     # its ON/OFF switch on the toolbar: shown or not
            self.toolbar_var = tk.BooleanVar(value=bool(self.api.get("_toolbar", True)))
            tk.Checkbutton(self.top, text="Show its ON/OFF switch on the toolbar", variable=self.toolbar_var, bg=BG, anchor="w").pack(fill="x")
        self.page = None
        self.api._ctx.seen = self.inherited = {}               # what this tab showed from 'All nodes' (see _prune)
        try:
            with self._ctx(): self.page = self.inst.build_options(self.holder)
        except Exception as e:
            tk.Label(self.holder, text=f"This addon's settings page failed to open:\n{e}", bg=BG, fg="#c00000", justify="left").pack(anchor="w")
        finally:
            self.api._ctx.seen = None
        if self.page is not None: self.page.pack(fill="both", expand=True)
        elif not self.holder.winfo_children():
            tk.Label(self.holder, text="This addon has no settings.", bg=BG).pack(anchor="w")
        self.canvas.yview_moveto(0)

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
