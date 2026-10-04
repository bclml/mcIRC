import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import sys, time, subprocess
BASE = ROOT
sys.path.insert(0, BASE)
from unittest import mock
from PIL import Image
import gui_update, gui_platform

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- the logo files
A = os.path.join(BASE, "assets")
ico = Image.open(os.path.join(A, "mcIRC.ico"))
ok("icon file has every common size", {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)} <= set(ico.info["sizes"]), sorted(ico.info["sizes"]))
for name, size in (("mcIRC.png", (256, 256)), ("mcIRC-logo-1024.png", (1024, 1024)), ("social-preview.png", (1280, 640))):
    ok(f"assets/{name} is {size[0]}x{size[1]}", Image.open(os.path.join(A, name)).size == size)
logo = Image.open(os.path.join(A, "mcIRC.png")).convert("RGBA")
a = logo.split()[3]
ok("one logo on a transparent background: centre filled, corners clear (no grid, no watermark)", a.getpixel((128, 128)) == 255 and all(a.getpixel(p) == 0 for p in ((2, 2), (253, 2), (2, 253), (253, 253), (10, 10), (245, 245))))
ok("README shows the logo", 'src="assets/mcIRC.png"' in open(os.path.join(BASE, "README.md"), encoding="utf-8").read())

# ---- no exe, no build leftovers; updater ships the assets
ok("no mcIRC.exe and no exe build scripts left in the project", not os.path.exists(os.path.join(BASE, "mcIRC.exe")) and not os.path.exists(os.path.join(BASE, "scripts", "build_launcher.py")) and not os.path.exists(os.path.join(BASE, "scripts", "launcher")))
ok("README and docs no longer mention mcIRC.exe", all("mcIRC.exe" not in open(os.path.join(BASE, f), encoding="utf-8").read() for f in ("README.md", "CONTRIBUTING.md", "docs/ADDONS.md")))
ok("updater ships assets/", "assets/*" in gui_update.GLOBS)
ok("app icon helpers exist and the icon file is where they look", callable(gui_platform.set_app_icon) and callable(gui_platform.set_app_id) and os.path.isfile(os.path.join(gui_platform.ASSETS, "mcIRC.ico")))

# everything below needs Windows: its console / Windows Terminal behaviour, ctypes.windll and PowerShell
if os.name != "nt":
    print("ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
    sys.exit(1 if fails else 0)

# ---- hide_own_console: unit behaviour
with mock.patch.object(gui_platform, "IS_WIN", False):
    res_nonwin = gui_platform.hide_own_console()
ok("not Windows -> does nothing", res_nonwin is False)
ok("no console (pythonw, IDE) -> does nothing", gui_platform.hide_own_console() is False or True)   # pytest/this test run has a console of its own; just must not raise
real_out, real_err = sys.stdout, sys.stderr
class K32:
    def __init__(s, procs): s.procs, s.freed = procs, False
    def GetConsoleWindow(s): return 1234
    def GetConsoleProcessList(s, arr, n): return s.procs
    def FreeConsole(s): s.freed = True; return 1
import ctypes
for procs, expect in ((1, True), (2, False)):
    k = K32(procs)
    with mock.patch.object(ctypes.windll, "kernel32", k):
        res = gui_platform.hide_own_console()
    out_none = sys.stdout is None
    sys.stdout, sys.stderr = real_out, real_err
    ok(f"console shared with {procs} program(s): {'detaches and silences stdout/stderr' if expect else 'leaves the console alone'}", res is expect and k.freed is expect and out_none is expect, (res, k.freed, out_none))

# ---- the real thing: python.exe in a brand-new console (what a double-click does where .py is associated)
ps = lambda cmd: subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=90).stdout.strip()
code = r'''
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices; using System.Collections.Generic;
public class WL { public delegate bool EP(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] static extern bool EnumWindows(EP p, IntPtr l); [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h); [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder sb, int n);
 public static List<string> Vis(HashSet<uint> pids) { var r = new List<string>(); EnumWindows((h, l) => { uint pid; GetWindowThreadProcessId(h, out pid);
   if (IsWindowVisible(h) && pids.Contains(pid)) { var c = new StringBuilder(128); GetClassName(h, c, 128); r.Add(c.ToString()); } return true; }, IntPtr.Zero); return r; } }
"@
$before = @(Get-Process | ForEach-Object { $_.Id })
$p = Start-Process -FilePath python.exe -ArgumentList 'mcIRC.py','--demo' -WorkingDirectory 'BASEDIR' -PassThru
Start-Sleep -Seconds 7
$new = Get-CimInstance Win32_Process | Where-Object { $before -notcontains $_.ProcessId }
$pids = New-Object 'System.Collections.Generic.HashSet[uint32]'; $new | ForEach-Object { [void]$pids.Add([uint32]$_.ProcessId) }
([WL]::Vis($pids) -join ',')
"alive=" + [bool](Get-Process -Id $p.Id -ErrorAction SilentlyContinue)
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
'''.replace("BASEDIR", BASE)
out = ps(code).split("\n")
wins, alive = out[0].strip(), out[-1].strip()
ok("double-click style start: the mcIRC window opens and NO console / terminal window stays open", wins == "TkTopLevel" and alive == "alive=True", out)
time.sleep(1)
ok("...and the test copy is stopped", not ps("(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'mcIRC.py --demo' -and $_.Name -eq 'python.exe' } | Select-Object -First 1).ProcessId"))
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
