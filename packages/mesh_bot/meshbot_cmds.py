"""The Mesh bot's commands, after agessaman/meshcore-bot (MIT): ping, hello, path, prefix, multitest, stats, sports, version, greeter.
Plain functions - the addon (mesh_bot.py) wires them to the mesh."""
import datetime
import random
import re

# ---- hello (robot greetings, from meshcore-bot's hello command) ----
GREETINGS = ["hello", "hi", "hey", "howdy", "greetings", "salutations", "good morning", "good afternoon", "good evening", "yo", "sup",
             "whats up", "what's up", "morning", "evening", "gday", "g'day", "hola", "bonjour", "ciao", "aloha"]
OPENINGS = ["Hello", "Greetings", "Salutations", "Hi", "Hey", "Howdy", "Well met", "Hail", "Ahoy", "Bonjour", "Hola", "Aloha", "G'day", "Cheers",
            "Welcome", "Nice to see you", "Good to see you", "Fancy meeting you here"]
MORNING = ["Good morning", "Top o' the morning", "Buenos dias", "Bonjour", "Guten morgen", "Buongiorno"]
AFTERNOON = ["Good afternoon", "Buenas tardes", "Boa tarde"]
EVENING = ["Good evening", "Buenas noches", "Boa noite", "Konbanwa"]
DESCRIPTORS = ["human", "carbon-based lifeform", "organic entity", "biological unit", "meat-based organism", "carbon unit", "flesh bot",
               "bipedal mammal", "water-based organism", "protein assembler", "fellow sentient being", "earthling", "fellow traveler",
               "kindred spirit", "friend", "buddy", "pal", "fellow human", "planet walker", "carbon-based buddy", "organic pal"]


def is_greeting(text):
    t = re.sub(r"[^a-z' ]", "", (text or "").lower()).strip()
    return t in GREETINGS


def hello(bot_name, hour=None, rng=random):
    hour = datetime.datetime.now().hour if hour is None else hour
    pool = OPENINGS + (MORNING if 5 <= hour < 12 else AFTERNOON if 12 <= hour < 17 else EVENING)
    sep = rng.choice([", ", " "])
    return f"{rng.choice(pool)}{sep}{rng.choice(DESCRIPTORS)}{rng.choice(['!', '.', '!', '!'])} I'm {bot_name}."


# ---- path / prefix: which repeaters a path or a key prefix stands for ----
HOP_RE = re.compile(r"^(?:[0-9a-f]{2}){1,3}$")


def split_hops(text):
    """'a1,b2 c3' / 'a1b2c3' (a run without commas: 1-byte hops) / 'a1b2,c3d4' (2-byte hops need commas) -> ['A1', 'B2', 'C3'] ...;
    ValueError when it isn't hex."""
    t = (text or "").strip().lower().replace(">", ",").replace(" ", ",")
    parts = [p for p in t.split(",") if p]
    if len(parts) == 1 and "," not in t and len(parts[0]) > 2:    # one run without separators: 1-byte hops
        parts = [parts[0][i:i + 2] for i in range(0, len(parts[0]), 2)]
    if not parts or not all(HOP_RE.match(p) for p in parts): raise ValueError("No valid hex values found in path data.")
    return [p.upper() for p in parts]


def repeaters_with_prefix(nodes, prefix):
    """Repeaters / room servers in node memory whose key starts with `prefix`, newest heard first."""
    p = prefix.lower()
    found = [n for n in nodes if n.get("type") in (2, 3) and (n.get("public_key") or "").lower().startswith(p)]
    return sorted(found, key=lambda n: -(n.get("last_seen") or 0))


def describe_hop(nodes, hop):
    m = repeaters_with_prefix(nodes, hop)
    if not m: return f"{hop}: Unknown"
    if len(m) == 1: return f"{hop}: {m[0]['name']}"
    return f"{hop}: {m[0]['name']} (or {len(m) - 1} more)"


def path_text(nodes, hops):
    if not hops: return "Direct connection (0 hops)"
    return "Path: " + " > ".join(describe_hop(nodes, h) for h in hops)


