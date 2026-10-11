"""Firmware builder: which MeshCore build to make for a board - a companion with any mix of USB, Bluetooth and Wi-Fi (all of them waiting,
one used at a time: MeshCore's MultiSerialInterface), a repeater, a room server or a sensor."""
import os
import re

ENV_LINE = re.compile(r"^\[env:([A-Za-z0-9_\-]+)\]\s*$", re.M)
KINDS = {"companion_radio_usb": ("companion", "usb"), "companion_radio_ble": ("companion", "ble"), "companion_radio_wifi": ("companion", "wifi"),
         "repeater": ("repeater", None), "room_server": ("room_server", None), "sensor": ("sensor", None),
         "repeater_observer_mqtt": ("observer", None), "room_server_observer_mqtt": ("observer_room", None),
         "repeater_bridge_espnow": ("bridge_espnow", None), "repeater_bridge_rs232": ("bridge_rs232", None),
         "terminal_chat": ("terminal_chat", None), "kiss_modem": ("kiss_modem", None)}
TYPE_TITLES = {"companion": "Companion (for chatting: mcIRC, the phone apps)", "repeater": "Repeater", "room_server": "Room server", "sensor": "Sensor",
               "observer": "Observer: repeater that also sends what it hears to MQTT analyzers", "observer_room": "Observer room server (MQTT)",
               "bridge_espnow": "Repeater bridge over ESP-NOW (links two repeaters by Wi-Fi radio)", "bridge_rs232": "Repeater bridge over RS232 (serial cable)",
               "terminal_chat": "Terminal chat (chat from a serial terminal, no app)", "kiss_modem": "KISS modem (LoRa modem for PC software)"}
WIFI_OTA_KINDS = {"repeater", "room_server", "sensor", "observer", "observer_room", "bridge_espnow", "bridge_rs232"}   # MeshCore's CLI has 'start ota'

# Where the source comes from: MeshCore's own releases, or a reviewed community fork pinned to one commit (like outside addons).
OBSERVER_SOURCE = {"title": "Observer firmware (community: agessaman/MeshCore observer-firmware, 2026-10-04)",
                   "repo": "agessaman/MeshCore", "ref": "7403067d1d6a3ae88ba3d8791243e0995cb8e37c"}
COMMUNITY = {OBSERVER_SOURCE["title"]: OBSERVER_SOURCE}
CONN_TITLES = {"usb": "USB", "ble": "Bluetooth", "wifi": "Wi-Fi"}
CUSTOM_ENV = "mcirc_custom"


def boards(src):
    """{board: {'companion_usb' | 'companion_ble' | 'companion_wifi' | 'repeater' | 'room_server' | 'sensor': (env, platformio.ini path)}}"""
    out = {}
    for root, _, files in os.walk(os.path.join(src, "variants")):
        if "platformio.ini" not in files: continue
        p = os.path.join(root, "platformio.ini")
        with open(p, encoding="utf-8", errors="replace") as f: text = f.read()
        for env in ENV_LINE.findall(text):
            for suffix, (kind, conn) in KINDS.items():
                if env.endswith("_" + suffix):
                    board = env[:-len(suffix) - 1]
                    out.setdefault(board, {})[kind + ("_" + conn if conn else "")] = (env, p)
                    break
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def connections(board_envs):
    """The connections this board's companion firmware can have: subset of ('usb', 'ble', 'wifi')."""
    return [c for c in ("usb", "ble", "wifi") if f"companion_{c}" in board_envs]


def plan(board_envs, kind, conns=(), ssid="", pwd=""):
    """-> (env to build, platformio.ini path, new ini text maker) for the choice.  The maker takes the ini file's text and returns the text to
    build with (Wi-Fi details filled in, or an added env that switches the extra connections on); ValueError when the board can't do it."""
    if kind != "companion":
        if kind not in board_envs: raise ValueError(f"this board has no {TYPE_TITLES[kind].lower()} firmware")
        env, ini = board_envs[kind]
        if kind in ("observer", "observer_room"): return CUSTOM_ENV, ini, lambda text: _custom(text, env, OBSERVER_QUIET)
        return env, ini, lambda text: text
    conns = [c for c in ("usb", "ble", "wifi") if c in set(conns)]
    if not conns: raise ValueError("tick at least one connection: USB, Bluetooth or Wi-Fi")
    missing = [CONN_TITLES[c] for c in conns if f"companion_{c}" not in board_envs]
    if missing: raise ValueError(f"this board's companion firmware has no {', '.join(missing)}")
    base_conn = "ble" if "ble" in conns else "wifi" if "wifi" in conns else "usb"     # the build that already brings the most along
    base, ini = board_envs[f"companion_{base_conn}"]
    extra = []
    if "usb" in conns and base_conn != "usb":
        extra += ["-D ENABLE_USB_INTERFACE", "-UBLE_DEBUG_LOGGING", "-UWIFI_DEBUG_LOGGING"]   # their debug text would garble the USB link
    if "wifi" in conns and base_conn != "wifi":
        extra += [f"-D WIFI_SSID='\"{ssid}\"'", f"-D WIFI_PWD='\"{pwd}\"'"]

    def make(text):
        if "wifi" in conns and base_conn == "wifi": text = with_wifi(text, base, ssid, pwd)
        if not extra: return text
        flags = "\n".join("  " + f for f in extra)
        return text.rstrip("\n") + f"\n\n[env:{CUSTOM_ENV}]\nextends = env:{base}\nbuild_flags =\n  ${{env:{base}.build_flags}}\n{flags}\n"
    return (CUSTOM_ENV if extra else base), ini, make


