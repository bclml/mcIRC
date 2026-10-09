"""Tool 9 - Firmware builder: build MeshCore firmware from its source - a companion with any mix of USB, Bluetooth and Wi-Fi (YOUR Wi-Fi name
and password compiled in: MeshCore publishes no ready-made Wi-Fi files), a repeater, a room server or a sensor - flash it over USB, find a
Wi-Fi board's IP address, and add it to Options > More nodes.
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
import ntools_fwbuild as fb
from ntools_fwsteps import OtaSteps
import ntools_ota as ota

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
    """tag: a MeshCore release tag ('companion-v1.17.1'), or the title of a community source (fb.COMMUNITY: a fork pinned to one commit)."""
    c = fb.COMMUNITY.get(tag)
    if c: return os.path.join(BUILD_ROOT, f"{c['repo'].replace('/', '-')}-{c['ref'][:10]}")
    return os.path.join(BUILD_ROOT, f"MeshCore-{tag}")


def source_url(tag):
    c = fb.COMMUNITY.get(tag)
    if c: return f"https://github.com/{c['repo']}/archive/{c['ref']}.zip"          # exactly the reviewed commit
    return f"https://github.com/meshcore-dev/MeshCore/archive/refs/tags/{tag}.zip"


def get_source(tag, log=print):
    """Downloads and unpacks the source of a MeshCore release tag or a community source (once; later builds reuse it)."""
    d = source_dir(tag)
    if os.path.exists(os.path.join(d, "platformio.ini")): return d
    os.makedirs(BUILD_ROOT, exist_ok=True)
    url = source_url(tag)
    log(f"Downloading the source ({tag})...\n")
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


class FirmwareBuilderWindow(ToolWindow, OtaSteps):
    """Firmware builder: a companion (any mix of USB, Bluetooth and Wi-Fi), a repeater, a room server or a sensor, built from MeshCore's
    source for the chosen release and flashed over USB."""
    def __init__(self, api):
        super().__init__(api, "Firmware builder", "820x860", choose_node=False)
        self.pio = find_pio()
        self.boards, self.tag, self.ip, self.flashed = {}, "", None, None
        f = tk.Frame(self, bg=BG)
        f.pack(fill="x", padx=10, pady=8)
        tk.Label(f, bg=BG, justify="left", wraplength=740, text=(
            "Builds MeshCore firmware from its source and flashes it to a board on USB. A companion can have USB, Bluetooth and Wi-Fi all "
            "waiting at once (one used at a time). The first build downloads PlatformIO's tools and takes several minutes.")).grid(row=0, column=0, columnspan=4, sticky="w")
        self.v = {k: tk.StringVar(value=v) for k, v in (("ver", ""), ("board", ""), ("port", ""), ("ssid", ""), ("pwd", ""), ("label", "node2"),
                                                          ("freq", ""), ("bw", ""), ("sf", ""), ("cr", ""), ("kind", "companion"))}
        self.conn = {c: tk.BooleanVar(value=(c == "wifi")) for c in ("usb", "ble", "wifi")}
        self.erase = tk.BooleanVar(value=True)
        r = 1
        for label, key in (("Firmware version:", "ver"), ("Board:", "board")):
            tk.Label(f, text=label, bg=BG).grid(row=r, column=0, sticky="w", pady=2)
            box = ttk.Combobox(f, textvariable=self.v[key], width=44, state="readonly")
            box.grid(row=r, column=1, columnspan=3, sticky="w", pady=2)
            setattr(self, key + "_box", box)
            r += 1
        tk.Label(f, text="Firmware:", bg=BG).grid(row=r, column=0, sticky="nw", pady=2)
        kf = tk.Frame(f, bg=BG); kf.grid(row=r, column=1, columnspan=3, sticky="w")
        self.kind_buttons = {}
        for k, title in fb.TYPE_TITLES.items():
            self.kind_buttons[k] = tk.Radiobutton(kf, text=title, value=k, variable=self.v["kind"], bg=BG, command=self.update_fields)
            self.kind_buttons[k].pack(anchor="w")
        r += 1
        tk.Label(f, text="Connections:", bg=BG).grid(row=r, column=0, sticky="w", pady=2)
        cf = tk.Frame(f, bg=BG); cf.grid(row=r, column=1, columnspan=3, sticky="w")
        self.conn_checks = {}
        for c, title in fb.CONN_TITLES.items():
            self.conn_checks[c] = tk.Checkbutton(cf, text=title, variable=self.conn[c], bg=BG, command=self.update_fields)
            self.conn_checks[c].pack(side="left", padx=(0, 10))
        tk.Label(cf, text="(all ticked ones wait on the node; one is used at a time)", bg=BG, fg="#555").pack(side="left")
        r += 1
        self.entries = {}
        for label, key in (("USB port:", "port"), ("Wi-Fi name:", "ssid"), ("Wi-Fi password:", "pwd"), ("Label in mcIRC:", "label")):
            tk.Label(f, text=label, bg=BG).grid(row=r, column=0, sticky="w", pady=2)
            if key == "port":
                w = ttk.Combobox(f, textvariable=self.v[key], width=44, postcommand=self.refresh_ports)
                self.port_box = w
            else:
                w = tk.Entry(f, textvariable=self.v[key], width=34, show="*" if key == "pwd" else "")
            w.grid(row=r, column=1, columnspan=3, sticky="w", pady=2)
            self.entries[key] = w
            r += 1
        tk.Label(f, text="Radio (optional):", bg=BG).grid(row=r, column=0, sticky="w")
        rf = tk.Frame(f, bg=BG); rf.grid(row=r, column=1, columnspan=3, sticky="w")
        for label, key, w in (("MHz", "freq", 8), ("BW kHz", "bw", 6), ("SF", "sf", 3), ("CR", "cr", 3)):
            tk.Entry(rf, textvariable=self.v[key], width=w).pack(side="left")
            tk.Label(rf, text=label + "  ", bg=BG).pack(side="left")
        tk.Checkbutton(f, text="Erase the board first (recommended when it runs other firmware - it resets the board's settings, channels and contacts)",
                       variable=self.erase, bg=BG).grid(row=r + 1, column=0, columnspan=4, sticky="w")
        self.ota_widgets(f, r + 2)
        self.setup_widgets(f, r + 3)
        b = tk.Frame(self, bg=BG); b.pack(fill="x", padx=10)
        self.go_btn = ttk.Button(b, text="Build and flash", command=self.go)
        self.go_btn.pack(side="left")
        self.add_btn = ttk.Button(b, text="Add to More nodes", command=self.add_node, state="disabled")
        self.add_btn.pack(side="left", padx=6)
        self.loading = ttk.Progressbar(b, mode="indeterminate", length=160)       # shown while the versions / boards are being fetched
        self.loading_text = tk.Label(b, bg=BG, fg="#555")
        self.out = tk.Text(self, font=MONO, bg="#101010", fg="#d0ffd0", height=14)
        self.out.pack(fill="both", expand=True, padx=10, pady=8)
        self.board_box.bind("<<ComboboxSelected>>", lambda e: self.update_fields())
        self.refresh_ports()
        self.update_fields()
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

    def update_fields(self):
        """Only what the choice needs: the connections for a companion (and only those the board has), the Wi-Fi details for Wi-Fi."""
        envs = self.boards.get(self.v["board"].get(), {})
        for k, rb in self.kind_buttons.items():
            rb.config(state="normal" if not envs or k in envs or (k == "companion" and fb.connections(envs)) else "disabled")
        companion = self.v["kind"].get() == "companion"
        have = fb.connections(envs) if envs else ["usb", "ble", "wifi"]
        for c, cb in self.conn_checks.items():
            cb.config(state="normal" if companion and c in have else "disabled")
            if c not in have: self.conn[c].set(False)
        wifi = companion and self.conn["wifi"].get()
        for key in ("ssid", "pwd"): self.entries[key].config(state="normal" if wifi else "disabled")
        self.update_ota_fields(envs, self.v["kind"].get())

    def source(self): return source_dir(self.tag)

    LOADING_VERSIONS, LOADING_BOARDS = "Loading the firmware list...", "Loading the boards..."

    def show_loading(self, what, boxes):
        """'Loading...' in the lists being fetched and a moving bar next to the buttons, until the fetch is over (done or failed)."""
        var = lambda box: self.v["ver" if box is self.ver_box else "board"]
        for box, text in boxes:
            box.config(state="disabled"); var(box).set(text)
        self.loading_text.config(text=what)
        self.loading.pack(side="left", padx=(16, 6)); self.loading_text.pack(side="left")
        self.loading.start(12)
        def watch():
            if not self.winfo_exists(): return
            if self.busy: return self.after(200, watch)
            self.loading.stop(); self.loading.pack_forget(); self.loading_text.pack_forget()
            for box, text in boxes:
                box.config(state="readonly")
                if var(box).get() == text: var(box).set("")                       # the fetch failed: no 'Loading...' left behind
        self.after(200, watch)

    def load_versions(self):
        import ntools_firmware
        def done(rels):
            self.ver_box.config(values=[v for v, _, _ in rels] + list(fb.COMMUNITY))      # community sources (observer) after the releases
            self.v["ver"].set(rels[0][0])                                      # the newest is preselected
            self.load_boards()
        self.job("Listing MeshCore releases", ntools_firmware.companion_releases, done, need_radio=False)
        if self.busy: self.show_loading(self.LOADING_VERSIONS, [(self.ver_box, self.LOADING_VERSIONS), (self.board_box, self.LOADING_BOARDS)])

    def load_boards(self):
        ver = self.v["ver"].get()
        tag = ver if ver in fb.COMMUNITY else "companion-" + ver
        self.go_btn.config(state="disabled")
        before = self.v["board"].get()                                          # kept when the new version has that board too
        def done(found):
            self.tag, self.boards = tag, found
            self.go_btn.config(state="normal")
            self.board_box.config(values=list(found))
            self.v["board"].set(before if before in found else fb.best_board(found, "Heltec v3") or "")
            self.update_fields()
            self.write(f"{len(found)} boards in MeshCore {self.tag}.\n")
        self.job(f"Getting the MeshCore source ({tag})", lambda: fb.boards(get_source(tag, self.write)), done, need_radio=False)
        if self.busy: self.show_loading(f"Loading the boards of MeshCore {tag}...", [(self.board_box, self.LOADING_BOARDS)])

    def go(self):
        board, port, kind = self.v["board"].get(), self.v["port"].get().strip(), self.v["kind"].get()
        conns = [c for c, v in self.conn.items() if v.get()] if kind == "companion" else []
        ssid = pwd = ""
        try:
            if "wifi" in conns:
                ssid, pwd = check_wifi_text(self.v["ssid"].get(), "name"), check_wifi_text(self.v["pwd"].get(), "password")
            if board not in self.boards or not (port or self.wifi_ota.get()): raise ValueError("Choose the board and its USB port.")
            env, ini_path, make = fb.plan(self.boards[board], kind, conns, ssid, pwd)
            setup = self.setup_values(kind)
        except ValueError as e:
            return messagebox.showerror("Firmware builder", str(e), parent=self)
        radio = [self.v[k].get().strip() for k in ("freq", "bw", "sf", "cr")]
        if any(radio) and not all(radio): return messagebox.showerror("Firmware builder", "Fill in all four radio values, or none.", parent=self)
        if self.wifi_ota.get(): return self.go_wifi_ota(env, ini_path, make, board, kind)
        ids = port_ids()
        if needs_boot_buttons(ids.get(port)):
            return messagebox.showinfo("Firmware builder", f"The board on {port} has to be put in download mode by hand first:\n\n"
                                       "hold its PRG (BOOT) button, tap RST, let go of PRG.\n\nIt then shows up on a new USB port - choose that one "
                                       "in 'USB port' and press Build and flash again.", parent=self)
        what = fb.TYPE_TITLES[kind].split(" (")[0].split(":")[0] +(f" ({', '.join(fb.CONN_TITLES[c] for c in conns)})" if conns else "")
        if not messagebox.askyesno("Firmware builder", f"Flash {what} for {board} to the board on {port}?"
                                   + ("\nThe board is erased first (its settings, channels and contacts are reset)." if self.erase.get() else "")
                                   + ("\n\nThe OTAFIX bootloader goes on first: when asked, double-press the board's reset button." if self.otafix.get() else "")
                                   + "\n\nDon't unplug it until this says it is done.", parent=self): return
        if io.CONNECTION_ARGS and io.CONNECTION_ARGS[:2] == ["-s", port]: self.api.disconnect()        # mcIRC must let go of that port
        erase, others, otafix = self.erase.get(), set(ids) - {port}, self.otafix.get()
        def work():
            mac = None
            with open(ini_path, encoding="utf-8") as f: original = f.read()
            try:
                with open(ini_path, "w", encoding="utf-8") as f: f.write(make(original))
                if otafix: self.install_otafix_step()                          # the bootloader first, then the firmware on top of it
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
            self.write("\nFlashed. If the board doesn't restart by itself (boards like the Heltec V4), tap its RST button now.\n")
            result = {"kind": kind, "conns": conns, "ip": None, "port": None}
            if "wifi" in conns:
                self.write(f"Looking for it on your network{' (' + mac + ')' if mac else ''} - joining the Wi-Fi can take a couple of minutes")
                result["ip"] = find_on_lan(mac, seconds=240, log=self.write) if mac else None
            if "usb" in conns:
                time.sleep(4)
                now = port_ids()
                result["port"] = port if port in now else next((p for p in now if p not in others), port)
            target = ["-t", result["ip"], "-p", "5000"] if result["ip"] else ["-s", result["port"]] if result["port"] else None
            if kind == "companion" and target:
                name, _, lat, lon = setup or ("", "", "", "")
                steps = ([["set", "name", name]] if name else []) + ([["set", "lat", lat]] if lat else []) + ([["set", "lon", lon]] if lon else []) \
                    + ([["set", "radio", ",".join(radio)]] if all(radio) else [])
                if steps:
                    self.write("\nSetting the node up: " + ", ".join(" ".join(s[1:]) for s in steps) + "\n")
                    for s in steps: io.execute_mesh_command(target + s, timeout=40, retries=2, lock=io._MeshLock())
                    io.execute_mesh_command(target + ["reboot"], timeout=20, retries=0, lock=io._MeshLock())
            elif setup and kind in ota.CLI_KINDS:
                cmds = ota.setup_commands(setup[0], setup[1], radio, setup[2], setup[3])
                if cmds:
                    time.sleep(4)
                    now = port_ids()
                    on = port if port in now else next((p for p in now if p not in others), port)
                    self.write(f"\nSetting the node up over USB ({on}):\n")
                    ota.serial_cli(on, cmds, log=self.write)
                    result["setup_done"] = True
            return result
        def done(r):
            self.flashed, self.ip = r, r["ip"]
            if r["kind"] != "companion":
                if r.get("setup_done"):
                    return self.write("\nSet up and restarted with your settings. Change more later in its private window (/login, then /set ...)"
                                      + (" - an observer also needs its Wi-Fi, MQTT server and area code: see its console or 'start webconfig'." if r["kind"].startswith("observer") else ".") + "\n")
                return self.write("\n" + fb.AFTER[r["kind"]] + "\n")
            if r["ip"]: self.write(f"\nThe board is on your Wi-Fi at {r['ip']} (port 5000). Give it a fixed address in your router so it keeps it.\n")
            elif "wifi" in r["conns"]:
                self.write("\nIt was not found on this PC's network. Check your router's client list for an 'esp32' / Espressif device (a guest "
                           "Wi-Fi is usually kept apart from your PC).\n")
            if r["port"]: self.write(f"On USB it is {r['port']}.\n")
            if "ble" in r["conns"]: self.write("Bluetooth is waiting too: pair it from the MeshCore app or Options > More nodes (Bluetooth).\n")
            if r["ip"] or r["port"]: self.add_btn.config(state="normal")
        self.job("Building and flashing (several minutes the first time)", work, done, need_radio=False)

    def add_node(self):
        r = self.flashed or {}
        if not (r.get("ip") or r.get("port")): return
        label = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9._ -]", "", self.v["label"].get())).strip()[:12].strip() or "node2"
        cfg = ({"label": label, "mode": "tcp", "host": r["ip"], "tcp_port": 5000, "enabled": True} if r.get("ip")
               else {"label": label, "mode": "usb", "port": r["port"], "enabled": True})
        self.api.add_extra_node(cfg)
        self.say(f"Added '{label}' ({r.get('ip') or r.get('port')}) to Options > More nodes - it connects with the main node.")
        self.add_btn.config(state="disabled")


WifiFirmwareWindow = FirmwareBuilderWindow          # (the name older parts of mcIRC use)