def prefix_text(nodes, arg, now):
    """'prefix A1' -> the repeaters using it; 'prefix free' -> some 1-byte prefixes no known repeater uses."""
    a = (arg or "").strip().lower()
    reps = [n for n in nodes if n.get("type") in (2, 3)]
    if a == "free":
        used = {(n.get("public_key") or "")[:2].lower() for n in reps}
        free = [f"{i:02X}" for i in range(1, 255) if f"{i:02x}" not in used]
        return f"Free prefixes ({len(free)} of 254): " + " ".join(free[:30]) + (" ..." if len(free) > 30 else "")
    if not re.fullmatch(r"(?:[0-9a-f]{2}){1,3}", a): return "Usage: prefix A1 (2, 4 or 6 hex characters), or prefix free"
    m = repeaters_with_prefix(reps, a)
    if not m: return f"No repeaters found with prefix '{a.upper()}'"
    ago = lambda t: f"{int((now - t) / 86400)}d" if now - t >= 86400 else f"{int((now - t) / 3600)}h" if now - t >= 3600 else "now"
    return f"Prefix {a.upper()}: {len(m)} repeater{'s' if len(m) > 1 else ''}: " + ", ".join(f"{n['name']} ({ago(n.get('last_seen') or now)})" for n in m[:6])


# ---- the packets the listener heard around a message (path / multitest) ----
def heard_around(packet_log, t, before=20, after=0, kind="GRP_TXT"):
    return [p for p in packet_log if p.get("type") == kind and t - before <= p.get("t", 0) <= t + after]


def path_of_message(packet_log, msg_t, hops):
    """The path of the packet that brought a message: the newest channel packet heard just before it with that many hops."""
    cands = [p for p in heard_around(packet_log, msg_t, before=20) if len(split_path(p.get("path", ""), p.get("size", 1))) == (hops or 0)]
    return split_path(cands[-1]["path"], cands[-1].get("size", 1)) if cands else None


def split_path(path_hex, size=1):
    h = (path_hex or "").upper()
    n = 2 * max(1, int(size or 1))
    return [h[i:i + n] for i in range(0, len(h), n)] if h else []


def multitest_paths(packet_log, msg_t, window=6):
    """The different paths the same message arrived by: channel packets of the same size heard from just before it until `window` s after."""
    near = heard_around(packet_log, msg_t, before=8, after=window)
    if not near: return []
    size = min(near, key=lambda p: abs(p.get("t", 0) - msg_t)).get("length")
    seen, out = set(), []
    for p in near:
        if p.get("length") != size: continue
        hops = tuple(split_path(p.get("path", ""), p.get("size", 1)))
        if hops not in seen: seen.add(hops); out.append(list(hops))
    return out


def multitest_text(paths):
    if not paths: return "Multitest: no copies of your message heard"
    show = ["direct" if not p else ">".join(p) for p in paths]
    return f"Multitest: {len(paths)} path{'s' if len(paths) > 1 else ''}: " + ", ".join(show)


# ---- stats (24 h) ----
SESSION_RE = re.compile(r"^Session (?:Start|Close): \w{3} (\w{3} \d{2} \d{2}:\d{2}:\d{2} \d{4})")
LINE_RE = re.compile(r"^\[(\d{2}):(\d{2})\] <([^>]*)>")


