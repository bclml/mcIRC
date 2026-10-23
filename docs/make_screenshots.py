"""Regenerates the screenshots in docs/images/ from mcIRC's demo mode (fake data, no radio, nothing written to your settings).

    python docs/make_screenshots.py

Needs Windows, Pillow and (for the map) tkintermapview + internet for the map tiles.  Leave the mouse alone while it runs."""
import ctypes, json, os, sys, tkinter as tk
from ctypes import wintypes

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "docs", "images")
sys.path.insert(0, BASE)
os.chdir(BASE)
os.makedirs(OUT, exist_ok=True)

import mcIRC, meshcore_io as io, gui_addons as ga, gui_addonsettings, gui_devices, gui_dialogs, gui_update_ui   # noqa: E402
from tkinter import ttk   # noqa: E402
from PIL import ImageGrab   # noqa: E402


def grab(widget, name):
    """Screenshot of a whole window including its title bar and menu."""
    widget.update_idletasks(); widget.update(); widget.lift(); widget.attributes("-topmost", True); widget.update()
    hwnd = ctypes.windll.user32.GetParent(widget.winfo_id())
    r = wintypes.RECT()
    # DWMWA_EXTENDED_FRAME_BOUNDS (9) = the visible window only; GetWindowRect also includes Windows' invisible resize border,
    # which would let a strip of whatever is behind the window leak into the picture.
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom)).save(os.path.join(OUT, name))
    widget.attributes("-topmost", False)
    print("saved", name)


# ---- simulated hardware for the device scanner (nothing real is touched)
class _Port:
    def __init__(s, d, desc, vid, pid): s.device, s.description, s.vid, s.pid, s.manufacturer = d, desc, vid, pid, ""
io.serial.tools.list_ports.comports = lambda: [_Port("COM3", "Silicon Labs CP210x USB to UART Bridge (COM3)", 0x10C4, 0xEA60),
                                               _Port("COM7", "USB-Enhanced-SERIAL CH9102 (COM7)", 0x1A86, 0x55D4),
                                               _Port("COM9", "USB Serial Device (COM9)", 0x303A, 0x1001)]
io.probe_device = lambda args, timeout=25: {"COM3": {"ok": True, "name": "Hilltop-Node", "model": "Heltec V3", "fw": "v1.16.0", "max_contacts": 350},
                                            "COM7": {"ok": True, "name": "Cabin-TBeam", "model": "LilyGo T-Beam", "fw": "v1.16.0", "max_contacts": 350}}.get(
    args[1], {"ok": False, "why": io.explain_failure("Are you sure your node is a serial companion ?")})
io.scan_ble = lambda timeout=6: ["AA:BB:CC:11:22:33  MeshCore-4F2A", "DD:EE:FF:44:55:66  MeshCore-T114"]
SAMPLE_NODE = {"info": {"tx_power": 22, "max_tx_power": 22, "public_key": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90", "adv_lat": 49.19, "adv_lon": -122.85,
                        "multi_acks": 0, "adv_loc_policy": 1, "telemetry_mode_env": 0, "telemetry_mode_loc": 1, "telemetry_mode_base": 2, "manual_add_contacts": False,
                        "radio_freq": 910.525, "radio_bw": 62.5, "radio_sf": 7, "radio_cr": 5, "name": "DemoNode"},
               "ver": {"max_contacts": 350, "max_channels": 40, "ble_pin": 0, "fw_build": "06-Jun-2026", "model": "Heltec V3", "ver": "v1.16.0", "path_hash_mode": 1},
               "core": {"battery_mv": 3947, "uptime_secs": 248451, "errors": 0, "queue_len": 0},
               "radio": {"noise_floor": -115, "last_rssi": -59, "last_snr": 13.25, "tx_air_secs": 111, "rx_air_secs": 2294}}

