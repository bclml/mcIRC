import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import os, sys, tempfile, time, types, subprocess, logging
from unittest import mock
sys.path.insert(0, ROOT)
import tkinter as tk
import gui_diag as d
import meshcore_io as io

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

KEY = "40acb1fe72f5475a2318bbccc49bb8d879a735f3c75ba3b4ff6d0184406154c5"
# ---- scrubbing
t = d.scrub(f"Unknown contact {KEY} prefix 3ddcdf84a1b2c3 mac AA:BB:CC:DD:EE:FF host 192.168.1.77 "
            f"C:\\Users\\alice\\Documents\\x.py password=hunter2 apikey=SECRET123 mail me@example.com adv_lat: 49.2827 \"adv_lon\": -123.1207")
ok("64-hex key shortened", KEY not in t and "40acb1fe..(key)" in t, t)
ok("12+ hex prefix shortened", "3ddcdf84a1b2c3" not in t)
ok("MAC hidden", "AA:BB:CC:DD:EE" not in t and "xx:xx:xx:xx:xx:FF" in t)
ok("IP partly hidden", "192.168.x.x" in t and "1.77" not in t)
ok("Windows user name hidden", "alice" not in t and "<user>" in t)
ok("password / api key hidden", "hunter2" not in t and "SECRET123" not in t)
ok("email hidden", "example.com" not in t)
ok("position hidden", "49.2827" not in t and "123.1207" not in t, t)
ok("plain timestamps and short hex untouched", d.scrub("took 1759500000123 ms build dee3e26") == "took 1759500000123 ms build dee3e26")
ok("describe_args hides msg text", d.describe_args(["-s", "COM4", "msg", KEY, "my secret dm text"]) == "-s COM4 msg <hidden> <hidden>", d.describe_args(["-s", "COM4", "msg", KEY, "my secret dm text"]))
a = d.describe_args(["-a", "AA:BB:CC:DD:EE:FF", "login", "abc", "pw123", "cmd", "abc", "ver", "wmt8"])
ok("login/cmd args hidden, wmt8 kept", "pw123" not in a and "ver" not in a.replace("<hidden>", "") and a.endswith("wmt8"), a)
ok("BLE/TCP targets masked", "<mac>" in a and "<host>" in d.describe_args(["-t", "10.0.0.5", "infos"]))

# ---- files: keep last 5
tmp = tempfile.mkdtemp()
d._state["dir"] = tmp
for i in range(7):
    open(os.path.join(tmp, f"mcirc-2026010{i}-000000.log"), "w").write("x")
d.DIAG_DIR = tmp
orig_mk = tempfile.mkdtemp
tempfile.mkdtemp = lambda prefix="": tmp          # demo=True path -> use our dir
d.start("9.9.9", demo=True)
ok("only 5 runs kept (4 old + this one)", len(d.session_files()) == 5, d.session_files())
ok("oldest were deleted", not os.path.exists(os.path.join(tmp, "mcirc-20260100-000000.log")) and os.path.exists(os.path.join(tmp, "mcirc-20260106-000000.log")))

# ---- meshcli tracing never records message text
class R:  # fake subprocess result
    def __init__(self, out="", err="", rc=0): self.stdout, self.stderr, self.returncode = out, err, rc
SECRET_TEXT = "meet at the cabin tonight, door code 4821"
with mock.patch("meshcore_io._run_cli", return_value=R(out="MESSAGE FROM ALICE: " + SECRET_TEXT)):
    io.execute_mesh_command(["-s", "COM4", "msg", KEY, SECRET_TEXT], retries=0)
    io.execute_mesh_command(["-s", "COM4", ".sync_msgs"], retries=0)
with mock.patch("meshcore_io._run_cli", return_value=R(err="Error: Unknown destination " + KEY, rc=1)):
    try: io.execute_mesh_command(["-s", "COM4", "cmd", KEY, "reboot", "wmt8"], retries=0)
    except RuntimeError: pass
