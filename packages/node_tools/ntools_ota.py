"""Over-the-air updates for the Firmware builder.

* OTAFIX bootloader (nRF52 boards: RAK4631, T1000-E, T-Echo, Xiao nRF52, ...): oltaco's fork of the Adafruit nRF52 bootloader, recommended by
  MeshCore for over-the-air (Bluetooth DFU) updates - faster, and a failed update falls back to update mode instead of bricking the node.
  Installed by copying its update-*.uf2 file onto the board's UF2 drive (double-press reset).  The files are pinned: one release, each file
  checked against its SHA-256 before it is used.
* Wi-Fi OTA (ESP32 repeaters, room servers, sensors, observers): MeshCore's own 'start ota' (the node opens the MeshCore-OTA Wi-Fi with an
  ElegantOTA page at http://192.168.4.1/update); this uploads a built firmware.bin to it - the same as that page does."""
import hashlib
import http.client
import json
import os
import string
import time
import sys
import urllib.request

OTAFIX_REPO = "oltaco/Adafruit_nRF52_Bootloader_OTAFIX"
OTAFIX_TAG = "0.9.2-OTAFIX2.3-BP1.4"
# Board-ID (INFO_UF2.TXT on the board's UF2 drive) -> (file name part, SHA-256 of update-<part>_bootloader-<tag>_nosd.uf2)
OTAFIX_FILES = {
    "Heltec-T096-v1": ("heltec_t096", "9024a960a07c99edc2d50f4b49b88871dff91dd2db535b59e6b5d4f02ace6059"),
    "HT-n5262": ("heltec_t114", "c689f755caccbbddb4dd0804d5dec5bd5e28e424908a055fd63af09eb85e0fc9"),
    "Heltec-T1": ("heltec_t1", "bab08d20022ed01d36e9aecf63bf8aa77d9f9dd45bd2904a837c473d17b0a807"),
    "nRF52840-TEcho-v1": ("lilygo_techo", "4a0435291eb058abf7dd266e6f39d476a8ebf9968b8aa5d9d4234a00f246815d"),
    "MinewSemi-MX25LE01": ("minewsemi_mx25le01", "0d587c5a590942ceb5c558f62dbffed4e9b52ae8cac31a200d9cdf0a177eaa06"),
    "nRF52840-promicro": ("promicro_nrf52840", "1d025dd26fe48ef295795218eb7a62b34a21f4232d5d17aed975c695303dc8ce"),
    "nRF52840-SeeedSenseCAPSolarP1-v1": ("sensecap_solar_p1", "7c2e88dda0568f47824a2a5b7660ac0ec238ef4bce8d3f34c95f5390dad552a2"),
    "nRF52840-T1000-E-v1": ("t1000_e", "200371714cf7fe39dfae233d750671acf438e110c96884c28f087acae5edaaba"),
    "nRF52840-ThinkNodeM1-v1": ("thinknode_m1", "bdc18e57427f15dc04f398d2d568b775f9e0fc051146f53c146d74b4f50e6f95"),
    "nRF52840-ThinkNode-M3-v1": ("thinknode_m3", "055ed7add8b71bf026141f1019493f18f390b1795112790369daae226c3ff328"),
    "nRF52840-ThinkNodeM6-v1": ("thinknode_m6", "508dcf4a92d7cc897a7481a0eb8c278ef356f837c62a5622728b9acf120989a3"),
    "TRACKER L1": ("wio_tracker_l1", "20ee551d33b3445a26ad3c96880fb483362dbbb8b4d5676703bb9c42db425970"),
    "WisBlock-RAK3401-Board": ("wiscore_rak3401", "33be1c0d7d28205a7d4609ccb8968a9a9408ed6dbec9ef745ded6e61397f28ea"),
    "WisBlock-RAK4631-Board": ("wiscore_rak4631_board", "7ba0897450a994230002f40c7da51669f80f60c6216f377d1f770f8af5ca3cad"),
    "WisMesh-Tag": ("wismesh_tag", "12eb14793e6cef2ffd90c41c64aa56ba55d48a61a9b961ccd5a8254a1e58737f"),
    "nRF52840-SeeedXiao-v1": ("xiao_nrf52840_ble", "97677d7815d7fe1f2600ff5c39f04c9d72bfc03e7f33e587e21b1bf7b30d04fa"),
    "nRF52840-SeeedXiaoSense-v1": ("xiao_nrf52840_ble_sense", "5aa99201f3adcc128e1ebdc7ea4b4ba8e370ededda13ad94942059da5a1617c4"),
}
OTA_HOST = "192.168.4.1"            # MeshCore's OTA access point (Wi-Fi 'MeshCore-OTA', no password)
OTA_SSID = "MeshCore-OTA"


