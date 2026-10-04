import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import importlib, os, sys, types
from unittest import mock
sys.path.insert(0, ROOT)
B = ROOT
fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

import gui_platform as gp

# ---- constants per system (re-import with a pretend platform)
def as_platform(name):
    with mock.patch.object(sys, "platform", name):
        return importlib.reload(gp)
mac = as_platform("darwin")
ok("macOS: right click is Button-2, middle is Button-3", mac.RIGHT_CLICK == "<Button-2>" and mac.MIDDLE_CLICK == "<Button-3>" and mac.EXTRA_RIGHT_CLICK)
ok("macOS fonts", mac.MONO_FONT_NAME == "Menlo" and mac.UI_FONT_SIZE == 11 and mac.DIALOG_FONT_NAME != "Segoe UI")
ok("macOS edition label", mac.edition_label() == "macOS edition 0.1.0 (experimental)" and mac.version_text("1.2.0") == "1.2.0 - macOS edition 0.1.0 (experimental)", mac.version_text("1.2.0"))
ok("macOS tk hint", "brew" in mac.tk_missing_hint())
with mock.patch("subprocess.Popen") as po:
    mac.open_path("/tmp/x"); ok("macOS opens with open", po.call_args[0][0] == ["open", "/tmp/x"], po.call_args)
    mac.reveal("/tmp/x/f.png"); ok("macOS reveal uses open -R", po.call_args[0][0] == ["open", "-R", "/tmp/x/f.png"], po.call_args)
lin = as_platform("linux")
ok("Linux: right click is Button-3 (as on Windows)", lin.RIGHT_CLICK == "<Button-3>" and lin.MIDDLE_CLICK == "<Button-2>" and not lin.EXTRA_RIGHT_CLICK)
ok("Linux fonts and edition", lin.MONO_FONT_NAME == "DejaVu Sans Mono" and "Linux edition 0.1.0" in lin.version_text("1.2.0"))
ok("Linux hints mention dialout and python3-tk", "dialout" in lin.permission_hint() and "python3-tk" in lin.tk_missing_hint())
with mock.patch("subprocess.Popen") as po:
    lin.open_path("/tmp/x"); ok("Linux opens with xdg-open", po.call_args[0][0] == ["xdg-open", "/tmp/x"], po.call_args)
    lin.reveal("/tmp/x/f.png"); ok("Linux reveal opens the folder", po.call_args[0][0] == ["xdg-open", "/tmp/x"], po.call_args)
win = as_platform("win32")
ok("Windows unchanged: no edition label, version as is", win.edition_label() == "" and win.version_text("1.2.0") == "1.2.0" and win.RIGHT_CLICK == "<Button-3>" and win.UI_FONT == ("Tahoma", 8))
ok("Windows meshcli path ends in Scripts\\meshcli.exe or PATH", win.meshcli_path().lower().endswith(("meshcli.exe", "meshcli")), win.meshcli_path())
with mock.patch.object(sys, "platform", "linux"):
    importlib.reload(gp)
    p = gp.meshcli_path()
    ok("Linux meshcli lookup falls back to 'meshcli' on the PATH", p.endswith("meshcli"), p)
importlib.reload(gp)       # real platform again

# ---- sounds on other systems
import gui_sounds as gs
gs.winsound = None
bells = []
with mock.patch.object(gp, "IS_MAC", True), mock.patch.object(gp, "IS_WIN", False), mock.patch("subprocess.Popen") as po:
    gs.play("Ding", "", lambda: bells.append(1)); ok("macOS 'Ding' plays Glass.aiff via afplay", po.call_args[0][0] == ["afplay", "/System/Library/Sounds/Glass.aiff"], po.call_args)
    gs.play("Rising chirp", "", lambda: bells.append(1)); ok("macOS beep patterns use a system sound", po.call_args[0][0][0] == "afplay")
with mock.patch.object(gp, "IS_MAC", False), mock.patch.object(gp, "IS_WIN", False), mock.patch("shutil.which", lambda n: "/usr/bin/" + n if n == "canberra-gtk-play" else None), mock.patch("subprocess.Popen") as po:
    gs.play("Exclamation", "", lambda: bells.append(1)); ok("Linux plays the freedesktop sound through canberra", po.call_args[0][0] == ["canberra-gtk-play", "-i", "dialog-warning"], po.call_args)
with mock.patch.object(gp, "IS_MAC", False), mock.patch.object(gp, "IS_WIN", False), mock.patch("shutil.which", lambda n: None), mock.patch("subprocess.Popen") as po:
    gs.play("Ding", "", lambda: bells.append(1)); ok("Linux with no sound tools falls back to the terminal bell", bells and not po.called)
    n = len(bells); gs.play("None", "", lambda: bells.append(1)); ok("'None' stays silent", len(bells) == n)