# The observer firmware sends what it hears to LetsMesh (two slots) as soon as it has Wi-Fi.  mcIRC builds it with every slot off:
# nothing is reported until you pick your area's analyzer yourself (set mqtt1.preset <name>, set mqtt.iata <code>).
OBSERVER_QUIET = [f"-D MQTT_DEFAULT_SLOT{n}_PRESET='\"none\"'" for n in range(1, 7)]


def _custom(text, base, flags):
    """The ini text plus an env that extends `base` with extra build flags."""
    lines = "\n".join("  " + f for f in flags)
    return text.rstrip("\n") + f"\n\n[env:{CUSTOM_ENV}]\nextends = env:{base}\nbuild_flags =\n  ${{env:{base}.build_flags}}\n{lines}\n"


def with_wifi(ini_text, env, ssid, pwd):
    """The platformio.ini text with this env's WIFI_SSID / WIFI_PWD set (other envs untouched)."""
    start = ini_text.index(f"[env:{env}]")
    nxt = ini_text.find("\n[", start + 1)
    end = len(ini_text) if nxt == -1 else nxt
    sec = ini_text[start:end]
    sec = re.sub(r"-D WIFI_SSID='\"[^\"]*\"'", lambda m: f"-D WIFI_SSID='\"{ssid}\"'", sec)
    sec = re.sub(r"-D WIFI_PWD='\"[^\"]*\"'", lambda m: f"-D WIFI_PWD='\"{pwd}\"'", sec)
    return ini_text[:start] + sec + ini_text[end:]


def arch(board_envs):
    """'esp32', 'nrf52' or 'other' - from the board's platformio.ini (its base section extends esp32_base / nrf52_base)."""
    for env, ini in board_envs.values():
        try:
            with open(ini, encoding="utf-8", errors="replace") as f: text = f.read()
        except OSError:
            continue
        if "esp32_base" in text: return "esp32"
        if "nrf52_base" in text: return "nrf52"
    return "other"


def wifi_ota_ok(board_envs, kind):
    """Update over Wi-Fi (MeshCore's 'start ota') is for ESP32 boards running a firmware with MeshCore's command line."""
    return kind in WIFI_OTA_KINDS and arch(board_envs) == "esp32"


def best_board(names, model="heltec v3"):
    key = re.sub(r"[^a-z0-9]+", "_", (model or "").lower()).strip("_")
    return next((b for b in names if b.lower() == key), next(iter(names), None))


AFTER = {k: f"A {v} is set up through its USB command line: open config.meshcore.dev in Chrome or Edge with the board on USB and set its name, "
             "admin password and radio there (or MeshCore's CLI over USB: set name ..., set password ..., set radio ..., reboot)."
         for k, v in (("repeater", "repeater"), ("room_server", "room server"), ("sensor", "sensor"), ("bridge_espnow", "repeater bridge"),
                      ("bridge_rs232", "repeater bridge"))}
for _k in ("observer", "observer_room"):
    AFTER[_k] = ("An observer is set up over USB like a repeater (name, admin password, radio), plus its Wi-Fi and your 3-letter area code "
                 "(the nearest airport's IATA code) - from its serial console, or 'start webconfig' for a web page. mcIRC built it with NO "
                 "analyzer switched on, so it reports nothing until you pick yours: 'get mqtt.presets' lists them, then e.g. "
                 "'set mqtt1.preset analyzer-eu', 'set mqtt.iata LHR', 'set wifi.ssid ...', 'set wifi.pwd ...', 'reboot'. "
                 "Community firmware: it repeats like a repeater and also sends what it hears to the analyzers you pick.")
AFTER["terminal_chat"] = "Terminal chat: open the board's USB port in a serial terminal (115200 baud) and type 'help'."
AFTER["kiss_modem"] = "KISS modem: point your KISS software at the board's USB port (115200 baud)."


