import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""MeshCore tools addon: clock, channels, backup/restore, firmware matching, paths, health, coverage - with a pretend radio."""
import importlib.util, json, tempfile, time, tkinter as tk
from unittest import mock

sys.path[:0] = [os.path.join(ROOT, "packages", "node_tools")]
import ntools_backup, ntools_channels, ntools_clock, ntools_common, ntools_firmware, ntools_monitor, ntools_paths

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- 1. clock
text, off = ntools_clock.describe(1724613400, 1791149081)
ok("clock: a node 770 days behind is reported as such", off and "770 days" in text and "behind" in text, text)
ok("clock: a few seconds off is fine", ntools_clock.describe(1000, 1030)[1] is False)

# ---- 2. channels
chs = [{"channel_idx": 0, "channel_name": "Public", "channel_secret": "aa" * 16}, {"channel_idx": 1, "channel_name": "#transportation", "channel_secret": "bb" * 16},
       {"channel_idx": 2, "channel_name": "#transportation", "channel_secret": "bb" * 16}, {"channel_idx": 3, "channel_name": "drivebc", "channel_secret": "cc" * 16}]
ok("channels: a duplicate slot is found", ntools_channels.duplicates(chs) == {2})
ok("channels: keys must be 32 hex characters", ntools_channels.check_key("ab" * 16) == "ab" * 16)
try: ntools_channels.check_key("xyz"); bad = False
except ValueError: bad = True
ok("...anything else is refused", bad)

# ---- 3. backup / restore against a pretend radio
calls = []
def fake_run(*args, **k):
    calls.append(args)
    if args[0] == ".contacts": return json.dumps({"k1" * 32: {"public_key": "k1" * 32, "adv_name": "Kept", "type": 2}})
    if args[0] == ".get_channels": return json.dumps(chs[:2] + [{"channel_idx": 3, "channel_name": "drivebc", "channel_secret": "dd" * 16}])
    return ""
data = {"mcirc_node_backup": 1, "settings": {}, "channels": chs, "contacts": [{"public_key": "k1" * 32, "adv_name": "Kept", "type": 2},
                                                                           {"public_key": "k2" * 32, "adv_name": "-Lost", "type": 1}]}
with mock.patch.object(ntools_backup, "run", fake_run), mock.patch.object(ntools_channels, "run", fake_run):
    lines = ntools_backup.restore(data, settings=False, channels=True, contacts=True)
sets = [c for c in calls if c[0] == "set_channel"]
ok("restore: only channels that differ are written (slot 2 missing, slot 3 has another key)", sorted(c[1] for c in sets) == [2, 3], sets)
adds = [c for c in calls if c[0] == "add_contact"]
ok("restore: only missing contacts are added, with a safe name and their path reset", len(adds) == 1 and adds[0][1] == "k2" * 32 and adds[0][3] == ("k2" * 32)[:8]
   and "reset_path" in adds[0], adds)
ok("restore: says what it did", any("1 contact(s) added back" in l for l in lines), lines)
tmp = tempfile.mkdtemp()
p = ntools_backup.save({"mcirc_node_backup": 1, "name": "My Node/1"}, folder=tmp)
ok("backups are files named after the node", os.path.basename(p).startswith("My_Node_1-") and ntools_backup.load(p)["name"] == "My Node/1")
open(os.path.join(tmp, "x.json"), "w").write("{}")
try: ntools_backup.load(os.path.join(tmp, "x.json")); refused = False
except ValueError: refused = True
ok("a file that is not a node backup is refused", refused)

# ---- 4. firmware
REL = [{"tag_name": "repeater-v1.18.0", "assets": []}, {"tag_name": "companion-v1.16.0", "assets": []},
       {"tag_name": "companion-v1.17.1", "html_url": "u", "assets": [{"name": "Heltec_v3_companion_radio_usb-v1.17.1-x-merged.bin"},
                                                                    {"name": "Heltec_v3_companion_radio_usb-v1.17.1-x.bin"}, {"name": "Heltec_v3_companion_radio_ble-v1.17.1-x.bin"},
                                                                    {"name": "LilyGo_T3S3_sx1262_companion_radio_usb-v1.17.1-x.bin"}]}]
ver, url, assets = ntools_firmware.latest_companion(get=lambda u: REL)
ok("firmware: the newest companion release (not repeater)", ver == "v1.17.1")
ok("firmware: every companion release is listed, newest first (the version list)", [r[0] for r in ntools_firmware.companion_releases(get=lambda u: REL)] == ["v1.17.1", "v1.16.0"])
ok("firmware: the application image for the board and connection (not -merged, not BLE)", ntools_firmware.pick_asset(assets, "Heltec V3", "usb")["name"] == "Heltec_v3_companion_radio_usb-v1.17.1-x.bin")
ok("firmware: an unknown board gets no file", ntools_firmware.pick_asset(assets, "RAK 4631", "usb") is None)
ok("firmware: versions compare as numbers", ntools_firmware.vkey("v1.17.1") > ntools_firmware.vkey("v1.16.0-07a3ca9") and ntools_firmware.vkey("v1.10.0") > ntools_firmware.vkey("v1.9.9"))

# ---- 5. paths
ok("paths: a route as trace hops", ntools_paths.trace_path("a1b2c3") == "a1,b2,c3" and ntools_paths.trace_path("a1b2c3d4", 2) == "a1b2,c3d4")

# ---- 7. health
smp = [{"t": 0, "battery_mv": 4100, "tx_air_secs": 0, "rx_air_secs": 0, "errors": 0, "recv_errors": 0},
       {"t": 300, "battery_mv": 4000, "tx_air_secs": 3, "rx_air_secs": 12, "errors": 1, "recv_errors": 1}]
d = ntools_monitor.derived(smp)
ok("health: battery in volts, airtime in percent, new errors per interval", d[1]["battery_v"] == 4.0 and d[1]["airtime_pct"] == 5.0 and d[1]["errors_new"] == 2, d[1])

# ---- 8. coverage
NODES = [{"public_key": "a1" + "0" * 62, "name": "Rep A", "type": 2, "lat": 49.2, "lon": -122.9}, {"public_key": "b2" + "0" * 62, "name": "Rep B", "type": 2, "lat": 49.3, "lon": -123.0}]
pk = [{"t": 1, "path": "b2a1", "size": 1, "snr": 7.5}, {"t": 2, "path": "a1", "size": 1, "snr": 3.0}, {"t": 3, "path": "b2", "size": 1, "snr": -2.0}, {"t": 4, "path": "", "snr": 9}]
cov = ntools_monitor.heard_repeaters(pk, NODES)
ok("coverage: the LAST hop is the one we hear directly; best SNR and count per repeater", cov["a1" + "0" * 62]["count"] == 2 and cov["a1" + "0" * 62]["best_snr"] == 7.5
   and cov["b2" + "0" * 62]["best_snr"] == -2.0, cov)

# ---- the addon in the window
import mcIRC
from gui_addons import AddonAPI
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
spec = importlib.util.spec_from_file_location("t_node_tools", os.path.join(ROOT, "packages", "node_tools", "node_tools.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
api = AddonAPI(app, "node_tools"); inst = m.Addon(api); api.display = inst.title; inst.on_load()
menu = [app.addon_menu.entrycget(i, "label") for i in range(app.addon_menu.index("end") + 1) if app.addon_menu.type(i) == "command"]
ok("all eight tools are in the Addons menu", all(any(t in l for l in menu) for t in ("Node clock", "Channels", "Backup", "Firmware", "Path tools", "Packet monitor", "Radio health", "Coverage")), menu)
ok("the coverage map layers are offered", "Coverage: strong (SNR >= 5)" in app.map_layers and "Coverage: weak (SNR < 5)" in app.map_layers)
app.packet_log[:] = [dict(p, t=time.time()) for p in pk]
app.nodes = type("N", (), {"all": staticmethod(lambda: NODES)})()
ok("...and fill with the heard repeaters", [x[2] for x in inst.coverage(True)] == ["Rep A +7.5 dB"] and [x[2] for x in inst.coverage(False)] == ["Rep B -2.0 dB"])
inst.open("monitor"); root.update()
ok("the packet monitor lists the heard packets", len(inst.windows["monitor"].t.get_children()) == 4)
inst.on_unload(); api._cleanup(); root.update()
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