def channel_activity(log_dir, now, me="", seconds=86400, tail_bytes=512 * 1024, with_extra=False):
    """{channel: messages in the last `seconds`} from mcIRC's chat logs (logs/<channel>.txt): every '<name> ...' line except our own.
    The logs carry the date on their 'Session Start' lines and only the time on each message, so the date is followed through the file."""
    import os
    out = {}
    try: files = os.listdir(log_dir)
    except OSError: return out
    for fn in files:
        if not fn.endswith(".txt") or fn.endswith(".old.txt") or fn.startswith(("@", "Status", "gui_")): continue
        if " [" in fn and not with_extra: continue                     # 'Public [wifi 1]': another node, another mesh
        try:
            with open(os.path.join(log_dir, fn), "rb") as f:
                f.seek(0, 2); f.seek(max(0, f.tell() - tail_bytes))
                lines = f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        day, last, n = None, None, 0
        for line in lines:
            m = SESSION_RE.match(line)
            if m:
                try: day = datetime.datetime.strptime(m.group(1), "%b %d %H:%M:%S %Y")
                except ValueError: day = None
                last = day
                continue
            m = LINE_RE.match(line)
            if not m or day is None: continue
            t = day.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0)
            while last and t < last - datetime.timedelta(minutes=5): t += datetime.timedelta(days=1)    # past midnight in the same session
            last = t
            if m.group(3) != me and 0 <= now - t.timestamp() <= seconds: n += 1
        if n: out[fn[:-4]] = n
    return out


def stats_text(packet_log, nodes, activity, now, since=None):
    """Last 24 h: nodes your node heard, the busiest channels (from the chat logs); packets the listener heard since mcIRC started.
    'Heard' goes by lastmod - stamped by YOUR node's clock when it hears a node's advert or path - not by the advert's own time: many
    nodes' clocks are wrong (some by years)."""
    adv = sum(1 for n in nodes if 0 <= now - (n.get("lastmod") or 0) <= 86400)
    busy = sorted(activity.items(), key=lambda kv: -kv[1])[:3]
    chans = ", ".join(f"{c} {k}" for c, k in busy) if busy else "none"
    pk = [p for p in packet_log if now - p.get("t", 0) <= 86400]
    start = since if since and now - since < 86400 else None
    pk_part = f"{len(pk)} packets heard" + (f" since {datetime.datetime.fromtimestamp(start).strftime('%H:%M')}" if start else "")
    return f"Mesh 24h: {adv} nodes heard; busiest channels {chans} msgs; {pk_part}"


# ---- sports (ESPN, like meshcore-bot) ----
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUES = {"nhl": ("hockey", "nhl"), "nba": ("basketball", "nba"), "wnba": ("basketball", "wnba"), "nfl": ("football", "nfl"),
           "mlb": ("baseball", "mlb"), "mls": ("soccer", "usa.1"), "epl": ("soccer", "eng.1"), "cfl": ("football", "cfl")}


def game_line(ev):
    c = ev["competitions"][0]
    teams = sorted(c["competitors"], key=lambda t: t.get("homeAway") != "away")
    st = c["status"]["type"]
    a, h = teams[0]["team"]["abbreviation"], teams[-1]["team"]["abbreviation"]
    if st.get("state") == "pre": return f"{a} @ {h} {st.get('shortDetail', '')}"
    return f"{a} {teams[0].get('score', '')}-{teams[-1].get('score', '')} {h} ({st.get('shortDetail', '')})"


def sports_text(arg, get, default_teams=()):
    """'sports nhl' -> today's NHL games; 'sports canucks' -> that team's game; 'sports' -> the default teams'."""
    q = (arg or "").strip().lower()
    if q in LEAGUES:
        sport, league = LEAGUES[q]
        evs = get(f"{ESPN}/{sport}/{league}/scoreboard").get("events", [])
        return f"{q.upper()}: " + "; ".join(game_line(e) for e in evs[:4]) if evs else f"No games found for {q.upper()}"
    wanted = [q] if q else [t.strip().lower() for t in default_teams if t.strip()]
    if not wanted: return "Usage: sports <team or league> (nhl, nba, nfl, mlb, mls, epl, cfl, wnba)"
    lines = []
    for sport, league in LEAGUES.values():
        try: evs = get(f"{ESPN}/{sport}/{league}/scoreboard").get("events", [])
        except Exception: continue
        for e in evs:
            names = " ".join(f"{t['team'].get('displayName', '')} {t['team'].get('abbreviation', '')} {t['team'].get('name', '')}".lower()
                             for t in e["competitions"][0]["competitors"])
            if any(w in names for w in wanted) and game_line(e) not in lines: lines.append(game_line(e))
        if len(lines) >= 4: break
    if lines: return "; ".join(lines[:4])
    return f"No games found for {', '.join(wanted)} today"


