"""Nodes dashboard - the data side (no tkinter): reading a heard advert, the history kept per node, and the numbers the window shows."""
import bisect, json, os, random

TYPE_ADVERT = 4                                    # payload type of an advert (header bits 2-5)
TYPE_NAMES = {1: "Companion", 2: "Repeater", 3: "Room server", 4: "Sensor"}
RELAY_TYPES = (2, 3)                               # nodes that repeat packets (repeaters, room servers)
KEEP_EVENTS = 3000                                 # per node, whatever the days setting says
ONLINE, QUIET = 3600, 86400                        # heard within an hour: online; within a day: quiet; longer: silent
KINDS = ("advert", "relay", "msg")


def split_path(path_hex, size=1):
    """'a1b2c3' with 1-byte hashes -> ['a1', 'b2', 'c3']."""
    step = 2 * max(1, int(size or 1))
    path_hex = (path_hex or "").lower()
    return [path_hex[i:i + step] for i in range(0, len(path_hex) - step + 1, step)]


def advert_key(hexstr):
    """A raw advert packet (hex, as it went over the air) -> the advertising node's public key (hex); None when it isn't one."""
    try:
        b = bytes.fromhex(hexstr or "")
        route, ptype, i = b[0] & 0x03, (b[0] >> 2) & 0x0F, 1
        if ptype != TYPE_ADVERT: return None
        if route in (0, 3): i += 4                                                      # transport codes
        plen = b[i]
        i += 1 + (plen & 0x3F) * ((plen >> 6) + 1)                                      # hop count x hash size (newer firmware)
        pub = b[i:i + 32]
        return pub.hex() if len(pub) == 32 else None
    except (ValueError, IndexError, TypeError):
        return None


def relay_owner(prefix, relay_keys):
    """The one repeater / room server whose key starts with this path hop; None when none or several do (1-byte hops are often shared)."""
    prefix = (prefix or "").lower()
    if not prefix: return None
    found = [k for k in relay_keys if k.lower().startswith(prefix)]
    return found[0] if len(found) == 1 else None


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)


class History:
    """Per node, events [t, kind, snr, rssi, hops], oldest first: 'advert' (its own advert heard), 'relay' (it repeated a packet straight
    to your radio - the signal is that link's), 'msg' (it wrote in a channel or to you).  path None: kept in memory only (demo)."""
    def __init__(self, path=None): self.path, self.ev, self.dirty = path, {}, False

    def load(self):
        if not self.path or not os.path.exists(self.path): return
        with open(self.path, encoding="utf-8") as f: data = json.load(f)
        self.ev = {k: [list(e) for e in v if isinstance(e, list) and len(e) == 5] for k, v in (data.get("events") or {}).items() if isinstance(v, list)}

    def snapshot(self): return {"version": 1, "events": {k: list(v) for k, v in self.ev.items()}}

    def save(self):
        if self.path: write_json(self.path, self.snapshot())
        self.dirty = False

    def add(self, key, t, kind, snr=None, rssi=None, hops=None):
        ev = self.ev.setdefault(key, [])
        e = [round(t, 1), kind, snr, rssi, hops]
        if not ev or ev[-1][0] <= e[0]: ev.append(e)
        else: ev.insert(bisect.bisect([x[0] for x in ev], e[0]), e)
        del ev[:-KEEP_EVENTS]
        self.dirty = True

    def events(self, key, since=0): return [e for e in self.ev.get(key, ()) if e[0] >= since]

    def last(self, key, kind):
        return next((e for e in reversed(self.ev.get(key, ())) if e[1] == kind), None)

    def newest(self): return max((v[-1][0] for v in self.ev.values() if v), default=0)

    def forget(self, key):
        if self.ev.pop(key, None) is not None: self.dirty = True

    def trim(self, now, days):
        cutoff = now - max(1, days) * 86400
        for k in list(self.ev):
            kept = [e for e in self.ev[k] if e[0] >= cutoff]
            if len(kept) != len(self.ev[k]): self.ev[k], self.dirty = kept, True


def status(now, last):
    if not last: return "never"
    return "online" if now - last < ONLINE else "quiet" if now - last < QUIET else "silent"


def node_rows(keys, known, heard_by, hist, now, span):
    """One dict per dashboard node for the table and graphs: what the node store knows, plus the history of the last `span` seconds."""
    out = []
    for k in keys:
        n, ev, allev = known.get(k, {}), hist.events(k, now - span), hist.ev.get(k, [])
        last = max([n.get("last_seen") or 0] + [e[0] for e in allev[-1:]])
        snrs = [e[2] for e in ev if isinstance(e[2], (int, float))]
        adv = hist.last(k, "advert")
        out.append({"key": k, "name": n.get("name") or k[:8], "type": TYPE_NAMES.get(n.get("type"), "?"), "last": last, "status": status(now, last),
                    "via": ", ".join(sorted(heard_by.get(k, ()))), "adverts": sum(e[1] == "advert" for e in ev),
                    "relays": sum(e[1] == "relay" for e in ev), "msgs": sum(e[1] == "msg" for e in ev),
                    "snr": snrs[-1] if snrs else None, "best": max(snrs) if snrs else None, "hops": adv[4] if adv else None,
                    "lat": n.get("lat"), "lon": n.get("lon"), "first": n.get("first_seen"), "events": ev})
    return out


def buckets(events, now, span, n):
    """Counts per kind in n equal slices of the last `span` seconds, oldest first."""
    size, start = span / n, now - span
    out = [dict.fromkeys(KINDS, 0) for _ in range(n)]
    for e in events:
        i = int((e[0] - start) / size)
        if 0 <= i < n and e[1] in KINDS: out[i][e[1]] += 1
    return out


def demo_history(nodes, now, seed=7):
    """Made-up events for `--demo`: [(key, type)] -> History (repeaters relay all day, companions advert and chat; the last one has gone silent)."""
    rng, hist = random.Random(seed), History(None)
    for i, (key, typ) in enumerate(nodes):
        stop = now - 30 * 3600 if i == len(nodes) - 1 and len(nodes) > 2 else now
        snr, t = rng.uniform(-6, 9), now - 2 * 86400
        while t < stop:
            snr = max(-15, min(12, snr + rng.uniform(-1.5, 1.5)))
            if typ in RELAY_TYPES:
                hist.add(key, t, "relay", round(snr, 1), int(-100 + snr * 2), None)
                if rng.random() < 0.04: hist.add(key, t + 5, "advert", round(snr, 1), int(-100 + snr * 2), rng.choice((0, 0, 1)))
                t += rng.uniform(60, 900)
            else:
                hist.add(key, t, rng.choice(("advert", "msg", "msg")), round(snr, 1), int(-105 + snr * 2), rng.choice((1, 2, 2, 3)))
                t += rng.uniform(900, 7200)
    return hist
