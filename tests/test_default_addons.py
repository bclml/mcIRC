import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""A brand-new setup comes with MeshCore tools installed and switched on; an existing setup is left alone.
Runs a real copy of mcIRC in a temporary folder (no radio is touched: it never connects)."""
import json, shutil, subprocess, tempfile

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

SKIP = {".git", "__pycache__", "logs", "diagnostics", "backup", "addons", "tests", ".venv", "venv", "skins"}
def fresh_copy(with_settings=None):
    d = tempfile.mkdtemp()
    for name in os.listdir(ROOT):
        src = os.path.join(ROOT, name)
        if name in SKIP or name.endswith((".log", ".db", ".lnk")) or name in ("gui_settings.json", "installed_addons.json"): continue
        if name.startswith(("meshbot_", "wxbot_", "funbot_", "ntools_")): continue          # helpers an install puts here: not part of a clean copy
        if os.path.isdir(src): shutil.copytree(src, os.path.join(d, name), ignore=shutil.ignore_patterns("__pycache__"))
        else: shutil.copy2(src, d)
    os.makedirs(os.path.join(d, "addons"))
    shutil.copy2(os.path.join(ROOT, "addons", "_example_addon.py"), os.path.join(d, "addons"))
    if with_settings is not None: json.dump(with_settings, open(os.path.join(d, "gui_settings.json"), "w"))
    return d

PROBE = r"""
import os, sys, json, tkinter as tk
os.environ["MCIRC_NO_LOG_FILE"] = "1"
sys.path.insert(0, os.getcwd())
import mcIRC
root = tk.Tk(); root.withdraw()
app = mcIRC.App(root, demo=False)
root.update()
print(json.dumps({"loaded": sorted(app.addons.loaded), "enabled": app.settings.get("addons_enabled", {}),
                  "files": sorted(f for f in os.listdir("addons") if f.endswith(".py")), "helpers": sorted(f for f in os.listdir(".") if f.startswith("ntools_"))}))
app.save(); root.destroy()
"""
def run_copy(d):
    p = subprocess.run([sys.executable, "-c", PROBE], cwd=d, capture_output=True, text=True, timeout=120, env=dict(os.environ, MCIRC_NO_LOG_FILE="1"))
    line = next((l for l in p.stdout.splitlines() if l.startswith("{")), None)
    return json.loads(line) if line else {"error": p.stderr[-800:]}

new = fresh_copy()
r = run_copy(new)
ok("a new setup installs MeshCore tools and switches it on", "node_tools" in r.get("loaded", []) and r.get("enabled", {}).get("node_tools") is True, r)
ok("...with its files in place", "node_tools.py" in r.get("files", []) and "ntools_clock.py" in r.get("helpers", []), r)
r2 = run_copy(new)
ok("the next start keeps it (and installs nothing again)", "node_tools" in r2.get("loaded", []), r2)
cfg = json.load(open(os.path.join(new, "gui_settings.json")))
cfg["addons_enabled"]["node_tools"] = False; json.dump(cfg, open(os.path.join(new, "gui_settings.json"), "w"))
r3 = run_copy(new)
ok("switched off by the user -> it stays off", "node_tools" not in r3.get("loaded", []), r3)
old = fresh_copy(with_settings={"node_name": "Existing"})
r4 = run_copy(old)
ok("an existing setup is left alone (nothing installed)", "node_tools" not in r4.get("files", []) and not r4.get("loaded"), r4)
for d in (new, old): shutil.rmtree(d, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
