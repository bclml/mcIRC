"""Tool 9 - Wi-Fi firmware: build MeshCore's companion firmware with YOUR Wi-Fi name and password in it (MeshCore publishes no ready-made Wi-Fi
files, the Wi-Fi details are compiled in), flash it over USB, find the board's IP address, and add it to Options > More nodes.
Needs PlatformIO.  The Wi-Fi password is only written into the build's settings file for the build and put back right after; it is never saved
by mcIRC.  (It does end up inside the firmware itself - that is how MeshCore's Wi-Fi firmware works.)"""
import io as _io
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import zipfile
from tkinter import messagebox, ttk

import meshcore_io as io
from ntools_common import BG, MONO, ToolWindow

BUILD_ROOT = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "mcIRC", "firmware-build")      # not in OneDrive: builds are big
ENV_RE = re.compile(r"^\[env:([A-Za-z0-9_\-]+_companion_radio_wifi)\]\s*$", re.M)
IP_RE = re.compile(r"\b((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})\b")


def find_pio():
    """The PlatformIO command, or None."""
    p = shutil.which("pio") or shutil.which("platformio")
    if p: return [p]
    home = os.path.join(os.path.expanduser("~"), ".platformio", "penv", "Scripts" if os.name == "nt" else "bin", "pio" + (".exe" if os.name == "nt" else ""))
    if os.path.exists(home): return [home]
    try:
        import importlib.util
        if importlib.util.find_spec("platformio"): return [sys.executable, "-m", "platformio"]
    except Exception:
        pass
    return None


def source_dir(tag):
    return os.path.join(BUILD_ROOT, f"MeshCore-{tag}")


def get_source(tag, log=print):
    """Downloads and unpacks MeshCore's source for a release tag (once; later builds reuse it)."""
    d = source_dir(tag)
    if os.path.exists(os.path.join(d, "platformio.ini")): return d
    os.makedirs(BUILD_ROOT, exist_ok=True)
    url = f"https://github.com/meshcore-dev/MeshCore/archive/refs/tags/{tag}.zip"
    log(f"Downloading the MeshCore source ({tag})...\n")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mcIRC"}), timeout=180) as r: data = r.read()
    with zipfile.ZipFile(_io.BytesIO(data)) as z:
        top = z.namelist()[0].split("/")[0]
        z.extractall(BUILD_ROOT)
    if os.path.abspath(os.path.join(BUILD_ROOT, top)) != os.path.abspath(d): os.replace(os.path.join(BUILD_ROOT, top), d)
    return d


def wifi_envs(src):
    """{env name: platformio.ini path} for every board with a Wi-Fi companion build."""
    out = {}
    for root, _, files in os.walk(os.path.join(src, "variants")):
        if "platformio.ini" in files:
            p = os.path.join(root, "platformio.ini")
            with open(p, encoding="utf-8", errors="replace") as f:
                for m in ENV_RE.finditer(f.read()): out[m.group(1)] = p
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def check_wifi_text(s, what):
    if not s: raise ValueError(f"the Wi-Fi {what} is empty")
    if any(c in s for c in "\"'\\\n\r"): raise ValueError(f"the Wi-Fi {what} contains a quote or backslash - MeshCore's build can't take those")
    return s


def with_wifi(ini_text, env, ssid, pwd):
    """The platformio.ini text with this env's WIFI_SSID / WIFI_PWD set (other envs untouched)."""
    start = ini_text.index(f"[env:{env}]")
    nxt = ini_text.find("\n[", start + 1)
    end = len(ini_text) if nxt == -1 else nxt
    sec = ini_text[start:end]
    sec = re.sub(r"-D WIFI_SSID='\"[^\"]*\"'", lambda m: f"-D WIFI_SSID='\"{ssid}\"'", sec)
    sec = re.sub(r"-D WIFI_PWD='\"[^\"]*\"'", lambda m: f"-D WIFI_PWD='\"{pwd}\"'", sec)
    return ini_text[:start] + sec + ini_text[end:]


def read_ip(port, seconds=30):
    """Listens to the board's start-up messages and returns the IP address it prints when it joins the Wi-Fi (or None)."""
    import gui_seriallines  # noqa: F401  - opens the port without holding the board's button
    import serial
    t0 = time.time()
    while True:                                                             # the port may need a moment to come back after a restart
        try:
            s = serial.serial_for_url(port, baudrate=115200, timeout=0.3)
            break
        except (serial.SerialException, OSError):
            if time.time() - t0 > seconds: return None
            time.sleep(1)
    buf = ""
    try:
        while time.time() - t0 < seconds:
            buf += s.read(2048).decode("utf-8", "replace")
            for ip in IP_RE.findall(buf):
                if not ip.startswith(("0.", "255.", "127.")): return ip
    finally:
        s.close()
    return None