import gui_common, subprocess   # noqa: E402
# pictures only: nothing here may reach a radio or start a program (flashing, the packet listener) - whatever is plugged in
def _no_radio(*a, **k): raise RuntimeError("screenshots: no radio")
io.execute_mesh_command = _no_radio
subprocess.run = subprocess.Popen = subprocess.call = subprocess.check_output = _no_radio
mcIRC.load_settings = lambda: dict(gui_common.DEFAULT_SETTINGS)   # a fresh setup: none of YOUR nodes, nick lists or names in public pictures
root = tk.Tk()
app = mcIRC.App(root, demo=True)
ga.fetch_catalog.__defaults__ = (ga.RAW, lambda url, timeout=20: open(os.path.join(BASE, url.rsplit("/", 1)[1]), "rb").read())   # catalog from the local file


def child(cls):
    return next(w for w in root.winfo_children() if isinstance(w, cls))


def steps():
    app.select_window("#drivebc"); yield 800
    grab(root, "chat.png")

    w = app.open_query("Alice")
    app.chat_line(w, "Alice", "Is the Highway 1 closure at Kensington still there?", "text", "(SNR 10.5, 1 hops)")
    app.chat_line(w, "DemoNode", "Cleared a few minutes ago, traffic is moving.", "self")
    app.chat_line(w, "Alice", "Thanks, heading out now. 73!", "text", "(SNR 10.0, 1 hops)")
    app.select_window("@Alice"); yield 800
    grab(root, "direct-messages.png")

    rpt = app.nodes.find_by_name("Hilltop Repeater")
    app.open_query("Hilltop Repeater", rpt["public_key"]); yield 400
    app.entry.delete(0, "end"); app.entry.insert(0, "/re"); app.cmd_popup.update("/re"); yield 700
    grab(root, "commands.png")
    app.cmd_popup.hide(); app.entry.delete(0, "end")

    pub = app.windows["Public"]
    app.select_window("Public")
    for nick, text in (("Alice", "@[Bob] did you get the relay up on the hill?"), ("Bob", "@Alice yes, 4 hops now - thanks for the help!"),
                       ("Carol", "@DemoNode can you check the Highway 1 bridge?"), ("Alice", "Installing the repeater soon, @Bob @[Carol]")):
        app.chat_line(pub, nick, text, "text", "(SNR 11.5, 3 hops)")
    app.settings["highlight_words"] = "bridge"; app.chat_line(pub, "Bob", "the bridge reopened", "text")
    app.settings["theme"] = "Night"; app.apply_theme(); yield 600
    grab(root, "theme-night.png")
    app.settings["theme"] = "Classic mIRC"; app.apply_theme(); app.settings["highlight_words"] = ""
    app.select_window("@Alice")

    app.switchbar.set_dock("left"); yield 700
    grab(root, "switchbar-docked.png")
    app.switchbar.set_dock("top")
    app.select_window("Public")

    app.open_map(); yield 6000
    grab(app.map_win, "map.png")
    app.map_win.destroy()

    app.open_options("Node: radio"); yield 800
    dlg = child(gui_dialogs.OptionsDialog)
    dlg.node_pages.fill(SAMPLE_NODE); yield 500
    grab(dlg, "node-settings.png")
    app.addons.loaded["auto_reply"][0].api.set("rules", [     # example rules for the picture (demo mode never saves them)
        {"name": "Test here", "enabled": True, "triggers": "test, t", "match": "exact", "listen": "#bot-van", "reply": "@{sender} Test received, {hops} hops", "reply_to": "", "cooldown": 20},
        {"name": "Test elsewhere", "enabled": True, "triggers": "test, t", "match": "exact", "listen": "", "reply": "@{sender} Please test in #bot-van", "reply_to": "", "cooldown": 20},
        {"name": "Ferry question", "enabled": True, "triggers": "!ferry", "match": "starts with", "listen": "Public", "reply": "@{sender} sailing news is on #bcferries", "reply_to": "", "cooldown": 30}])
    dlg.destroy(); app.open_options("Connect"); yield 600; dlg = child(gui_dialogs.OptionsDialog); dlg.node_pages.fill(SAMPLE_NODE)
    dlg.tree.selection_set("Connect"); yield 400
    dlg.scan_devices(); yield 2500
    grab(child(gui_devices.DeviceScanDialog), "device-scan.png")
    child(gui_devices.DeviceScanDialog).destroy()
    dlg.destroy()

    ga.read_installed = lambda: {}   # show the catalog as a fresh install sees it
    gui_update_ui.CatalogDialog(app); yield 1800
    grab(child(gui_update_ui.CatalogDialog), "addons-catalog.png")
    child(gui_update_ui.CatalogDialog).destroy()

    # each addon's own settings window, with example settings (demo mode never saves them)
    def addon(name, picture, values=None, tab=None, scroll=None):
        if name not in app.addons.loaded: print("not loaded:", name); return
        api = app.addons.loaded[name][0].api
        for k, v in (values or {}).items(): api.set(k, v)
        win = gui_addonsettings.open_settings(app, name); yield 900
        if tab is not None:
            nb = next((w for w in _descendants(win) if isinstance(w, ttk.Notebook)), None)
            if nb is not None: nb.select(tab); yield 500
        if scroll is not None: win.canvas.yview_moveto(scroll); yield 500
        grab(win, picture)
        win.destroy(); yield 300

    yield from addon("auto_reply", "auto-reply-options.png")       # (its example rules were set above)
    yield from addon("area_alerts", "addon-area-alerts.png", {"kinds": {"disasters": True, "weather": True, "emergency": True}, "forecast_on": True, "forecast_channels": "#daily"})
    yield from addon("area_alerts", "addon-area-alerts-daily.png", {"forecast_on": True, "forecast_channels": "#daily"}, scroll=1.0)   # Daily weather
    yield from addon("area_alerts", "addon-area-alerts-route.png", {"route_on": True}, tab=4)    # Route and more
    yield from addon("area_alerts", "addon-area-alerts-weather.png", {"wx_on": True, "wx_channels": "#weather"}, tab=3)    # Weather commands (the Weather bot's)
    yield from addon("fun_bot", "addon-fun-bot.png", {"enabled": True, "channels": {c: "#fun" for c in ("dice", "roll", "magic8", "joke", "dadjoke", "hacker", "catfact")}})
    yield from addon("mesh_bot", "addon-mesh-bot.png", {"enabled": True})
    yield from addon("packet_upload", "addon-packet-upload.png")
    yield from addon("map_uploader", "addon-map-uploader.png")
    yield from how_to()
    upd = gui_update_ui.UpdateDialog(app, auto_check=False); yield 400        # the box at the end of an update (never installs anything here)
    box = upd.done_box("mcIRC was updated to 2026.10.12-4 (2 addon(s) too).\nIt runs the new version after a restart.", restart=True); yield 600
    grab(box, "update-done.png")
    box.destroy(); upd.destroy()
    root.destroy()


