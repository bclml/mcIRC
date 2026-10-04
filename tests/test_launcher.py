import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Windows only: Run_GUI.bat / scripts/start_mcirc.ps1 (finding Python, first-start install, no console window) and the optional desktop shortcut."""
import shutil, subprocess, tempfile, time

if os.name != "nt":
    print("skipped: the launcher is Windows only\n\nALL PASSED")
    sys.exit(0)

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

work = tempfile.mkdtemp()
GOOD = sys.executable                                                      # the Python running the tests: has the packages
GOODW = os.path.join(os.path.dirname(GOOD), "pythonw.exe")
subprocess.run([GOOD, "-m", "venv", os.path.join(work, "bare")], check=True, capture_output=True)
BARE = os.path.join(work, "bare", "Scripts", "python.exe")                 # a real Python (with Tk) that does NOT have the packages
same = lambda a, b: os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))

def run_ps1(args=(), pythons=None, root=ROOT, extra_env=None):
    log = tempfile.mktemp(suffix=".txt", dir=work)
    env = dict(os.environ, MCIRC_LAUNCHER_TEST=log, **(extra_env or {}))
    if pythons is not None: env["MCIRC_TEST_PYTHONS"] = ";".join(pythons)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(root, "scripts", "start_mcirc.ps1"), *args], capture_output=True, text=True, env=env, timeout=180)
    text = open(log, encoding="utf-8-sig").read() if os.path.exists(log) else ""
    return r.returncode, text, r.stderr

# ---- choosing a Python
code, out, err = run_ps1()
ok("normal PC (real discovery): starts mcIRC windowless", code == 0 and out.startswith("START: ") and "pythonw.exe" in out and "mcIRC.py" in out, (code, out, err[:200]))
code, out, err = run_ps1(pythons=[BARE, GOOD])
ok("a Python without the packages listed first is skipped in favour of the one that has them", out.startswith("START: ") and GOODW.lower() in out.lower(), out)
code, out, err = run_ps1(pythons=[BARE])
ok("only a Python without the packages -> it would install them (first start)", "WOULD INSTALL packages with" in out, out)
code, out, err = run_ps1(pythons=[os.path.join(work, "no", "such", "python.exe")])
ok("no Python at all -> clear message with what to install, exit code 2", code == 2 and "needs Python 3.10" in out and "Add python.exe to PATH" in out, (code, out))
code, out, err = run_ps1(args=["--demo", "--foo"], pythons=[GOOD])
ok("arguments are passed on to mcIRC.py", out.strip().endswith("--demo --foo"), out)
code, out, err = run_ps1(args=["--name", "two words"], pythons=[GOOD])
ok("arguments with spaces are quoted when passed on", 'mcIRC.py" --name "two words"' in out, out)

# ---- the first-start install command survives cmd's quoting rules (a harmless pip command stands in for the download)
d = os.path.join(work, "dir with spaces"); os.makedirs(d)
outfile = os.path.join(d, "pip out.txt")
code, out, err = run_ps1(pythons=[BARE], extra_env={"MCIRC_TEST_PIPARGS": f'--version > "{outfile}" 2>&1'})
txt = open(outfile, encoding="utf-8", errors="replace").read() if os.path.exists(outfile) else ""
ok("the install command actually runs (pip answers), with spaces in the paths", txt.startswith("pip "), (txt[:80], err[:200]))
ok("and when the packages are still missing afterwards the user is told, exit code 3", code == 3 and "could not be installed" in out, (code, out[-200:]))

# ---- a folder with spaces in its name
tmp = os.path.join(work, "my mc IRC folder")
os.makedirs(os.path.join(tmp, "scripts"))
shutil.copy(os.path.join(ROOT, "scripts", "start_mcirc.ps1"), os.path.join(tmp, "scripts"))
open(os.path.join(tmp, "mcIRC.py"), "w").write("print('hi')\n")
code, out, err = run_ps1(pythons=[GOOD], root=tmp)
ok("a folder with spaces in its name works (path is quoted)", f'"{tmp}\\mcIRC.py"' in out, out)

# ---- Run_GUI.bat still starts mcIRC when scripts/ is missing (an install an old updater left incomplete)
fb = os.path.join(work, "fallback"); os.makedirs(fb)
shutil.copy(os.path.join(ROOT, "Run_GUI.bat"), fb)
marker = os.path.join(fb, "ran.txt")
open(os.path.join(fb, "mcIRC.py"), "w").write(f"import sys\nopen(r'{marker}', 'w').write(sys.executable + '|' + ' '.join(sys.argv[1:]))\n")
subprocess.run(["cmd", "/c", os.path.join(fb, "Run_GUI.bat"), "--demo"], timeout=60, env=dict(os.environ, PATH=os.path.dirname(GOOD) + ";" + os.environ["PATH"]))
for _ in range(40):
    if os.path.exists(marker): break
    time.sleep(0.3)
got = open(marker).read() if os.path.exists(marker) else ""
ok("without scripts/ the batch file falls back to starting pythonw mcIRC.py directly, arguments included", "pythonw.exe|--demo" in got.lower() or got.lower().endswith("|--demo"), got)

# ---- real double-click style start through Run_GUI.bat
ps = lambda cmd: subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120).stdout.strip()
probe = r'''
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices; using System.Collections.Generic;
public class WL4 { public delegate bool EP(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] static extern bool EnumWindows(EP p, IntPtr l); [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h); [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder sb, int n);
 public static List<string> Vis(HashSet<uint> pids) { var r = new List<string>(); EnumWindows((h, l) => { uint pid; GetWindowThreadProcessId(h, out pid);
   if (IsWindowVisible(h) && pids.Contains(pid)) { var c = new StringBuilder(128); GetClassName(h, c, 128); r.Add(c.ToString()); } return true; }, IntPtr.Zero); return r; } }
"@
$before = @(Get-Process | ForEach-Object { $_.Id })
Start-Process -FilePath 'ROOTDIR\Run_GUI.bat' -ArgumentList '--demo' | Out-Null
Start-Sleep -Seconds 12
$new = Get-CimInstance Win32_Process | Where-Object { $before -notcontains $_.ProcessId }
$pids = New-Object 'System.Collections.Generic.HashSet[uint32]'; $new | ForEach-Object { [void]$pids.Add([uint32]$_.ProcessId) }
"WINDOWS=" + (([WL4]::Vis($pids) | Sort-Object) -join ',')
$mine = $new | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -match 'mcIRC.py.*--demo' }
"STARTED=" + (@($mine).Count)
$mine | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
'''.replace("ROOTDIR", ROOT)
lines = ps(probe).split("\n")
get = lambda k: next((l.split("=", 1)[1].strip() for l in lines if l.startswith(k + "=")), "")
ok("double-clicking Run_GUI.bat opens the mcIRC window and nothing else stays on screen (no console, terminal or PowerShell window)", get("WINDOWS") == "TkTopLevel", lines)
ok("...as one pythonw process running mcIRC.py with the arguments", get("STARTED") == "1", lines)

# ---- the optional shortcut
code, out, err = run_ps1(args=["--make-shortcut"], pythons=[GOOD])
ok("Run_GUI.bat --make-shortcut reports the shortcuts it made", "SAY: Created:" in out and "mcIRC.lnk" in out, out)
lnk = os.path.join(ROOT, "mcIRC.lnk")
dd = ps(f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); $s.TargetPath + '|' + $s.Arguments + '|' + $s.WorkingDirectory + '|' + $s.IconLocation")
ok("the shortcut starts pythonw on mcIRC.py in the project folder with the logo as its icon", dd.lower().startswith(GOODW.lower() + "|") and "mcIRC.py" in dd and "mcIRC.ico" in dd and ROOT.lower() in dd.lower(), dd)
shutil.rmtree(work, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
