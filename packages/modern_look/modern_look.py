"""Modern look: flat window chrome (toolbar, buttons, tabs, status bar, scrollbars, dialogs) in the colours of your skin or colour theme."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from gui_addons import AddonBase

CLASSIC_BG = {"#d4d0c8", "systembuttonface", "#d9d9d9", "#f0f0f0", "#ececec"}      # the backgrounds of the classic grey look
WHITE_BG = {"white", "#ffffff", "systemwindow"}
DARK_TEXT = {"black", "#000000", "#000", "systembuttontext", "systemwindowtext"}
CHROME = {"Frame", "Label", "Button", "Checkbutton", "Radiobutton", "PanedWindow", "Labelframe", "Toplevel", "Tk", "Scale", "Canvas", "Message"}
FIELDS = {"Entry", "Listbox", "Spinbox"}
OPTS = ("bg", "fg", "relief", "overrelief", "bd", "activebackground", "activeforeground", "highlightthickness", "highlightbackground", "highlightcolor",
        "selectcolor", "sashrelief", "insertbackground", "font", "readonlybackground", "disabledforeground")
TAG = "ModernLookHover"


class Addon(AddonBase):
    title = "Modern look"
    version = "1.0.0"
    author = "mcIRC"
    description = "Flat, modern window chrome - toolbar, buttons, tabs, status bar, scrollbars and dialogs - in the colours of your skin or colour theme. Switch it off to get the classic look back."
    tick_seconds = 1                       # restyle windows and buttons that appeared since the last pass

    def on_load(self):
        self.saved, self.target, self.style_saved = {}, {}, None
        self.ui = self.api.ui()
        self.root = self.ui.get("root") if isinstance(self.ui, dict) else None
        self.active = isinstance(self.root, tk.Misc)               # (the package checker runs addons without a real window)
        if not self.active: return
        self.root.bind_class(TAG, "<Enter>", self._hover_in, add="+")
        self.root.bind_class(TAG, "<Leave>", self._hover_out, add="+")
        self.colours(self.api.theme)
        self.restyle()

    def on_unload(self):
        if not getattr(self, "active", False): return
        self.active = False
        for w, orig in list(self.saved.items()):
            try:
                w.config(**orig)
                w.bindtags(tuple(t for t in w.bindtags() if t != TAG))
            except tk.TclError:
                pass
        self.saved, self.target = {}, {}
        if self.style_saved:
            st = ttk.Style()
            try: st.theme_use(self.style_saved)
            except tk.TclError: pass
        self.root.unbind_class(TAG, "<Enter>")
        self.root.unbind_class(TAG, "<Leave>")

    def on_theme(self, theme):
        if not getattr(self, "active", False): return
        self.colours(theme)
        self.restyle()

    def on_tick(self):
        if getattr(self, "active", False): self.restyle(widgets_only=True)

    # ---- colours ----
    def _rgb(self, c):
        r, g, b = self.root.winfo_rgb(c)
        return r / 257, g / 257, b / 257

    @staticmethod
    def _hex(c): return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)
    def _mix(self, a, b, t): return self._hex(tuple(x * (1 - t) + y * t for x, y in zip(self._rgb(a), self._rgb(b))))
    def _lum(self, c):
        r, g, b = self._rgb(c)
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    def _text_on(self, bg): return "#101010" if self._lum(bg) > 0.55 else "#f2f2f2"

    def colours(self, t):
        pane, accent = t.get("pane_bg", "#ffffff"), t.get("sel_bg", "#316ac5")
        dark = self._lum(pane) < 0.5
        self.c = {
            "chrome": self._mix(pane, "#ffffff" if dark else "#000000", 0.06),
            "bar": self._mix(pane, accent, 0.28 if dark else 0.16),
            "hover": self._mix(pane, accent, 0.5),
            "accent": accent, "accent_fg": t.get("sel_fg", "#ffffff"),
            "field": t.get("entry_bg", "#ffffff"), "field_fg": t.get("entry_fg", "#000000"), "pane": pane, "pane_fg": t.get("pane_fg", "#000000"),
        }
        self.c["chrome_fg"], self.c["bar_fg"] = self._text_on(self.c["chrome"]), self._text_on(self.c["bar"])

    # ---- ttk widgets (buttons, scrollbars, combo boxes, lists, tabs) ----
    def style_ttk(self):
        c, st = self.c, ttk.Style()
        if self.style_saved is None:
            self.style_saved = st.theme_use()
            self._font = st.lookup(".", "font") or "TkDefaultFont"
            self._rowheight = st.lookup("Treeview", "rowheight") or 18
        if st.theme_use() != "clam": st.theme_use("clam")
        font = self.font_name()
        st.configure(".", background=c["chrome"], foreground=c["chrome_fg"], fieldbackground=c["field"], bordercolor=c["bar"], lightcolor=c["chrome"],
                     darkcolor=c["chrome"], troughcolor=c["pane"], focuscolor=c["accent"], selectbackground=c["accent"], selectforeground=c["accent_fg"], font=font)
        st.configure("TButton", background=c["bar"], foreground=c["bar_fg"], borderwidth=0, padding=(10, 3), relief="flat")
        st.map("TButton", background=[("pressed", c["accent"]), ("active", c["hover"])], foreground=[("pressed", c["accent_fg"]), ("active", self._text_on(c["hover"]))])
        st.configure("TScrollbar", background=c["bar"], troughcolor=c["pane"], arrowcolor=c["bar_fg"], bordercolor=c["pane"], relief="flat", gripcount=0)
        st.map("TScrollbar", background=[("active", c["hover"])])
        st.configure("Treeview", background=c["pane"], fieldbackground=c["pane"], foreground=c["pane_fg"], borderwidth=0, rowheight=self._rowheight, font=font)
        st.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", c["accent_fg"])])
        st.configure("Treeview.Heading", background=c["bar"], foreground=c["bar_fg"], relief="flat", font=font)
        st.map("Treeview.Heading", background=[("active", c["hover"])])
        for kind in ("TCombobox", "TEntry", "TSpinbox"):
            st.configure(kind, fieldbackground=c["field"], foreground=c["field_fg"], background=c["bar"], arrowcolor=c["bar_fg"], insertcolor=c["field_fg"])
            st.map(kind, fieldbackground=[("readonly", c["field"])], foreground=[("readonly", c["field_fg"])])
        for kind in ("TCheckbutton", "TRadiobutton", "TLabel", "TFrame", "TLabelframe", "TLabelframe.Label"):
            st.configure(kind, background=c["chrome"], foreground=c["chrome_fg"])
        st.configure("TNotebook", background=c["chrome"], bordercolor=c["bar"])
        st.configure("TNotebook.Tab", background=c["bar"], foreground=c["bar_fg"], padding=(10, 3))
        st.map("TNotebook.Tab", background=[("selected", c["chrome"])], foreground=[("selected", c["chrome_fg"])])

    def font_name(self):
        if not self.api.get("modern_font", True): return getattr(self, "_font", "TkDefaultFont")
        have = {f.lower() for f in tkfont.families(self.root)}
        for fam in ("Segoe UI", "Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans", "Helvetica Neue", "Helvetica"):
            if fam.lower() in have: return (fam, 9)
        return "TkDefaultFont"

    # ---- classic tk widgets ----
    def _all(self, w):
        yield w
        for ch in w.winfo_children(): yield from self._all(ch)

    def _in_bar(self, w):
        bars = [self.ui.get("toolbar"), self.ui.get("statusbar")]
        while w is not None:
            if w in bars: return True
            w = w.master
        return False

    def _remember(self, w):
        if w in self.saved: return
        orig = {}
        for o in OPTS:
            try: orig[o] = w.cget(o)
            except tk.TclError: pass
        self.saved[w] = orig

    def _set(self, w, **kw):
        ok = {}
        for k, v in kw.items():
            try:
                w.cget(k)
                ok[k] = v
            except tk.TclError:
                pass
        if ok: w.config(**ok)

    def style_widget(self, w):
        cls = w.winfo_class()
        try: bg = str(w.cget("bg")).lower()
        except tk.TclError: return
        mine = w in self.target and bg == self.target[w].lower()
        c = self.c
        if cls in CHROME and (bg in CLASSIC_BG or mine):
            self._remember(w)
            back = c["bar"] if self._in_bar(w) else c["chrome"]
            text = self._text_on(back)
            relief = str(self.saved[w].get("relief", "flat"))
            if cls == "Button" and relief == "sunken":                  # the tab of the window in front
                back, text = self._mix(c["accent"], c["chrome"], 0.35), c["accent_fg"]
            self._set(w, bg=back, highlightthickness=0, activebackground=c["hover"], activeforeground=self._text_on(c["hover"]))
            if str(self.saved[w].get("fg", "")).lower() in DARK_TEXT: self._set(w, fg=text)      # plain black text follows the background; coloured text (status words, unread tabs) keeps its colour
            if cls in ("Button", "Label"): self._set(w, relief="flat", overrelief="flat", bd=0 if cls == "Button" else 1)
            if cls in ("Checkbutton", "Radiobutton"): self._set(w, selectcolor=c["field"])
            if cls == "PanedWindow": self._set(w, sashrelief="flat")
            if cls in ("Label", "Button", "Checkbutton", "Radiobutton") and self.api.get("modern_font", True) and not w.cget("image"):
                self._set(w, font=self.font_name())
            if cls == "Button" and TAG not in w.bindtags(): w.bindtags((TAG,) + w.bindtags())
            self.target[w] = back
        elif cls in ("Text", "Listbox", "Entry") and (w in (self.ui.get("entry"), self.ui.get("nicklist"), self.ui.get("topic")) or cls == "Text"):
            if w not in self.saved and str(w.cget("relief")) != "sunken": return
            self._remember(w)                                             # chat text, name list, input line: their colours come from the theme; only the 3D border goes
            self._set(w, relief="flat", bd=0, highlightthickness=1, highlightbackground=c["bar"], highlightcolor=c["accent"])
        elif cls in FIELDS and (bg in WHITE_BG or mine) and w not in (self.ui.get("entry"), self.ui.get("nicklist")):
            self._remember(w)
            self._set(w, bg=c["field"], fg=c["field_fg"], insertbackground=c["field_fg"], relief="flat", highlightthickness=1,
                      highlightbackground=c["bar"], highlightcolor=c["accent"], readonlybackground=c["field"])
            self.target[w] = c["field"]

    def restyle(self, widgets_only=False):
        if not widgets_only: self.style_ttk()
        for w in self._all(self.root):
            try: self.style_widget(w)
            except tk.TclError: pass
        for w in [w for w in self.saved if not w.winfo_exists()]:          # closed dialogs
            self.saved.pop(w, None)
            self.target.pop(w, None)

    # ---- hover on flat buttons ----
    def _hover_in(self, e):
        w = e.widget
        if w in self.target and str(w.cget("bg")).lower() == self.target[w].lower() and str(w.cget("state")) != "disabled":
            w.config(bg=self.c["hover"])

    def _hover_out(self, e):
        w = e.widget
        if w in self.target and str(w.cget("bg")).lower() == self.c["hover"].lower(): w.config(bg=self.target[w])

    # ---- options ----
    def build_options(self, parent):
        self.v_font = tk.BooleanVar(value=self.api.get("modern_font", True))
        f = tk.Frame(parent, bg=parent["bg"])
        tk.Checkbutton(f, text="Modern font for menus and buttons (Segoe UI instead of Tahoma)", variable=self.v_font, bg=parent["bg"]).pack(anchor="w")
        tk.Label(f, text="The colours follow your skin or colour theme (Options > Display). Switch this addon off for the classic grey look.",
                 bg=parent["bg"], fg="#555", wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))
        return f

    def apply_options(self):
        changed = self.api.get("modern_font", True) != self.v_font.get()
        self.api.set("modern_font", self.v_font.get())
        if changed:
            self.on_unload()
            self.on_load()
