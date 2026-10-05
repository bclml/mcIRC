"""/dolphins [nick]: a little pod of dolphins for the channel in front.  Fun actions for a person - the trout slap, dolphins, water
balloons, ... - in the right-click menu on a name (your own list, dolphin_actions.py).  And a picture behind the channel list (the window
tree), with every channel name in its own box so it stays readable - your own picture, or a pod of dolphins drawn by dolphin_scene.py."""
import os
import random
import re
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from gui_addons import AddonBase

MIN_GAP = 10          # seconds between two sends: the mesh is a tiny shared channel
PODS = [
    "~~~ 🐬 🐬 🐬 ~~~ a pod of dolphins leaps through the waves ~~~ 🐬 ~~~",
    "🐬 . 🐬 . 🐬 . 🐬  dolphins ride the bow wave",
    "~ ~ 🐬 ~ ~  splash!  🐬 ~ ~ 🐬 ~ ~ 🐬 ~ ~",
    "🌊 🐬 🌊 🐬 🌊 🐬 🌊 🐬  so long, and thanks for all the fish",
]
TO_ONE = "🐬 🐬 🐬 sends a pod of dolphins to @[{nick}] 🐬"

STYLE = "DolphinBg.Treeview"                     # inherits mcIRC's Treeview colours; only the field (the picture) and the padding are its own
FITS = ("cover", "stretch", "tile")
MAX_PIXELS = 25_000_000
MARGIN = 12                                      # pixels of picture left and right of the boxes


def render(img, width, height, fit="cover", fade=0.35, fade_to="#ffffff"):
    """The picture sized for a list `width` x `height` pixels, faded `fade` (0-0.9) towards the list's own colour so the names stay readable."""
    from PIL import Image
    width, height = max(1, width), max(1, height)
    img = img.convert("RGB")
    if fit == "stretch":
        out = img.resize((width, height))
    elif fit == "tile":
        out = Image.new("RGB", (width, height))
        for x in range(0, width, img.width):
            for y in range(0, height, img.height): out.paste(img, (x, y))
    else:                                                    # cover: fill the list, crop what overflows (centred)
        scale = max(width / img.width, height / img.height)
        big = img.resize((max(width, round(img.width * scale)), max(height, round(img.height * scale))))
        left, top = (big.width - width) // 2, (big.height - height) // 2
        out = big.crop((left, top, left + width, top + height))
    fade = max(0.0, min(0.9, float(fade)))
    if fade:
        rgb = tuple(int(fade_to[i:i + 2], 16) for i in (1, 3, 5)) if isinstance(fade_to, str) and len(fade_to) == 7 else (255, 255, 255)
        out = Image.blend(out, Image.new("RGB", out.size, rgb), fade)
    return out


def load_picture(path):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    img = Image.open(path)
    img.load()
    if img.width * img.height > MAX_PIXELS: raise ValueError("the picture is too big")
    return img.convert("RGB")


def helper(name):
    """A helper module of this addon: installed next to mcIRC, or next to this file (a package being tried out)."""
    import importlib
    try:
        return importlib.import_module(name)
    except ImportError:
        if name == "dolphin_scene" and not pillow_ok(): raise
        import importlib.util
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
        if not os.path.isfile(p): raise
        spec = importlib.util.spec_from_file_location(name, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def scene_module(): return helper("dolphin_scene")


def pillow_ok():
    import importlib.util
    return importlib.util.find_spec("PIL") is not None


def install_pillow():
    """Downloads and installs Pillow for the Python mcIRC runs on (pip; `pip --user` when that is not allowed; uv for a uv setup).
    Returns (installed, what the installer said)."""
    import importlib, shutil, subprocess, sys
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    tries = [[sys.executable, "-m", "pip", "install", "pillow"], [sys.executable, "-m", "pip", "install", "--user", "pillow"]]
    uv = shutil.which("uv")
    if uv: tries.append([uv, "pip", "install", "--python", sys.executable, "pillow"])
    said = ""
    for cmd in tries:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, creationflags=flags)
        except (OSError, subprocess.SubprocessError) as e:
            said += f"{e}\n"
            continue
        said += (r.stdout + r.stderr)[-1500:]
        if r.returncode == 0: break
    importlib.invalidate_caches()
    return pillow_ok(), said


PILLOW_NEEDED = ("The dolphin picture behind the channel list needs Pillow (a free picture library), which isn't installed. "
                 "Install it: double-click Dolphins in Tools > Addons > Install Pillow (or run: pip install pillow).")


