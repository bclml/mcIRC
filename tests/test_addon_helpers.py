import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""After an addon update, its helper modules (installed next to the app) are re-read when the addon is loaded again,
so the new addon never runs with an old copy that is still in memory (the weather bot crashed that way)."""
import importlib, shutil, tempfile
from unittest import mock

import gui_addons as ga

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

tmp = tempfile.mkdtemp()
sys.path.insert(0, tmp)
helper = os.path.join(tmp, "zz_helper_mod.py")
open(helper, "w").write("def old(): return 1\n")
import zz_helper_mod
ok("setup: the old helper is in memory", hasattr(zz_helper_mod, "old") and not hasattr(zz_helper_mod, "new"))
open(helper, "w").write("def old(): return 1\ndef new(): return 2\n")
os.utime(helper, (1, 4_000_000_000))                       # (a newer timestamp, so Python does not reuse a cached .pyc)
with mock.patch.object(ga, "read_installed", lambda: {"zz": {"files": ["addons/zz.py", "zz_helper_mod.py"]}}):
    ga._fresh_helpers("zz")
ok("loading the addon again re-reads its helper", hasattr(zz_helper_mod, "new") and zz_helper_mod.new() == 2)
with mock.patch.object(ga, "read_installed", lambda: {"other": {"files": ["zz_helper_mod.py"]}}):
    ga._fresh_helpers("zz")                                 # an addon that does not own the helper changes nothing
ok("helpers of other packages are left alone (and nothing crashes)", True)
sys.path.remove(tmp); shutil.rmtree(tmp, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
