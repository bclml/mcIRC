"""Skins, like Winamp's: drop a picture into the skins/ folder and pick it in Options > Display.

A skin is either one loose image (skins/Sunset.png) or a folder (skins/Sunset/) holding banner.png (or .jpg/.gif/.bmp) and an optional skin.json.
The picture becomes a banner across the top of the window and the colours of the chat panes are taken from it, so any image makes a usable skin.
skin.json (all optional):  {"banner_height": 56, "mode": "cover" | "stretch" | "tile", "base": "Night", "theme": {"pane_bg": "#112233", ...}}"""
import colorsys
import json
import os
import tkinter as tk

from gui_common import BASE_DIR

SKIN_DIR = os.path.join(BASE_DIR, "skins")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp")
NONE = "None"
MAX_PIXELS = 25_000_000            # refuse absurd pictures instead of freezing the window


class Skin:
    def __init__(self, name, image, height=56, mode="cover", base=None, overrides=None):
        self.name, self.image, self.height, self.mode, self.base, self.overrides = name, image, height, mode, base, overrides or {}


def list_skins():
    """Names of the skins found in skins/ (folders with a banner image, and loose image files)."""
    out = []
    try:
        for f in sorted(os.listdir(SKIN_DIR), key=str.lower):
            p = os.path.join(SKIN_DIR, f)
            if os.path.isdir(p) and _find_banner(p): out.append(f)
            elif f.lower().endswith(IMAGE_EXT): out.append(os.path.splitext(f)[0])
    except OSError:
        pass
    return out


def _find_banner(folder):
    for stem in ("banner", "skin", "background"):
        for ext in IMAGE_EXT:
            p = os.path.join(folder, stem + ext)
            if os.path.isfile(p): return p
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith(IMAGE_EXT): return os.path.join(folder, f)
    return None


def load(name):
    """The Skin called `name`, or None for 'None' / unknown / unreadable (a broken skin must never stop mcIRC from starting)."""
    if not name or name == NONE or "/" in name or chr(92) in name or name.startswith("."): return None
    try:
        from PIL import Image
        folder = os.path.join(SKIN_DIR, name)
        meta, path = {}, None
        if os.path.isdir(folder):
            path = _find_banner(folder)
            mp = os.path.join(folder, "skin.json")
            if os.path.isfile(mp):
                with open(mp, encoding="utf-8") as fh: meta = json.load(fh)
        else:
            for ext in IMAGE_EXT:
                if os.path.isfile(os.path.join(SKIN_DIR, name + ext)): path = os.path.join(SKIN_DIR, name + ext)
        if not path: return None
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        img = Image.open(path)
        img.load()
        img = img.convert("RGB")
        if img.width * img.height > MAX_PIXELS: return None
        height = int(meta.get("banner_height") or 56)
        mode = meta.get("mode") if meta.get("mode") in ("cover", "stretch", "tile") else "cover"
        ov = {k: v for k, v in (meta.get("theme") or {}).items() if isinstance(v, str) and _is_colour(v)}
        return Skin(name, img, max(24, min(height, 160)), mode, meta.get("base"), ov)
    except Exception:
        return None


def _is_colour(s): return len(s) == 7 and s[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in s[1:])
def _rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
def _hex(c): return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)
def _mix(a, b, t): return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))     # t=0 -> a, t=1 -> b
def _lum(c): return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


def palette(img):
    """(average colour, accent colour) of a picture: the accent is the most colourful area."""
    px = list(img.resize((24, 24)).getdata())
    avg = tuple(sum(p[i] for p in px) / len(px) for i in range(3))
    best, best_s = avg, -1.0
    for p in px:
        h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in p))
        score = s * (1 - abs(l - 0.5) * 1.4)
        if score > best_s: best, best_s = p, score
    return avg, best


def themed(theme, skin):
    """The chat colour theme with the skin's picture colours blended in."""
    if skin is None: return theme
    import gui_themes
    avg, accent = palette(skin.image)
    t = dict(gui_themes.THEMES.get(skin.base) or (gui_themes.THEMES["Night"] if _lum(avg) < 0.5 else gui_themes.THEMES["Classic mIRC"]))
    dark = _lum(_rgb(t["bg"])) < 0.5
    white, black = (255, 255, 255), (0, 0, 0)
    t["bg"] = _hex(_mix(_rgb(t["bg"]), avg, 0.22))
    t["pane_bg"] = _hex(_mix(_rgb(t["pane_bg"]), avg, 0.35))
    t["entry_bg"] = _hex(_mix(_rgb(t["entry_bg"]), avg, 0.28))
    sel = accent
    while _lum(sel) > 0.38: sel = _mix(sel, black, 0.2)
    while _lum(sel) < 0.12: sel = _mix(sel, white, 0.2)
    t["sel_bg"], t["sel_fg"] = _hex(sel), "#ffffff"
    t["me_bg"], t["me_fg"] = _hex(sel), "#ffffff"
    t["hl_bg"] = _hex(_mix(_rgb(t["hl_bg"]), accent, 0.3))
    for fg, bg in (("fg", "bg"), ("pane_fg", "pane_bg"), ("entry_fg", "entry_bg")):      # keep the text readable whatever the picture looks like
        if abs(_lum(_rgb(t[fg])) - _lum(_rgb(t[bg]))) < 0.45: t[fg] = "#f0f0f0" if dark else "#101010"
    t.update(skin.overrides)
    return t


def _render(skin, width):
    """The banner picture sized for a window `width` pixels wide."""
    from PIL import Image
    h, img = skin.height, skin.image
    if skin.mode == "stretch": return img.resize((width, h))
    if skin.mode == "tile":
        tile = img if img.height == h else img.resize((max(1, round(img.width * h / img.height)), h))
        out = Image.new("RGB", (width, h))
        for x in range(0, width, tile.width): out.paste(tile, (x, 0))
        return out
    scale = max(width / img.width, h / img.height)                # cover: fill the strip, crop what overflows
    big = img.resize((max(width, round(img.width * scale)), max(h, round(img.height * scale))))
    left, top = (big.width - width) // 2, (big.height - h) // 2
    return big.crop((left, top, left + width, top + h))


def show_banner(app, skin):
    """Put the skin's picture across the top of the window (or remove it when there is no skin)."""
    lab = getattr(app, "_banner", None)
    if skin is None:
        if lab is not None: lab.destroy(); app._banner = None
        return
    if lab is None:
        lab = app._banner = tk.Label(app.root, bd=0, padx=0, pady=0, bg="#000000")
        lab.pack(side="top", fill="x", before=app.toolbar)
        lab.bind("<Configure>", lambda e: _redraw(app))
    app._banner_skin = skin
    lab.config(height=skin.height)
    _redraw(app)


def _redraw(app):
    lab, skin = getattr(app, "_banner", None), getattr(app, "_banner_skin", None)
    if lab is None or skin is None: return
    width = max(lab.winfo_width(), 200)
    if getattr(lab, "_drawn", None) == (skin.name, width, skin.height, skin.mode): return
    try:
        from PIL import ImageTk
        lab._photo = ImageTk.PhotoImage(_render(skin, width))
        lab.config(image=lab._photo)
        lab._drawn = (skin.name, width, skin.height, skin.mode)
    except Exception:
        pass
