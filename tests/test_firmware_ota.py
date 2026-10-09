import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Firmware builder extras: more firmware types (observer, bridges, terminal chat, KISS modem), the OTAFIX bootloader for nRF52 boards,
updates over Wi-Fi for ESP32, and the first setup after flashing.  No radio, no board, no internet (a local stand-in for the node's OTA page)."""
import hashlib, http.server, tempfile, threading
from unittest import mock

sys.path[:0] = [os.path.join(ROOT, "packages", "node_tools")]
import ntools_fwbuild as fb
import ntools_ota as ota
import ntools_wifi as w

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- firmware types, from a source tree like the observer fork's
src = tempfile.mkdtemp()
os.makedirs(os.path.join(src, "variants", "heltec_v3")); os.makedirs(os.path.join(src, "variants", "rak4631"))
with open(os.path.join(src, "variants", "heltec_v3", "platformio.ini"), "w") as f:
    f.write("[Heltec_lora32_v3]\nextends = esp32_base\n\n" + "".join(f"[env:Heltec_v3_{s}]\nextends = Heltec_lora32_v3\n\n" for s in (
        "repeater", "repeater_bridge_rs232", "repeater_bridge_espnow", "repeater_observer_mqtt", "room_server", "room_server_observer_mqtt",
        "terminal_chat", "companion_radio_usb", "companion_radio_ble", "companion_radio_wifi", "sensor", "kiss_modem")))
with open(os.path.join(src, "variants", "rak4631", "platformio.ini"), "w") as f:
    f.write("[rak4631]\nextends = nrf52_base\n\n[env:RAK_4631_repeater]\nextends = rak4631\n\n[env:RAK_4631_companion_radio_ble]\nextends = rak4631\n")
bd = fb.boards(src)
ok("every firmware type is found, each as its own type", sorted(bd["Heltec_v3"]) == sorted(["repeater", "bridge_rs232", "bridge_espnow", "observer", "room_server",
   "observer_room", "terminal_chat", "companion_usb", "companion_ble", "companion_wifi", "sensor", "kiss_modem"]), sorted(bd["Heltec_v3"]))
ok("...the observer is the observer build, not the repeater", bd["Heltec_v3"]["observer"][0] == "Heltec_v3_repeater_observer_mqtt"
   and bd["Heltec_v3"]["repeater"][0] == "Heltec_v3_repeater")
ok("every type has a title and an after-flashing note (companion: its own)", all(k in fb.TYPE_TITLES for k in ("observer", "bridge_espnow", "terminal_chat", "kiss_modem"))
   and all(k in fb.AFTER for k in fb.TYPE_TITLES if k != "companion"))
env, ini, make = fb.plan(bd["Heltec_v3"], "observer")
t = make("[env:Heltec_v3_repeater_observer_mqtt]\nbuild_flags = -D X\n")
ok("an observer is built with every analyzer slot off - it reports nothing until you pick one", env == fb.CUSTOM_ENV
   and "extends = env:Heltec_v3_repeater_observer_mqtt" in t and all(f"-D MQTT_DEFAULT_SLOT{n}_PRESET='\"none\"'" in t for n in range(1, 7)), t)
ok("...and the after-flashing note says how to pick one", "NO analyzer" in fb.AFTER["observer"] and "set mqtt1.preset" in fb.AFTER["observer"])
ok("ESP32 or nRF52 is read from the board's build file", fb.arch(bd["Heltec_v3"]) == "esp32" and fb.arch(bd["RAK_4631"]) == "nrf52")
ok("Wi-Fi OTA: offered for ESP32 repeater types", fb.wifi_ota_ok(bd["Heltec_v3"], "repeater") and fb.wifi_ota_ok(bd["Heltec_v3"], "observer"))
ok("...not for a companion, terminal chat or KISS modem (no 'start ota'), nor for nRF52 boards",
   not fb.wifi_ota_ok(bd["Heltec_v3"], "companion") and not fb.wifi_ota_ok(bd["Heltec_v3"], "kiss_modem") and not fb.wifi_ota_ok(bd["RAK_4631"], "repeater"))

# ---- the community source is pinned to one reviewed commit
title = fb.OBSERVER_SOURCE["title"]
ok("the observer source downloads exactly the reviewed commit", w.source_url(title) == f"https://github.com/agessaman/MeshCore/archive/{fb.OBSERVER_SOURCE['ref']}.zip"
   and len(fb.OBSERVER_SOURCE["ref"]) == 40, w.source_url(title))
ok("...into its own folder; MeshCore releases keep theirs", w.source_dir(title).endswith("agessaman-MeshCore-7403067d1d") and w.source_dir("companion-v1.17.1").endswith("MeshCore-companion-v1.17.1"))

# ---- OTAFIX
INFO = "UF2 Bootloader 0.6.1 lib/nrfx (v2.0.0) s140 6.1.1\nModel: WisBlock RAK4631 Board\nBoard-ID: WisBlock-RAK4631-Board\nDate: Jan 1 2024\n"
info = ota.parse_info(INFO)
ok("INFO_UF2.TXT: model and Board-ID", info["board_id"] == "WisBlock-RAK4631-Board" and info["model"] == "WisBlock RAK4631 Board", info)
ok("a stock bootloader is not OTAFIX; an OTAFIX one is", not ota.has_otafix(info) and ota.has_otafix(ota.parse_info("UF2 Bootloader 0.9.2-OTAFIX2.3-BP1.4 lib/nrfx\nBoard-ID: x")))
name, url, sha = ota.otafix_file("WisBlock-RAK4631-Board")
ok("the right OTAFIX file for the board, from the pinned release", name == f"update-wiscore_rak4631_board_bootloader-{ota.OTAFIX_TAG}_nosd.uf2"
   and url.endswith(f"/releases/download/{ota.OTAFIX_TAG}/{name}") and len(sha) == 64)
ok("...none for a board OTAFIX doesn't support", ota.otafix_file("nRF52840-Unknown") is None)
drive = tempfile.mkdtemp()
with open(os.path.join(drive, "INFO_UF2.TXT"), "w") as f: f.write(INFO)
good = b"UF2 bootloader bytes"
got = ota.install_otafix(drive, log=lambda s: None, fetch=lambda u, s: good)
ok("install: the update file is copied onto the UF2 drive", got == "installed" and open(os.path.join(drive, name), "rb").read() == good)
with mock.patch("urllib.request.urlopen") as uo:
    uo.return_value.__enter__.return_value.read.return_value = b"something else"
    try: ota.fetch_checked("https://example.invalid/x.uf2", hashlib.sha256(good).hexdigest()); refused = False
    except ValueError: refused = True
ok("a downloaded file that isn't the reviewed one (checksum) is refused", refused)
with open(os.path.join(drive, "INFO_UF2.TXT"), "w") as f: f.write(INFO.replace("0.6.1", "0.9.2-OTAFIX2.3-BP1.4"))
ok("a board that already has OTAFIX: nothing is copied", ota.install_otafix(drive, log=lambda s: None, fetch=lambda u, s: 1 / 0) == "already")

# ---- Wi-Fi OTA: upload to a stand-in for the node's ElegantOTA page
seen = {}
class Node(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = b'{"id": "Hilltop (Heltec V3)", "hardware": "ESP32"}'
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        seen["path"], seen["type"] = self.path, self.headers["Content-Type"]
        seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"OK")
srv = http.server.HTTPServer(("127.0.0.1", 0), Node); threading.Thread(target=srv.serve_forever, daemon=True).start()
host = "127.0.0.1"
import http.client
real = http.client.HTTPConnection
with mock.patch.object(ota.http.client, "HTTPConnection", lambda h, p, timeout=0: real(host, srv.server_port, timeout=timeout)):
    ident = ota.ota_identity()
    fw = os.path.join(tempfile.mkdtemp(), "firmware.bin"); data = os.urandom(20000)
    with open(fw, "wb") as f: f.write(data)
    steps = []
    answer = ota.ota_upload(fw, progress=lambda d, t: steps.append(d))
srv.shutdown()
ok("the node in update mode says who it is", ident.get("id") == "Hilltop (Heltec V3)", ident)
body = seen.get("body", b"")
ok("upload: POST /update, the MD5 first and then the file (what ElegantOTA expects)", seen.get("path") == "/update" and answer == "OK"
   and body.find(b'name="MD5"') < body.find(b'name="firmware"') and hashlib.md5(data).hexdigest().encode() in body and data in body)
ok("...with progress", steps and steps[-1] == len(body))
ok("the application file is uploaded, never the -merged one", ota.firmware_bin("S", "Heltec_v3_repeater").replace("\\", "/") == "S/.pio/build/Heltec_v3_repeater/firmware.bin")

# ---- first setup after flashing
ok("setup: name, password, position, then the radio and a reboot", ota.setup_commands("Hilltop", "s3cret", ["910.525", "62.5", "7", "5"], "49.28", "-123.12") ==
   ["set name Hilltop", "password s3cret", "set lat 49.28", "set lon -123.12", "set radio 910.525,62.5,7,5", "reboot"])
ok("...nothing filled in: nothing sent", ota.setup_commands() == [])
for args, why in ((("x" * 40, "", "", ""), "a name that is too long"), (("ok", "has space", "", ""), "a password with a space"),
                  (("ok", "", "91", ""), "a latitude out of range"), (("ok", "", "", "east"), "a longitude that isn't a number")):
    try: ota.check_setup(*args); refused = False
    except ValueError: refused = True
    ok(f"setup refuses {why}", refused)
lines, sent = [], []
class Port:
    def read(self, n): return b"  -> OK" if sent else b""
    def write(self, b): sent.append(b)
    def close(self): pass
with mock.patch.object(ota.time, "sleep", lambda s: None):
    ota.serial_cli("COM99", ["set name Hilltop", "password s3cret", "reboot"], log=lines.append, opener=Port)
ok("the commands go to the node's USB command line, each ended by a carriage return", sent == [b"set name Hilltop\r", b"password s3cret\r", b"reboot\r"], sent)
ok("...and the admin password is never shown", not any("s3cret" in l for l in lines), lines)
# ---- radio presets
import ntools_presets as pr
API_JSON = {"config": {"suggested_radio_settings": {"entries": [
    {"title": "Canada", "frequency": "910.525", "bandwidth": "62.5", "spreading_factor": "7", "coding_rate": "5"},
    {"title": "Broken", "frequency": "abc", "bandwidth": "62.5", "spreading_factor": "7", "coding_rate": "5"},
    {"title": "Bad BW", "frequency": "910.0", "bandwidth": "63", "spreading_factor": "7", "coding_rate": "5"}]}}}
got = pr.official(lambda url: API_JSON)
ok("presets: MeshCore's own list is read; entries with impossible values are left out", got == [("Canada", "910.525", "62.5", "7", "5")], got)
allp = pr.merged([("South BC 909", "909.000", "62.5", "7", "5")], got)
ok("...your own first ('My: '), then the official ones, then local groups' (South BC 909 included)", allp[0][0] == "My: South BC 909" and allp[1][0] == "Canada"
   and any(p[0] == "Canada: South BC 909 (Salish Mesh)" and p[1:] == ("909.000", "62.5", "7", "5") for p in allp), allp[:3])
names = [p[0] for p in pr.merged([], [])]
ok("countries are together: Canada next to South BC, the USA ones next to each other", names.index("Canada: South BC 909 (Salish Mesh)") == names.index("Canada") + 1
   and names[names.index("USA"):names.index("USA") + 4] == ["USA", "USA - Southern California", "USA: 500 kHz (MeshCore 500)", "USA: Florida, CR8 (Florida Mesh)"], names)
ok("...offline: the built-in copy of the official list (26 regions)", len(pr.BUILTIN) == 26 and pr.merged([], [])[0][0] == "Australia")
ok("every built-in and local-group preset is a valid MeshCore radio setting", all(pr.valid(*p[1:]) for p in pr.BUILTIN + pr.COMMUNITY))
ok("valid() refuses bad values", not pr.valid("1000", "62.5", "7", "5") and not pr.valid("910", "62.5", "13", "5") and not pr.valid("910", "62.5", "7", "4"))

# ---- the window: each box only where it makes sense
import tkinter as tk
root = tk.Tk(); root.withdraw()
class API:
    def ui(self): return {"root": root}
    def run_background(self, fn, done): pass
with mock.patch.object(w, "find_pio", lambda: None), mock.patch.object(ota, "uf2_drives", lambda: []):
    win = w.FirmwareBuilderWindow(API())
    win.boards = bd
    st = lambda c: str(c.cget("state"))
    def pick(board, kind, uf2=None):
        win._uf2_info = uf2
        win.v["board"].set(board); win.v["kind"].set(kind); win.update_fields(); root.update_idletasks()
    pick("Heltec_v3", "repeater")
    ok("ESP32 repeater: Wi-Fi update offered, OTAFIX not (ESP32 boards have OTA already)", st(win.wifi_ota_check) == "normal" and st(win.otafix_check) == "disabled")
    pick("Heltec_v3", "companion")
    ok("ESP32 companion: no Wi-Fi update (no 'start ota'), no OTAFIX", st(win.wifi_ota_check) == "disabled" and st(win.otafix_check) == "disabled")
    pick("RAK_4631", "repeater")
    ok("nRF52 board: OTAFIX offered, Wi-Fi update not", st(win.otafix_check) == "normal" and st(win.wifi_ota_check) == "disabled")
    pick("RAK_4631", "repeater", uf2=ota.parse_info(INFO.replace("0.6.1", "0.9.2-OTAFIX2.3-BP1.4")))
    ok("...not offered when the board on USB already has OTAFIX - and it says so", st(win.otafix_check) == "disabled" and "already" in win.ota_note.cget("text"), win.ota_note.cget("text"))
    pick("Heltec_v3", "repeater")
    ok("setup after flashing: name, admin password and position for a repeater", st(win.setup_check) == "normal" and st(win.setup_entries["admin"]) == "normal")
    pick("Heltec_v3", "companion")
    ok("...a companion has no admin password", st(win.setup_entries["admin"]) == "disabled" and st(win.setup_entries["name"]) == "normal")
    pick("Heltec_v3", "kiss_modem")
    ok("...nothing to set up on a KISS modem", st(win.setup_check) == "disabled")
    pick("Heltec_v3", "repeater"); win.wifi_ota.set(True); win.update_fields()
    ok("updating over Wi-Fi: no USB port and no setup (the node keeps its settings)", st(win.entries["port"]) == "disabled" and st(win.setup_check) == "disabled")
    win.destroy()
store = {}
class API2(API):
    def get(self, k, d=None): return store.get(k, d)
    def set(self, k, v): store[k] = v
with mock.patch.object(w, "find_pio", lambda: None), mock.patch.object(ota, "uf2_drives", lambda: []), \
        mock.patch("tkinter.simpledialog.askstring", lambda *a, **k: "South BC 909"), mock.patch("tkinter.messagebox.showerror", lambda *a, **k: None):
    win = w.FirmwareBuilderWindow(API2())
    vals = list(win.preset_box.cget("values"))
    i = next(n for n, v in enumerate(vals) if v.startswith("Canada: South BC 909 (Salish Mesh)"))
    win.preset_box.current(i); win._use_preset()
    ok("choosing a preset fills in the radio", [win.v[k].get() for k in ("freq", "bw", "sf", "cr")] == ["909.000", "62.5", "7", "5"])
    win.save_preset()
    ok("'Save as preset...' keeps the radio under your name (saved with the addon)", store.get("radio_presets") == [["South BC 909", "909.000", "62.5", "7", "5"]]
       and any(v.startswith("My: South BC 909") for v in win.preset_box.cget("values")), store)
    win.preset_box.set(pr.label(("My: South BC 909", "909.000", "62.5", "7", "5"))); win.remove_preset()
    ok("'Remove' deletes one of your own presets", store.get("radio_presets") == [])
    import urllib.parse
    opened, answers = [], iter(["Ridgeline Mesh", "Canada: Fraser Valley"])
    win.v["freq"].set("909.000")
    with mock.patch("tkinter.simpledialog.askstring", lambda *a, **k: next(answers)), mock.patch("tkinter.messagebox.askokcancel", lambda *a, **k: True):
        win.suggest_preset(open_url=opened.append)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(opened[0]).query) if opened else {}
    ok("'Suggest to mcIRC...' opens a ready-filled GitHub issue (the person submits it there)", opened and opened[0].startswith("https://github.com/bclml/mcIRC/issues/new?")
       and q.get("title") == ["Radio preset: Canada: Fraser Valley (Ridgeline Mesh)"] and "909.000 MHz" in q["body"][0] and q.get("labels") == ["radio-preset"], opened)
    ok("...with the preset line ready to paste into the list", '("Canada: Fraser Valley (Ridgeline Mesh)", "909.000", "62.5", "7", "5")' in q["body"][0])
    win.v["freq"].set("2000"); win.save_preset()
    ok("an impossible radio is not saved", store.get("radio_presets") == [])
    win.destroy()
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