logging.getLogger().info("Rebooting node to apply settings")
logging.getLogger().info("[DIAGNOSTIC] Raw .sync_msgs output: 'secret " + SECRET_TEXT + "'")
d.count("messages_dm")
d.event("x", "line with password=abc and " + KEY)
text = open(d.current_path(), encoding="utf-8").read()
ok("message text never written", SECRET_TEXT not in text and "ALICE" not in text and "door code" not in text)
ok("full key never written", KEY not in text)
ok("trace lines present", "msg <hidden> <hidden>" in text and "EXIT 1" in text and "ok" in text, text)
ok("[DIAGNOSTIC] raw dump skipped", "Raw .sync_msgs" not in text)
ok("logging records captured", "Rebooting node" in text)
d.node_summary({"ver": {"model": "Heltec V3", "fw_build": "19 Apr 2026", "ver": "v1.15.0"}, "info": {"name": "My Home Node", "adv_lat": 49.28, "adv_lon": -123.12, "radio_freq": 910.525, "tx_power": 22, "public_key": KEY}})
text = open(d.current_path(), encoding="utf-8").read()
ok("node summary has firmware/radio, no name/position/key", "Heltec V3" in text and "910.525" in text and "My Home Node" not in text and "49.28" not in text and KEY not in text)
ok("device line remembered", "Heltec V3" in d.device())
d.ports_snapshot()
ok("serial ports listed", "[ports]" in open(d.current_path(), encoding="utf-8").read())

# ---- crash hook
try: raise ValueError("boom in callback")
except ValueError: d.tk_exception(*sys.exc_info())
ok("GUI callback exceptions recorded", "boom in callback" in open(d.current_path(), encoding="utf-8").read())

# ---- size cap
d._state["bytes"] = d.MAX_BYTES + 1
d.event("x", "after cap")
ok("log is capped", "log capped" in open(d.current_path(), encoding="utf-8").read())
d._state["bytes"] = 0; d._state["capped"] = False

# ---- report dialog
import mcIRC
root = tk.Tk()
app = mcIRC.App(root, demo=True)
import gui_report
dlg = gui_report.BugReportDialog(app)
root.update()
ok("dialog has a description box and preview", dlg.what.winfo_exists() and "mcirc-" in dlg.preview.get("1.0", "end"))
opened = []
with mock.patch("webbrowser.open", lambda u: opened.append(u)), mock.patch("tkinter.messagebox.showinfo", lambda *a, **k: shown.append(a)) as _:
    shown = []
    dlg.send()
    ok("empty description is refused", not opened and shown, shown)
    dlg.what.insert("1.0", "Heltec V4 will not connect over USB\nit says access denied")
    # lots of log -> must be trimmed to fit
    for i in range(3000): d.event("filler", f"line {i} " + "x" * 60)
    dlg.refresh()
    dlg.send()
ok("browser opened with the issue form", opened and opened[0].startswith("https://github.com/bclml/mcIRC/issues/new?template=bug_report.yml"), opened)
u = opened[0]
ok("address short enough", len(u) <= gui_report.MAX_URL + 50, len(u))
ok("title/version/what pre-filled", "title=" in u and "Heltec%20V4" in u and "version=" in u and "what=" in u)
ok("trim note present", "trimmed" in __import__("urllib.parse", fromlist=["x"]).unquote(u))
clip = root.clipboard_get()
ok("clipboard has the COMPLETE report incl. description + newest log", "access denied" in clip and "line 2999" in clip and len(clip) > 100000, len(clip))
ok("report saved beside the logs", any(f.startswith("report-") for f in os.listdir(tmp)))
dlg.include.set(False); dlg.refresh()
ok("log can be left out", "(log not attached)" in dlg.preview.get("1.0", "end"))
ok("slash command registered", any(r[0] == "bug" for r in __import__("gui_commands").APP))
root.destroy()
tempfile.mkdtemp = orig_mk
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