# ---- OTAFIX bootloader (nRF52) ----
def uf2_drives():
    """Mounted UF2 drives (a board in its bootloader after a double-press of reset): [path]."""
    if os.name == "nt":
        import ctypes
        k32, mask = ctypes.windll.kernel32, ctypes.windll.kernel32.GetLogicalDrives()
        roots = [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase)
                 if mask >> i & 1 and i >= 2 and k32.GetDriveTypeW(f"{c}:\\") == 2]       # removable only: a lost network drive would hang the check
    else:
        user = os.environ.get("USER", "")
        bases = ["/Volumes"] if sys.platform == "darwin" else [f"/media/{user}", f"/run/media/{user}", "/media"]
        roots = [os.path.join(b, d) for b in bases if os.path.isdir(b) for d in os.listdir(b)]
    return [r for r in roots if os.path.isfile(os.path.join(r, "INFO_UF2.TXT"))]


def read_info(drive):
    """INFO_UF2.TXT -> {'bootloader': first line, 'model': ..., 'board_id': ...}."""
    with open(os.path.join(drive, "INFO_UF2.TXT"), encoding="utf-8", errors="replace") as f: return parse_info(f.read())


def parse_info(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = {"bootloader": lines[0] if lines else "", "model": "", "board_id": ""}
    for l in lines[1:]:
        k, _, v = l.partition(":")
        if k.strip().lower() == "model": out["model"] = v.strip()
        elif k.strip().lower() == "board-id": out["board_id"] = v.strip()
    return out


def has_otafix(info): return "OTAFIX" in (info.get("bootloader") or "").upper()


def otafix_file(board_id):
    """-> (file name, url, sha256) of the OTAFIX update for this Board-ID, or None when OTAFIX has no build for it."""
    hit = OTAFIX_FILES.get(board_id)
    if not hit: return None
    name = f"update-{hit[0]}_bootloader-{OTAFIX_TAG}_nosd.uf2"
    return name, f"https://github.com/{OTAFIX_REPO}/releases/download/{OTAFIX_TAG}/{name}", hit[1]


def fetch_checked(url, sha256, timeout=60):
    """Downloads a file and refuses it unless its SHA-256 is the pinned one."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mcIRC"}), timeout=timeout) as r: data = r.read()
    if hashlib.sha256(data).hexdigest() != sha256: raise ValueError("the downloaded bootloader file is not the reviewed one (checksum differs) - not installed")
    return data


def install_otafix(drive, log=print, fetch=fetch_checked):
    """Copies the OTAFIX bootloader onto a UF2 drive.  -> 'installed' | 'already' ; ValueError when the board has no OTAFIX build."""
    info = read_info(drive)
    if has_otafix(info):
        log(f"The board already has the OTAFIX bootloader ({info['bootloader']}).\n")
        return "already"
    f = otafix_file(info["board_id"])
    if f is None: raise ValueError(f"OTAFIX has no bootloader for this board (Board-ID '{info['board_id'] or '?'}', {info['model'] or 'unknown model'})")
    name, url, sha = f
    log(f"Downloading the OTAFIX bootloader for {info['model'] or info['board_id']} ({name})...\n")
    data = fetch(url, sha)
    log(f"Copying it to the board ({drive}) - it installs and restarts by itself...\n")
    try:
        with open(os.path.join(drive, name), "wb") as out: out.write(data)
    except OSError:
        pass                                    # the board restarts as soon as the copy is complete; the drive can vanish before the file is closed
    return "installed"


# ---- Wi-Fi OTA (ESP32) ----
def firmware_bin(src, env):
    """The firmware.bin PlatformIO built for env (the application only - what OTA takes; never the -merged file)."""
    return os.path.join(src, ".pio", "build", env, "firmware.bin")


def ota_identity(host=OTA_HOST, timeout=6):
    """The node waiting in OTA mode: {'id': 'name (maker)', 'hardware': 'ESP32'}."""
    c = http.client.HTTPConnection(host, 80, timeout=timeout)
    try:
        c.request("GET", "/update/identity")
        r = c.getresponse()
        if r.status != 200: raise OSError(f"the node answered {r.status}")
        return json.loads(r.read().decode("utf-8", "replace"))
    finally:
        c.close()


def multipart(data, md5, boundary="----mcIRCota7f3a"):
    """The upload body ElegantOTA expects: the MD5 field first, then the file."""
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"MD5\"\r\n\r\n{md5}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"firmware\"; filename=\"firmware.bin\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def ota_upload(path, host=OTA_HOST, progress=None, timeout=120, chunk=8192):
    """Sends firmware.bin to the node's OTA page.  -> the node's answer ('OK'); it restarts with the new firmware."""
    with open(path, "rb") as f: data = f.read()
    body, ctype = multipart(data, hashlib.md5(data).hexdigest())
    c = http.client.HTTPConnection(host, 80, timeout=timeout)
    try:
        c.putrequest("POST", "/update")
        c.putheader("Content-Type", ctype)
        c.putheader("Content-Length", str(len(body)))
        c.endheaders()
        for i in range(0, len(body), chunk):
            c.send(body[i:i + chunk])
            if progress: progress(min(len(body), i + chunk), len(body))
        r = c.getresponse()
        answer = r.read().decode("utf-8", "replace").strip()
        if r.status != 200: raise OSError(f"the node refused the firmware ({r.status}: {answer})")
        return answer
    finally:
        c.close()


# ---- first setup after flashing (repeater, room server, sensor, observer, bridges: MeshCore's command line over USB) ----
CLI_KINDS = {"repeater", "room_server", "sensor", "observer", "observer_room", "bridge_espnow", "bridge_rs232"}


def check_setup(name, password, lat, lon, cli=True):
    """Checks the setup fields; -> (name, password, lat, lon) cleaned.  ValueError explains what is wrong."""
    name = (name or "").strip()
    if any(c in name for c in "\r\n") or len(name.encode("utf-8")) > 31: raise ValueError("the node name must be one line of at most 31 characters")
    password = password or ""
    if cli and password and (len(password) > 15 or any(c.isspace() for c in password)):
        raise ValueError("the admin password must be at most 15 characters, without spaces")
    out = []
    for v, lo, hi, what in ((lat, -90, 90, "latitude"), (lon, -180, 180, "longitude")):
        v = (v or "").strip()
        if v:
            try: f = float(v)
            except ValueError: raise ValueError(f"the {what} must be a number (e.g. 49.2827)")
            if not lo <= f <= hi: raise ValueError(f"the {what} must be between {lo} and {hi}")
        out.append(v)
    return name, password, out[0], out[1]


def setup_commands(name="", password="", radio=None, lat="", lon=""):
    """The command-line lines that set a freshly flashed repeater-type node up (the radio last: it needs the reboot at the end)."""
    cmds = []
    if name: cmds.append(f"set name {name}")
    if password: cmds.append(f"password {password}")
    if lat: cmds.append(f"set lat {lat}")
    if lon: cmds.append(f"set lon {lon}")
    if radio and all(radio): cmds.append("set radio " + ",".join(radio))
    if cmds: cmds.append("reboot")
    return cmds


def serial_cli(port, commands, log=print, boot_wait=6, opener=None):
    """Types commands into the node's USB command line (115200 baud, each line ended by a carriage return) and logs its answers.
    The admin password is never logged."""
    import gui_seriallines  # noqa: F401  - opens the port without holding the board's button
    import serial
    s = (opener or (lambda: serial.serial_for_url(port, baudrate=115200, timeout=0.3)))()
    try:
        time.sleep(boot_wait)                                           # let it finish starting after the flash
        s.read(8192)
        for cmd in commands:
            shown = "password ********" if cmd.startswith("password ") else cmd
            log(f"> {shown}\n")
            s.write((cmd + "\r").encode("utf-8"))
            time.sleep(1.5 if cmd != "reboot" else 0.5)
            answer = s.read(4096).decode("utf-8", "replace").strip()
            if answer and not cmd.startswith("password "): log(f"  {answer}\n")
    finally:
        s.close()
