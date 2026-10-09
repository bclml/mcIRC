import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Wi-Fi firmware tool (build settings, boards, finding the IP) and the radio settings of an extra node.  No build, no flashing, no radio."""
import json, tempfile, tkinter as tk
from types import SimpleNamespace
from unittest import mock

sys.path[:0] = [os.path.join(ROOT, "packages", "node_tools")]
import ntools_wifi as w
import gui_seriallines  # noqa: F401  (loaded first, as in the app: the stand-in port below replaces the patched opener)

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

INI = """[Heltec_lora32_v3]
build_flags = -D X=1

[env:Heltec_v3_companion_radio_wifi]
extends = Heltec_lora32_v3
build_flags =
  -D WIFI_DEBUG_LOGGING=1
  -D WIFI_SSID='"myssid"'
  -D WIFI_PWD='"mypwd"'

[env:Heltec_WSL3_companion_radio_wifi]
build_flags =
  -D WIFI_SSID='"myssid"'
  -D WIFI_PWD='"mypwd"'
"""
new = w.with_wifi(INI, "Heltec_v3_companion_radio_wifi", "HomeNet", "s3cret pass")
ok("the chosen board gets the Wi-Fi name and password", "-D WIFI_SSID='\"HomeNet\"'" in new and "-D WIFI_PWD='\"s3cret pass\"'" in new)
ok("...other boards in the same file are left alone", new.split("[env:Heltec_WSL3")[1] == INI.split("[env:Heltec_WSL3")[1])
for bad in ('my"net', "it's", "back\\slash", ""):
    try: w.check_wifi_text(bad, "name"); refused = False
    except ValueError: refused = True
    ok(f"a Wi-Fi name the build can't take is refused: {bad!r}", refused)
src = tempfile.mkdtemp()
os.makedirs(os.path.join(src, "variants", "heltec_v3")); os.makedirs(os.path.join(src, "variants", "xiao_s3"))
open(os.path.join(src, "variants", "heltec_v3", "platformio.ini"), "w").write(INI)
open(os.path.join(src, "variants", "xiao_s3", "platformio.ini"), "w").write("[env:Xiao_S3_WIO_companion_radio_wifi]\nbuild_flags =\n")
envs = w.wifi_envs(src)
ok("every board with a Wi-Fi companion build is offered", list(envs) == ["Heltec_v3_companion_radio_wifi", "Heltec_WSL3_companion_radio_wifi", "Xiao_S3_WIO_companion_radio_wifi"], list(envs))
ok("Heltec V3 is picked for a Heltec V3", w.best_env(envs, "Heltec V3") == "Heltec_v3_companion_radio_wifi")
class FakeSerial:
    def __init__(self, chunks): self.chunks = list(chunks)
    def read(self, n): return self.chunks.pop(0) if self.chunks else b""
    def close(self): pass
boot = [b"ESP-ROM:esp32s3\r\nWiFi: connecting to HomeNet\r\n", b"WiFi connected, IP address: 192.168.1.77\r\n"]
with mock.patch("serial.serial_for_url", lambda *a, **k: FakeSerial(boot)):
    ok("its IP address is read from the board's start-up messages", w.read_ip("COMX", seconds=2) == "192.168.1.77")
with mock.patch("serial.serial_for_url", lambda *a, **k: FakeSerial([b"WiFi: connecting...\r\n"])):
    ok("...and None when it never says one", w.read_ip("COMX", seconds=1) is None)
ok("the board's MAC is picked out of the flasher's output", w.MAC_RE.search("MAC:                90:70:69:84:9a:44").group(1) == "90:70:69:84:9a:44")
ok("a Heltec V4 running MeshCore needs the PRG + RST buttons to flash, a USB-JTAG port does not",
   w.needs_boot_buttons("USB VID:PID=303A:0002 SER=1") and not w.needs_boot_buttons("USB VID:PID=303A:1001 SER=1"))
ARP = "  192.168.1.39          90-70-69-84-9a-44     dynamic\n  192.168.1.61          90-70-69-83-f4-00     dynamic\n"
with mock.patch.object(w.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=ARP)), \
     mock.patch("socket.socket.connect", lambda self, addr: None if addr[0] in ("192.168.1.39", "192.168.1.61") else (_ for _ in ()).throw(OSError())), \
     mock.patch("socket.getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("192.168.1.46", 0))]):
    ok("the flashed board is found on the network by its MAC (not another ESP32 with port 5000)", w.find_on_lan("90:70:69:84:9a:44", seconds=5) == "192.168.1.39")
want = w.mac_key("90:70:69:84:9a:44")
for system, text in (("Windows", "Interface: 192.168.1.46 --- 0x5\n  192.168.1.39          90-70-69-84-9a-44     dynamic\n"),
                     ("Linux", "? (192.168.1.39) at 90:70:69:84:9a:44 [ether] on wlan0\n? (192.168.1.1) at <incomplete> on wlan0\n"),
                     ("macOS", "? (192.168.1.39) at 90:70:69:84:9a:44 on en0 ifscope [ethernet]\n? (192.168.1.61) at 90:70:69:83:f4:0 on en0\n"),
                     ("ip neigh", "192.168.1.39 dev wlan0 lladdr 90:70:69:84:9a:44 REACHABLE\n")):
    ok(f"the PC's address table is read on {system}", ("192.168.1.39", want) in w.parse_neighbours(text), w.parse_neighbours(text))
ok("macOS's short MAC form (no leading zeros) matches", w.mac_key("90:70:69:83:f4:0") == w.mac_key("90-70-69-83-F4-00"))
ok("PlatformIO is found on this PC (or reported missing)", w.find_pio() is None or isinstance(w.find_pio(), list))

# ---- the firmware builder: which build for which choice
import ntools_fwbuild as fb
src2 = tempfile.mkdtemp()
os.makedirs(os.path.join(src2, "variants", "heltec_v3")); os.makedirs(os.path.join(src2, "variants", "rak4631"))
MORE = ("[env:Heltec_v3_companion_radio_usb]\nbuild_flags = -D ENABLE_USB_INTERFACE\n\n"
        "[env:Heltec_v3_companion_radio_ble]\nbuild_flags = -D BLE_PIN_CODE=123456\n  -D BLE_DEBUG_LOGGING=1\n\n"
        "[env:Heltec_v3_repeater]\nbuild_flags =\n\n[env:Heltec_v3_repeater_bridge_rs232]\nbuild_flags =\n\n"
        "[env:Heltec_v3_room_server]\nbuild_flags =\n\n[env:Heltec_v3_sensor]\nbuild_flags =\n\n")
V3 = INI.replace("[env:Heltec_WSL3_companion_radio_wifi]", MORE + "[env:Heltec_WSL3_companion_radio_wifi]")
open(os.path.join(src2, "variants", "heltec_v3", "platformio.ini"), "w").write(V3)
open(os.path.join(src2, "variants", "rak4631", "platformio.ini"), "w").write("[env:RAK_4631_companion_radio_usb]\n\n[env:RAK_4631_companion_radio_ble]\n\n[env:RAK_4631_repeater]\n")
bd = fb.boards(src2)
ok("boards and their firmware types are found", sorted(bd["Heltec_v3"]) == ["companion_ble", "companion_usb", "companion_wifi", "repeater", "room_server", "sensor"]
   and sorted(bd["RAK_4631"]) == ["companion_ble", "companion_usb", "repeater"], {k: sorted(v) for k, v in bd.items()})
ok("...a repeater bridge isn't mistaken for a repeater", bd["Heltec_v3"]["repeater"][0] == "Heltec_v3_repeater")
ok("a board without Wi-Fi offers only USB and Bluetooth", fb.connections(bd["RAK_4631"]) == ["usb", "ble"])
env, ini, make = fb.plan(bd["Heltec_v3"], "repeater")
ok("a repeater is the board's own repeater build, unchanged", env == "Heltec_v3_repeater" and make(V3) == V3)
env, ini, make = fb.plan(bd["Heltec_v3"], "companion", ["wifi"], "Home", "pw")
ok("Wi-Fi only: the Wi-Fi build with your network in it", env == "Heltec_v3_companion_radio_wifi" and "-D WIFI_SSID='\"Home\"'" in make(V3) and "[env:mcirc_custom]" not in make(V3))
env, ini, make = fb.plan(bd["Heltec_v3"], "companion", ["usb", "ble", "wifi"], "Home", "pw")
t = make(V3)
ok("all three: a build on the Bluetooth one that also switches USB and Wi-Fi on", env == "mcirc_custom" and "extends = env:Heltec_v3_companion_radio_ble" in t
   and "-D ENABLE_USB_INTERFACE" in t and "-D WIFI_SSID='\"Home\"'" in t and "-UBLE_DEBUG_LOGGING" in t, t[-400:])
env, ini, make = fb.plan(bd["Heltec_v3"], "companion", ["usb"])
ok("USB only: the plain USB build", env == "Heltec_v3_companion_radio_usb" and make(V3) == V3)
for board, args, why in (("Heltec_v3", ("companion", []), "no connection ticked"), ("RAK_4631", ("companion", ["wifi"]), "Wi-Fi on a board without it"),
                         ("RAK_4631", ("room_server", []), "a type the board lacks")):
    try: fb.plan(bd[board], *args); refused = False
    except ValueError: refused = True
    ok(f"refused: {why}", refused)

# ---- adding the flashed board as a node; the radio settings of an extra node
import mcIRC, gui_multinode_ui
from gui_addons import AddonAPI
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
api = AddonAPI(app, "node_tools")
api.add_extra_node({"label": "wifi", "mode": "tcp", "host": "192.168.1.77", "tcp_port": 5000, "enabled": True})
api.add_extra_node({"label": "wifi", "mode": "tcp", "host": "192.168.1.78", "tcp_port": 5000, "enabled": True})
ok("the board is added to More nodes (once, the newest address wins)", [c["host"] for c in app.settings["extra_nodes"] if c["label"] == "wifi"] == ["192.168.1.78"])
calls = []
INFO = {"name": "Old", "radio_freq": 909.0, "radio_bw": 62.5, "radio_sf": 7, "radio_cr": 5, "tx_power": 22}
def fake_exec(args, timeout=30, retries=2, retry_delay=2, lock=None, health=None):
    calls.append(args)
    return SimpleNamespace(stdout=json.dumps(INFO) if ".infos" in args else "", stderr="", returncode=0)
app.bg = lambda fn, done: done(fn())
import meshcore_io as io
with mock.patch.object(io, "execute_mesh_command", fake_exec):
    dlg = gui_multinode_ui.RadioDialog(root, app, {"label": "wifi", "mode": "tcp", "host": "192.168.1.78", "tcp_port": 5000})
    ok("the radio settings are read from that node (over its own connection)", dlg.v["radio_freq"].get() == "909" and calls[0][:4] == ["-t", "192.168.1.78", "-p", "5000"], (dlg.v["radio_freq"].get(), calls[0]))
    calls.clear(); dlg.v["radio_freq"].set("915"); dlg.v["name"].set("Node915")
    with mock.patch.object(gui_multinode_ui.messagebox, "askyesno", lambda *a, **k: True):
        dlg.write()
    sent = [c[4:] for c in calls]
    ok("changed name and radio are written, then the node restarts", ["set", "name", "Node915"] in sent and ["set", "radio", "915,62.5,7,5"] in sent and ["reboot"] in sent and not any(s[:2] == ["set", "tx"] for s in sent), sent)
    calls.clear(); dlg.old = {**INFO, "radio_freq": 915.0, "name": "Node915"}; dlg.write()
    ok("nothing changed -> nothing is sent", calls == [], calls)
    dlg.destroy()

# ---- the firmware builder says it is loading while the version list and the boards are fetched
import threading, time, ntools_firmware
class SlowAPI:
    def ui(self): return {"root": root}
    def run_background(self, fn, done):
        def t():
            try: r = fn()
            except Exception as e: r = e
            root.after(0, lambda: done(r))
        threading.Thread(target=t, daemon=True).start()
for failing in (False, True):
    def rels():
        time.sleep(0.6)
        if failing: raise OSError("no internet")
        return [("v1.17.1", "", ""), ("v1.16.0", "", "")]
    seen = []
    with mock.patch.object(w, "find_pio", lambda: ["pio"]), mock.patch.object(ntools_firmware, "companion_releases", rels), \
            mock.patch.object(w, "get_source", lambda tag, log: (time.sleep(0.6), "src")[1]), \
            mock.patch.object(fb, "boards", lambda src: {"Heltec_v3": {"companion_usb": ("e", "p")}, "RAK_4631": {"companion_ble": ("b", "p")}}):
        win = w.FirmwareBuilderWindow(SlowAPI())
        for ms in (200, 900, 2000):
            root.after(ms, lambda: (root.update_idletasks(), seen.append((win.v["ver"].get(), win.v["board"].get(), win.loading.winfo_ismapped()))))
        root.after(2100, root.quit); root.mainloop()
        win.destroy()
    if not failing:
        ok("firmware builder: 'Loading...' in the lists and a moving bar while the firmware list is fetched",
           seen[0] == (win.LOADING_VERSIONS, win.LOADING_BOARDS, 1) and seen[1][1:] == (win.LOADING_BOARDS, 1), seen)
        ok("...then the newest version and a board, and the bar is gone", seen[2] == ("v1.17.1", "Heltec_v3", 0), seen)
    else:
        ok("...when the list can't be fetched, no 'Loading...' is left behind", seen[-1] == ("", "", 0), seen)
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
