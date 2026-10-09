"""Map uploader: puts the repeaters, room servers and sensors your node hears on the official MeshCore map (map.meshcore.io), like
recrof/map.meshcore.io-uploader.  Each upload is signed by your node itself - its private key never leaves the radio.
Off until you switch it on; only adverts whose signature checks out, the same node at most once an hour, one upload every 20 seconds."""
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request

from gui_addons import AddonBase, BASE_DIR
import meshcore_io as io
import mapup_core as core

GAP = 20                       # seconds between uploads
RADIO_EVERY = 3600             # re-read the node's own key and radio settings this often


def helper_path():
    for d in (BASE_DIR, os.path.dirname(os.path.abspath(__file__))):
        p = os.path.join(d, "mapup_sign_proc.py")
        if os.path.exists(p): return p
    return None


def helper_args(conn):
    """meshcli connection arguments -> the signing helper's ('-s COM4' -> --serial COM4, '-t host -p 5000' -> --tcp host --port 5000)."""
    a = list(conn or [])
    if a[:1] == ["-s"] and len(a) > 1: return ["--serial", a[1]] + (["--baud", a[a.index("-b") + 1]] if "-b" in a else [])
    if a[:1] == ["-t"] and len(a) > 1: return ["--tcp", a[1]] + (["--port", a[a.index("-p") + 1]] if "-p" in a else [])
    return None                                               # Bluetooth: not supported by the helper


def sign_with_node(digest):
    """The node signs the 32 bytes (its key stays on it).  Holds the radio for the few seconds it takes."""
    args, helper = helper_args(io.CONNECTION_ARGS), helper_path()
    if args is None: raise RuntimeError("signing needs a USB or Wi-Fi connection to the node (not Bluetooth)")
    if helper is None: raise RuntimeError("mapup_sign_proc.py is missing - Tools > Addons > Update fixes it")
    with io.MESH_LOCK:
        r = subprocess.run([sys.executable, helper] + args + ["--hex", digest.hex()], capture_output=True, text=True, timeout=60,
                           creationflags=io.NO_WINDOW, cwd=BASE_DIR)
    res = next((json.loads(l) for l in reversed(r.stdout.splitlines()) if l.startswith("{")), {"error": r.stderr.strip()[-200:] or "no answer"})
    if "signature" not in res: raise RuntimeError(f"the node did not sign: {res.get('error')}")
    return res["signature"]


def node_info():
    """(own public key hex, radio dict) from the node."""
    res = io.execute_mesh_command(io.CONNECTION_ARGS + [".infos"], timeout=40)
    info = next((d for d in io.json_docs(res.stdout) if isinstance(d, dict) and "public_key" in d), None)
    if not info: raise RuntimeError("the node did not report its settings")
    return info["public_key"], {"freq": float(info["radio_freq"]), "cr": int(info["radio_cr"]), "sf": int(info["radio_sf"]), "bw": float(info["radio_bw"])}


def post(body):
    req = urllib.request.Request(core.API_URL, data=body.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "mcIRC map uploader"})
    with urllib.request.urlopen(req, timeout=20) as r: return r.read().decode("utf-8", "replace")[:300]


