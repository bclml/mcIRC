"""Packet upload: the packet analyzer servers, and the messages and log-in token they expect - as agessaman/meshcore-packet-capture (MIT)
sends them, so the analyzers read mcIRC's uploads like any other observer's."""
import base64
import datetime
import hashlib
import json

CLIENT_VERSION = "mcIRC-packet-upload/1.0.0"
# key: (title, area, [(server, port, transport, websocket path, token audience or None, token lifetime s)])
PRESETS = {
    "meshcore-ca": ("MeshCore.ca", "Canada", [("mqtt1.meshcore.ca", 443, "websockets", "/", "mqtt1.meshcore.ca", 86400),
                                              ("mqtt2.meshcore.ca", 443, "websockets", "/", "mqtt2.meshcore.ca", 86400)]),
    "cascadiamesh": ("CascadiaMesh", "Pacific Northwest", [("mqtt-v1.cascadiamesh.org", 443, "websockets", "/", "mqtt-v1.cascadiamesh.org", 86400)]),
    "letsmesh": ("LetsMesh Analyzer", "worldwide", [("mqtt-us-v1.letsmesh.net", 443, "websockets", "/", "mqtt-us-v1.letsmesh.net", 86400),
                                                    ("mqtt-eu-v1.letsmesh.net", 443, "websockets", "/", "mqtt-eu-v1.letsmesh.net", 86400)]),
    "meshmapper": ("MeshMapper", "coverage maps", [("mqtt.meshmapper.net", 443, "websockets", "/", "mqtt.meshmapper.net", 86400)]),
    "meshomatic": ("Meshomatic", "US East", [("us-east.meshomatic.net", 443, "websockets", "/mqtt", "us-east.meshomatic.net", 86400)]),
    "waev": ("WAEV", "", [("mqtt.waev.app", 443, "websockets", "/", "mqtt.waev.app", 3600)]),
    "bostonmesh": ("BostonMesh", "Boston", [("mqttmc01.bostonme.sh", 443, "websockets", "/", "mqttmc01.bostonme.sh", 86400)]),
    "chimesh": ("ChiMesh", "Chicago", [("mqtt.chimesh.org", 443, "websockets", "/", "mqtt.chimesh.org", 86400)]),
    "coloradomesh": ("ColoradoMesh", "Colorado", [("mqtt.meshcore.coloradomesh.org", 443, "websockets", "/", "mqtt.meshcore.coloradomesh.org", 86400)]),
    "flmesh-us": ("FLMesh", "Florida", [("mcmqtt.jntconnections.com", 443, "websockets", "/", "mcmqtt.jntconnections.com", 86400)]),
    "ntxmesh": ("NTXMesh", "North Texas", [("ntxmesh.dhovin.me", 8883, "websockets", "/", "ntxmesh.dhovin.me", 86400)]),
    "eastidahomesh": ("East Idaho Mesh", "East Idaho", [("broker.eastidahomesh.net", 443, "websockets", "/", None, 0)]),
    "bsmesh": ("BSMesh", "Germany", [("mqtt.bsmesh.de", 8885, "websockets", "/", "mqtt.bsmesh.de", 86400)]),
    "czechmesh": ("CzechMesh", "Czechia", [("mqtt1.meshcore.cz", 443, "websockets", "/", "mqtt1.meshcore.cz", 86400),
                                           ("mqtt2.meshcore.website", 443, "websockets", "/", "mqtt2.meshcore.website", 86400)]),
    "dutchmeshcore": ("Dutch MeshCore", "Netherlands", [("collector1.dutchmeshcore.nl", 443, "websockets", "/", "collector1.dutchmeshcore.nl", 86400),
                                                        ("collector2.dutchmeshcore.nl", 443, "websockets", "/", "collector2.dutchmeshcore.nl", 86400)]),
    "meshat-se": ("Meshat", "Sweden", [("meshcore-mqtt.meshat.se", 443, "websockets", "/", "meshcore-mqtt.meshat.se", 86400)]),
    "nz-analyzer": ("NZ Analyzer", "New Zealand", [("meshcore-mqtt-1.baird.io", 443, "websockets", "/", "meshcore-mqtt-1.baird.io", 86400)]),
}
RECOMMENDED = ("meshcore-ca", "cascadiamesh", "letsmesh")
ROUTE_LETTER = {0: "F", 1: "F", 2: "D", 3: "T"}           # transport flood counts as flood, as upstream


def _b64url(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def token_signing_input(public_key_hex, audience, now, ttl):
    """The part of the log-in token the node signs: base64url(header).base64url(claims), compact JSON as upstream."""
    header = json.dumps({"alg": "Ed25519", "typ": "JWT"}, separators=(",", ":"))
    claims = {"publicKey": public_key_hex.upper(), "iat": int(now)}
    if ttl: claims["exp"] = int(now) + int(ttl)
    if audience: claims["aud"] = audience
    return f"{_b64url(header.encode())}.{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"


def token(signing_input, signature_hex): return f"{signing_input}.{signature_hex.lower()}"


def topic(area, public_key_hex, kind): return f"meshcore/{area.upper()}/{public_key_hex.upper()}/{kind}"


def _split(raw):
    """(header, route, payload type, path-length byte, path hops as hex strings, payload) of a raw packet."""
    header, i = raw[0], 1
    route, ptype = header & 0x03, (header >> 2) & 0x0F
    if route in (0, 3): i += 4
    plen = raw[i]; i += 1
    hops, size = plen & 0x3F, (plen >> 6) + 1
    path = [raw[i + k * size:i + (k + 1) * size].hex().upper() for k in range(hops)]
    return header, route, ptype, plen, path, raw[i + hops * size:]


def packet_hash(raw_hex):
    """MeshCore's Packet::calculatePacketHash: SHA-256 of payload type (+ path length for TRACE) + payload, first 8 bytes."""
    try:
        _, _, ptype, plen, _, payload = _split(bytes.fromhex(raw_hex))
        h = hashlib.sha256(bytes([ptype]))
        if ptype == 9: h.update(plen.to_bytes(2, "little"))
        h.update(payload)
        return h.hexdigest()[:16].upper()
    except (ValueError, IndexError):
        return "0000000000000000"


def packet_message(raw_hex, snr, rssi, origin, origin_id, now=None):
    """One heard packet as the analyzers read it."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    raw = bytes.fromhex(raw_hex)
    _, route, ptype, _, path, payload = _split(raw)
    msg = {"origin": origin, "origin_id": origin_id.upper(), "timestamp": now.isoformat(), "type": "PACKET", "direction": "rx",
           "time": now.strftime("%H:%M:%S"), "date": now.strftime("%d/%m/%Y"), "len": str(len(raw)), "packet_type": str(ptype),
           "route": ROUTE_LETTER.get(route, "U"), "payload_len": str(len(payload)), "raw": raw_hex.upper(),
           "SNR": str(snr if snr is not None else "Unknown"), "RSSI": str(rssi if rssi is not None else "Unknown"), "hash": packet_hash(raw_hex)}
    if msg["route"] == "D" and path: msg["path"] = ",".join(path)
    return msg


def status_message(status, origin, origin_id, model="unknown", firmware="unknown", radio="unknown", now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return {"status": status, "timestamp": now.isoformat(), "origin": origin, "origin_id": origin_id.upper(), "model": model,
            "firmware_version": firmware, "radio": radio, "client_version": CLIENT_VERSION}
