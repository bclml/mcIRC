"""Firmware builder: which MeshCore build to make for a board - a companion with any mix of USB, Bluetooth and Wi-Fi (all of them waiting,
one used at a time: MeshCore's MultiSerialInterface), a repeater, a room server or a sensor."""
import os
import re

ENV_LINE = re.compile(r"^\[env:([A-Za-z0-9_\-]+)\]\s*$", re.M)
KINDS = {"companion_radio_usb": ("companion", "usb"), "companion_radio_ble": ("companion", "ble"), "companion_radio_wifi": ("companion", "wifi"),
         "repeater": ("repeater", None), "room_server": ("room_server", None), "sensor": ("sensor", None)}
TYPE_TITLES = {"companion": "Companion (for chatting: mcIRC, the phone apps)", "repeater": "Repeater", "room_server": "Room server", "sensor": "Sensor"}
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


def with_wifi(ini_text, env, ssid, pwd):
    """The platformio.ini text with this env's WIFI_SSID / WIFI_PWD set (other envs untouched)."""
    start = ini_text.index(f"[env:{env}]")
    nxt = ini_text.find("\n[", start + 1)
    end = len(ini_text) if nxt == -1 else nxt
    sec = ini_text[start:end]
    sec = re.sub(r"-D WIFI_SSID='\"[^\"]*\"'", lambda m: f"-D WIFI_SSID='\"{ssid}\"'", sec)
    sec = re.sub(r"-D WIFI_PWD='\"[^\"]*\"'", lambda m: f"-D WIFI_PWD='\"{pwd}\"'", sec)
    return ini_text[:start] + sec + ini_text[end:]


def best_board(names, model="heltec v3"):
    key = re.sub(r"[^a-z0-9]+", "_", (model or "").lower()).strip("_")
    return next((b for b in names if b.lower() == key), next(iter(names), None))


AFTER = {k: f"A {v} is set up through its USB command line: open config.meshcore.dev in Chrome or Edge with the board on USB and set its name, "
             "admin password and radio there (or MeshCore's CLI over USB: set name ..., set password ..., set radio ..., reboot)."
         for k, v in (("repeater", "repeater"), ("room_server", "room server"), ("sensor", "sensor"))}
