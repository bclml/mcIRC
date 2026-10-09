"""Radio presets for the Firmware builder: MeshCore's official community list (the same one its apps show, read live with a built-in copy
for when there's no internet), settings used by local groups found on the web, and your own presets (saved with the addon's settings)."""
import json
import tkinter as tk
import urllib.request
from tkinter import messagebox, simpledialog, ttk

from ntools_common import BG

OFFICIAL_URL = "https://api.meshcore.nz/api/v1/config"        # suggested_radio_settings - what the MeshCore apps list
# (title, MHz, BW kHz, SF, CR) - the official list as of 2026-10-09, used when it can't be read
BUILTIN = [
    ("Australia", "915.800", "250", "10", "5"), ("Australia (Narrow)", "916.575", "62.5", "7", "7"), ("Australia (Mid)", "915.075", "125", "9", "5"),
    ("Australia: SA, WA", "923.125", "62.5", "8", "8"), ("Australia: QLD", "923.125", "62.5", "8", "5"), ("Brazil", "923.125", "62.5", "8", "8"),
    ("Canada", "910.525", "62.5", "7", "5"), ("Costa Rica", "910.525", "125", "11", "5"), ("EU/UK (Narrow)", "869.618", "62.5", "8", "8"),
    ("EU/UK (Deprecated)", "869.525", "250", "11", "5"), ("Czech Republic (Narrow)", "869.432", "62.5", "7", "5"),
    ("EU 433MHz (Long Range)", "433.650", "250", "11", "5"), ("EU 433MHz (Narrow)", "433.650", "62.5", "8", "8"), ("Hungary", "869.618", "62.5", "7", "5"),
    ("Netherlands", "869.618", "62.5", "7", "5"), ("Netherlands (Limburg)", "869.618", "62.5", "8", "8"), ("New Zealand (Narrow)", "917.375", "62.5", "7", "5"),
    ("New Zealand (Gisborne)", "917.375", "250", "11", "5"), ("Portugal 433", "433.375", "62.5", "9", "6"), ("Portugal 868", "869.618", "62.5", "7", "6"),
    ("Slovakia", "869.618", "62.5", "7", "5"), ("Switzerland", "869.618", "62.5", "8", "8"), ("USA", "910.525", "62.5", "7", "5"),
    ("USA - Southern California", "927.875", "62.5", "7", "5"), ("Vietnam (Narrow)", "920.250", "62.5", "8", "5"), ("Vietnam (Deprecated)", "920.250", "250", "11", "5"),
]
# Local groups whose settings differ from the official list (found on their own pages)
COMMUNITY = [
    ("Canada: South BC 909 (Salish Mesh)", "909.000", "62.5", "7", "5"),     # south BC (mcIRC's home)
    ("USA: Florida, CR8 (Florida Mesh)", "910.525", "62.5", "7", "8"),       # areyoumeshingwith.us - the USA preset with CR 8
    ("USA: 500 kHz (MeshCore 500)", "902.250", "500", "11", "5"),            # meshmap.me/meshcore500 - some US networks, for FCC Part 15
]
BANDWIDTHS = {"7.8", "10.4", "15.6", "20.8", "31.25", "41.7", "62.5", "125", "250", "500"}


def valid(freq, bw, sf, cr):
    """True when the four values are a radio setting MeshCore accepts."""
    try:
        f, s, c = float(freq), int(sf), int(cr)
        b = float(bw)
    except (TypeError, ValueError):
        return False
    return 150 <= f <= 960 and any(abs(b - float(x)) < 0.01 for x in BANDWIDTHS) and 5 <= s <= 12 and 5 <= c <= 8


def official(get=None):
    """The official list, read now: [(title, MHz, BW, SF, CR)] (bad entries are left out)."""
    if get is None:
        def get(url):
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mcIRC"}), timeout=15) as r: return json.loads(r.read().decode("utf-8"))
    out = []
    for e in get(OFFICIAL_URL).get("config", {}).get("suggested_radio_settings", {}).get("entries", []):
        p = (str(e.get("title", "")).strip()[:60], str(e.get("frequency", "")), str(e.get("bandwidth", "")), str(e.get("spreading_factor", "")),
             str(e.get("coding_rate", "")))
        if p[0] and valid(*p[1:]): out.append(p)
    return out


ISSUES_URL = "https://github.com/bclml/mcIRC/issues/new"


def suggest_url(group, where, vals):
    """A new-issue link with the suggestion filled in (radio values and the names typed - nothing else)."""
    import urllib.parse
    title = f"Radio preset: {where} ({group})"
    body = (f"A local group's radio setting for the Firmware builder's preset list.\n\n"
            f"- Group: {group}\n- Where: {where}\n- Frequency: {vals[0]} MHz\n- Bandwidth: {vals[1]} kHz\n- Spreading factor: {vals[2]}\n"
            f"- Coding rate: {vals[3]}\n- Group's page or source (please add a link):\n\n"
            f"Preset line: (\"{where} ({group})\", \"{vals[0]}\", \"{vals[1]}\", \"{vals[2]}\", \"{vals[3]}\")\n")
    return ISSUES_URL + "?" + urllib.parse.urlencode({"title": title, "body": body, "labels": "radio-preset"})