# ---- serial port picking
import meshcore_io as io
P = lambda dev, desc, vid=None, pid=None, maker="": types.SimpleNamespace(device=dev, description=desc, manufacturer=maker, vid=vid, pid=pid)
ports = [P("/dev/ttyUSB0", "CP2102 USB to UART Bridge", 0x10C4, 0xEA60, "Silicon Labs"), P("/dev/ttyS0", "n/a"), P("/dev/rfcomm0", "Bluetooth serial", None),
         P("/dev/tty.usbserial-0001", "USB Serial", 0x1A86, 0x7523), P("/dev/cu.usbserial-0001", "USB Serial", 0x1A86, 0x7523),
         P("/dev/cu.Bluetooth-Incoming-Port", "n/a"), P("/dev/ttyACM0", "USB ACM", 0x303A, 0x1001)]
with mock.patch("serial.tools.list_ports.comports", return_value=ports), mock.patch.object(gp, "IS_MAC", True):
    found = [c["device"] for c in io.usb_candidates()]
ok("macOS: tty. duplicates and Bluetooth ports skipped, cu. kept", "/dev/cu.usbserial-0001" in found and "/dev/tty.usbserial-0001" not in found and not any("Bluetooth" in f for f in found), found)
with mock.patch("serial.tools.list_ports.comports", return_value=ports), mock.patch.object(gp, "IS_MAC", False):
    found = [c["device"] for c in io.usb_candidates()]
ok("Linux: ttyUSB0 / ttyACM0 found, ttyS0 and rfcomm ignored", "/dev/ttyUSB0" in found and "/dev/ttyACM0" in found and "/dev/ttyS0" not in found and "/dev/rfcomm0" not in found, found)
with mock.patch.object(gp, "IS_WIN", False):
    why = io.explain_failure("PermissionError: [Errno 13] could not open port /dev/ttyUSB0: Permission denied")
ok("Linux permission error explains the dialout group", "dialout" in why, why)
ok("Windows 'access is denied' still means port busy", "busy" in io.explain_failure("could not open port COM4: Access is denied"))

# ---- fonts / theme in a real Tk
import tkinter as tk, gui_style
root = tk.Tk()
gui_style.apply_classic(root)
f = gui_style.chat_font(10)
ok("chat font picks an installed fixed-width font", f.actual("family") != "")
root.destroy()

# ---- launchers, versions, packages
for n in ("Run_GUI.sh", "Run_GUI.command"):
    t = open(os.path.join(B, n), "rb").read()
    ok(f"{n}: shebang and Unix line endings", t.startswith(b"#!/usr/bin/env sh\n") and b"\r" not in t and b"mcIRC.py" in t)
import gui_update
ok("updater ships the new launchers", "Run_GUI.sh" in gui_update.EXACT and "Run_GUI.command" in gui_update.EXACT)
import json
cat = json.load(open(os.path.join(B, "addons-catalog.json")))
mans = {p: json.load(open(os.path.join(B, "packages", p, "addon.json"))) for p in ("auto_reply", "broadcast_alerts")}
ok("addon versions in the manifests match the catalog (and are at least 1.1.1, so installed copies refresh)", all(m["version"] == next(c["version"] for c in cat["addons"] if c["name"] == n) for n, m in mans.items()) and all(tuple(map(int, m["version"].split("."))) >= (1, 1, 1) for m in mans.values()), [(n, m["version"]) for n, m in mans.items()])
src = open(os.path.join(B, "mcIRC.py"), encoding="utf-8").read() + "".join(open(os.path.join(B, f), encoding="utf-8").read() for f in os.listdir(B) if f.startswith("gui_") and f.endswith(".py"))
ok("no os.startfile left outside gui_platform", src.count("os.startfile") == 1, src.count("os.startfile"))
ok("no hard-coded Segoe UI / Consolas left in the app", '"Segoe UI"' not in src.replace('"Segoe UI" if IS_WIN', "") and src.count('"Consolas"') <= 2)
try: import tomllib
except ImportError: import tomli as tomllib      # Python 3.10 (CI installs tomli)
py = tomllib.load(open(os.path.join(B, "pyproject.toml"), "rb"))
ok("pyproject version equals VERSION", py["project"]["version"] == open(os.path.join(B, "VERSION")).read().strip(), py["project"]["version"])
req = [l.split("#")[0].strip() for l in open(os.path.join(B, "requirements.txt"), encoding="utf-8") if l.split("#")[0].strip()]
ok("requirements.txt and pyproject.toml list the same packages", sorted(req) == sorted(py["project"]["dependencies"]), (req, py["project"]["dependencies"]))
ok("updater ships requirements.txt and pyproject.toml", "requirements.txt" in gui_update.EXACT and "pyproject.toml" in gui_update.EXACT)
ok("uv does not try to build mcIRC as a package", py["tool"]["uv"]["package"] is False)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
