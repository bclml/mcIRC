"""Weather bot answers about the sky: satellite passes (CelesTrak orbits + the sgp4 package) and aircraft overhead (airplanes.live)."""
import datetime as dt
import math

from meshbot_common import compass, http_get, http_json

SATS = {"iss": 25544, "zarya": 25544, "hubble": 20580, "hst": 20580, "tiangong": 48274, "css": 48274,
        "noaa15": 25338, "noaa18": 28654, "noaa19": 33591}


def _gmst(jd):
    t = (jd - 2451545.0) / 36525
    sec = 67310.54841 + (876600 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return math.radians((sec % 86400) / 240)


def _observer(lat, lon):
    a, e2 = 6378.137, 6.69437999014e-3
    p, l = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    return (n * math.cos(p) * math.cos(l), n * math.cos(p) * math.sin(l), n * (1 - e2) * math.sin(p)), p, l


def look_angles(sat, when, obs):
    """(elevation, azimuth) in degrees of a satellite seen from `obs` at datetime `when` (UTC)."""
    from sgp4.api import jday
    jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second + when.microsecond / 1e6)
    err, r, _ = sat.sgp4(jd, fr)
    if err: return None
    g = _gmst(jd + fr)
    x, y, z = r[0] * math.cos(g) + r[1] * math.sin(g), -r[0] * math.sin(g) + r[1] * math.cos(g), r[2]
    (ox, oy, oz), p, l = obs
    dx, dy, dz = x - ox, y - oy, z - oz
    east = -math.sin(l) * dx + math.cos(l) * dy
    north = -math.sin(p) * math.cos(l) * dx - math.sin(p) * math.sin(l) * dy + math.cos(p) * dz
    up = math.cos(p) * math.cos(l) * dx + math.cos(p) * math.sin(l) * dy + math.sin(p) * dz
    return math.degrees(math.atan2(up, math.hypot(east, north))), math.degrees(math.atan2(east, north)) % 360


def next_pass(sat, lat, lon, start, hours=24, step=20, min_max_el=10):
    """The next pass whose highest point is at least `min_max_el` degrees: dict(rise, rise_az, top, top_el, set, set_az) or None."""
    obs = _observer(lat, lon)
    t, end, cur = start, start + dt.timedelta(hours=hours), None
    while t <= end:
        la = look_angles(sat, t, obs)
        if la is None: return None
        el, az = la
        if el > 0 and cur is None: cur = {"rise": t, "rise_az": az, "top": t, "top_el": el}
        if cur is not None:
            if el > cur["top_el"]: cur["top"], cur["top_el"] = t, el
            if el <= 0:
                cur["set"], cur["set_az"] = t, az
                if cur["top_el"] >= min_max_el: return cur
                cur = None
        t += dt.timedelta(seconds=step)
    return None


def satpass(arg, lat, lon, label, get=http_get, now=None):
    try:
        from sgp4.api import Satrec
    except ImportError:
        raise ValueError("satpass needs the sgp4 package on the bot's PC (pip install sgp4)")
    a = (arg or "iss").strip().lower()
    catnr = SATS.get(a.replace(" ", "")) or (int(a) if a.isdigit() else None)
    if not catnr: raise ValueError("satpass iss | hubble | tiangong | noaa19 | <NORAD number>")
    lines = [x for x in get(f"https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=TLE").decode("utf-8", "replace").splitlines() if x.strip()]
    if len(lines) < 3 or not lines[1].startswith("1 "): raise ValueError(f"no orbit data for {catnr}")
    sat = Satrec.twoline2rv(lines[1], lines[2])
    p = next_pass(sat, lat, lon, now or dt.datetime.now(dt.timezone.utc))
    name = lines[0].strip().split("(")[0].strip().title()[:16]
    if not p: return f"{name}: no pass higher than 10 deg over {label} in the next 24h"
    loc = lambda t: t.astimezone().strftime("%H:%M")
    day = "" if p["rise"].astimezone().date() == dt.datetime.now().astimezone().date() else p["rise"].astimezone().strftime("%a ")
    return (f"{name} over {label}: {day}rise {loc(p['rise'])} {compass(p['rise_az'])}, max {p['top_el']:.0f} deg {loc(p['top'])}, "
            f"set {loc(p['set'])} {compass(p['set_az'])}")


def airplanes(lat, lon, label, nm=25, get=http_json):
    nm = max(1, min(int(nm), 100))
    d = None
    for url in ("https://api.adsb.lol/v2/point/{0:.4f}/{1:.4f}/{2}", "https://api.airplanes.live/v2/point/{0:.4f}/{1:.4f}/{2}"):     # two free ADS-B feeds, same format
        try:
            d = get(url.format(lat, lon, nm))
            break
        except Exception as e:
            last = e
    if d is None: raise last
    rows = sorted([a for a in (d.get("ac") or []) if a.get("dst") is not None], key=lambda a: a["dst"])
    if not rows: return f"No aircraft within {nm}nm of {label} right now"
    bits = []
    for a in rows[:4]:
        cs = (a.get("flight") or a.get("r") or a.get("hex") or "?").strip()
        alt = a.get("alt_baro")
        alt = "gnd" if alt == "ground" else f"{int(alt):,}ft" if isinstance(alt, (int, float)) else "?"
        where = f"{a['dst']:.0f}nm {compass(a['dir'])}" if a.get("dir") is not None else f"{a['dst']:.0f}nm"
        bits.append(f"{cs} {a.get('t', '')} {alt} {where}".replace("  ", " "))
    return f"{len(rows)} aircraft within {nm}nm of {label}: " + "; ".join(bits)
