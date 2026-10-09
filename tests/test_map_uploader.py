import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Map uploader: only genuinely signed adverts of repeaters / room servers / sensors, the original's replay rules, the request the map
expects, signed by the node.  No radio, nothing is uploaded (fakes)."""
import importlib.util, json, struct, time
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, os.path.join(ROOT, "packages", "map_uploader"))
import mapup_core as core
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

def make_advert(kind=2, name="Hilltop Rptr", ts=None, tamper=False, route=1, hops=1, hash_size=2):
    key = ECC.generate(curve="ed25519")
    pub = key.public_key().export_key(format="raw")
    ts = ts or int(time.time())
    app = bytes([kind | 0x10 | 0x80]) + struct.pack("<ii", 49_123456, -122_654321) + name.encode()
    sig = eddsa.new(key, "rfc8032").sign(pub + struct.pack("<I", ts) + app)
    if tamper: app = app[:-1] + b"X"
    header = (core.PAYLOAD_ADVERT << 2) | route
    transport = b"\x00\x00\x00\x00" if route in (0, 3) else b""
    path = bytes([((hash_size - 1) << 6) | hops]) + b"\xab" * (hops * hash_size)
    return (bytes([header]) + transport + path + pub + struct.pack("<I", ts) + sig + app).hex(), pub.hex(), ts

raw, pub, ts = make_advert()
p = core.parse_packet(raw)
adv = core.parse_advert(p["payload"])
ok("an advert packet is read (route, path with 2-byte hashes, payload)", p["type"] == core.PAYLOAD_ADVERT and adv["public_key"].hex() == pub)
ok("...its node: type, name, position", (adv["type"], adv["name"], round(adv["lat"], 4), round(adv["lon"], 4)) == ("repeater", "Hilltop Rptr", 49.1235, -122.6543), adv)
ok("a genuinely signed advert checks out", core.verified(adv))
raw_t, *_ = make_advert(tamper=True)
ok("a changed advert does not", not core.verified(core.parse_advert(core.parse_packet(raw_t)["payload"])))
raw_tr, *_ = make_advert(route=0)
ok("adverts with transport codes are read too", core.verified(core.parse_advert(core.parse_packet(raw_tr)["payload"])))
seen = core.Seen()
ok("a node never uploaded: fine", seen.why_not(pub, ts) is None)
seen.done(pub, ts)
ok("...the same advert again: refused (replay)", seen.why_not(pub, ts) is not None)
ok("...a newer one within the hour: refused", "hour" in seen.why_not(pub, ts + 600))
ok("...an hour later: fine", seen.why_not(pub, ts + 3700) is None)
data = core.request_data(raw, {"freq": 910.525, "cr": 5, "sf": 7, "bw": 62.5})
ok("the request is the original's: radio settings and a meshcore:// link, compact JSON",
   data == '{"params":{"freq":910.525,"cr":5,"sf":7,"bw":62.5},"links":["meshcore://' + raw + '"]}', data)
body = json.loads(core.request_body(data, "ee" * 64, "11" * 32))
ok("...sent with the signature and your node's public key", body == {"data": data, "signature": "ee" * 64, "publicKey": "11" * 32})

# the addon: what it uploads, what it skips
import tkinter as tk, mcIRC
from gui_addons import AddonAPI
spec = importlib.util.spec_from_file_location("t_map_uploader", os.path.join(ROOT, "packages", "map_uploader", "map_uploader.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
def run_now(fn, done):                                   # like mcIRC's: an exception goes to done()
    try: r = fn()
    except Exception as e: r = e
    done(r)
app.bg = run_now
api = AddonAPI(app, "map_uploader")
vals, logged, posted, signed = {}, [], [], []
api.get = lambda k, d=None: vals.get(k, d); api.set = lambda k, v: vals.__setitem__(k, v)
api.log = lambda t, level="info": logged.append((level, t))
inst = mod.Addon(api); inst.on_load()
mod.GAP = 0
fakes = [mock.patch.object(mod, "node_info", lambda: ("cc" * 32, {"freq": 910.525, "cr": 5, "sf": 7, "bw": 62.5})),
         mock.patch.object(mod, "sign_with_node", lambda d: signed.append(d) or "ee" * 64),
         mock.patch.object(mod, "post", lambda body: posted.append(json.loads(body)) or '{"ok":true}')]
for f in fakes: f.start()
inst.on_packet({"packet": raw})
ok("off until switched on: nothing uploaded", posted == [])
vals["enabled"] = True
inst.on_packet({"packet": raw})
ok("switched on: a repeater's advert is uploaded, signed by the node", len(posted) == 1 and posted[0]["publicKey"] == "cc" * 32 and signed[0] == core.digest(posted[0]["data"]))
ok("...and noted in Status", any("uploaded repeater 'Hilltop Rptr'" in t for _, t in logged), logged)
inst.on_packet({"packet": raw})
ok("the same advert again is not uploaded twice", len(posted) == 1)
for kind, label in ((1, "a person's companion"), ):
    r2, *_ = make_advert(kind=kind, name="Bob phone")
    inst.on_packet({"packet": r2})
    ok(f"{label} is never uploaded", len(posted) == 1)
inst.on_packet({"packet": raw_t})
ok("a forged advert is never uploaded", len(posted) == 1)
r3, *_ = make_advert(kind=3, name="Room")
inst.on_packet({"packet": r3})
ok("a room server is uploaded", len(posted) == 2)
for f in fakes: f.stop()
with mock.patch.object(mod, "node_info", lambda: ("cc" * 32, {"freq": 910.525, "cr": 5, "sf": 7, "bw": 62.5})), \
     mock.patch.object(mod, "sign_with_node", lambda d: (_ for _ in ()).throw(RuntimeError("the node did not sign: unsupported"))):
    r4, *_ = make_advert(kind=4, name="Sensor")
    inst.on_packet({"packet": r4})
ok("a node that can't sign: uploads pause with a clear note", inst.paused and any(l == "warn" and "paused" in t for l, t in logged), logged[-1:])
ok("helper arguments for USB and Wi-Fi; Bluetooth refused", mod.helper_args(["-s", "COM4"]) == ["--serial", "COM4"]
   and mod.helper_args(["-t", "192.168.1.57", "-p", "5000"]) == ["--tcp", "192.168.1.57", "--port", "5000"] and mod.helper_args(["-a", "x"]) is None)
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