# ---- the Wi-Fi page: press and hold switches Wi-Fi on or off (companion builds with Wi-Fi) ----
WIFI_PAGE_MARK = "mcIRC: Wi-Fi page"
_UI_EDITS = [   # (anchor, text put before it) in examples/companion_radio/ui-new/UITask.cpp
    ("    ADVERT,\n", "#ifdef WIFI_SSID\n    WIFI_PAGE,   // " + WIFI_PAGE_MARK + "\n#endif\n"),
    ("    } else if (_page == HomePage::ADVERT) {\n",
     "#ifdef WIFI_SSID\n"
     "    } else if (_page == HomePage::WIFI_PAGE) {   // " + WIFI_PAGE_MARK + ": on / off, and the address\n"
     "      display.setColor(UIColor::primary_txt);\n"
     "      display.setTextSize(2);\n"
     "      display.drawTextCentered(display.width() / 2, 20, mcirc_wifi_off ? \"Wi-Fi OFF\" : \"Wi-Fi ON\");\n"
     "      display.setTextSize(1);\n"
     "      if (!mcirc_wifi_off) {\n"
     "        IPAddress ip = WiFi.localIP();\n"
     "        if (WiFi.status() == WL_CONNECTED) snprintf(tmp, sizeof(tmp), \"IP: %d.%d.%d.%d\", ip[0], ip[1], ip[2], ip[3]);\n"
     "        else snprintf(tmp, sizeof(tmp), \"joining Wi-Fi...\");\n"
     "        display.drawTextCentered(display.width() / 2, 40, tmp);\n"
     "      }\n"
     "      display.setColor(UIColor::secondary_txt);\n"
     "      display.drawTextCentered(display.width() / 2, 64 - 11, \"toggle: \" PRESS_LABEL);\n"
     "#endif\n"),
    ("    if (c == KEY_ENTER && _page == HomePage::ADVERT) {\n",
     "#ifdef WIFI_SSID\n"
     "    if (c == KEY_ENTER && _page == HomePage::WIFI_PAGE) {   // " + WIFI_PAGE_MARK + ": press and hold switches Wi-Fi\n"
     "      mcirc_wifi_off = !mcirc_wifi_off;\n"
     "      if (mcirc_wifi_off) { WiFi.disconnect(true); WiFi.mode(WIFI_OFF); _task->showAlert(\"Wi-Fi off\", 1000); }\n"
     "      else { WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PWD); _task->showAlert(\"Wi-Fi on\", 1000); }\n"
     "      return true;\n"
     "    }\n"
     "#endif\n"),
]
_UI_INCLUDE = ("  #include <WiFi.h>\n", "  extern bool mcirc_wifi_off;   // " + WIFI_PAGE_MARK + " (main.cpp)\n")         # (put after the anchor)
_MAIN_EDITS = [   # examples/companion_radio/main.cpp
    ("  bool wifi_needs_reconnect = false;\n", "  bool mcirc_wifi_off = false;   // " + WIFI_PAGE_MARK + ": switched off there - no automatic reconnect\n", "after"),
    ("  if (wifi_needs_reconnect && (millis()", "  if (wifi_needs_reconnect && !mcirc_wifi_off && (millis()", "replace"),
]


def add_wifi_page(src):
    """Adds the Wi-Fi page to the companion firmware's screen menu in the unpacked source `src`: it shows Wi-Fi ON / OFF and the address;
    press and hold switches Wi-Fi off or back on (until the next restart).  Only in builds with Wi-Fi (#ifdef WIFI_SSID).  Done once;
    -> True when the source has it, False when this MeshCore version doesn't look as expected (then the build goes ahead without it)."""
    import os
    ui = os.path.join(src, "examples", "companion_radio", "ui-new", "UITask.cpp")
    main = os.path.join(src, "examples", "companion_radio", "main.cpp")
    try:
        with open(ui, encoding="utf-8") as f: u = f.read()
        with open(main, encoding="utf-8") as f: m = f.read()
    except OSError:
        return False
    if WIFI_PAGE_MARK in u and WIFI_PAGE_MARK in m: return True
    if any(u.count(a) != 1 for a, _ in _UI_EDITS) or u.count(_UI_INCLUDE[0]) != 1 or any(m.count(a) != 1 for a, _, _ in _MAIN_EDITS):
        return False
    for anchor, text in _UI_EDITS: u = u.replace(anchor, text + anchor)
    u = u.replace(_UI_INCLUDE[0], _UI_INCLUDE[0] + _UI_INCLUDE[1])
    for anchor, text, how in _MAIN_EDITS: m = m.replace(anchor, anchor + text if how == "after" else text)
    with open(ui, "w", encoding="utf-8", newline="") as f: f.write(u)
    with open(main, "w", encoding="utf-8", newline="") as f: f.write(m)
    return True
