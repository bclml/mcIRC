import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The board's button (GPIO0 via DTR): every port mcIRC opens keeps it released; the rescue console presses it on purpose.  Pretend ports only."""
import time, tkinter as tk
from unittest import mock

import serial

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- every port opens with DTR and RTS off (the meshcore library used to open with DTR on, then RTS off = button held)
plain = serial.serial_for_url("loop://", do_not_open=True)
ok("setup: pyserial's own default is DTR on (the cause)", plain.dtr is True)
import gui_seriallines
p = serial.serial_for_url("loop://", baudrate=115200, timeout=0.1)
ok("with gui_seriallines a port opens with DTR off and RTS off", p.is_open and p.dtr is False and p.rts is False, (p.dtr, p.rts))
p.close()
q = serial.serial_for_url("loop://", do_not_open=True)
ok("...also when the caller opens it later", q.dtr is False and q.rts is False and not q.is_open)
import importlib; importlib.reload(gui_seriallines)
ok("importing it twice does not wrap it twice", serial.serial_for_url.__module__ == "gui_seriallines" and serial.serial_for_url is gui_seriallines.serial_for_url)
src = open(os.path.join(ROOT, "gui_advert_proc.py"), encoding="utf-8").read() + open(os.path.join(ROOT, "gui_echo_proc.py"), encoding="utf-8").read()
ok("both helper processes load it before the meshcore library", src.count("import gui_seriallines") == 2 and all(
    s.index("import gui_seriallines") < s.index("from meshcore import") for s in src.split('"""Send-and-listen')))

# ---- meshcli is started through the launcher that loads it
import meshcore_io as io
cmd = io.cli_command if hasattr(io, "cli_command") else io.cli_cmd
c = cmd()
try:
    import meshcore_cli  # noqa: F401
    ok("meshcli runs through gui_meshcli.py when this Python has meshcore-cli", c[0] == sys.executable and c[1].endswith("gui_meshcli.py"), c)
except ImportError:
    ok("without meshcore-cli in this Python the installed meshcli is used", c[0].lower().endswith(("meshcli", "meshcli.exe")), c)
with mock.patch.object(io, "DEFAULT_CLI_PATH", "C:/fake/meshcli.cmd"):
    ok("a stand-in meshcli (tests) is still used as given", cmd()[0] in ("C:/fake/meshcli.cmd", "meshcli"))
ok("the launcher loads gui_seriallines before meshcore-cli", (lambda s: s.index("import gui_seriallines") < s.index("from meshcore_cli"))(open(os.path.join(ROOT, "gui_meshcli.py"), encoding="utf-8").read()))

# ---- entering rescue mode: reset (RTS), then hold the button (DTR) inside the 8 s window
import gui_rescue
class FakePort:
    def __init__(self): self.events, self.buf, self._dtr, self._rts, self.sent = [], b"", False, False, []
    dtr = property(lambda s: s._dtr, lambda s, v: (s.events.append(("dtr", v)), setattr(s, "_dtr", v)))
    rts = property(lambda s: s._rts, lambda s, v: (s.events.append(("rts", v)), setattr(s, "_rts", v)))
    def read(self, n):
        b, self.buf = self.buf, b""
        return b
    def write(self, b):
        self.sent.append(b)
        if b == b"\r": self.buf += b"\r\n  Error: unknown command\r\n"
    def reset_input_buffer(self): self.buf = b""
fp = FakePort()
with mock.patch("time.sleep"):
    gui_rescue.enter_rescue(fp)
ok("rescue: reset first (RTS on/off), then the button held (DTR on) and released", fp.events == [("rts", True), ("rts", False), ("dtr", True), ("dtr", False)], fp.events)
ok("the rescue console is recognised", gui_rescue.in_rescue(fp))
fp2 = FakePort(); fp2.write = lambda b: None
ok("...and a normal (silent) port is not", not gui_rescue.in_rescue(fp2))

# ---- the window: dangerous commands ask first
import mcIRC
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
dlg = gui_rescue.RescueDialog(app); root.update()
dlg.port = FakePort()
with mock.patch.object(gui_rescue.messagebox, "askyesno", lambda *a, **k: False):
    dlg.send("erase")
    dlg.send("rebuild")
ok("erase / rebuild are not sent without a yes", dlg.port.sent == [], dlg.port.sent)
with mock.patch.object(gui_rescue.messagebox, "askyesno", lambda *a, **k: True):
    dlg.send("rebuild")
ok("...and are sent after a yes", dlg.port.sent == [b"rebuild\r"], dlg.port.sent)
dlg.port.sent.clear(); dlg.send("ls UserData/")
ok("harmless commands go straight out", dlg.port.sent == [b"ls UserData/\r"])
dlg.close(); root.update()
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
