import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Updater tests: a real in-app update from an OLD install layout, hostile paths, repair of missing files, and message text staying out of the log."""
import io, json, logging, shutil, tempfile, zipfile
from unittest import mock
import gui_update as gu, meshcore_io as io_mod

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

SKIP_DIRS = {".git", "__pycache__", "diagnostics", "logs", "backup", ".venv", "venv", "addons"}
SKIP_FILES = {"gui_settings.json", "nodes.db", "update_state.json"}


def repo_files(include_new=True):
    """The files a clean checkout has (no user data, no caches).  With include_new=False also drops what versions up to 1.4.9 could not deliver."""
    out = []
    for d, dirs, files in os.walk(ROOT):
        rel_d = os.path.relpath(d, ROOT).replace("\\", "/")
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not (not include_new and rel_d == "." and x in ("scripts", "assets", "tests"))]
        for f in files:
            if f in SKIP_FILES or f.endswith((".lnk", ".log", ".pyc")) or ".log." in f: continue
            out.append(os.path.normpath(os.path.join(rel_d, f)).replace("\\", "/") if rel_d != "." else f)
    return out


work = tempfile.mkdtemp()
install = os.path.join(work, "install")
for f in repo_files(include_new=False):
    os.makedirs(os.path.dirname(os.path.join(install, f)) or install, exist_ok=True)
    shutil.copy(os.path.join(ROOT, f), os.path.join(install, f))
ok("setup: the old-layout install has none of scripts/ or assets/", not os.path.exists(os.path.join(install, "scripts")) and not os.path.exists(os.path.join(install, "assets")))
old_version = "1.4.7"
open(os.path.join(install, "VERSION"), "w").write(old_version + "\n")

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("mcIRC-master/", "")
    for f in repo_files(): z.write(os.path.join(ROOT, f), "mcIRC-master/" + f)
    for evil in ("docs/..\\evil_a.py", "docs/sub\\..\\..\\evil_b.py", "docs/C:/evil_c.py", "docs/../../evil_d.py", "scripts/..\\..\\evil_e.py"):
        z.writestr("mcIRC-master/" + evil, "raise SystemExit('pwned')\n")
data = buf.getvalue()
res = gu.apply_update(get=lambda url, timeout=90: data, base=install, state_path=os.path.join(work, "state.json"))
ok("update applied; the version moved to the current one", res["new"] == open(os.path.join(ROOT, "VERSION")).read().strip() and res["old"] == old_version, res)
ok("scripts/start_mcirc.ps1 and the logo files were delivered", all(os.path.isfile(os.path.join(install, *r.split("/"))) for r in gu.REQUIRED), [r for r in gu.REQUIRED if not os.path.isfile(os.path.join(install, *r.split("/")))])
bat = open(os.path.join(install, "Run_GUI.bat")).read()
ok("the new Run_GUI.bat arrived together with the script it needs", "start_mcirc.ps1" in bat and os.path.isfile(os.path.join(install, "scripts", "start_mcirc.ps1")))
outside = [f for f in os.listdir(work) if f.startswith("evil")] + [f for f in os.listdir(install) if f.startswith("evil")] + [f for f in os.listdir(os.path.join(install, "docs")) if f.startswith("evil")]
ok("hostile entries (backslash .., drive letter, ../..) wrote nothing anywhere", not outside, outside)
ok("user data untouched: no settings file was created by the update", not os.path.exists(os.path.join(install, "gui_settings.json")))
for rel, want in (("assets/mcIRC.png", True), ("scripts/start_mcirc.ps1", True), ("docs/ADDONS.md", True), ("Run_GUI.bat", True), ("gui_platform.py", True), ("mcIRC.exe", False),
                  ("docs/..\\x.py", False), ("docs/C:/x.py", False), ("../x.py", False), ("/etc/x", False), ("docs//x", False)):
    ok(f"updatable({rel!r}) is {want}", gu.updatable(rel) is want)

# ---- repair(): restores only what is missing, never overwrites
old2 = os.path.join(work, "old2")
for f in repo_files(include_new=False):
    os.makedirs(os.path.dirname(os.path.join(old2, f)) or old2, exist_ok=True)
    shutil.copy(os.path.join(ROOT, f), os.path.join(old2, f))
os.makedirs(os.path.join(old2, "assets"))
open(os.path.join(old2, "assets", "mcIRC.png"), "wb").write(b"USER FILE")
need = gu.missing_required(old2)
ok("missing_required finds what an old update could not deliver", set(need) == {"scripts/start_mcirc.ps1", "assets/mcIRC.ico"}, need)
wrote = gu.repair(get=lambda url, timeout=90: data, base=old2)
ok("repair writes only the missing files", set(wrote) == {"scripts/start_mcirc.ps1", "assets/mcIRC.ico"}, wrote)
ok("...and leaves an existing file alone", open(os.path.join(old2, "assets", "mcIRC.png"), "rb").read() == b"USER FILE")
ok("...and does nothing (no download at all) when nothing is missing", gu.repair(get=lambda *a, **k: 1 / 0, base=old2) == [])

# ---- private message text is not written to any log
class R:
    def __init__(self, out): self.stdout, self.stderr, self.returncode = out, "INFO:meshcore:Serial Connection started", 0
dm = json.dumps([{"type": "PRIV", "pubkey_prefix": "aabbccddeeff", "text": "my PRIVATE secret words", "SNR": 5, "path_len": 1},
                 {"type": "CHAN", "channel_idx": 0, "text": "Bob: public hello", "SNR": 5, "path_len": 1}])
lines = []
class H(logging.Handler):
    def emit(self, rec): lines.append(rec.getMessage())
h = H(); logging.getLogger().addHandler(h); logging.getLogger().setLevel(logging.INFO)
io_mod.CONNECTION_ARGS = ["-s", "COMX"]
with mock.patch.object(io_mod, "_run_cli", return_value=R(dm)), mock.patch.object(io_mod, "_emit", lambda *a, **k: None):
    io_mod.fetch_incoming_messages()
    ok("default: neither the private nor the public message text reaches any log", not any("PRIVATE secret" in l or "public hello" in l for l in lines), [l[:80] for l in lines])
    ok("default: no raw-dump line at all", not any("[DIAGNOSTIC]" in l for l in lines))
    with mock.patch.dict(os.environ, {"MCIRC_DEBUG_RAW": "1"}):
        io_mod.fetch_incoming_messages()
    ok("MCIRC_DEBUG_RAW=1 switches the raw dump back on for debugging", any("[DIAGNOSTIC] Raw .sync_msgs output" in l for l in lines))
logging.getLogger().removeHandler(h)
shutil.rmtree(work, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
