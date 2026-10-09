"""Packet upload: sends the packets your node hears to community packet analyzers (MeshCore.ca, CascadiaMesh, LetsMesh, ...) over MQTT,
like agessaman/meshcore-packet-capture - but on mcIRC's own connection, so the radio stays free for chat.  You log in with a token your
node signs (no password; the private key never leaves the radio).  Off until you switch it on and give your area code."""
import json
import random
import re
import time
import tkinter as tk

from gui_addons import AddonBase
import meshcore_io as io
import pktup_core as core

RENEW_BEFORE = 300                 # seconds before the token runs out a new one is made


def node_details():
    """(public key, name, 'freq,bw,sf,cr', model, firmware) of the main node."""
    res = io.execute_mesh_command(io.CONNECTION_ARGS + [".infos", ".ver"], timeout=40)
    docs = [d for d in io.json_docs(res.stdout) if isinstance(d, dict)]
    info = next((d for d in docs if "public_key" in d), None)
    ver = next((d for d in docs if "fw_build" in d or "model" in d), {})
    if not info: raise RuntimeError("the node did not report its settings")
    radio = f"{info.get('radio_freq')},{info.get('radio_bw')},{info.get('radio_sf')},{info.get('radio_cr')}"
    return info["public_key"], info.get("name", "MeshCore node"), radio, ver.get("model", "unknown"), ver.get("ver", "unknown")


def new_client(transport, client_id):
    import paho.mqtt.client as mqtt
    try: return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id, transport=transport, clean_session=True)    # paho 2.x
    except AttributeError: return mqtt.Client(client_id=client_id, transport=transport, clean_session=True)                     # paho 1.x


