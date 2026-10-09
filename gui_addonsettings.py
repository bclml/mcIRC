"""An addon's settings in a window of their own: Tools > Addons, double-click the addon (or select it and press Settings...).
The addon builds the page itself (build_options); OK / Apply call its apply_options.  Long pages scroll."""
import tkinter as tk
from tkinter import messagebox, ttk

import gui_platform
from gui_common import BG


class AddonSettingsWindow(tk.Toplevel):
    def __init__(self, app, name, parent=None):
        super().__init__(parent or app.root, bg=BG)
        self.app, self.name = app, name
        inst, _ = app.addons.loaded[name]
        title, ver, author, desc = app.addons.info(name)
        self.title(f"{title} - settings")
        self.geometry("700x560")
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(head, text=f"{title}  {ver}", bg=BG, font=(gui_platform.UI_FONT_NAME, 11, "bold"), anchor="w").pack(anchor="w")
        if desc: tk.Label(head, text=desc, bg=BG, fg="#555", wraplength=660, justify="left", anchor="w").pack(anchor="w")
        self.node_vars = {}
        extra = [c["label"] for c in app.settings.get("extra_nodes", []) if c.get("label")]
        if extra:                                              # more than one node: which ones this addon works on
            row = tk.Frame(self, bg=BG)
            row.pack(fill="x", padx=10, pady=(4, 0))
            tk.Label(row, text="Use on these nodes:", bg=BG).pack(side="left")
            on = set(app.addons.nodes_for(name))
            for label in ["main"] + extra:
                self.node_vars[label] = tk.BooleanVar(value=label in on)
                tk.Checkbutton(row, text="main node" if label == "main" else label, variable=self.node_vars[label], bg=BG).pack(side="left")
        self.private_var = None
        if self._is_bot(inst):                                 # an addon that answers people: answers in the channel or privately
            self.private_var = tk.BooleanVar(value=bool(app.settings.get("addons", {}).get(name, {}).get("_reply_private", False)))
            tk.Checkbutton(self, text="Send answers by private message instead of in the channel (to whoever asked)", variable=self.private_var,
                           bg=BG, anchor="w").pack(fill="x", padx=10, pady=(4, 0))
        self.toolbar_var = None
        if getattr(inst, "switch", None):                      # it has an ON/OFF switch on the toolbar: shown or not
            self.toolbar_var = tk.BooleanVar(value=bool(app.settings.get("addons", {}).get(name, {}).get("_toolbar", True)))
            tk.Checkbutton(self, text="Show its ON/OFF switch on the toolbar", variable=self.toolbar_var, bg=BG, anchor="w").pack(fill="x", padx=10)
        buttons = tk.Frame(self, bg=BG)
        buttons.pack(side="bottom", fill="x", padx=10, pady=8)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply", command=self.apply).pack(side="right", padx=4)
        ttk.Button(buttons, text="OK", command=lambda: self.apply() and self.destroy()).pack(side="right")
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=4)
        canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(body, command=canvas.yview)
        canvas.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        holder = tk.Frame(canvas, bg=BG)
        canvas.create_window(0, 0, window=holder, anchor="nw")
        holder.bind("<Configure>", lambda e: canvas.config(scrollregion=canvas.bbox("all")))
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self.page = None
        try: self.page = inst.build_options(holder)
        except Exception as e:
            tk.Label(holder, text=f"This addon's settings page failed to open:\n{e}", bg=BG, fg="#c00000", justify="left").pack(anchor="w")
        if self.page is not None: self.page.pack(fill="both", expand=True)
        elif not holder.winfo_children():
            tk.Label(holder, text="This addon has no settings.", bg=BG).pack(anchor="w")
        self.transient(parent or app.root)

    def _is_bot(self, inst):
        """Answers people: it lists bot commands for 'bothelp', or says so (replies = True)."""
        return getattr(inst, "replies", False) or any(getattr(api, "name", None) == self.name for api, _ in getattr(self.app, "bot_helps", []))

    def apply(self):
        if self.private_var is not None:
            self.app.settings.setdefault("addons", {}).setdefault(self.name, {})["_reply_private"] = bool(self.private_var.get())
            self.app.save()
        if self.node_vars:
            self.app.settings.setdefault("addons", {}).setdefault(self.name, {})["_nodes"] = [k for k, v in self.node_vars.items() if v.get()]
            self.app.save()
        if self.toolbar_var is not None and self.name in self.app.addons.loaded:
            self.app.settings.setdefault("addons", {}).setdefault(self.name, {})["_toolbar"] = bool(self.toolbar_var.get())
            self.app.save()
            self.app.addons.loaded[self.name][1]._draw_switch()
        if self.page is None: return True
        try: self.app.addons._call(self.name, "apply_options")
        except Exception as e:
            messagebox.showerror("Settings", f"Could not save: {e}", parent=self)
            return False
        self.app.save()
        return True


def open_settings(app, name, parent=None):
    """Opens the settings window of an addon; an addon that is switched off is switched on first (after asking)."""
    if name not in app.addons.loaded:
        if not messagebox.askyesno("Addon settings", f"'{name}' is switched off. Switch it on to change its settings?", parent=parent): return None
        app.addons.set_enabled(name, True)
        if name not in app.addons.loaded:
            messagebox.showerror("Addon settings", f"'{name}' could not be switched on:\n{app.addons.errors.get(name, '')[-400:]}", parent=parent)
            return None
    return AddonSettingsWindow(app, name, parent)
