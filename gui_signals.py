"""Signals on the map: the routes of packets the radio really heard.

Every flooded MeshCore packet carries its path: the short hash (1-3 bytes of the public key) of each repeater it went through.  mcIRC keeps
the paths it hears for a while (mcIRC.note_signal): repeats of our own messages ("out": our node -> the repeaters that passed it on) and
packets arriving from further away ("in": the repeaters it came through -> our node).  Here a path becomes points on the map by looking
the hashes up among the nodes mcIRC knows; a repeater it doesn't know (or that has no position) is left out of the line."""
import math

KEEP_SECONDS = 600                     # a route stays on the map for 10 minutes
OUT_COLOR, IN_COLOR = "#ff6d00", "#00b8d4"


def split_path(path_hex, size=1):
    """'a1b2c3' with 1-byte hashes -> ['a1', 'b2', 'c3']."""
    step = 2 * max(1, int(size or 1))
    path_hex = (path_hex or "").lower()
    return [path_hex[i:i + step] for i in range(0, len(path_hex) - step + 1, step)]


def _dist(a, b): return math.hypot(a[0] - b[0], (a[1] - b[1]) * math.cos(math.radians(a[0])))


def locate(prefix, nodes, near=None):
    """The known node (with a position) whose key starts with `prefix`; repeaters first, and the closest to `near` when several match."""
    cands = [n for n in nodes if n["public_key"].lower().startswith(prefix) and (n["lat"] or n["lon"])]
    if not cands: return None
    best = [n for n in cands if n["type"] in (2, 3)] or cands
    if near: best.sort(key=lambda n: _dist((n["lat"], n["lon"]), near))
    return best[0]


def route(trace, nodes, me):
    """[(lat, lon), ...] along a heard path.  me = (lat, lon) of our node or None."""
    hops = split_path(trace.get("path", ""), trace.get("size", 1))
    if trace.get("dir") == "out":                       # we sent it: the first hop is our neighbour
        pts, near = ([me] if me else []), me
        for h in hops:
            n = locate(h, nodes, near)
            if n: pts.append((n["lat"], n["lon"])); near = (n["lat"], n["lon"])
        return pts
    pts, near = ([me] if me else []), me                # heard from afar: the last hop is our neighbour, so resolve backwards from us
    for h in reversed(hops):
        n = locate(h, nodes, near)
        if n: pts.append((n["lat"], n["lon"])); near = (n["lat"], n["lon"])
    return list(reversed(pts))


def along(pts, f):
    """The point a fraction f (0..1) of the way along a polyline (for the moving dot)."""
    if len(pts) < 2: return pts[0] if pts else None
    legs = [_dist(a, b) for a, b in zip(pts, pts[1:])]
    total = sum(legs) or 1.0
    d = max(0.0, min(1.0, f)) * total
    for (a, b), leg in zip(zip(pts, pts[1:]), legs):
        if d <= leg or leg == 0:
            t = d / leg if leg else 0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        d -= leg
    return pts[-1]
