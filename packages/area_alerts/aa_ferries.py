"""Area alerts: BC Ferries (British Columbia) - service notices and sailing delays, from bcferries.com (moved here from the Traffic,
transit and weather addon).  Read once every few minutes for all areas; each BC area gets the notices / delays that name a place in it.

  notices  the 'Service notices' page: agency-announced disruptions (breakdowns, weather cancellations), one per notice code
  delays   the 'Departures' page: a sailing that left 15+ minutes late, or whose status says delay / incident / cancel"""
import datetime
import html
import re
import time

from aa_sources import Alert, UA, short

NOTICES_URL = "https://www.bcferries.com/current-conditions/service-notices?feed=rss"
DEPARTURES_URL = "https://www.bcferries.com/current-conditions/departures"
LATE_MIN = 15                                    # minutes late that count as a delay on their own
SIGNAL_WORDS = ("delay", "incident", "cancel", "problem", "disruption")      # a status that counts whatever the minutes
CACHE_S = 240
# the places each BC area covers, as bcferries.com names them (routes, terminals, regions)
LM = ("lower mainland", "vancouver", "tsawwassen", "horseshoe bay", "west vancouver", "delta", "richmond", "bowen")
VI = ("vancouver island", "victoria", "swartz bay", "nanaimo", "departure bay", "duke point", "salt spring", "gabriola", "comox", "campbell river",
      "quadra", "cortes", "denman", "hornby", "alert bay", "sointula", "mill bay", "brentwood", "southern gulf islands", "port hardy", "duncan")
SC = ("sunshine coast", "langdale", "gibsons", "sechelt", "earls cove", "saltery bay", "powell river", "texada", "lund")
NORTH = ("prince rupert", "haida gwaii", "skidegate", "alliford bay", "bella coola", "bella bella", "klemtu", "north coast", "central coast")
GROUPS = {"lower mainland": LM + SC, "metro vancouver": LM, "fraser valley": LM, "vancouver island": VI, "sunshine coast": SC,
          "capital regional district (victoria)": VI, "cowichan valley": VI, "comox valley": VI, "north coast (prince rupert)": NORTH,
          "sea to sky (squamish-lillooet)": ("horseshoe bay", "bowen")}
_cache = {"t": 0.0, "items": None}


def _get(url):
    import requests
    for attempt in (1, 2):                       # bcferries.com often times out once
        try:
            r = requests.get(url, headers=UA, timeout=25)
            r.raise_for_status()
            return r.text
        except Exception:
            if attempt == 2: raise


def _plain(text): return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", text or "")).split())


def _minutes(t):
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)", (t or "").strip(), re.I)
    if not m: return None
    h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "PM" and h != 12: h += 12
    if ap == "AM" and h == 12: h = 0
    return h * 60 + mn


def notices(page):
    """[(id, title, where)] from the service notices page."""
    out, region = [], ""
    for m in re.finditer(r'<h[2-4][^>]*>(.*?)</h[2-4]>|<a[^>]+href="([^"]*serviceNoticeCode=[^"]*)"[^>]*>(.*?)</a>', page, re.S):
        if m.group(1) is not None: region = _plain(m.group(1)); continue
        title = _plain(m.group(3))
        if not title: continue
        code = re.search(r"serviceNoticeCode=(\d+)", m.group(2))
        out.append((f"bcf:{code.group(1) if code else abs(hash(title))}", title, region))
    return out


_ROW = re.compile(r"^(?P<ferry>.*?)\s*SCHEDULED:\s*(\d{1,2}:\d{2}\s*[AP]M)(?:\s*ACTUAL:\s*(\d{1,2}:\d{2}\s*[AP]M))?"
                  r"(?:\s*(?:ARRIVAL|ETA):\s*(?:\d{1,2}:\d{2}\s*[AP]M|Variable))?\s*(?P<status>.*)$", re.I)


def delays(page, today=None):
    """[(id, title, where)] for the sailings that left late (or whose status reports a problem)."""
    out, terminal, route = [], "", ""
    today = today or datetime.date.today().isoformat()
    for b in re.finditer(r"<h3[^>]*>(.*?)</h3>|<table[^>]*>(.*?)</table>", page, re.S | re.I):
        if b.group(1) is not None: terminal = _plain(b.group(1)); continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", b.group(2), re.S | re.I):
            txt = _plain(row)
            if "sailing duration" in txt.lower(): route = re.split(r"\s*Sailing duration", txt, flags=re.I)[0].strip(); continue
            m = _ROW.match(txt) if "SCHEDULED:" in txt.upper() else None
            if not m: continue
            sched, actual = _minutes(m.group(2)), _minutes(m.group(3))
            if sched is None or actual is None: continue            # not left yet
            late = actual - sched + (1440 if actual - sched < -600 else 0)
            status = (m.group("status") or "").strip()
            if late < LATE_MIN and not any(w in status.lower() for w in SIGNAL_WORDS): continue
            ferry = m.group("ferry").strip()
            title = f"{route}: {ferry} ~{late} min late" if late > 0 else f"{route}: {ferry} delay reported"
            out.append((f"bcf-delay:{route}:{ferry}:{m.group(2)}:{today}".replace(" ", "_"), title + (f" - {status}" if status else ""), f"{route} {terminal}"))
    return out


def ferries(area, get=None, now=None):
    """BC Ferries' notices and delays that name a place in this BC area; [] outside British Columbia."""
    if (area.get("country"), area.get("region")) != ("CA", "British Columbia"): return []
    now = now or time.time()
    if get is not None or _cache["items"] is None or now - _cache["t"] > CACHE_S:
        items, errors = [], []
        for url, parse in ((NOTICES_URL, notices), (DEPARTURES_URL, delays)):
            try: items += parse((get or _get)(url))
            except Exception as e: errors.append(e)
        if len(errors) == 2: raise errors[0]
        _cache.update(t=now, items=items)
    words = GROUPS.get(area["name"].lower()) or tuple(w for w in {area["name"].lower(), (area.get("district") or "").lower()} if w)
    return [Alert(i, "ferries", short(f"BC Ferries: {title}"), "BC Ferries") for i, title, where in _cache["items"]
            if any(w in f"{title} {where}".lower() for w in words)]