class Addon(AddonBase):
    title = "Map uploader"
    version = "1.0.2"
    author = "mcIRC (after recrof/map.meshcore.io-uploader)"
    description = ("Puts the repeaters, room servers and sensors your node hears on the official MeshCore map (map.meshcore.io). "
                   "Each upload is signed by your node; its private key never leaves the radio. Off until you switch it on.")
    tick_seconds = 0
    switch = "enabled"           # its ON/OFF switch on the toolbar

    def on_load(self):
        self.seen, self.queue, self.lock = core.Seen(), [], threading.Lock()
        self.busy, self.paused, self.uploaded, self.last_upload = False, "", 0, 0.0
        self.me = self.radio = None
        self.radio_at = 0.0
        self.recent = []                                     # (time, kind, name) of this session's uploads, newest last
        self.api.add_menu_item("Uploading on / off", self.toggle)
        self.api.add_menu_item("Recent uploads...", self.show_recent)

    def toggle(self):
        on = not self.api.get("enabled", False)
        self.api.set("enabled", on)
        if on: self.paused = ""
        self.api.log("Map uploader is ON - repeaters, room servers and sensors your node hears go to map.meshcore.io" if on
                     else "Map uploader is OFF", "warn" if on else "info")

    def recent_text(self):
        state = ("ON" if self.api.get("enabled", False) else "OFF") + (f" (paused: {self.paused})" if self.paused else "")
        lines = [f"{time.strftime('%H:%M:%S', time.localtime(t))}  {kind:<12} {name}" for t, kind, name in reversed(self.recent)]
        return f"Map uploader: {state}.  Uploaded since mcIRC started: {self.uploaded}\n\n" + ("\n".join(lines) or "Nothing uploaded yet.")

    def show_recent(self):
        show = getattr(self.api, "show_text", None)
        if show: show("Map uploader - recent uploads", self.recent_text)
        else: self.api.notice(self.recent_text())

    def on_unload(self):
        with self.lock: self.queue.clear()

    def on_disconnect(self):
        self.me = self.radio = None                          # read again when the next node connects

    def on_packet(self, pkt):
        if not self.api.get("enabled", False) or self.paused or not pkt.get("packet"): return
        p = core.parse_packet(pkt["packet"])
        if not p or p["type"] != core.PAYLOAD_ADVERT: return
        adv = core.parse_advert(p["payload"])
        if not adv or adv["type"] == "chat": return            # companions (people) are never uploaded
        if not core.verified(adv): return                      # not really signed by that node: ignored
        pub = adv["public_key"].hex()
        if self.seen.why_not(pub, adv["timestamp"]): return
        with self.lock:
            if any(q[1] == pub for q in self.queue): return
            self.queue.append((pkt["packet"], pub, adv))
            del self.queue[:-20]
        if not self.busy:
            self.busy = True
            self.api.run_background(self._work, self._done)

    def _work(self):
        done = []
        while True:
            with self.lock:
                if not self.queue: return done
                raw_hex, pub, adv = self.queue.pop(0)
            if self.seen.why_not(pub, adv["timestamp"]): continue
            if self.radio is None or time.time() - self.radio_at > RADIO_EVERY:
                self.me, self.radio = node_info()
                self.radio_at = time.time()
            wait = GAP - (time.time() - self.last_upload)
            if wait > 0: time.sleep(wait)
            data = core.request_data(raw_hex, self.radio)
            sig = sign_with_node(core.digest(data))
            answer = post(core.request_body(data, sig, self.me))
            self.last_upload = time.time()
            self.seen.done(pub, adv["timestamp"])
            done.append((adv["name"] or pub[:8], adv["type"], answer))

    def _done(self, r):
        self.busy = False
        if isinstance(r, Exception):
            msg = str(r)
            if "did not sign" in msg or "signing needs" in msg:
                self.paused = msg                               # this node can't sign: stop trying this session
                self.api.log(f"Map uploader paused: {msg}. (Older firmware can't sign; update it with MeshCore tools > Firmware.)", "warn")
            else:
                self.api.log(f"Map upload failed: {msg}", "warn")
            return
        for name, kind, answer in r:
            self.uploaded += 1
            self.recent = (self.recent + [(time.time(), kind, name)])[-100:]
            self.api.log(f"Map: uploaded {kind} '{name}' to map.meshcore.io", "info")
        with self.lock: more = bool(self.queue)
        if more and not self.busy:
            self.busy = True
            self.api.run_background(self._work, self._done)

    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_on = tk.BooleanVar(value=self.api.get("enabled", False))
        tk.Checkbutton(f, text="Upload the repeaters, room servers and sensors my node hears to map.meshcore.io", variable=self.v_on, bg=bg).pack(anchor="w")
        tk.Label(f, bg=bg, fg="#555", wraplength=460, justify="left", text=(
            "What goes out: the advert each node broadcasts itself (its name, type and position - public anyway), checked to be really "
            "signed by that node, plus your radio settings (frequency, BW, SF, CR) and your node's public key. Your node signs each upload; "
            "its private key never leaves it. People's companions (phones) are never uploaded. Needs a USB or Wi-Fi connection.")).pack(anchor="w")
        tk.Label(f, bg=bg, text=f"Uploaded since mcIRC started: {self.uploaded}" + (f"   (paused: {self.paused})" if self.paused else "")).pack(anchor="w", pady=(6, 0))
        return f

    def apply_options(self):
        self.api.set("enabled", bool(self.v_on.get()))
        if self.v_on.get(): self.paused = ""