class Addon(AddonBase):
    title = "Packet upload"
    version = "1.0.2"
    author = "mcIRC (after agessaman/meshcore-packet-capture)"
    description = ("Sends the packets your node hears to community packet analyzers (MeshCore.ca, CascadiaMesh, LetsMesh, ...) so they can "
                   "map coverage and routes. Logs in with a token your node signs. Off until you switch it on and give your area code.")
    tick_seconds = 60
    switch = "enabled"           # its ON/OFF switch on the toolbar

    def on_load(self):
        self.clients, self.me, self.sent, self.notes = {}, None, 0, {}
        self.starting = False
        self.api.add_menu_item("Sending on / off", self.toggle)
        self.api.add_menu_item("Status...", self.show_status)
        if self.api.connected: self.on_connect()

    def toggle(self):
        on = not self.api.get("enabled", False)
        self.api.set("enabled", on)
        self.stop()
        if not on: return self.api.log("Packet upload is OFF.", "info")
        if not re.fullmatch(r"[A-Za-z]{3}", self.api.get("area", "") or ""):
            return self.api.log("Packet upload is ON, but set your 3-letter area code first (Addons > Packet upload > Settings...).", "warn")
        self.api.log("Packet upload is ON - the packets your node hears go to the analyzers you ticked.", "warn")
        if self.api.connected: self.on_connect()

    def status_text(self):
        on = self.api.get("enabled", False)
        area = (self.api.get("area", "") or "").upper() or "(not set)"
        lines = [f"Packet upload: {'ON' if on else 'OFF'}.  Area: {area}.  Packets sent since mcIRC started: {self.sent}", ""]
        names = {s[1]: core.PRESETS[s[0]][0] for s in self.servers()}
        for server, name in names.items():
            c = self.clients.get(server)
            state = "connected" if c and c["client"].is_connected() else "connecting..." if c else "not connected"
            lines.append(f"{name:<24} {server:<34} {state}")
        if not names: lines.append("No analyzers ticked (Settings...).")
        if on and not self.api.connected: lines += ["", "mcIRC is not connected to a node: nothing to send."]
        return "\n".join(lines)

    def show_status(self):
        show = getattr(self.api, "show_text", None)
        if show: show("Packet upload - status", self.status_text)
        else: self.api.notice(self.status_text())

    def on_unload(self): self.stop()
    def on_disconnect(self): self.stop()

    def ready(self):
        return self.api.get("enabled", False) and re.fullmatch(r"[A-Za-z]{3}", self.api.get("area", "") or "") and self.servers()

    def servers(self):
        """[(preset key, server, port, transport, path, audience, ttl)] that are ticked."""
        on = self.api.get("presets", list(core.RECOMMENDED))
        return [(k,) + s for k in on if k in core.PRESETS for s in core.PRESETS[k][2]]

    def on_connect(self):
        if not self.ready() or self.clients or self.starting: return
        self.starting = True
        self.api.run_background(node_details, self._have_node)

    def _have_node(self, r):
        self.starting = False
        if isinstance(r, Exception): return self.api.log(f"Packet upload: couldn't read the node ({r}).", "warn")
        self.me = dict(zip(("key", "name", "radio", "model", "fw"), r))
        self.api.want_raw_packets(True)
        for s in self.servers(): self.api.run_background(lambda s=s: self._connect(*s), lambda res, s=s: self._connected(s, res))

    def _connect(self, key, server, port, transport, path, audience, ttl):
        """One server: a token signed by the node (where the server wants one), then the MQTT connection (runs in the background)."""
        me, area = self.me, self.api.get("area", "").upper()
        c = new_client(transport, f"mcirc_{me['key'][:8]}_{random.randint(1000, 9999)}")
        c.tls_set()
        if transport == "websockets": c.ws_set_options(path=path)
        exp = 0
        if audience:
            now = time.time()
            sig_in = core.token_signing_input(me["key"], audience, now, ttl)
            c.username_pw_set(f"v1_{me['key'].upper()}", core.token(sig_in, self.api.sign_with_node(sig_in.encode())))
            exp = now + ttl
        status = lambda s: json.dumps(core.status_message(s, me["name"], me["key"], me["model"], me["fw"], me["radio"]))
        c.will_set(core.topic(area, me["key"], "status"), status("offline"), qos=0, retain=True)
        c.on_connect = lambda cl, ud, flags, rc: cl.publish(core.topic(area, me["key"], "status"), status("online"), qos=0, retain=True) if rc == 0 else None
        c.reconnect_delay_set(min_delay=2, max_delay=120)
        c.connect_async(server, port, keepalive=55)
        c.loop_start()
        return c, exp, (key, server, port, transport, path, audience, ttl)

    def _connected(self, s, res):
        if isinstance(res, Exception):
            return self.api.log(f"Packet upload: couldn't connect to {s[1]}: {res}", "warn")
        c, exp, spec = res
        if not self.ready():                                    # switched off meanwhile
            c.loop_stop(); c.disconnect(); return
        self.clients[s[1]] = {"client": c, "exp": exp, "spec": spec}
        self.api.log(f"Packet upload: sending to {s[1]} ({core.PRESETS[s[0]][0]}).", "info")

    def on_packet(self, pkt):
        if not self.clients or not pkt.get("packet") or not self.me: return
        area = self.api.get("area", "").upper()
        try: payload = json.dumps(core.packet_message(pkt["packet"], pkt.get("snr"), pkt.get("rssi"), self.me["name"], self.me["key"]))
        except (ValueError, IndexError): return
        for c in self.clients.values(): c["client"].publish(core.topic(area, self.me["key"], "packets"), payload, qos=0, retain=False)
        self.sent += 1

    def on_tick(self):
        """Tokens run out: a fresh one before they do (the node signs it again)."""
        for server, c in list(self.clients.items()):
            if c["exp"] and c["exp"] - time.time() < RENEW_BEFORE and not c.get("renewing"):
                c["renewing"] = True
                self.api.run_background(lambda c=c: self._renew(c), lambda r, c=c: c.update(renewing=False))

    def _renew(self, c):
        key, server, port, transport, path, audience, ttl = c["spec"]
        now = time.time()
        sig_in = core.token_signing_input(self.me["key"], audience, now, ttl)
        c["client"].username_pw_set(f"v1_{self.me['key'].upper()}", core.token(sig_in, self.api.sign_with_node(sig_in.encode())))
        c["exp"] = now + ttl
        c["client"].reconnect()

    def stop(self):
        area = (self.api.get("area", "") or "").upper()
        for c in self.clients.values():
            try:
                if self.me: c["client"].publish(core.topic(area, self.me["key"], "status"),
                                                json.dumps(core.status_message("offline", self.me["name"], self.me["key"])), qos=0, retain=True)
                c["client"].disconnect(); c["client"].loop_stop()
            except Exception: pass
        self.clients = {}
        self.api.want_raw_packets(False)

    # ---- settings ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_on = tk.BooleanVar(value=self.api.get("enabled", False))
        self.v_area = tk.StringVar(value=self.api.get("area", ""))
        on = set(self.api.get("presets", list(core.RECOMMENDED)))
        self.v_presets = {k: tk.BooleanVar(value=k in on) for k in core.PRESETS}
        tk.Checkbutton(f, text="Send the packets my node hears to the analyzers ticked below", variable=self.v_on, bg=bg).pack(anchor="w")
        r = tk.Frame(f, bg=bg); r.pack(anchor="w", pady=4)
        tk.Label(r, text="Your area code (3 letters, the nearest airport: YVR, YXX, SEA, ...):", bg=bg).pack(side="left")
        tk.Entry(r, textvariable=self.v_area, width=5).pack(side="left", padx=4)
        tk.Label(f, bg=bg, fg="#555", wraplength=460, justify="left", text=(
            "What goes out: every packet your node hears, exactly as it went over the air (public-channel text can be read by anyone who knows "
            "the channel; private messages and private channels stay encrypted), with its signal strength, your node's name and public key, and "
            "an online/offline status. You log in with a token your node signs - no password, and its private key never leaves the radio. "
            "Needs a USB or Wi-Fi connection.")).pack(anchor="w", pady=(0, 6))
        grid = tk.Frame(f, bg=bg); grid.pack(anchor="w")
        keys = list(core.RECOMMENDED) + [k for k in core.PRESETS if k not in core.RECOMMENDED]
        for i, k in enumerate(keys):
            title, area, _ = core.PRESETS[k]
            tk.Checkbutton(grid, text=title + (f" ({area})" if area else "") + (" *" if k in core.RECOMMENDED else ""), variable=self.v_presets[k],
                           bg=bg, anchor="w").grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        tk.Label(f, bg=bg, fg="#555", text="* suggested for BC").pack(anchor="w")
        try:
            import paho.mqtt  # noqa: F401
        except ImportError:
            tk.Label(f, bg=bg, fg="#c00000", text="Needs the paho-mqtt package: pip install paho-mqtt  (then restart mcIRC)").pack(anchor="w", pady=4)
        tk.Label(f, bg=bg, text=f"Packets sent since mcIRC started: {self.sent}" + (f" - connected to {len(self.clients)} server(s)" if self.clients else "")).pack(anchor="w", pady=(6, 0))
        return f

    def apply_options(self):
        area = re.sub(r"[^A-Za-z]", "", self.v_area.get()).upper()[:3]
        self.api.set("area", area)
        self.api.set("presets", [k for k, v in self.v_presets.items() if v.get()])
        self.api.set("enabled", bool(self.v_on.get()))
        self.stop()
        if self.v_on.get() and len(area) != 3: self.api.log("Packet upload: set your 3-letter area code first (e.g. YVR).", "warn")
        elif self.api.connected: self.on_connect()