class Addon(AddonBase):
    title = "Dolphins"
    version = "1.2.0"
    author = "mcIRC"
    description = ("Fun actions in the right-click menu on a name - slap with a large trout, send dolphins, water balloon, ... "
                   "(your own list); /dolphins, /slap and /fun.  A picture behind the channel list, each channel name in a box.")
    tick_seconds = 0

    def on_load(self):
        self._last = 0.0
        self._installing = False
        self._img = self._photo = self._job = None
        self._size = None
        self._theme = dict(getattr(self.api, "theme", None) or {})
        self.api.add_command("dolphins", self.cmd_dolphins, "/dolphins [nick]: send a pod of dolphins")
        self.api.add_command("fun", self.cmd_fun, "/fun <number or name> <nick>: a fun action (no arguments: the list)")
        if not self.api.has_command("slap"): self.api.add_command("slap", self.cmd_slap, "/slap <nick>: slap someone around a bit with a large trout")
        self.register_actions()
        self.api.after(3000, self._old_slap_note)
        tree = self._tree()
        if tree is not None:
            tree._dolphin_owner = self                            # the copy of this addon that is running now (after an update: the new one)
            if not getattr(tree, "_dolphin_owner_bound", False):  # one hook per window, calling whichever copy is current
                tree.bind("<Configure>", lambda e, t=tree: getattr(t, "_dolphin_owner", None) is not None and t._dolphin_owner._resized(), add="+")
                tree._dolphin_owner_bound = True
        self.api.after(0, self.apply_background)

    def on_unload(self):
        self.remove_background()
        tree = self._tree()
        if tree is not None and getattr(tree, "_dolphin_owner", None) is self: tree._dolphin_owner = None

    def on_theme(self, theme):
        self._theme = dict(theme or {})
        self._size = None                                       # redraw: the fade colour and the boxes follow the new colours
        self.apply_background()

    # ---- fun actions: the right-click menu on a name, /fun and /slap ----
    def actions(self):
        acts = helper("dolphin_actions")
        saved = self.api.get("actions", None)
        return acts.clean(saved) if saved is not None else acts.defaults()

    def register_actions(self):
        self.api.clear_name_actions()
        for a in self.actions(): self.api.add_name_action(a["label"], lambda nick, a=a: self.do_action(a, nick), group="Fun")

    def do_action(self, action, nick):
        nick = re.sub(r"[\[\]@]", "", nick).strip()[:32]
        if not nick: return
        if time.time() - self._last < MIN_GAP: return self.api.notice(f"Easy there - one every {MIN_GAP} seconds: the mesh is a small shared channel.", "warn")
        if not self.api.send_current(helper("dolphin_actions").line(action, nick)):
            return self.api.notice("Open a channel or private window first - it goes to the window in front.", "warn")
        self._last = time.time()

    def cmd_fun(self, arg):
        acts = self.actions()
        words = arg.split()
        if len(words) < 2:
            return self.api.notice("Fun actions: " + ", ".join(f"{i}. {a['label']}" for i, a in enumerate(acts, 1)) + "  - /fun <number or name> <nick>", "info")
        a = helper("dolphin_actions").find(acts, " ".join(words[:-1]))
        if a is None: return self.api.notice(f"No fun action called '{' '.join(words[:-1])}' - /fun lists them.", "warn")
        self.do_action(a, words[-1])

    def cmd_slap(self, arg):
        if not arg.strip(): return self.api.notice("Usage: /slap <nick>", "warn")
        acts = self.actions()
        a = next((x for x in acts if "slap" in x["label"].lower()), None) or helper("dolphin_actions").defaults()[0]
        self.do_action(a, arg)

    def _old_slap_note(self):
        """The Slap addon is replaced by these actions: say so once if it is still switched on."""
        old_slap_on = self.api.has_command("slap") and "slap" not in self.api._commands       # /slap exists, but not ours: the Slap addon's
        if self.api.get("slap_note_shown", False) or not old_slap_on: return
        self.api.set("slap_note_shown", True)
        self.api.log("The trout slap is now one of the Dolphins addon's fun actions (right-click a name > Fun). The Slap addon is no "
                     "longer needed - remove it in Tools > Addons.", "info")

    def cmd_dolphins(self, arg):
        nick = re.sub(r"[\[\]@]", "", arg).strip()[:32]
        if time.time() - self._last < MIN_GAP: return self.api.notice(f"Easy there - one pod every {MIN_GAP} seconds.", "warn")
        if not self.api.send_current(TO_ONE.format(nick=nick) if nick else random.choice(PODS)): return self.api.notice("Open a channel or private window first - /dolphins sends to the window in front.", "warn")
        self._last = time.time()

    # ---- the picture behind the channel list ----
    def _tree(self): return self.api.ui().get("tree")

    def apply_background(self):
        tree = self._tree()
        if tree is None: return
        if not self.api.get("bg_on", True): return self.remove_background()
        path = self.api.get("bg_path", "")
        try:
            if path: self._img = load_picture(path)
            else: self._img = scene_module()                        # the addon's own dolphins, drawn at the list's own size in _redraw
        except ImportError as e:
            self.remove_background()
            if not pillow_ok(): return self.need_pillow()
            return self.api.log(f"The dolphin picture is missing a file ({e}) - Tools > Addons > Update fixes it.", "warn")
        except Exception as e:
            self.remove_background()
            return self.api.log(f"Can't use that picture for the channel list ({e}).", "warn")
        self._size = None
        self._redraw()

    def _resized(self):
        if self._img is not None: self._soon()

    # ---- Pillow missing: a warning, a one-time offer to install it, and the Install Pillow button in the settings ----
    def need_pillow(self):
        self.api.log(PILLOW_NEEDED, "warn")
        if self._installing or self.api.get("pillow_offered", False): return
        self.api.set("pillow_offered", True)                       # asked once; after that the warning and the button remain
        root = self.api.ui().get("root")
        if messagebox.askyesno("Dolphins", "The dolphin picture behind the channel list needs Pillow, a free picture library.\n\n"
                               "Download and install it now? (about 10 MB, from the Python Package Index)", parent=root):
            self.get_pillow()

    def get_pillow(self, then=None):
        """Installs Pillow in the background; the picture appears when it's done (no restart)."""
        if self._installing: return
        self._installing = True
        self.api.log("Downloading and installing Pillow...", "info")
        def done(r):
            self._installing = False
            ok, said = r if isinstance(r, tuple) else (False, str(r))
            if ok:
                self.api.log("Pillow is installed - here come the dolphins.", "info")
                self._size = None
                self.apply_background()
            else:
                self.api.log("Installing Pillow didn't work. Run: pip install pillow  (then restart mcIRC).", "error")
                messagebox.showerror("Dolphins", "Installing Pillow didn't work.\n\nRun this in a command window, then restart mcIRC:\n"
                                     "pip install pillow\n\n" + (said or "")[-600:], parent=self.api.ui().get("root"))
            if then: then(ok)
        self.api.run_background(install_pillow, done)

    def _soon(self):
        if self._job is not None: return
        self._job = self.api.after(250, self._redraw)            # many resize events while dragging the divider become one redraw

    def _redraw(self):
        self._job = None
        tree = self._tree()
        if tree is None or self._img is None or not self.api.get("bg_on", True): return
        try: w, h = tree.winfo_width(), tree.winfo_height()
        except tk.TclError: return
        if w < 20 or h < 20: return self.api.after(300, self._redraw)            # not laid out yet
        if self._size == (w, h): return
        self._size = (w, h)
        from PIL import ImageTk
        t = self._theme or {}
        pane_bg = t.get("pane_bg", "#ffffff")
        if hasattr(self._img, "scene"): pic = render(self._img.scene(w, h), w, h, "stretch", self.api.get("bg_fade", 0.15), pane_bg)
        else: pic = render(self._img, w, h, self.api.get("bg_fit", "cover"), self.api.get("bg_fade", 0.15), pane_bg)
        st = ttk.Style(tree)
        # an image element can't be changed once made: one per size (sizes repeat).  Tk keeps elements for the whole program, so they
        # are kept on the list itself - an addon reload (update) reuses them; a name an older copy of the addon used is skipped
        elements = tree.__dict__.setdefault("_dolphin_elements", {})
        if (w, h) not in elements:
            photo, n = ImageTk.PhotoImage(pic, master=tree), 0
            while True:
                name = f"DolphinBg{w}x{h}{'-' + str(n) if n else ''}.field"
                try:
                    st.element_create(name, "image", photo, sticky="nsew")
                    break
                except tk.TclError:
                    n += 1
            elements[(w, h)] = (name, photo)
        else:
            elements[(w, h)][1].paste(pic)
        name, self._photo = elements[(w, h)]
        st.layout(STYLE, [(name, {"sticky": "nswe", "children": [
            ("Treeview.padding", {"sticky": "nswe", "children": [("Treeview.treearea", {"sticky": "nswe"})]})]})])
        # every channel name sits in its own box - a row in the list's own colour - so it stays readable; the picture shows in the margin
        # around the boxes and below the last one
        st.configure(STYLE, padding=(MARGIN, MARGIN // 2, MARGIN, MARGIN // 2), background=pane_bg)
        tree.configure(style=STYLE)

    def remove_background(self):
        tree = self._tree()
        if self._job is not None:
            try: tree.after_cancel(self._job)
            except Exception: pass
            self._job = None
        if tree is not None:
            try:
                if str(tree.cget("style")) == STYLE: tree.configure(style="Treeview")
            except tk.TclError:
                pass
        self._img, self._size = None, None                      # the <Configure> binding stays but does nothing without a picture

    # ---- settings (double-click the addon in Tools > Addons) ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        tk.Label(f, text="Picture behind the channel list", bg=bg, font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        self.v_on = tk.BooleanVar(value=self.api.get("bg_on", True))
        self.v_path = tk.StringVar(value=self.api.get("bg_path", ""))
        self.v_fit = tk.StringVar(value=self.api.get("bg_fit", "cover"))
        self.v_fade = tk.IntVar(value=int(round(float(self.api.get("bg_fade", 0.15)) * 100)))
        tk.Checkbutton(f, text="Show a picture behind the channel list", variable=self.v_on, bg=bg).pack(anchor="w")
        r = tk.Frame(f, bg=bg)
        r.pack(fill="x", pady=2)
        tk.Label(r, text="Picture:", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_path, width=40).pack(side="left", padx=4)
        ttk.Button(r, text="Browse...", command=self._browse).pack(side="left")
        tk.Label(f, text="Empty = mcIRC's own pod of dolphins. Your own: PNG, JPG, GIF or BMP.",
                 bg=bg, fg="#555", wraplength=460, justify="left").pack(anchor="w")
        if not pillow_ok():
            r = tk.Frame(f, bg=bg)
            r.pack(fill="x", pady=4)
            note = tk.Label(r, text="Pillow (the picture library) isn't installed - no picture until it is.", bg=bg, fg="#c00000")
            note.pack(side="left")
            btn = ttk.Button(r, text="Install Pillow")
            btn.pack(side="left", padx=6)
            def after(ok):
                if note.winfo_exists():
                    note.config(text="Pillow is installed." if ok else "Pillow could not be installed - see the Status window.", fg="#2e7d32" if ok else "#c00000")
                    btn.config(state="disabled" if ok else "normal")
            def install():
                btn.config(state="disabled")
                note.config(text="Downloading and installing Pillow...", fg="#555")
                self.get_pillow(after)
            btn.config(command=install)
        r = tk.Frame(f, bg=bg)
        r.pack(fill="x", pady=2)
        tk.Label(r, text="Fit:", bg=bg).pack(side="left")
        for fit in FITS: tk.Radiobutton(r, text=fit, value=fit, variable=self.v_fit, bg=bg).pack(side="left")
        r = tk.Frame(f, bg=bg)
        r.pack(fill="x", pady=2)
        tk.Label(r, text="Fade (%):", bg=bg).pack(side="left")
        tk.Scale(r, from_=0, to=90, orient="horizontal", variable=self.v_fade, length=200, bg=bg, highlightthickness=0).pack(side="left")
        tk.Label(f, text="Each channel name sits in its own box, so it stays readable on a busy picture.", bg=bg, fg="#555").pack(anchor="w")
        self.editor = helper("dolphin_actions").ActionsEditor(f, self.actions(), bg)
        self.editor.f.pack(fill="x")
        return f

    def _browse(self):
        p = filedialog.askopenfilename(title="Picture for the channel list", filetypes=[("Pictures", "*.png *.jpg *.jpeg *.gif *.bmp"), ("All files", "*.*")])
        if p: self.v_path.set(p)

    def apply_options(self):
        self.api.set("bg_on", bool(self.v_on.get()))
        self.api.set("bg_path", self.v_path.get().strip())
        self.api.set("bg_fit", self.v_fit.get() if self.v_fit.get() in FITS else "cover")
        self.api.set("bg_fade", max(0, min(90, int(self.v_fade.get()))) / 100)
        if hasattr(self, "editor"):
            self.api.set("actions", self.editor.items())
            self.register_actions()
        self._size = None
        self.apply_background()