# ---- greeter ----
# A random one of these for each newcomer (editable in the bot's settings), in the spirit of mIRC's Invision script.  The mesh carries
# plain text only: no mIRC colour codes (the phone apps would show them as junk and they eat into the short message limit).
DEFAULT_GREETINGS = [
    "Welcome to the mesh, @[{nick}]! Type bothelp for the bot commands.",
    "»» Welcome @[{nick}] to {channel} | Mesh: MeshCore | Script: m-c-I-R-C ««",
    "«°·.¸.·°» Attention everyone! @[{nick}] has graced us with their presence! «°·.¸.·°»",
    "»» @[{nick}] has entered the room. Everyone act natural... ««",
    "*** @[{nick}] has joined {channel} - say hi! (bothelp for the bot commands)",
]


def greeting_lines(text):
    """The greetings typed in the settings box: one per line, blank lines skipped."""
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def pick_greeting(lines, last=None):
    """A random greeting, not the same one twice in a row when there are several."""
    lines = list(lines) or DEFAULT_GREETINGS
    choices = [l for l in lines if l != last] or lines
    return random.choice(choices)


def greeting_for(nick, template, channel=""):
    return template.replace("{nick}", nick.replace("[", "").replace("]", "")).replace("{channel}", channel or "the mesh")


# ---- firmware (read-only: the newest MeshCore releases) ----
RELEASES_URL = "https://api.github.com/repos/meshcore-dev/MeshCore/releases?per_page=40"
FW_KINDS = (("companion", "companion"), ("repeater", "repeater"), ("room-server", "room server"))


def _vkey(v): return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v.lstrip("v")))


def firmware_text(releases):
    """'MeshCore firmware: companion v1.17.1, repeater v1.17.1, room server v1.17.1 (2026-08-14)' from GitHub's release list."""
    newest = {}
    for r in releases:
        tag = str(r.get("tag_name", ""))
        if r.get("prerelease") or r.get("draft"): continue
        for prefix, name in FW_KINDS:
            if tag.startswith(prefix + "-v"):
                v = tag[len(prefix) + 1:]
                if name not in newest or _vkey(v) > _vkey(newest[name][0]): newest[name] = (v, (r.get("published_at") or "")[:10])
    if not newest: return "No MeshCore firmware release found"
    parts = [f"{name} {newest[name][0]}" for _, name in FW_KINDS if name in newest]
    date = max(d for _, d in newest.values())
    return f"MeshCore firmware: {', '.join(parts)}" + (f" ({date})" if date else "") + " - github.com/meshcore-dev/MeshCore/releases"


# ---- is this really a newcomer? ----
def known_node(nodes, nick):
    """In mcIRC's node memory: that exact name, or another device of the same person (a remembered node whose name starts with it,
    e.g. 'Ann' and 'Ann-repeater')."""
    n = (nick or "").strip()
    if not n: return False
    names = [(x.get("name") or "").strip() for x in nodes]
    return n in names or (len(n) >= 4 and any(m.startswith(n) and m != n for m in names))


def known_from_logs(log_dir, nick, tail_bytes=1024 * 1024):
    """Has this name been in the chat before?  The message being greeted is already in the log, so: two or more lines written under
    that name, or anyone having mentioned it (@[name]) - in any channel's log (private chats are not read)."""
    import os
    if not log_dir or not nick: return False
    mentioned = f"@[{nick}]".encode()
    lines = 0
    try: files = os.listdir(log_dir)
    except OSError: return False
    for fn in files:
        if not fn.endswith(".txt") or fn.startswith(("@", "Status", "gui_")): continue
        try:
            with open(os.path.join(log_dir, fn), "rb") as f:
                f.seek(0, 2); f.seek(max(0, f.tell() - tail_bytes))
                data = f.read()
        except OSError:
            continue
        if mentioned in data: return True
        lines += data.count(f"] <{nick}> ".encode())
        if lines >= 2: return True
    return False
