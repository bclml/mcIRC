"""Map uploader: reading MeshCore adverts and building the signed upload for map.meshcore.io.
A Python port of recrof/map.meshcore.io-uploader (MIT): the same checks, the same request."""
import hashlib
import json
import struct

API_URL = "https://map.meshcore.io/api/v1/uploader/node"
ROUTE_TRANSPORT_FLOOD, ROUTE_TRANSPORT_DIRECT = 0, 3
PAYLOAD_ADVERT = 4
NODE_TYPES = {1: "chat", 2: "repeater", 3: "room", 4: "sensor"}
REUPLOAD_AFTER = 3600            # the same node again only with an advert at least an hour newer (as the original)


def parse_packet(hexstr):
    """A raw MeshCore packet -> {'route', 'type', 'payload' (bytes)}; None when it can't be read."""
    try:
        b = bytes.fromhex(hexstr)
        header, i = b[0], 1
        route, ptype = header & 0x03, (header >> 2) & 0x0F
        if route in (ROUTE_TRANSPORT_FLOOD, ROUTE_TRANSPORT_DIRECT): i += 4          # transport codes
        plen = b[i]; i += 1
        hops, size = plen & 0x3F, (plen >> 6) + 1                                     # path length: hop count + hash size (newer firmware)
        i += hops * size
        if i > len(b): return None
        return {"route": route, "type": ptype, "payload": b[i:]}
    except (ValueError, IndexError):
        return None


def parse_advert(payload):
    """An advert's payload -> {'public_key', 'timestamp', 'signature', 'app_data', 'type', 'name', 'lat', 'lon'}; None if too short."""
    if len(payload) < 101: return None
    pub, ts, sig, app = payload[:32], struct.unpack("<I", payload[32:36])[0], payload[36:100], payload[100:]
    flags, j = app[0], 1
    lat = lon = None
    if flags & 0x10 and len(app) >= j + 8:
        lat, lon = (v / 1e6 for v in struct.unpack("<ii", app[j:j + 8]))
        j += 8
    if flags & 0x20: j += 2
    if flags & 0x40: j += 2
    name = app[j:].decode("utf-8", "replace").rstrip("\x00") if flags & 0x80 else ""
    return {"public_key": pub, "timestamp": ts, "signature": sig, "app_data": app, "type": NODE_TYPES.get(flags & 0x0F, "unknown"),
            "name": name, "lat": lat, "lon": lon}


def verified(adv):
    """True when the advert's signature is its node's (Ed25519 over public key + timestamp + app data)."""
    try:
        from Crypto.Signature import eddsa
        key = eddsa.import_public_key(adv["public_key"])
        eddsa.new(key, "rfc8032").verify(adv["public_key"] + struct.pack("<I", adv["timestamp"]) + adv["app_data"], adv["signature"])
        return True
    except (ValueError, ImportError):
        return False


class Seen:
    """The original's replay rules: never an advert older than or as old as the last one uploaded for that node, and the same node again
    only an hour later."""
    def __init__(self): self.last = {}

    def why_not(self, pub_hex, ts):
        prev = self.last.get(pub_hex)
        if prev is None: return None
        if ts <= prev: return "not newer than the last upload (possible replay)"
        if ts < prev + REUPLOAD_AFTER: return "uploaded less than an hour ago"
        return None

    def done(self, pub_hex, ts): self.last[pub_hex] = ts


def request_data(raw_hex, radio):
    """The 'data' JSON string the map wants (signed as is): the radio settings and a meshcore:// link to the advert."""
    data = {"params": {"freq": radio["freq"], "cr": radio["cr"], "sf": radio["sf"], "bw": radio["bw"]}, "links": [f"meshcore://{raw_hex.lower()}"]}
    return json.dumps(data, separators=(",", ":"))


def digest(data_json): return hashlib.sha256(data_json.encode("utf-8")).digest()


def request_body(data_json, signature_hex, my_public_key_hex):
    return json.dumps({"data": data_json, "signature": signature_hex, "publicKey": my_public_key_hex})
