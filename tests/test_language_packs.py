import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Language packs: the packs load, mcIRC's windows use them, bots' answers are translated only when chosen, English stays untouched,
and Options > Display saves the choice.  No radio."""
import json, re, tkinter as tk
from tkinter import ttk, messagebox

import gui_lang as L

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- the packs
codes = [c for c, _ in L.available()]
ok("English plus the four packs, by name", L.available() == [("en", "English"), ("de", "Deutsch"), ("es", "Español"), ("fr", "Français"), ("pt", "Português")], L.available())
for code in ("fr", "es", "de", "pt"):
    p = L.load(code)
    ok(f"{code}: a few hundred window strings, bot phrases and patterns", len(p["ui"]) > 250 and len(p["mesh"]) > 20 and len(p["mesh_patterns"]) > 30)
    bad = [r[0] for r in p["ui_patterns"] + p["mesh_patterns"] if not (lambda rx: (re.compile(rx), True))(r[0])]
    ok(f"{code}: every pattern compiles", not bad, bad)
    keep = [k for k, v in p["ui"].items() if ("{" in k) != ("{" in v) or k.count("\n") != v.count("\n")]
    ok(f"{code}: line breaks kept in step", not keep, keep[:3])
ok("an unknown or unsafe code loads nothing", L.load("xx") == {} and L.load("../gui_settings") == {} and L.load("en") == {})

# ---- the windows
L.install(); L.install()                                   # (twice is harmless)
root = tk.Tk(); root.withdraw()
L.set_ui("fr")
b = tk.Button(root, text="Cancel"); lab = tk.Label(root, text="Some node name")
m = tk.Menu(root, tearoff=0); m.add_command(label="Options...")
ok("French: buttons, labels and menu entries", b.cget("text") == "Annuler" and m.entrycget(0, "label") == "Options..." and lab.cget("text") == "Some node name")
b.config(text="Apply")
ok("...also when the text changes later", b.cget("text") == "Appliquer")
t = tk.Toplevel(root); t.title("Options")
ok("...window titles", t.title() == "Options")
t.title("Node list...")
tv = ttk.Treeview(root, columns=("a",)); tv.heading("a", text="Name"); tv.insert("", "end", iid="Display", text="Display")
ok("...table headings and tree rows (their ids stay English)", tv.heading("a", "text") == "Nom" and tv.item("Display", "text") == "Affichage")
ok("...strings with a changing part", L.tr("Fun bot: OFF") == "Fun bot : ARRÊT" and L.tr("About (version 2026.11.11-1)") == "À propos (version 2026.11.11-1)")
seen = {}
real = messagebox._show if hasattr(messagebox, "_show") else None
orig = L.tr
ok("...message boxes go through it too", messagebox.showinfo.__name__ == "wrapped")
L.set_ui("de")
ok("German", tk.Button(root, text="Cancel").cget("text") == "Abbrechen")
L.set_ui("en")
ok("English: nothing changes", tk.Button(root, text="Cancel").cget("text") == "Cancel" and L.tr("Fun bot: OFF") == "Fun bot: OFF")

# ---- what bots send
ok("bots' answers stay English until chosen", L.mesh("HF 0003Z: SFI 89 | Day: 80m-40m Good") == "HF 0003Z: SFI 89 | Day: 80m-40m Good")
L.set_mesh("fr")
hf = L.mesh("HF 0003Z: SFI 89, SSN 22, A 4, K 0 (quiet), X-ray B2.6, noise S0-S1 | Day: 80m-40m Good, 30m-20m Fair | Night: 80m-40m Poor")
ok("French: the HF answer", hf == "HF 0003Z: SFI 89, SSN 22, A 4, K 0 (calme), X-ray B2.6, bruit S0-S1 | Jour : 80m-40m Bon, 30m-20m Moyen | Nuit : 80m-40m Mauvais", hf)
wx = L.mesh("Victoria: 14C light rain, wind 20 km/h SW, 80% RH")
ok("...a weather answer", wx == "Victoria: 14C pluie légère, vent 20 km/h SW, 80 % HR", wx)
sun = L.mesh("Sun Paris: rise 07:12, set 17:30, 10h18m of daylight (-2m10s tomorrow)")
ok("...the sun answer, keeping its numbers", sun == "Soleil Paris : lever 07:12, coucher 17:30, 10h18m de jour (-2m10s demain)", sun)
joke = "Why did the rain stop? The terrain was clear and the weather Good."
ok("...a joke from the internet that happens to say 'rain', 'clear' or 'Good' stays as it was", L.mesh(joke) == joke, L.mesh(joke))
ok("...a word inside another word is never touched", L.mesh("Ukraine windows litany") == "Ukraine windows litany")
L.set_mesh("es")
ok("Spanish: a failure message", L.mesh("hfcond: not reachable right now, try later") == "hfcond: no disponible ahora, inténtalo más tarde")
L.set_mesh("en")

# ---- in mcIRC: the settings, and bots' answers through the addon API
import mcIRC
from gui_addons import AddonAPI
app = mcIRC.App(root, demo=True); root.update()
ok("both languages are English in a new setup", app.settings["language"] == "en" and app.settings["mesh_language"] == "en")
sent = []
app.send_to = lambda ch, text: sent.append((ch, text))
app.connected = True
api = AddonAPI(app, "t"); api._needs_channel = lambda ch: False
app.settings["mesh_language"] = "pt"; app.apply_settings()
api.send("#weather", "Lisboa: 18C clear, wind 10 km/h N")
ok("bots answer in the language chosen for the mesh (Portuguese)", sent[-1] == ("#weather", "Lisboa: 18C limpo, vento 10 km/h N"), sent[-1:])
app.send_to("#chat", "the rain is clear")
ok("...what you type yourself is never translated", sent[-1] == ("#chat", "the rain is clear"))
app.settings["mesh_language"] = "en"; app.apply_settings()
api.send("#weather", "Lisboa: 18C clear")
ok("...back to English", sent[-1] == ("#weather", "Lisboa: 18C clear"))
import gui_dialogs
shown = []
gui_dialogs.messagebox.showinfo = lambda *a, **k: shown.append(a)
app.open_options(); root.update()
dlg = app.options_win if getattr(app, "options_win", None) else next(w for w in root.winfo_children() if isinstance(w, gui_dialogs.OptionsDialog))
ok("Options > Display offers every pack", [c for c, _ in dlg.langs] == ["en", "de", "es", "fr", "pt"])
dlg.lang_vars["language"].set("Español"); dlg.lang_vars["mesh_language"].set("Deutsch")
dlg.apply()
ok("...and saves the codes: windows Spanish, bots German", app.settings["language"] == "es" and app.settings["mesh_language"] == "de")
ok("...it says the main window changes after a restart", shown and "Restart mcIRC" in shown[-1][1], shown)
ok("...new windows are Spanish at once", tk.Button(root, text="Cancel").cget("text") == "Cancelar")
app.settings["language"] = app.settings["mesh_language"] = "en"; app.apply_settings()
root.destroy()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
