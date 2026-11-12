"""Repeater manager - the data side (no tkinter): the meshcli commands for a repeater (log in, status, neighbours, telemetry, a remote
command), reading their answers, and the status history kept for the graphs."""
import json
import os
import re

KEEP = 2000                        # status readings per repeater at most
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# remote commands that change or stop the repeater: always asked about first
DANGEROUS = ("reboot", "poweroff", "shutdown", "clkreboot", "start ota", "erase", "password", "set ", "setperm", "neighbor.remove", "clear stats",
             "region remove", "region save", "tempradio")


def dangerous(cmd):
    """True for a remote command that changes or stops the repeater ('reboot', 'set tx 22', 'password x' ...)."""
    c = " ".join((cmd or "").lower().split())
    return any(c == d.strip() or c.startswith(d.strip() + " ") for d in DANGEROUS)


def request_args(key, what, password=None, text=None):
    """meshcli arguments (after the connection ones) for one request to the repeater with this public key.
    what: 'login' | 'status' | 'neighbours' | 'telemetry' | 'cmd'.  A known password logs in first (it stays in memory only)."""
    login = ["login", key, password] if password else []
    if what == "login": return ["-j"] + ["login", key, password or ""]
    if what == "status": return ["-j"] + login + ["req_status", key]
    if what == "neighbours": return ["-j"] + login + ["req_neighbours", key]
    if what == "telemetry": return ["-j"] + login + ["req_telemetry", key]
    if what == "cmd": return login + ["cmd", key, text, "wmt8"]
    raise ValueError(what)


def readd_args(key, ctype, name, args):
    """The same request, after putting the repeater back on the radio's contact list from mcIRC's memory (flood routed) - for when the radio
    has forgotten it (its contact list was full, or it was pruned)."""
    flags = [a for a in args if a == "-j"]
    rest = [a for a in args if a != "-j"]
    return flags + ["add_contact", key, str(ctype or 2), name or key[:8], "reset_path", key] + rest


def unknown_contact(text):
    t = (text or "").lower()
    return "unknown contact" in t or "contact unknown" in t or "unknown destination" in t


def json_docs(text):
    """Every JSON document meshcli printed, in order (its log lines skipped)."""
    docs, dec, i = [], json.JSONDecoder(), 0
    while True:
        j = text.find("{", i)
        if j == -1: return docs
        try:
            obj, i = dec.raw_decode(text, j)
            docs.append(obj)
        except ValueError:
            i = j + 1


def clean_lines(text):
    """A remote command's answer: the lines without meshcli's INFO / DEBUG logging and colour codes."""
    lines = ANSI.sub("", text or "").splitlines()
    return [l.rstrip() for l in lines if l.strip() and not re.match(r"^(INFO|DEBUG|WARNING):", l)]


def parse(text):
    """What a request answered: {'login': True/False/None, 'status': {...}, 'neighbours': {...}, 'telemetry': [...], 'error': str}."""
    out = {"login": None, "status": None, "neighbours": None, "telemetry": None, "error": ""}
    for d in json_docs(text):
        if "login_success" in d: out["login"] = bool(d["login_success"])
        elif "bat" in d and "uptime" in d: out["status"] = d
        elif "neighbours" in d: out["neighbours"] = d
        elif "lpp" in d: out["telemetry"] = d["lpp"] if isinstance(d["lpp"], list) else []
        elif "error" in d and not out["error"]: out["error"] = str(d["error"])
    if not out["error"] and "Login failed" in text: out["login"], out["error"] = False, "login failed (wrong password, or no reply)"
    if not out["error"] and "Error getting data" in text: out["error"] = "no answer (out of range, or it wants a login)"
    return out


def duration(secs):
    secs = int(secs or 0)
    d, h, m = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    return f"{d} d {h} h" if d else f"{h} h {m} min" if h else f"{m} min"


def status_text(st):
    """One readable line from a req_status answer."""
    parts = [f"battery {st.get('bat', 0) / 1000:.2f} V", f"up {duration(st.get('uptime'))}", f"noise {st.get('noise_floor')} dBm",
             f"last signal {st.get('last_rssi')} dBm / SNR {st.get('last_snr')}", f"received {st.get('nb_recv')}", f"sent {st.get('nb_sent')}",
             f"airtime {duration(st.get('airtime'))}", f"queue {st.get('tx_queue_len')}"]
    if st.get("recv_errors") is not None: parts.append(f"receive errors {st['recv_errors']}")
    return ", ".join(parts)


def neighbours_text(res, names):
    """The repeater's neighbours, strongest first: 'Hilltop RPT +6.5 dB (2 min ago)'."""
    rows = sorted(res.get("neighbours") or [], key=lambda n: -(n.get("snr") or -99))
    if not rows: return "no neighbours"
    def who(prefix):
        hit = [nm for k, nm in names.items() if k.lower().startswith((prefix or "").lower())]
        return hit[0] if len(hit) == 1 else f"[{prefix}]"
    return "; ".join(f"{who(n.get('pubkey'))} {n.get('snr', 0):+.1f} dB ({duration(n.get('secs_ago'))} ago)" for n in rows) + \
           f"  ({res.get('results_count', len(rows))} of {res.get('neighbours_count', len(rows))})"


def telemetry_text(lpp):
    """'voltage 4.12 (ch 1), temperature 21.5 (ch 2)'."""
    if not lpp: return "no telemetry"
    def val(v): return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else json.dumps(v) if isinstance(v, (dict, list)) else str(v)
    return ", ".join(f"{e.get('type')} {val(e.get('value'))} (ch {e.get('channel')})" for e in lpp)


class History:
    """Status readings per repeater: [t, battery mV, noise floor, last rssi, last snr, received, sent, airtime s, uptime s]."""
    def __init__(self, path=None): self.path, self.rows, self.dirty = path, {}, False

    def load(self):
        if not self.path or not os.path.exists(self.path): return
        with open(self.path, encoding="utf-8") as f: data = json.load(f)
        self.rows = {k: [r for r in v if isinstance(r, list) and len(r) == 9] for k, v in (data.get("rows") or {}).items()}

    def save(self):
        if self.path:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f: json.dump({"version": 1, "rows": self.rows}, f, separators=(",", ":"))
            os.replace(tmp, self.path)
        self.dirty = False

    def add(self, key, t, st):
        self.rows.setdefault(key, []).append([round(t), st.get("bat"), st.get("noise_floor"), st.get("last_rssi"), st.get("last_snr"),
                                              st.get("nb_recv"), st.get("nb_sent"), st.get("airtime"), st.get("uptime")])
        del self.rows[key][:-KEEP]
        self.dirty = True

    def last(self, key): return (self.rows.get(key) or [None])[-1]

    def forget(self, key):
        if self.rows.pop(key, None) is not None: self.dirty = True

    def series(self, key, col, since=0):
        """[(t, value)] of one column (1 battery mV, 2 noise floor, 5 received ...) for the graphs."""
        return [(r[0], r[col]) for r in self.rows.get(key, []) if r[0] >= since and isinstance(r[col], (int, float))]

    def per_hour(self, key, col, since=0):
        """A counter (received / sent) as a rate per hour between readings; a restart (the counter going back) is skipped."""
        rows = [r for r in self.rows.get(key, []) if r[0] >= since and isinstance(r[col], (int, float))]
        out = []
        for a, b in zip(rows, rows[1:]):
            if b[col] >= a[col] and b[0] > a[0]: out.append((b[0], (b[col] - a[col]) / (b[0] - a[0]) * 3600))
        return out
