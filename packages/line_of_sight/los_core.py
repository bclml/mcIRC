"""Line of sight - the maths and the elevation data (no tkinter).

Between two points: the ground height every few hundred metres (Open-Meteo's free elevation service, no key), raised by the earth's
curve (with the usual 4/3 radio-horizon factor), against the straight line between the two antennas and the first Fresnel zone around
it - the space a radio signal needs mostly free (60 % of it is the usual rule) to arrive at full strength."""
import json
import math
import urllib.parse
import urllib.request

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
SAMPLES = 100                      # points along the path (the most Open-Meteo answers in one request)
EARTH_M = 6371000.0
K_FACTOR = 4 / 3                   # radio waves bend a little with the atmosphere: the earth looks this much bigger to them
CLEAR_RATIO = 0.6                  # 60 % of the first Fresnel zone free: counted as clear


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (haversine), in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M / 1000 * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Direction from point 1 to point 2: 0 = north, 90 = east."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def path_points(lat1, lon1, lat2, lon2, n=SAMPLES):
    """n points from A to B, evenly spaced (a straight line in lat/lon: close enough to the great circle over a mesh link's length)."""
    return [(lat1 + (lat2 - lat1) * i / (n - 1), lon1 + (lon2 - lon1) * i / (n - 1)) for i in range(n)]


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "mcIRC (MeshCore chat client)"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()


def elevations(points, get=None):
    """Ground height (m above sea level) of each (lat, lon) point, from Open-Meteo (90 m terrain data)."""
    get = get or http_get                                         # (looked up now, not when this file was read: tests replace it)
    q = urllib.parse.urlencode({"latitude": ",".join(f"{p[0]:.5f}" for p in points), "longitude": ",".join(f"{p[1]:.5f}" for p in points)})
    data = json.loads(get(f"{ELEVATION_URL}?{q}").decode("utf-8"))
    out = data.get("elevation")
    if not isinstance(out, list) or len(out) != len(points): raise ValueError(data.get("reason") or "no elevation data in the answer")
    return [float(v) if v is not None else 0.0 for v in out]


def fresnel_radius_m(d1_m, d2_m, freq_mhz):
    """Radius of the first Fresnel zone at a point d1 from one end and d2 from the other (metres)."""
    lam = 299.792458 / freq_mhz                                   # wavelength in metres
    return math.sqrt(lam * d1_m * d2_m / (d1_m + d2_m)) if d1_m > 0 and d2_m > 0 else 0.0


def profile(ground, total_km, h1=2.0, h2=10.0, freq_mhz=910.525, k=K_FACTOR):
    """The path, point by point, and the verdict.

    ground: heights along the path (first = A, last = B); h1 / h2: antenna height above the ground at A / B; freq in MHz.
    -> {'points': [{'km', 'ground', 'bulge', 'terrain', 'line', 'fresnel'}], 'verdict': 'clear' | 'fresnel' | 'blocked',
        'worst_km', 'worst_ratio' (free share of the Fresnel radius at the worst point; < 0 = the ground is above the line),
        'above_m' (blocked: how far the ground rises above the line there)}"""
    n, total_m = len(ground), total_km * 1000
    a, b = ground[0] + h1, ground[-1] + h2                       # the two antennas
    pts, worst = [], None
    for i, g in enumerate(ground):
        d1 = total_m * i / (n - 1)
        d2 = total_m - d1
        bulge = d1 * d2 / (2 * k * EARTH_M)                      # how much the earth's curve lifts the ground into the path here
        terrain = g + bulge
        line = a + (b - a) * d1 / total_m if total_m else a
        r = fresnel_radius_m(d1, d2, freq_mhz)
        pts.append({"km": d1 / 1000, "ground": g, "bulge": bulge, "terrain": terrain, "line": line, "fresnel": r})
        if 0 < i < n - 1 and r > 0:                              # (the antennas themselves don't count)
            ratio = (line - terrain) / r
            if worst is None or ratio < worst[0]: worst = (ratio, i)
    if worst is None: return {"points": pts, "verdict": "clear", "worst_km": 0.0, "worst_ratio": 1.0, "above_m": 0.0}
    ratio, i = worst
    verdict = "clear" if ratio >= CLEAR_RATIO else "fresnel" if ratio >= 0 else "blocked"
    return {"points": pts, "verdict": verdict, "worst_km": pts[i]["km"], "worst_ratio": ratio,
            "above_m": max(0.0, pts[i]["terrain"] - pts[i]["line"])}


def summary(res, name_a, name_b, km, deg):
    """One line for the window and the Status log."""
    head = f"{name_a} -> {name_b}: {km:.1f} km, heading {deg:.0f} degrees. "
    if res["verdict"] == "clear": return head + "Clear line of sight (the Fresnel zone is at least 60 % free all the way)."
    if res["verdict"] == "fresnel":
        return head + (f"Line of sight, but the ground takes up part of the Fresnel zone at {res['worst_km']:.1f} km "
                       f"({max(0, res['worst_ratio']) * 100:.0f} % free there): expect a weaker signal. Higher antennas help.")
    return head + f"Blocked by the ground at {res['worst_km']:.1f} km ({res['above_m']:.0f} m above the line). A repeater in between, or much higher antennas, would be needed."


def check(lat1, lon1, lat2, lon2, h1=2.0, h2=10.0, freq_mhz=910.525, get=None):
    """The whole check (slow: one web request) -> (profile result, km, bearing)."""
    km = distance_km(lat1, lon1, lat2, lon2)
    if km < 0.05: raise ValueError("the two points are the same place")
    if km > 500: raise ValueError("more than 500 km apart - no LoRa link reaches that far over ground")
    ground = elevations(path_points(lat1, lon1, lat2, lon2), get)
    return profile(ground, km, h1, h2, freq_mhz), km, bearing_deg(lat1, lon1, lat2, lon2)