def port_ids():
    """{port: hardware id} of the serial ports on this PC."""
    try:
        import serial.tools.list_ports as lp
        return {p.device: p.hwid or "" for p in lp.comports()}
    except Exception:
        return {}


def needs_boot_buttons(hwid):
    """True for a board whose USB port is made by its running firmware (ESP32-S2/S3 'TinyUSB', e.g. Heltec V4 with MeshCore):
    the flasher can't switch it to download mode, the PRG/BOOT + RST buttons must."""
    return "303A:0002" in (hwid or "").upper()


MAC_RE = re.compile(r"\bMAC:\s*([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})")


ARP_MAC_RE = re.compile(r"\b([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})\b")


def mac_key(mac):
    """'90:70:69:84:9a:44', '90-70-69-84-9A-44' and macOS's '90:70:69:84:9a:4' style (no leading zeros) -> one comparable form."""
    parts = re.split(r"[:-]", (mac or "").strip())
    try: return tuple(int(p, 16) for p in parts) if len(parts) == 6 else None
    except ValueError: return None


def parse_neighbours(text):
    """[(ip, mac_key)] from `arp -a` (Windows '  192.168.1.39  90-70-69-84-9a-44  dynamic', Linux/macOS '? (192.168.1.39) at 90:70:...')
    or `ip neigh` ('192.168.1.39 dev wlan0 lladdr 90:70:...')."""
    out = []
    for line in (text or "").splitlines():
        ip, m = IP_RE.search(line), ARP_MAC_RE.search(line)
        if ip and m and mac_key(m.group(1)): out.append((ip.group(1), mac_key(m.group(1))))
    return out


