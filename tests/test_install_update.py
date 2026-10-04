import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Sandboxed tests of: addon install/uninstall, catalog install, app updater. Nothing here touches the real install."""
import io as _io, json, os, shutil, sys, tempfile, zipfile

REAL = ROOT
sys.path.insert(0, REAL)
import gui_addons as ga, gui_update as gu

ok_all = []
def check(label, cond, detail=""):
    ok_all.append(bool(cond)); print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))

def sandbox():
    """A temp copy of the app (code + packages) plus 'user data' that must never be touched."""
    d = tempfile.mkdtemp(prefix="sbx_")
    for f in ("emergency_agent.py", "mcIRC.py", "meshcore_io.py", "VERSION", "README.md", "addons-catalog.json"):
        shutil.copy(os.path.join(REAL, f), d)
    for f in os.listdir(REAL):
        if f.startswith("gui_") and f.endswith(".py"): shutil.copy(os.path.join(REAL, f), d)
    shutil.copytree(os.path.join(REAL, "packages"), os.path.join(d, "packages"), ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(d, "addons")); os.makedirs(os.path.join(d, "logs"))
    shutil.copy(os.path.join(REAL, "addons", "_example_addon.py"), os.path.join(d, "addons"))
    open(os.path.join(d, "gui_settings.json"), "w").write('{"node_name": "MY-NODE", "addons": {"broadcast_alerts": {"test_reply": "custom text"}}}')
    open(os.path.join(d, "nodes.db"), "wb").write(b"SQLite format 3\x00 fake node memory")
    open(os.path.join(d, "logs", "Public.txt"), "w").write("[10:00] <bob> hi\n")
    open(os.path.join(d, "addons", "my_own_addon.py"), "w").write("# a user's own addon\nfrom gui_addons import AddonBase\nclass Addon(AddonBase): pass\n")
    return d

def point_at(d):
    ga.BASE_DIR, ga.ADDON_DIR, ga.STATE_PATH = d, os.path.join(d, "addons"), os.path.join(d, "addons", ".installed.json")

def snapshot(d, rels): return {r: open(os.path.join(d, r), "rb").read() for r in rels}

# ============================== addon install / uninstall ==============================
d = sandbox(); point_at(d)
check("fresh install lists NO addons except the template", [n for n in os.listdir(os.path.join(d, "addons")) if n.endswith(".py") and not n.startswith("_")] == ["my_own_addon.py"])
info = ga.install_package(os.path.join(d, "packages", "broadcast_alerts"))
check("install from folder", info["name"] == "broadcast_alerts" and os.path.exists(os.path.join(d, "addons", "broadcast_alerts.py")), f"missing deps reported: {info['missing']}")
check("install recorded", ga.read_installed()["broadcast_alerts"]["version"] == json.load(open(os.path.join(REAL, "packages", "broadcast_alerts", "addon.json")))["version"])
check("user's own addon untouched", "a user's own addon" in open(os.path.join(d, "addons", "my_own_addon.py")).read())

# zip install
zpath = os.path.join(d, "ba.zip")
with zipfile.ZipFile(zpath, "w") as z:
    z.writestr("addon.json", json.dumps({"name": "zipped", "title": "Zipped", "version": "2.0", "files": {"zipped.py": "addons/zipped.py"}}))
    z.writestr("zipped.py", "from gui_addons import AddonBase\nclass Addon(AddonBase): pass\n")
check("install from .zip", ga.install_package(zpath)["name"] == "zipped" and os.path.exists(os.path.join(d, "addons", "zipped.py")))

# hostile / broken packages are rejected and write nothing
def rejects(label, manifest, files):
    pk = tempfile.mkdtemp(dir=d)
    open(os.path.join(pk, "addon.json"), "w").write(json.dumps(manifest))
    for n, c in files.items():
        os.makedirs(os.path.dirname(os.path.join(pk, n)), exist_ok=True); open(os.path.join(pk, n), "w").write(c)
    before = os.listdir(os.path.join(d, "addons"))
    try: ga.install_package(pk); check(label, False, "was accepted!")
    except ValueError as e: check(label, os.listdir(os.path.join(d, "addons")) == before, str(e)[:70])
good = "from gui_addons import AddonBase\nclass Addon(AddonBase): pass\n"
rejects("rejects overwriting core file meshcore_io.py", {"name": "evil", "files": {"a.py": "addons/evil.py", "b.py": "meshcore_io.py"}}, {"a.py": good, "b.py": "x=1"})
rejects("rejects overwriting gui_*.py", {"name": "evil", "files": {"a.py": "addons/evil.py", "b.py": "gui_common.py"}}, {"a.py": good, "b.py": "x=1"})
rejects("rejects path traversal in destination", {"name": "evil", "files": {"a.py": "addons/../../evil.py"}}, {"a.py": good})
rejects("rejects absolute destination", {"name": "evil", "files": {"a.py": "C:/Windows/evil.py"}}, {"a.py": good})
rejects("rejects syntax error", {"name": "evil", "files": {"a.py": "addons/evil.py"}}, {"a.py": "def (:\n"})
rejects("rejects name/file mismatch", {"name": "evil", "files": {"a.py": "addons/other.py"}}, {"a.py": good})
rejects("rejects source path escaping the package", {"name": "evil", "files": {"../../../../Windows/win.ini": "addons/evil.py"}}, {})

# uninstall keeps engine + settings
ga.uninstall_package("broadcast_alerts")
check("uninstall removes addon file", not os.path.exists(os.path.join(d, "addons", "broadcast_alerts.py")))
check("uninstall keeps the engine file and settings", os.path.exists(os.path.join(d, "emergency_agent.py")) and "custom text" in open(os.path.join(d, "gui_settings.json")).read())

# ============================== catalog install (fake GitHub) ==============================
point_at(sandbox())
src_repo = REAL
def fake_get(url, timeout=20):
    assert url.startswith("https://raw.githubusercontent.com/test/repo/main/"), url
    return open(os.path.join(src_repo, url.split("/main/", 1)[1].replace("/", os.sep)), "rb").read()
RAW = "https://raw.githubusercontent.com/test/repo/main/"
cat = ga.fetch_catalog(RAW, fake_get)
check("catalog parses", cat and cat[0]["name"] == "broadcast_alerts", f"{len(cat)} entry")
r = ga.install_from_catalog(cat[0], RAW, fake_get)
check("install straight from the catalog", r["name"] == "broadcast_alerts" and os.path.exists(os.path.join(ga.ADDON_DIR, "broadcast_alerts.py")))
check("version ordering", ga.vkey("1.10.0") > ga.vkey("1.9.2") and ga.vkey("v2") > ga.vkey("1.99"))

INSTALLED_VER = json.load(open(os.path.join(REAL, "packages", "broadcast_alerts", "addon.json")))["version"]
# ============================== updater ==============================
def build_release(version, gui_marker, engine_text, pkg_version, extra=None, bad_syntax=False):
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        root = "meshcore-bc-traffic-bot-master/"
        z.writestr(root + "VERSION", version + "\n")
        z.writestr(root + "mcIRC.py", f"# release {version}\n" + ("def (:\n" if bad_syntax else "x = 1\n"))
        z.writestr(root + "gui_common.py", f"# {gui_marker}\nX = 1\n")
        z.writestr(root + "emergency_agent.py", engine_text)
        z.writestr(root + "packages/broadcast_alerts/addon.json", json.dumps({"name": "broadcast_alerts", "title": "Broadcast alerts", "version": pkg_version,
                   "files": {"broadcast_alerts.py": "addons/broadcast_alerts.py"}}))
        z.writestr(root + "packages/broadcast_alerts/broadcast_alerts.py", f"# addon v{pkg_version}\nfrom gui_addons import AddonBase\nclass Addon(AddonBase): pass\n")
        z.writestr(root + "gui_settings.json", "EVIL OVERWRITE")           # must be ignored: not on the allow-list
        z.writestr(root + "addons/my_own_addon.py", "EVIL OVERWRITE")       # must be ignored
        z.writestr(root + "nodes.db", "EVIL OVERWRITE")
        z.writestr(root + "logs/Public.txt", "EVIL OVERWRITE")
        z.writestr(root + "../outside.txt", "EVIL")                          # path traversal attempt
        for k, v in (extra or {}).items(): z.writestr(root + k, v)
    return buf.getvalue()

d = sandbox(); point_at(d)
ga.install_package(os.path.join(d, "packages", "broadcast_alerts"))        # an installed addon at 1.0.0
open(os.path.join(d, "addons", "broadcast_alerts.py"), "a").write("\n# local tweak in the installed copy\n")
user_files = ["gui_settings.json", "nodes.db", "logs/Public.txt", "addons/my_own_addon.py"]
before_user = snapshot(d, user_files)
engine_user_edit = open(os.path.join(d, "emergency_agent.py"), encoding="utf-8").read() + "\nMY_CHANNEL_EDIT = 'keep me'\n"
open(os.path.join(d, "emergency_agent.py"), "w", encoding="utf-8").write(engine_user_edit)
state_path = os.path.join(d, "update_state.json")

check("version check: newer detected", gu.check(lambda u, timeout=20: b"9.0.0\n", RAW)["newer"])
check("version check: same version is not an update", not gu.check(lambda u, timeout=20: b"1.1.0\n", RAW)["newer"])

# 1) broken download -> nothing changes
bad = build_release("9.0.0", "new gui", "NEW_ENGINE = 1\n", "1.1.0", bad_syntax=True)
snap_before = snapshot(d, ["mcIRC.py", "gui_common.py", "emergency_agent.py", "VERSION"])
try: gu.apply_update(get=lambda u, timeout=90: bad, base=d, state_path=state_path); check("syntax-error release is refused", False)
except ValueError as e: check("syntax-error release is refused", True, str(e)[:60])
check("...and nothing was changed", snapshot(d, ["mcIRC.py", "gui_common.py", "emergency_agent.py", "VERSION"]) == snap_before)
try: gu.apply_update(get=lambda u, timeout=90: b"not a zip at all", base=d, state_path=state_path); check("garbage download refused", False)
except Exception as e: check("garbage download refused", True, type(e).__name__)

# 2) good release
rel = build_release("9.0.0", "new gui", "NEW_ENGINE = 1\n", "9.9.0")
res = gu.apply_update(get=lambda u, timeout=90: rel, base=d, state_path=state_path)
check("update applied", res["new"] == "9.0.0" and open(os.path.join(d, "VERSION")).read().strip() == "9.0.0", f"updated={len(res['updated'])} added={len(res['added'])} kept={res['kept']}")
check("code files replaced", "release 9.0.0" in open(os.path.join(d, "mcIRC.py")).read() and "new gui" in open(os.path.join(d, "gui_common.py")).read())
check("settings / node memory / logs / user addon UNTOUCHED", snapshot(d, user_files) == before_user)
check("hostile files in the zip were ignored", not os.path.exists(os.path.join(d, "..", "outside.txt")) and b"EVIL" not in open(os.path.join(d, "gui_settings.json"), "rb").read())
check("replaced files were backed up", os.path.isdir(res["backup"]) and os.path.exists(os.path.join(res["backup"], "gui_common.py")))
check("user-edited emergency_agent.py KEPT", open(os.path.join(d, "emergency_agent.py"), encoding="utf-8").read() == engine_user_edit and res["kept"] == ["emergency_agent.py"])
check("...new engine saved beside it as .new", open(os.path.join(d, "emergency_agent.py.new")).read() == "NEW_ENGINE = 1\n")

# 3) installed addon gets the newer package version, its settings stay
class App:  # minimal stand-in for the GUI
    settings = json.load(open(os.path.join(d, "gui_settings.json")))
    def save(self): pass
    def status_line(self, *a, **k): pass
    connected = False
mgr = ga.AddonManager(App())
refreshed = mgr.update_installed(d)
check("installed addon refreshed to the new package version", refreshed == [("broadcast_alerts", INSTALLED_VER, "9.9.0")] and "addon v9.9.0" in open(os.path.join(d, "addons", "broadcast_alerts.py")).read(), str(refreshed))
check("addon settings still intact", json.load(open(os.path.join(d, "gui_settings.json")))["addons"]["broadcast_alerts"]["test_reply"] == "custom text")
check("addon refresh backed up the old copy", any(os.path.isdir(os.path.join(d, "backup", n)) for n in os.listdir(os.path.join(d, "backup")) if n.startswith("addon-broadcast_alerts")))

# 4) the user adopts the .new file -> later updates apply the engine normally
shutil.copy(os.path.join(d, "emergency_agent.py.new"), os.path.join(d, "emergency_agent.py"))
rel2 = build_release("9.1.0", "newer gui", "NEWER_ENGINE = 2\n", "9.9.0")
res2 = gu.apply_update(get=lambda u, timeout=90: rel2, base=d, state_path=state_path)
check("after adopting .new, the next update replaces the engine automatically", open(os.path.join(d, "emergency_agent.py")).read() == "NEWER_ENGINE = 2\n" and not res2["kept"])
check("user data still untouched after second update", snapshot(d, user_files) == before_user)

print("\nALL PASSED" if all(ok_all) else f"\n{ok_all.count(False)} FAILED of {len(ok_all)}")
shutil.rmtree(d, ignore_errors=True)
