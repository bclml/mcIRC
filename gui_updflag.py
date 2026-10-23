"""'An update is waiting': a big red UPDATE square flashes at the start of the toolbar (clicking it opens Help > Check for updates) until
the update is installed.  What is waiting is remembered in the settings ('update_waiting'), so it still shows after a restart (the check
itself runs once a day), and goes away by itself once mcIRC / the addons are at those versions."""
import tkinter as tk

import gui_addons as ga
import gui_update

FLASH_MS = 600
RED, DARK = "#d00000", "#6e0000"


def waiting(settings, local_version, installed_version):
    """What is still waiting from settings['update_waiting'] {'app': '<version>', 'addons': {name: version}}: (app version or '', [addon names])."""
    w = settings.get("update_waiting") or {}
    app = w.get("app") or ""
    if app and ga.vkey(local_version) >= ga.vkey(app): app = ""
    addons = [n for n, v in (w.get("addons") or {}).items() if installed_version(n) and ga.vkey(installed_version(n)) < ga.vkey(v)]
    return app, addons


class UpdateFlagMixin:
    def note_updates(self, newer_version, addon_updates):
        """A check found (or didn't find) updates: newer_version '' / None when mcIRC is up to date; addon_updates [(name, old, new, entry)]."""
        self.settings["update_waiting"] = {"app": newer_version or "", "addons": {u[0]: u[2] for u in addon_updates or []}}
        self.save()
        self.show_update_flag()

    def show_update_flag(self):
        """The UPDATE square while something is waiting; gone (and forgotten) when nothing is."""
        app, addons = waiting(self.settings, gui_update.local_version(), self.addons.installed_version)
        on = bool(app or addons)
        btn = getattr(self, "update_btn", None)
        if not on:
            if self.settings.get("update_waiting"):
                self.settings["update_waiting"] = {}
                self.save()
            if btn is not None: btn.destroy()
            self.update_btn = None
            return
        if btn is None and getattr(self, "toolbar", None) is not None:
            from gui_update_ui import UpdateDialog
            first = next(iter(self.toolbar.pack_slaves()), None)
            btn = self.update_btn = tk.Button(self.toolbar, text="UPDATE", command=lambda: UpdateDialog(self), fg="white", bg=RED,
                                              activebackground=RED, activeforeground="white", relief="raised", bd=3, padx=16, pady=4,
                                              cursor="hand2", takefocus=False, font=("TkDefaultFont", 12, "bold"))
            btn.pack(side="left", padx=(2, 8), pady=2, **({"before": first} if first is not None else {}))
            try:
                import gui_style
                what = (["mcIRC " + app] if app else []) + ([f"{len(addons)} addon update{'s' if len(addons) > 1 else ''}"] if addons else [])
                gui_style.Tooltip(btn, "Update waiting: " + " + ".join(what) + " - click to install")
            except Exception: pass
            self._flash_update(True)

    def _flash_update(self, lit):
        btn = getattr(self, "update_btn", None)
        if btn is None or not btn.winfo_exists(): return
        btn.config(bg=RED if lit else DARK)
        self.root.after(FLASH_MS, lambda: self._flash_update(not lit))
