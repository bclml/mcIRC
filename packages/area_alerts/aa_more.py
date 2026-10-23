"""Area alerts: what came over from the Traffic, transit and weather addon besides its alert feeds -
  * daily forecast posts: a 3-day forecast (6 AM by default) and a 5-day outlook (8 AM) for each area (Open-Meteo, free, no key)
  * the weekly reminder: Sundays around noon, which channels carry the alerts
  * moving that addon's settings over (move_settings): its channels are ADDED to what Area alerts has - nothing is overwritten or removed."""
import datetime
import re

from aa_sources import Alert, UA

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
EMOJI = {0: "☀️", 1: "☀️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️", 51: "🌦️", 53: "🌦️", 55: "🌦️", 61: "🌧️", 63: "🌧️", 65: "🌧️", 71: "❄️", 73: "❄️",
         75: "❄️", 80: "🌧️", 81: "🌧️", 82: "🌧️", 95: "⛈️", 96: "⛈️", 99: "⛈️"}
WEEKLY_TEXT = "Don't forget to check the traffic this week."
MAX_CHANNELS = 5


def _get(url, params):
    import requests
    r = requests.get(url, params=params, headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()


def forecast(area, hour, label, get=None):
    """The 6 AM 3-day forecast or the 8 AM 5-day outlook for an area, as one short message (an Alert for the 'weather' channel)."""
    daily = (get or _get)(OPEN_METEO, {"latitude": area["lat"], "longitude": area["lon"], "timezone": "auto",
                                       "daily": "weathercode,temperature_2m_max,temperature_2m_min"}).get("daily", {})
    days, codes, hi, lo = daily.get("time", []), daily.get("weathercode", []), daily.get("temperature_2m_max", []), daily.get("temperature_2m_min", [])
    name = lambda i, n=3: datetime.date.fromisoformat(days[i]).strftime("%a")[:n]
    if hour == 6 and len(days) >= 3 and len(hi) >= 3 and len(lo) >= 3:
        text = f"3-day forecast {area['name']}: " + " | ".join(f"{EMOJI.get(codes[i], '☀️')} {name(i)} H{round(hi[i])} L{round(lo[i])}" for i in range(3))
    elif hour == 8 and len(days) >= 5:
        text = f"5-day outlook {area['name']}: " + " ".join(f"{name(i, 1)}{EMOJI.get(codes[i], '☀️')}" for i in range(5))
    else: return None
    return Alert(f"forecast{hour}:{label}:{days[0]}", "weather", text, "Open-Meteo")


DEFAULT_TIMES = {6: "06:00", 8: "08:00"}        # which post (6 = the 3-day forecast, 8 = the 5-day outlook): its time of day


def parse_time(text, default=None):
    """'6', '06:30', '6:30 PM', '18:30', '7am' -> (hour, minute); default when it isn't a time."""
    m = re.fullmatch(r"\s*(\d{1,2})(?:[:h.](\d{2}))?\s*([ap])?\.?\s*m?\.?\s*", (text or "").lower())
    if not m: return default
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap:
        if not 1 <= h <= 12: return default
        h = h % 12 + (12 if ap == "p" else 0)
    return (h, mi) if h < 24 and mi < 60 else default


def shown_time(text, default):
    """A time as it is saved and shown: '06:30'."""
    h, mi = parse_time(text, parse_time(default))
    return f"{h:02d}:{mi:02d}"


def due_posts(now, sent, times=None, on=(6, 8)):
    """Which daily posts are due now, each once a day: from its time (times: {6: '06:00', 8: '08:00'}) for an hour - mcIRC started later
    in the day doesn't post a stale one.  sent: {'6': 'YYYY-MM-DD', ...}.  on: the posts switched on."""
    today, mins = now.date().isoformat(), now.hour * 60 + now.minute
    out = []
    for p in on:
        h, mi = parse_time((times or {}).get(p) or (times or {}).get(str(p)), parse_time(DEFAULT_TIMES[p]))
        if 0 <= mins - (h * 60 + mi) < 60 and sent.get(str(p)) != today: out.append(p)
    return out


def weekly_due(now, last):
    """Sundays 12:00-12:59, once a week (last: 'YYYY-Www' of the last one sent)."""
    week = "%d-W%02d" % now.isocalendar()[:2]
    return now.weekday() == 6 and now.hour == 12 and last != week, week


def weekly_texts(channels):
    return [WEEKLY_TEXT] + ([f"Channels in use: {', '.join(channels)}"] if channels else [])


# ---- moving Traffic, transit and weather's settings over ----
BC_TRANSIT = {"Victoria": "mdb-2572", "Nanaimo": "mdb-2474", "Comox Valley": "mdb-2525", "Cowichan Valley": "mdb-1380", "Salt Spring Island": "mdb-2486",
              "Campbell River": "mdb-1376", "Powell River": "mdb-2530", "Sunshine Coast": "mdb-2568"}       # the systems it read
TRANSLINK = "mdb-3348"
KIND_OF = {"DriveBC": "traffic", "BC Ferries": "ferries", "BC Transit": "transit", "TransLink": "transit", "Weather": "weather",
           "Earthquake": "quakes", "Tsunami": "tsunami"}
BC_REGIONS = ("Lower Mainland", "Vancouver Island", "Sunshine Coast")


def channels_union(*boxes):
    """'#a, #b' + '#b, c' -> '#a, #b, #c' (each once, in order, at most MAX_CHANNELS)."""
    out = []
    for box in boxes:
        for n in re.split(r"[,;\s]+", box or ""):
            n = n.strip()
            if not n or n.lstrip("#").lower() == "public": continue
            n = n if n.startswith("#") else "#" + n
            if n.lower() not in (o.lower() for o in out): out.append(n)
    return ", ".join(out[:MAX_CHANNELS])


def move_settings(old, get, kinds_default, kind_channel, make_area):
    """Traffic, transit and weather's settings (old: its values, the main node's own on top) -> {key: new value} for Area alerts.
    get(key, default): Area alerts' current values.  Everything is ADDED: areas, kinds switched on, channels next to the ones it has."""
    new = {}
    src = old.get("sources", {}) or {}
    on = lambda k: src.get(k, k != "Weekly reminder")
    lists = old.get("channel_lists", {}) or {}
    # areas: its three regions and the weather areas it watched
    areas = list(get("areas", []))
    have = {(a.get("country"), a.get("region"), a.get("name")) for a in areas}
    for name in list(BC_REGIONS) + list(old.get("weather_areas", []) or []):
        a = make_area(name)
        if a and (a.get("country"), a.get("region"), a.get("name")) not in have:
            areas.append(a); have.add((a.get("country"), a.get("region"), a.get("name")))
    if areas != list(get("areas", [])): new["areas"] = areas
    # kinds: what it broadcast is switched on (nothing is switched off)
    kinds = dict(get("kinds", {}))
    for ttw, kind in KIND_OF.items():
        if on(ttw) and not kinds.get(kind, kind in kinds_default): kinds[kind] = True
    if kinds != dict(get("kinds", {})): new["kinds"] = kinds
    if not old.get("muted", True) and not get("broadcast", False): new["broadcast"] = True
    # channels: its channels next to Area alerts' own
    chans = dict(get("channels", {}))
    for ttw, kind in (("Weather", "weather"), ("BC Ferries", "ferries")):
        if on(ttw) and lists.get(ttw):
            chans[kind] = channels_union(chans.get(kind) or kind_channel(kind), lists[ttw])
    if chans != dict(get("channels", {})): new["channels"] = chans
    tchans = dict(get("traffic_channels", {}))
    if on("DriveBC") and lists.get("DriveBC"):
        tchans["drivebc"] = channels_union(tchans.get("drivebc") or chans.get("traffic") or kind_channel("traffic"), lists["DriveBC"])
    if tchans != dict(get("traffic_channels", {})): new["traffic_channels"] = tchans
    feeds, fchans, keys = list(get("transit_feeds", [])), dict(get("transit_channels", {})), dict(get("keys", {}))
    wanted = ([(fid, lists.get("BC Transit", "")) for fid in BC_TRANSIT.values()] if on("BC Transit") else []) \
        + ([(TRANSLINK, lists.get("TransLink", ""))] if on("TransLink") and old.get("translink_key") else [])
    for fid, box in wanted:
        if fid not in feeds: feeds.append(fid)
        if box: fchans[fid] = channels_union(fchans.get(fid) or chans.get("transit") or kind_channel("transit"), box)
    if old.get("translink_key") and not keys.get(f"transit:{TRANSLINK}"): keys[f"transit:{TRANSLINK}"] = old["translink_key"]
    for key, val, was in (("transit_feeds", feeds, get("transit_feeds", [])), ("transit_channels", fchans, get("transit_channels", {})), ("keys", keys, get("keys", {}))):
        if val != was: new[key] = val
    # the route command, daily posts, weekly reminder, a busier hour
    if old.get("route_on") and not get("route_on", False): new["route_on"] = True
    if old.get("tomtom_key") and not get("tomtom_key", ""): new["tomtom_key"] = old["tomtom_key"]
    if on("Weather") and not get("forecast_on", False): new["forecast_on"] = True
    if on("Weekly reminder") and not get("weekly_on", False): new["weekly_on"] = True
    if int(get("per_hour", 10)) < 30: new["per_hour"] = 30
    codes = [old.get(k, "").strip() for k in ("scope_lm", "scope_vi", "scope_sc")] if old.get("use_scopes") else []
    codes = [c for c in dict.fromkeys(codes) if c]                 # its region codes ('[on] NEW ...'): one prefix for every alert
    if codes and not get("prefix", ""): new["prefix"] = f"[{codes[0]}]"
    return new
