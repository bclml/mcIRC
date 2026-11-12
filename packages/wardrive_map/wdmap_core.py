"""Wardrive map - the data side (no tkinter): who was heard where.

Each record: where you were (your node's position at the time), which repeater your radio heard directly (the last hop of the packet's
path, or a repeater's own advert heard with no hops), and how well (SNR, RSSI).  Records are kept in a JSON file on this PC."""
import json
import math
import os

KEEP = 20000                       # records at most (the oldest go first)
SAME_SPOT = 60                     # seconds: the same repeater heard again at the same spot within this keeps only the best
GRID = 3                           # decimals of lat/lon a map spot is rounded to (about 100 m)
STRONG, WEAK = 5.0, -5.0           # SNR limits of the map's strong / weak layers (dB)
RELAY_TYPES = (2, 3)               # repeaters and room servers


def split_path(path_hex, size=1):
    step = 2 * max(1, int(size or 1))
    path_hex = (path_hex or "").lower()
    return [path_hex[i:i + step] for i in range(0, len(path_hex) - step + 1, step)]


def relay_owner(prefix, relay_keys):
    """The one repeater whose key starts with this path hop; None when none or several do (1-byte hops are often shared)."""
    found = [k for k in relay_keys if k.lower().startswith((prefix or "").lower())] if prefix else []
    return found[0] if len(found) == 1 else None


def advert_key(hexstr):
    """A raw advert packet (hex) -> the advertising node's public key, or None."""
    try:
        b = bytes.fromhex(hexstr or "")
        route, ptype, i = b[0] & 0x03, (b[0] >> 2) & 0x0F, 1
        if ptype != 4: return None
        if route in (0, 3): i += 4
        plen = b[i]
        i += 1 + (plen & 0x3F) * ((plen >> 6) + 1)
        pub = b[i:i + 32]
        return pub.hex() if len(pub) == 32 else None
    except (ValueError, IndexError, TypeError):
        return None


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(min(1.0, math.sqrt(a)))


class Log:
    """The records: [t, lat, lon, key, snr, rssi]."""
    def __init__(self, path=None): self.path, self.rows, self.dirty = path, [], False

    def load(self):
        if not self.path or not os.path.exists(self.path): return
        with open(self.path, encoding="utf-8") as f: data = json.load(f)
        self.rows = [r for r in data.get("rows", []) if isinstance(r, list) and len(r) == 6]

    def save(self):
        if self.path:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f: json.dump({"version": 1, "rows": self.rows}, f, separators=(",", ":"))
            os.replace(tmp, self.path)
        self.dirty = False

    def add(self, t, lat, lon, key, snr, rssi=None):
        """One sighting; the same repeater at the same spot within SAME_SPOT seconds keeps only the better signal."""
        spot = (round(lat, GRID), round(lon, GRID))
        for r in reversed(self.rows[-50:]):
            if t - r[0] > SAME_SPOT: break
            if r[3] == key and (round(r[1], GRID), round(r[2], GRID)) == spot:
                if snr > r[4]: r[4], r[5] = snr, rssi
                self.dirty = True
                return False
        self.rows.append([round(t, 1), round(lat, 6), round(lon, 6), key, snr, rssi])
        del self.rows[:-KEEP]
        self.dirty = True
        return True

    def clear(self): self.rows, self.dirty = [], True

    def spots(self, key=None):
        """Map spots: {(lat, lon) rounded: (best snr, key of the best, how many repeaters heard there)} - for one repeater or all."""
        out = {}
        for t, lat, lon, k, snr, rssi in self.rows:
            if key and k != key: continue
            s = (round(lat, GRID), round(lon, GRID))
            best, bkey, keys = out.get(s, (None, None, set()))
            keys = keys | {k}
            out[s] = (snr, k, keys) if best is None or snr > best else (best, bkey, keys)
        return {s: (b, k, len(ks)) for s, (b, k, ks) in out.items()}

    def per_repeater(self, nodes):
        """{key: {'name', 'count', 'best', 'best_at', 'far_km', 'last'}}; far_km: the farthest spot it was heard from (when its
        own position is known)."""
        info = {n["public_key"]: n for n in nodes}
        out = {}
        for t, lat, lon, k, snr, rssi in self.rows:
            n = info.get(k, {})
            r = out.setdefault(k, {"name": n.get("name") or k[:8], "count": 0, "best": None, "best_at": None, "far_km": None, "last": 0})
            r["count"] += 1
            r["last"] = max(r["last"], t)
            if r["best"] is None or snr > r["best"]: r["best"], r["best_at"] = snr, (lat, lon)
            if n.get("lat") or n.get("lon"):
                d = distance_km(lat, lon, n["lat"], n["lon"])
                r["far_km"] = d if r["far_km"] is None else max(r["far_km"], d)
        return out


def layer(spots, names, kind):
    """One map layer's points: (lat, lon, label) for the spots whose best SNR is 'strong' / 'fair' / 'weak'."""
    out = []
    for (lat, lon), (snr, key, n) in spots.items():
        k = "strong" if snr >= STRONG else "weak" if snr < WEAK else "fair"
        if k != kind: continue
        more = f" (+{n - 1} more)" if n > 1 else ""
        out.append((lat, lon, f"{names.get(key, key[:8])} {snr:+.1f} dB{more}"))
    return out
