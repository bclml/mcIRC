"""Language packs: mcIRC's windows - and, separately, what bots send over the mesh - in another language.

A pack is lang/<code>.json (text only, never code):
    {"name": "Français",
     "ui": {"English text": "texte", ...},                  menus, buttons, labels, window titles, message boxes - whole strings
     "ui_patterns": [["^(.+): OFF$", "\\1 : ARRÊT"], ...],  strings with a changing part (regular expressions, whole string)
     "mesh": {"English phrase": "phrase", ...},            what bots send: phrases replaced wherever they appear in an answer
     "mesh_patterns": [[regex, replacement], ...]}
Anything a pack doesn't have stays English, so a pack can grow a bit at a time.

install() hooks tkinter once at startup: every 'text' / 'label' a widget or menu gets, window titles, Treeview headings, message boxes
and simple dialogs go through tr().  Bots' answers go through mesh() in gui_addons (AddonAPI.send / reply) - never what you type yourself."""
import json, os, re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LANG_DIR = os.path.join(BASE_DIR, "lang")
ENGLISH = ("en", "English")

_ui, _ui_pat, _mesh, _mesh_pat = {}, [], {}, []
_installed = False


def available():
    """[(code, name)]: English first, then every pack in lang/ by name."""
    out = []
    try: files = sorted(f for f in os.listdir(LANG_DIR) if f.endswith(".json"))
    except OSError: files = []
    for f in files:
        code = f[:-5]
        if not re.fullmatch(r"[a-z]{2}(_[a-z]{2})?", code): continue           # (only names like 'fr' or 'pt_br')
        try:
            with open(os.path.join(LANG_DIR, f), encoding="utf-8") as fh: name = json.load(fh).get("name") or code
        except (OSError, ValueError): continue
        out.append((code, name))
    return [ENGLISH] + sorted(out, key=lambda x: x[1].lower())


def load(code):
    """The pack for this code as a dict ({} for English, an unknown code or a broken file)."""
    if not code or code == "en" or not re.fullmatch(r"[a-z]{2}(_[a-z]{2})?", code): return {}
    try:
        with open(os.path.join(LANG_DIR, code + ".json"), encoding="utf-8") as fh: data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _patterns(rows):
    """[[regex, replacement]] -> compiled pairs; a bad pattern is skipped, never fatal."""
    out = []
    for row in rows or []:
        try: out.append((re.compile(row[0]), row[1]))
        except (re.error, IndexError, TypeError): pass
    return out


def set_ui(code):
    """The language of mcIRC's windows (windows opened from now on; the main window after a restart)."""
    global _ui, _ui_pat
    pack = load(code)
    _ui, _ui_pat = dict(pack.get("ui") or {}), _patterns(pack.get("ui_patterns"))


def set_mesh(code):
    """The language of what bots send over the mesh."""
    global _mesh, _mesh_pat
    pack = load(code)
    # each phrase as a whole-word match ('rain' never inside 'terrain'), longest phrases first
    _mesh = [(re.compile(r"(?<!\w)" + re.escape(en) + r"(?!\w)"), other.replace("\\", "\\\\"))
             for en, other in sorted((pack.get("mesh") or {}).items(), key=lambda kv: -len(kv[0])) if en and isinstance(other, str)]
    _mesh_pat = _patterns(pack.get("mesh_patterns"))


def tr(text):
    """A whole interface string in the chosen language, or as it was."""
    if not isinstance(text, str) or not (_ui or _ui_pat): return text
    hit = _ui.get(text)
    if hit is not None: return hit
    for rx, rep in _ui_pat:
        if rx.fullmatch(text):
            try: return rx.sub(rep, text, count=1)
            except (re.error, IndexError): return text
    return text


def mesh(text):
    """A bot's answer with the pack's phrases replaced (the parts that come from the internet - jokes, places - stay as they are)."""
    if not isinstance(text, str) or not (_mesh or _mesh_pat): return text
    for rx, rep in _mesh_pat:                                  # whole answers first ('Sun X: rise 07:12, set ...'): they need the English shape
        try: text = rx.sub(rep, text)
        except (re.error, IndexError): pass
    for rx, other in _mesh:                                    # then single phrases, as whole words
        text = rx.sub(other, text)
    return text


def install():
    """Route tkinter's text through tr() - once.  Strings a pack doesn't have pass through untouched."""
    global _installed
    if _installed: return
    _installed = True
    import tkinter, tkinter.ttk as ttk, tkinter.messagebox as mb, tkinter.simpledialog as sd

    orig_options = tkinter.Misc._options
    def _options(self, cnf, kw=None):                          # every widget's and menu entry's options, at creation and on configure
        if _ui or _ui_pat:
            if isinstance(cnf, dict) and ("text" in cnf or "label" in cnf): cnf = {k: tr(v) if k in ("text", "label") else v for k, v in cnf.items()}
            if isinstance(kw, dict) and ("text" in kw or "label" in kw): kw = {k: tr(v) if k in ("text", "label") else v for k, v in kw.items()}
        return orig_options(self, cnf, kw)
    tkinter.Misc._options = _options

    orig_title = tkinter.Wm.wm_title
    def wm_title(self, string=None): return orig_title(self, tr(string) if string is not None else None)
    tkinter.Wm.wm_title = tkinter.Wm.title = wm_title

    orig_heading = ttk.Treeview.heading
    def heading(self, column, option=None, **kw):
        if "text" in kw: kw["text"] = tr(kw["text"])
        return orig_heading(self, column, option, **kw)
    ttk.Treeview.heading = heading

    orig_insert = ttk.Treeview.insert
    def insert(self, parent, index, iid=None, **kw):           # (tree rows' own text, e.g. the Options page list - their ids stay English)
        if "text" in kw: kw["text"] = tr(kw["text"])
        return orig_insert(self, parent, index, iid, **kw)
    ttk.Treeview.insert = insert

    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askyesnocancel", "askquestion", "askretrycancel"):
        fn = getattr(mb, name, None)
        if fn is None: continue
        def wrapped(title=None, message=None, _fn=fn, **options): return _fn(tr(title), tr(message), **options)
        setattr(mb, name, wrapped)
    for name in ("askstring", "askinteger", "askfloat"):
        fn = getattr(sd, name, None)
        if fn is None: continue
        def wrapped(title, prompt, _fn=fn, **kw): return _fn(tr(title), tr(prompt), **kw)
        setattr(sd, name, wrapped)
