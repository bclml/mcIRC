"""Channel activity - the numbers (no tkinter): how long each heard packet kept the channel busy (LoRa time on air), per-minute
buckets of what the radio heard, and the node's own noise floor / airtime counters."""
import json
import math
import statistics

PREAMBLE = 16                      # LoRa preamble symbols MeshCore sends
KEEP_MINUTES = 24 * 60             # a day of minute buckets


def time_on_air_ms(nbytes, sf=7, bw_khz=62.5, cr=5, preamble=PREAMBLE):
    """How long a LoRa packet of nbytes keeps the channel busy (Semtech's formula: explicit header, CRC on, low data rate
    optimisation when a symbol lasts more than 16 ms).  cr: 5..8 for coding rate 4/5..4/8."""
    t_sym = (2 ** sf) / (bw_khz * 1000) * 1000                  # ms per symbol
    de = 1 if t_sym > 16 else 0
    cr_n = max(1, min(4, int(cr) - 4))
    payload = 8 + max(math.ceil((8 * nbytes - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))) * (cr_n + 4), 0)
    return (preamble + 4.25) * t_sym + payload * t_sym


def packet_bytes(rec):
    """Bytes on air of a heard packet: its payload, plus the header byte, the path length byte and the path itself."""
    path_bytes = len(rec.get("path") or "") // 2
    return int(rec.get("length") or 0) + 2 + path_bytes


def minute(t): return int(t // 60) * 60


class Activity:
    """Per-minute buckets {minute start: {'n', 'air_ms', 'kinds': {type: n}, 'snr': [...], 'rssi': [...]}} and noise readings
    [(t, noise_floor, rx_air_secs, tx_air_secs)]."""
    def __init__(self): self.buckets, self.noise, self.last_t = {}, [], 0.0

    def add_packets(self, packets, sf, bw, cr):
        """The packets heard since the last call (packet_log entries); returns how many were new."""
        new = [p for p in packets if p.get("t", 0) > self.last_t]
        for p in new:
            b = self.buckets.setdefault(minute(p["t"]), {"n": 0, "air_ms": 0.0, "kinds": {}, "snr": [], "rssi": []})
            b["n"] += 1
            b["air_ms"] += time_on_air_ms(packet_bytes(p), sf, bw, cr)
            kind = p.get("type") or "?"
            b["kinds"][kind] = b["kinds"].get(kind, 0) + 1
            if isinstance(p.get("snr"), (int, float)): b["snr"].append(p["snr"])
            if isinstance(p.get("rssi"), (int, float)): b["rssi"].append(p["rssi"])
        if new: self.last_t = max(p["t"] for p in new)
        return len(new)

    def add_noise(self, t, stats):
        """A stats_radio reading of the node: noise floor (dBm) and its rx / tx airtime counters (seconds since it started)."""
        nf = stats.get("noise_floor")
        if isinstance(nf, (int, float)): self.noise.append((t, nf, stats.get("rx_air_secs"), stats.get("tx_air_secs")))
        del self.noise[:-2000]

    def trim(self, now):
        for k in [k for k in self.buckets if k < now - KEEP_MINUTES * 60]: del self.buckets[k]
        self.noise = [n for n in self.noise if n[0] >= now - KEEP_MINUTES * 60]

    def summary(self, now, minutes):
        """The numbers for the last `minutes`: packets per minute, estimated airtime %, kinds, median SNR / RSSI."""
        start = minute(now) - (minutes - 1) * 60
        bs = [b for k, b in self.buckets.items() if k >= start]
        n = sum(b["n"] for b in bs)
        kinds = {}
        for b in bs:
            for k, v in b["kinds"].items(): kinds[k] = kinds.get(k, 0) + v
        snr = [v for b in bs for v in b["snr"]]
        rssi = [v for b in bs for v in b["rssi"]]
        span_s = max(60.0, min(minutes * 60.0, now - start))
        return {"packets": n, "per_min": n / minutes, "air_pct": sum(b["air_ms"] for b in bs) / 1000 / span_s * 100,
                "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])), "snr": statistics.median(snr) if snr else None,
                "rssi": statistics.median(rssi) if rssi else None}

    def node_airtime_pct(self):
        """What the node itself counted: receive and transmit airtime between its last two readings, as % of the time between them."""
        rows = [r for r in self.noise if isinstance(r[2], (int, float)) and isinstance(r[3], (int, float))]
        if len(rows) < 2: return None
        (t0, _, rx0, tx0), (t1, _, rx1, tx1) = rows[-2], rows[-1]
        if t1 - t0 < 30 or rx1 < rx0 or tx1 < tx0: return None          # (the node restarted: its counters went back to zero)
        return (rx1 - rx0) / (t1 - t0) * 100, (tx1 - tx0) / (t1 - t0) * 100

    def series(self, now, minutes, step):
        """Graph data, oldest first, one row per `step` minutes: (start, packets per minute, airtime %)."""
        out, first = [], minute(now) - (minutes - step) * 60
        for i in range(minutes // step):
            s = first + i * step * 60
            bs = [self.buckets[k] for k in range(s, s + step * 60, 60) if k in self.buckets]
            out.append((s, sum(b["n"] for b in bs) / step, sum(b["air_ms"] for b in bs) / 1000 / (step * 60) * 100))
        return out


def parse_stats(text):
    """meshcli's '.get stats_radio' output -> the dict with 'noise_floor' in it (or {})."""
    dec, i = json.JSONDecoder(), 0
    while True:
        j = text.find("{", i)
        if j == -1: return {}
        try:
            obj, i = dec.raw_decode(text, j)
            if isinstance(obj, dict) and "noise_floor" in obj: return obj
        except ValueError:
            i = j + 1


def margin_word(db):
    """How far signals stand above the noise, in words."""
    return "good" if db >= 15 else "fair" if db >= 6 else "weak"