def how_to():
    """Step-by-step pictures for the wiki: connecting (USB / Bluetooth / Wi-Fi), the node's pages, every Options page, MeshCore tools."""
    def options(page, picture, values=None, fill=False):
        app.open_options(page); yield 700
        dlg = child(gui_dialogs.OptionsDialog)
        if fill: dlg.node_pages.fill(SAMPLE_NODE)
        for k, v in (values or {}).items(): dlg.vars[k].set(v)
        dlg.tree.selection_set(page); yield 500
        grab(dlg, picture)
        dlg.destroy(); yield 300

    yield from options("Connect", "connect-usb.png", {"mode": "usb", "port": "COM3"})
    yield from options("Connect", "connect-bluetooth.png", {"mode": "bluetooth", "ble_target": "MeshCore-4F2A"})
    yield from options("Connect", "connect-wifi.png", {"mode": "tcp", "tcp_host": "192.168.1.50", "tcp_port": "5000"})
    app.settings["extra_nodes"] = [{"label": "915", "mode": "tcp", "host": "192.168.1.60", "port": 5000, "enabled": True}]   # an example second node
    yield from options("More nodes", "options-more-nodes.png")
    app.settings["extra_nodes"] = []
    yield from options("Node: behaviour", "node-behaviour.png", fill=True)
    yield from options("Node: status", "node-status.png", fill=True)
    for page, picture in (("Node memory", "options-node-memory.png"), ("Map", "options-map.png"), ("Display", "options-display.png"),
                          ("Sounds", "options-sounds.png")):
        yield from options(page, picture)

    tools = app.addons.loaded.get("node_tools", (None,))[0]
    if tools is None: print("not loaded: node_tools"); return
    import random, time as _t
    rnd, now = random.Random(7), _t.time()             # a day of made-up readings for the health graphs
    tools.samples = [{"t": now - (288 - i) * 300, "noise_floor": -116 + rnd.randint(-3, 3), "last_rssi": -60 + rnd.randint(-15, 8),
                      "last_snr": round(9 + rnd.uniform(-5, 4), 1), "battery_mv": 4150 - i * 2 + rnd.randint(-10, 10),
                      "tx_air_secs": i * 2, "rx_air_secs": i * 9 + rnd.randint(0, 6), "errors": i // 90} for i in range(288)]
    example = {   # what each window shows when a node answers (made up)
        "channels": lambda w: [w.t.insert("", "end", values=v) for v in ((0, "Public", "11", "8b3387e9c5cdea6ac9e5edbaa115cd72"),
                                                                        (1, "#weather", "a4", "(from the name)"), (2, "#bot-van", "3c", "(from the name)"))]
                              and w.say("3 channel(s)."),
        "firmware": lambda w: next(x for x in _descendants(w) if isinstance(x, tk.Text)).insert(
            "end", "Your node: Heltec V3, companion firmware v1.16.0\nNewest MeshCore release: v1.17.1 (companion)\n\n"
                   "Pick v1.17.1 and press 'Update the node...' - mcIRC downloads it and flashes it over USB.\n"),
        "clock": lambda w: w.say("The node's clock: 08:15:02 - this PC: 08:15:04 (2 s apart)."),
    }
    for key, picture in (("clock", "tool-clock.png"), ("channels", "tool-channels.png"), ("backup", "tool-backup.png"),
                         ("firmware", "tool-firmware.png"), ("paths", "tool-paths.png"), ("monitor", "tool-packet-monitor.png"),
                         ("health", "tool-radio-health.png"), ("coverage", "tool-coverage.png")):
        tools.open(key); yield 1200
        win = tools.windows.get(key)
        if win is None: print("no window:", key); continue
        if hasattr(win, "say"): win.say("")                # (not 'Connect to your node first': demo mode has no radio)
        if key in example: example[key](win)
        yield 400
        grab(win, picture)
        win.destroy(); yield 300
    tools.open("wifi"); yield 1000                       # (the versions come from GitHub, the boards from MeshCore's source: up to 90 s)
    win = tools.windows["wifi"]
    for _ in range(180):
        if win.boards and not win.busy: break
        yield 500
    for k, v in (("port", "COM3"), ("ssid", "MyHomeWiFi"), ("pwd", "example-password"), ("label", "node2")): win.v[k].set(v)
    win.update_fields(); yield 600
    grab(win, "firmware-builder.png")
    win.v["kind"].set("repeater"); win.update_fields(); yield 600
    grab(win, "firmware-builder-repeater.png")
    win.destroy()


def _descendants(w):
    for c in w.winfo_children():
        yield c
        yield from _descendants(c)


def run(gen):
    try: delay = next(gen)
    except StopIteration: return
    except Exception:                       # a step failed: say which, and close instead of leaving the window hanging
        import traceback; traceback.print_exc(); root.destroy(); return
    root.after(delay, lambda: run(gen))


root.after(1500, lambda: run(steps()))
root.mainloop()