def label(p): return f"{p[0]}  -  {p[1]} MHz / {p[2]} kHz / SF{p[3]} / CR{p[4]}"


def merged(mine, official_list):
    """The preset list: yours first, then the official ones and the local groups' together, by country (A-Z) - each title once."""
    seen, out = set(), []
    for group, prefix in ((mine, "My: "), (sorted(list(official_list or BUILTIN) + COMMUNITY, key=lambda p: p[0].lower()), "")):
        for p in group:
            t = prefix + p[0]
            if t.lower() in seen: continue
            seen.add(t.lower())
            out.append((t,) + tuple(p[1:5]))
    return out


class PresetSteps:
    """Mixed into FirmwareBuilderWindow: a Preset list beside the radio fields (needs self.v freq/bw/sf/cr, self.api)."""

    def preset_widgets(self, parent):
        self._official = []
        box = ttk.Combobox(parent, width=46, state="readonly")
        box.pack(side="left", padx=(8, 4))
        box.bind("<<ComboboxSelected>>", lambda e: self._use_preset())
        self.preset_box = box
        ttk.Button(parent, text="Save as preset...", command=self.save_preset).pack(side="left")
        ttk.Button(parent, text="Remove", command=self.remove_preset).pack(side="left", padx=(4, 0))
        ttk.Button(parent, text="Suggest to mcIRC...", command=self.suggest_preset).pack(side="left", padx=(4, 0))
        self._fill_presets()
        self.api.run_background(official, lambda r: (setattr(self, "_official", r if not isinstance(r, Exception) else []),
                                                     self.winfo_exists() and self._fill_presets()))

    def mine(self):
        get = getattr(self.api, "get", None)
        return [tuple(p) for p in (get("radio_presets", []) if get else []) if len(p) == 5]

    def presets(self): return merged(self.mine(), self._official)

    def _fill_presets(self):
        self.preset_box.config(values=["Preset..."] + [label(p) for p in self.presets()])
        if not self.preset_box.get(): self.preset_box.set("Preset...")

    def _use_preset(self):
        i = self.preset_box.current() - 1
        if i < 0: return
        p = self.presets()[i]
        for key, val in zip(("freq", "bw", "sf", "cr"), p[1:]): self.v[key].set(val)

    def save_preset(self):
        vals = tuple(self.v[k].get().strip() for k in ("freq", "bw", "sf", "cr"))
        if not valid(*vals):
            return messagebox.showerror("Radio preset", "Fill in a valid radio first: MHz (150-960), bandwidth (e.g. 62.5, 125, 250), SF 5-12, CR 5-8.", parent=self)
        name = simpledialog.askstring("Radio preset", "Name for this radio preset (e.g. 'South BC 909'):", parent=self)
        name = (name or "").strip()[:40]
        if not name: return
        mine = [p for p in self.mine() if p[0].lower() != name.lower()] + [(name,) + vals]
        self.api.set("radio_presets", [list(p) for p in mine])
        self._fill_presets()
        self.preset_box.set(label(("My: " + name,) + vals))

    def suggest_preset(self, open_url=None):
        """Opens a ready-filled GitHub issue for a local group's radio setting; the person checks it and presses Submit on GitHub themselves
        (nothing is sent from mcIRC).  The maintainers add good ones to COMMUNITY in an update."""
        vals = tuple(self.v[k].get().strip() for k in ("freq", "bw", "sf", "cr"))
        if not valid(*vals):
            return messagebox.showerror("Suggest a radio preset", "Fill in the group's radio first (or pick one of your own presets): MHz, bandwidth, SF, CR.", parent=self)
        group = (simpledialog.askstring("Suggest a radio preset", "The group's name (e.g. Salish Mesh):", parent=self) or "").strip()[:60]
        if not group: return
        where = (simpledialog.askstring("Suggest a radio preset", "Where it is used (country and area, e.g. Canada: South BC):", parent=self) or "").strip()[:60]
        if not where: return
        url = suggest_url(group, where, vals)
        if not messagebox.askokcancel("Suggest a radio preset", f"Your browser opens a new GitHub issue for:\n\n    {where} ({group})\n    "
                                      f"{vals[0]} MHz / {vals[1]} kHz / SF{vals[2]} / CR{vals[3]}\n\nCheck it there and press Submit (needs a "
                                      "GitHub account). Nothing is sent until you do.", parent=self): return
        (open_url or __import__("webbrowser").open)(url)

    def remove_preset(self):
        i = self.preset_box.current() - 1
        p = self.presets()[i] if i >= 0 else None
        if not p or not p[0].startswith("My: "):
            return messagebox.showinfo("Radio preset", "Choose one of your own presets ('My: ...') to remove it. The others come from MeshCore and local groups.", parent=self)
        self.api.set("radio_presets", [list(x) for x in self.mine() if x[0] != p[0][4:]])
        self.preset_box.set("Preset...")
        self._fill_presets()
