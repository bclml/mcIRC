import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import glob, json, subprocess, tempfile
from unittest import mock
fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

import gui_common as gc

tmp = tempfile.mkdtemp(prefix="mcirc_settings_")
path = os.path.join(tmp, "gui_settings.json")
gc.SETTINGS_PATH = path                                        # never the real settings file
MINE = {"node_name": "TestNode", "addons": {"fun_bot": {"enabled": True}}, "extra_nodes": [{"label": "b"}]}
def write_raw(data):
    with open(path, "wb") as f: f.write(data)
def read_raw():
    with open(path, "rb") as f: return f.read()
def asides(): return glob.glob(path + ".broken-*")

# ---- no file yet: defaults, and a save writes a whole file
s = gc.load_settings()
ok("no file: defaults, no problem reported", s == gc.DEFAULT_SETTINGS and not gc.SETTINGS_PROBLEM and not gc._SAVE_BLOCKED)
s.update(MINE)
ok("save writes the file", gc.save_settings(s) is True and json.loads(read_raw())["node_name"] == "TestNode")
ok("no temp file left behind", not os.path.exists(path + ".tmp"))
ok("saved settings load back", gc.load_settings()["addons"] == MINE["addons"] and not gc.SETTINGS_PROBLEM)

# ---- a crash in the middle of a save leaves the old file whole
good = read_raw()
with mock.patch("gui_common.json.dumps", side_effect=RuntimeError("boom")):
    try: gc.save_settings(dict(s, node_name="Other")); raised = False
    except RuntimeError: raised = True
ok("an error while preparing the save leaves the file untouched", raised and read_raw() == good)
with mock.patch("gui_common.os.replace", side_effect=OSError("disk gone")):
    try: gc.save_settings(dict(s, node_name="Other")); raised = False
    except OSError: raised = True
ok("an error while swapping the file in leaves the file untouched", raised and read_raw() == good)
ok("...and leaves no temp file behind", not os.path.exists(path + ".tmp"))

# ---- the file is held for a moment (OneDrive / antivirus): the save tries again
real_replace, calls = os.replace, []
def flaky(a, b):
    calls.append(1)
    if len(calls) < 3: raise PermissionError("in use")
    return real_replace(a, b)
with mock.patch("gui_common.os.replace", side_effect=flaky), mock.patch("gui_common.time.sleep"):
    done = gc.save_settings(dict(s, node_name="Retried"))
ok("a briefly locked file is retried and saved", done and len(calls) == 3 and json.loads(read_raw())["node_name"] == "Retried")

# ---- half a file (crash or power cut with an older version): kept aside, defaults, the user is told
gc.save_settings(s)
half = read_raw()[:40]
write_raw(half)
s2 = gc.load_settings()
kept = asides()
ok("a broken file gives the defaults", s2 == gc.DEFAULT_SETTINGS)
ok("the broken file is kept aside, byte for byte", len(kept) == 1 and open(kept[0], "rb").read() == half, kept)
ok("the Status window gets told where it is", "broken-" in gc.SETTINGS_PROBLEM and "default settings" in gc.SETTINGS_PROBLEM, gc.SETTINGS_PROBLEM)
gc.save_settings(s2)
ok("saving afterwards never touches the kept copy", open(kept[0], "rb").read() == half and os.path.exists(path))
for k in kept: os.remove(k)

# ---- JSON that holds no settings, and text that isn't UTF-8: the same
for label, raw in (("a JSON list", b"[1, 2]"), ("bytes that aren't UTF-8", b"\xff\xfe\x00{")):
    write_raw(raw)
    s3 = gc.load_settings()
    kept = asides()
    ok(f"{label}: kept aside, defaults", s3 == gc.DEFAULT_SETTINGS and len(kept) == 1 and open(kept[0], "rb").read() == raw and gc.SETTINGS_PROBLEM)
    for k in kept: os.remove(k)

# ---- broken and can't be moved aside: nothing is ever saved over it
write_raw(b"{not json")
with mock.patch("gui_common.os.replace", side_effect=PermissionError("in use")):
    s4 = gc.load_settings()
ok("broken and stuck: defaults, saving blocked, user told", s4 == gc.DEFAULT_SETTINGS and gc._SAVE_BLOCKED and "won't save" in gc.SETTINGS_PROBLEM)
ok("broken and stuck: a save writes nothing", gc.save_settings(s4) is False and read_raw() == b"{not json" and not os.path.exists(path + ".tmp"))

# ---- a good file that can't be opened right now: never replaced by defaults
gc.SETTINGS_PROBLEM, gc._SAVE_BLOCKED = "", False
gc.save_settings(s)
good = read_raw()
real_open = open
def locked(p, *a, **k):
    if p == path and not a: raise PermissionError(13, "Permission denied")
    return real_open(p, *a, **k)
with mock.patch("builtins.open", side_effect=locked):
    s5 = gc.load_settings()
ok("a locked file: defaults this session, user told", s5 == gc.DEFAULT_SETTINGS and gc._SAVE_BLOCKED and "OneDrive" in gc.SETTINGS_PROBLEM, gc.SETTINGS_PROBLEM)
ok("a locked file: a save never writes defaults over it", gc.save_settings(s5) is False and read_raw() == good and not asides())
ok("a locked file: once it opens again (next start), everything is back", gc.load_settings()["addons"] == MINE["addons"] and not gc._SAVE_BLOCKED)

# ---- copies of the settings file never get committed (they can hold an API key)
names = ["gui_settings.json.broken-20260101-000000", "gui_settings.json.tmp"]
r = subprocess.run(["git", "check-ignore"] + names, cwd=ROOT, capture_output=True, text=True)
ok("kept-aside and temp copies are git-ignored", r.returncode == 0 and r.stdout.split() == names, r.stdout + r.stderr)

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