def neighbours():
    """This PC's ARP table (the addresses it has talked to on the local network)."""
    for cmd in (["arp", "-a"], ["arp", "-an"], ["ip", "neigh"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=io.NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        found = parse_neighbours(r.stdout)
        if found: return found
    return []


def find_on_lan(mac, seconds=180, port=5000, log=print):
    """MeshCore's Wi-Fi firmware does not print its IP address, so look for the board on this PC's network: knock on port `port` of every
    address of the local /24 networks (that also fills the PC's ARP table) and match the board's MAC (printed by the flasher)."""
    import concurrent.futures as cf
    import socket
    want = mac_key(mac)
    def local_nets():
        nets = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                nets.add(info[4][0])
        except OSError:
            pass
        try:                                                    # the address this PC goes out with (Linux often names itself 127.0.1.1)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
                u.connect(("192.0.2.1", 9))                     # UDP: nothing is sent
                nets.add(u.getsockname()[0])
        except OSError:
            pass
        return sorted({ip.rsplit(".", 1)[0] for ip in nets if not ip.startswith(("127.", "169.254.", "0."))})
    def knock(ip):
        s = socket.socket()
        s.settimeout(0.5)
        try: s.connect((ip, port)); return ip
        except OSError: return None
        finally: s.close()
    t0 = time.time()
    while time.time() - t0 < seconds:
        open_ = []
        with cf.ThreadPoolExecutor(64) as ex:
            for net in local_nets(): open_ += [r for r in ex.map(knock, [f"{net}.{i}" for i in range(1, 255)]) if r]
        for ip, m in neighbours():
            if want and m == want and ip in open_: return ip
        log(".")
        time.sleep(5)
    return None


def best_env(envs, model):
    key = re.sub(r"[^a-z0-9]+", "_", (model or "heltec v3").lower()).strip("_")
    return next((e for e in envs if e.lower().startswith(key + "_companion")), next(iter(envs), None))


class WifiFirmwareWindow(ToolWindow):
    def __init__(self, api):
        super().__init__(api, "Wi-Fi firmware", "760x620", choose_node=False)
        self.pio = find_pio()
        f = tk.Frame(self, bg=BG)
        f.pack(fill="x", padx=10, pady=8)
        tk.Label(f, bg=BG, justify="left", wraplength=720, text=(
            "Builds MeshCore's companion firmware for Wi-Fi with your network's name and password in it, flashes it to a board on USB, finds "
            "its IP address and adds it to Options > More nodes. The first build downloads PlatformIO's ESP32 tools and takes several minutes.")).grid(row=0, column=0, columnspan=4, sticky="w")
        self.v = {k: tk.StringVar(value=v) for k, v in (("ver", ""), ("env", ""), ("port", ""), ("ssid", ""), ("pwd", ""), ("label", "wifi"), ("freq", ""), ("bw", ""), ("sf", ""), ("cr", ""))}
        self.erase = tk.BooleanVar(value=True)
        rows = (("Firmware version:", "ver"), ("Board:", "env"), ("USB port:", "port"), ("Wi-Fi name:", "ssid"), ("Wi-Fi password:", "pwd"), ("Label in mcIRC:", "label"))
        for r, (label, key) in enumerate(rows, start=1):
            tk.Label(f, text=label, bg=BG).grid(row=r, column=0, sticky="w", pady=2)
            if key in ("ver", "env", "port"):
                w = ttk.Combobox(f, textvariable=self.v[key], width=44, state="readonly" if key == "ver" else "normal",
                                 postcommand=self.refresh_ports if key == "port" else None)          # the list is fresh each time it opens
                setattr(self, key + "_box", w)
            else:
                w = tk.Entry(f, textvariable=self.v[key], width=34, show="*" if key == "pwd" else "")
            w.grid(row=r, column=1, columnspan=3, sticky="w", pady=2)
        r = len(rows) + 1
        tk.Label(f, text="Radio (optional):", bg=BG).grid(row=r, column=0, sticky="w")
        rf = tk.Frame(f, bg=BG)
        rf.grid(row=r, column=1, columnspan=3, sticky="w")
        for label, key, w in (("MHz", "freq", 8), ("BW kHz", "bw", 6), ("SF", "sf", 3), ("CR", "cr", 3)):
            tk.Entry(rf, textvariable=self.v[key], width=w).pack(side="left")
            tk.Label(rf, text=label + "  ", bg=BG).pack(side="left")
        tk.Checkbutton(f, text="Erase the board first (recommended when it runs other firmware - it resets the board's settings)", variable=self.erase,
                       bg=BG).grid(row=r + 1, column=0, columnspan=4, sticky="w")
        b = tk.Frame(self, bg=BG)
        b.pack(fill="x", padx=10)
        self.go_btn = ttk.Button(b, text="Build and flash", command=self.go)
        self.go_btn.pack(side="left")
        self.add_btn = ttk.Button(b, text="Add to More nodes", command=self.add_node, state="disabled")
        self.add_btn.pack(side="left", padx=6)
        self.out = tk.Text(self, font=MONO, bg="#101010", fg="#d0ffd0", height=16)
        self.out.pack(fill="both", expand=True, padx=10, pady=8)
        self.ip = None
        self.refresh_ports()
        if not self.pio:
            self.write("PlatformIO is not installed. Install it (pip install platformio, or the VS Code PlatformIO extension), then reopen this window.\n")
            self.go_btn.config(state="disabled")
        else:
            self.ver_box.bind("<<ComboboxSelected>>", lambda e: self.load_boards())
            self.load_versions()

    def write(self, text):
        self.api.ui()["root"].after(0, lambda: self.winfo_exists() and (self.out.insert("end", text), self.out.see("end")))

    def refresh_ports(self):
        try:
            import serial.tools.list_ports as lp
            ports = [p.device for p in lp.comports()]
        except Exception:
            ports = []
        self.port_box.config(values=ports)

    def load_versions(self):
        import ntools_firmware
        def done(rels):
            self.ver_box.config(values=[v for v, _, _ in rels])
            self.v["ver"].set(rels[0][0])                                      # the newest is preselected
            self.load_boards()
        self.job("Listing MeshCore releases", ntools_firmware.companion_releases, done, need_radio=False)

    def load_boards(self):
        tag = "companion-" + self.v["ver"].get()
        self.envs = {}
        self.go_btn.config(state="disabled")
        def done(envs):
            self.tag, self.envs = tag, envs
            self.go_btn.config(state="normal")
            self.env_box.config(values=list(self.envs))
            if self.v["env"].get() not in self.envs: self.v["env"].set(best_env(self.envs, "Heltec V3") or "")
            self.write(f"{len(self.envs)} boards have a Wi-Fi build in {self.tag}.\n")
        self.job(f"Getting the MeshCore source ({tag})", lambda: wifi_envs(get_source(tag, self.write)), done, need_radio=False)

    def go(self):
        env, port = self.v["env"].get().strip(), self.v["port"].get().strip()
        try:
            ssid, pwd = check_wifi_text(self.v["ssid"].get(), "name"), check_wifi_text(self.v["pwd"].get(), "password")
        except ValueError as e:
            return messagebox.showerror("Wi-Fi firmware", str(e), parent=self)
        if env not in getattr(self, "envs", {}) or not port: return messagebox.showerror("Wi-Fi firmware", "Choose the board and its USB port.", parent=self)
        radio = [self.v[k].get().strip() for k in ("freq", "bw", "sf", "cr")]
        if any(radio) and not all(radio): return messagebox.showerror("Wi-Fi firmware", "Fill in all four radio values, or none.", parent=self)
        ids = port_ids()
        if needs_boot_buttons(ids.get(port)):
            return messagebox.showinfo("Wi-Fi firmware", f"The board on {port} has to be put in download mode by hand first:\n\n"
                                       "hold its PRG (BOOT) button, tap RST, let go of PRG.\n\nIt then shows up on a new USB port - choose that one "
                                       "in 'USB port' and press Build and flash again.", parent=self)
        if not messagebox.askyesno("Wi-Fi firmware", f"Flash {env} to the board on {port}?" + ("\nThe board is erased first (its settings are reset)." if self.erase.get() else "")
                                   + "\n\nDon't unplug it until this says it is done.", parent=self): return
        if io.CONNECTION_ARGS and io.CONNECTION_ARGS[:2] == ["-s", port]: self.api.disconnect()        # mcIRC must let go of that port
        ini_path, erase = self.envs[env], self.erase.get()
        def work():
            mac = None
            with open(ini_path, encoding="utf-8") as f: original = f.read()
            try:
                with open(ini_path, "w", encoding="utf-8") as f: f.write(with_wifi(original, env, ssid, pwd))
                for target in (["erase"] if erase else []) + ["upload"]:
                    self.write(f"\n== pio run -e {env} -t {target} --upload-port {port}\n")
                    p = subprocess.Popen(self.pio + ["run", "-e", env, "-t", target, "--upload-port", port], cwd=source_dir(self.tag),
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", creationflags=io.NO_WINDOW)
                    for line in p.stdout:
                        self.write(line)
                        m = MAC_RE.search(line)
                        if m: mac = m.group(1)                                  # the board's address on the Wi-Fi, used to find it below
                    if p.wait() != 0:
                        self.write("\nIf it could not open or connect to the port: hold PRG (BOOT), tap RST, let go of PRG, choose the board's "
                                   "(new) USB port and press Build and flash again.\n")
                        raise RuntimeError(f"PlatformIO stopped ({target}) - see above")
            finally:
                with open(ini_path, "w", encoding="utf-8") as f: f.write(original)      # the password is not left in the build files
            self.write("\nFlashed. If the board doesn't restart by itself (boards like the Heltec V4), tap its RST button now.\n"
                       f"Looking for it on your network{' (' + mac + ')' if mac else ''} - joining the Wi-Fi can take a couple of minutes")
            ip = find_on_lan(mac, seconds=240, log=self.write) if mac else None
            if ip and all(radio):                                               # the Wi-Fi firmware is controlled over Wi-Fi, not USB
                self.write(f"\nSetting the radio: {','.join(radio)} MHz/kHz/SF/CR\n")
                io.execute_mesh_command(["-t", ip, "-p", "5000", "set", "radio", ",".join(radio)], timeout=40, retries=2, lock=io._MeshLock())
                io.execute_mesh_command(["-t", ip, "-p", "5000", "reboot"], timeout=20, retries=0, lock=io._MeshLock())
            return ip
        def done(ip):
            self.ip = ip
            if ip:
                self.write(f"\nThe board is on your Wi-Fi at {ip} (port 5000). Give it a fixed address in your router so it keeps it.\n")
                self.add_btn.config(state="normal")
            else:
                self.write("\nFlashed, but the board was not found on this PC's network. Check your router's client list for an 'esp32s3' / Espressif "
                           "device (a guest Wi-Fi is usually kept apart from your PC), then add it in Options > More nodes (Wi-Fi, port 5000).\n")
        self.job("Building and flashing (several minutes the first time)", work, done, need_radio=False)

    def add_node(self):
        if not self.ip: return
        label = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9._ -]", "", self.v["label"].get())).strip()[:12].strip() or "wifi"
        self.api.add_extra_node({"label": label, "mode": "tcp", "host": self.ip, "tcp_port": 5000, "enabled": True})
        self.say(f"Added '{label}' ({self.ip}) to Options > More nodes - it connects with the main node.")
        self.add_btn.config(state="disabled")
