import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Packet upload: messages, hashes and log-in token exactly as agessaman/meshcore-packet-capture sends them (reference values computed with
its own code), and the addon's behaviour.  No radio, no network (fake MQTT)."""
import base64, importlib.util, json, time
from unittest import mock

sys.path.insert(0, os.path.join(ROOT, "packages", "packet_upload"))
import pktup_core as core

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# reference hashes: computed with meshcore-packet-capture's calculate_packet_hash on the same packets
REF = {"15" + "41" + "abcd" + "00" * 40: "EF75C7F1FD765274", "0A" + "02" + "1122" + "deadbeef" * 5: "F821EAB5B72F0F71",
       "24" + "01020304" + "00" + "cafe" * 8: "917B03936A665891", "27" + "01020304" + "83" + "aabbccddeeff112233" + "77" * 9: "F6E6C03F632A589A"}
ok("packet hashes match the upstream uploader (flood, direct, transport, TRACE)", all(core.packet_hash(k) == v for k, v in REF.items()),
   {k[:6]: core.packet_hash(k) for k in REF})
m = core.packet_message("0A" + "02" + "1122" + "deadbeef" * 5, 7.25, -88, "mcIRC", "ab" * 32)
ok("a heard packet is described as the analyzers expect",
   (m["type"], m["direction"], m["packet_type"], m["route"], m["len"], m["payload_len"], m["SNR"], m["RSSI"], m["origin_id"], m["path"])
   == ("PACKET", "rx", "2", "D", "24", "20", "7.25", "-88", ("AB" * 32), "11,22"), m)
ok("...flood packets carry no path", "path" not in core.packet_message(list(REF)[0], 1, -1, "x", "ab" * 32))
ok("the topics: meshcore/<AREA>/<KEY>/packets|status", core.topic("yvr", "ab" * 2, "packets") == "meshcore/YVR/ABAB/packets")
sig_in = core.token_signing_input("ab" * 32, "mqtt1.meshcore.ca", 1000, 86400)
h, p = (json.loads(base64.urlsafe_b64decode(x + "==")) for x in sig_in.split("."))
ok("the log-in token: Ed25519 JWT with the node's key, issued/expiry times and the server as audience",
   h == {"alg": "Ed25519", "typ": "JWT"} and p == {"publicKey": "AB" * 32, "iat": 1000, "exp": 87400, "aud": "mqtt1.meshcore.ca"}, (h, p))
ok("...signed by the node: <header>.<claims>.<signature hex>", core.token(sig_in, "EE" * 64) == sig_in + "." + "ee" * 64)
ok("17 servers, the three suggested for BC among them", len(core.PRESETS) == 17 and all(k in core.PRESETS for k in core.RECOMMENDED))

# the addon with a fake MQTT library
class FakeClient:
    made = []
    def __init__(self, *a, **k): self.pub, self.user, self.will, self.connected_to, self.reconnects = [], None, None, None, 0; FakeClient.made.append(self)
    def tls_set(self): pass
    def ws_set_options(self, path): self.path = path
    def username_pw_set(self, u, p): self.user = (u, p)
    def will_set(self, t, payload, qos, retain): self.will = (t, json.loads(payload)["status"], retain)
    def reconnect_delay_set(self, **k): pass
    def connect_async(self, host, port, keepalive): self.connected_to = (host, port); self.on_connect(self, None, {}, 0)
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass
    def reconnect(self): self.reconnects += 1
    def publish(self, topic, payload, qos=0, retain=False): self.pub.append((topic, json.loads(payload), retain))
import tkinter as tk, mcIRC
from gui_addons import AddonAPI
spec = importlib.util.spec_from_file_location("t_packet_upload", os.path.join(ROOT, "packages", "packet_upload", "packet_upload.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
def run_now(fn, done):
    try: r = fn()
    except Exception as e: r = e
    done(r)
app.bg = run_now
api = AddonAPI(app, "packet_upload")
vals, logged, signed = {}, [], []
api.get = lambda k, d=None: vals.get(k, d); api.set = lambda k, v: vals.__setitem__(k, v)
api.log = lambda t, level="info": logged.append((level, t))
api.sign_with_node = lambda data: signed.append(data) or "ee" * 64
fakes = [mock.patch.object(mod, "node_details", lambda: ("ab" * 32, "mcIRC", "909.0,62.5,7,5", "Heltec V3", "v1.17.1")),
         mock.patch.object(mod, "new_client", lambda transport, cid: FakeClient())]
for f in fakes: f.start()
app.connected = True
inst = mod.Addon(api); inst.on_load()
ok("off until switched on: no connections", FakeClient.made == [])
vals.update(enabled=True)
inst.on_connect()
ok("switched on without an area code: still nothing", FakeClient.made == [])
vals.update(area="YVR")
inst.on_connect()
ok("with an area code: the suggested servers are connected (MeshCore.ca x2, CascadiaMesh, LetsMesh x2)",
   sorted(c.connected_to[0] for c in FakeClient.made) == sorted(["mqtt1.meshcore.ca", "mqtt2.meshcore.ca", "mqtt-v1.cascadiamesh.org", "mqtt-us-v1.letsmesh.net", "mqtt-eu-v1.letsmesh.net"]),
   [c.connected_to for c in FakeClient.made])
c0 = FakeClient.made[0]
ok("...logging in as v1_<node key> with a token the node signed", c0.user[0] == "v1_" + "AB" * 32 and c0.user[1].endswith("." + "ee" * 64) and len(signed) == 5)
ok("...announcing 'online' (kept), with 'offline' as the last will", c0.pub[0][0] == "meshcore/YVR/" + "AB" * 32 + "/status" and c0.pub[0][1]["status"] == "online" and c0.pub[0][2]
   and c0.will[1:] == ("offline", True))
ok("...and every packet the radio hears is now wanted whole", "packet_upload" in app.raw_packets_wanted)
inst.on_packet({"packet": "0A" + "02" + "1122" + "deadbeef" * 5, "snr": 6.5, "rssi": -90})
ok("a heard packet goes to every server", all(c.pub[-1][0].endswith("/packets") and c.pub[-1][1]["SNR"] == "6.5" for c in FakeClient.made) and inst.sent == 1)
for c in inst.clients.values(): c["exp"] = time.time() + 60
inst.on_tick()
ok("a token about to run out is renewed (signed again) and the connection refreshed", all(c.reconnects == 1 for c in FakeClient.made) and len(signed) == 10)
inst.on_disconnect()
ok("disconnecting: 'offline' is sent and nothing more is wanted", all(c.pub[-1][1]["status"] == "offline" for c in FakeClient.made) and not app.raw_packets_wanted and not inst.clients)
ok("...and 'offline' keeps the node's radio, model and firmware (the analyzers' observer list shows them)",
   all(c.pub[-1][1]["radio"] != "unknown" and c.pub[-1][1]["model"] != "unknown" for c in FakeClient.made), [c.pub[-1][1] for c in FakeClient.made][:1])
for f in fakes: f.stop()
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
