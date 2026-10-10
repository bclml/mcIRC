"""Area alerts: the places to choose from - country, then region (state / province / ...), then area.

From GeoNames (geonames.org, CC BY 4.0): every country, its first-level regions, and its towns of 15,000 people or more
(aa_world.py).  In Canada the regions also have the areas the Traffic, transit and weather addon uses (ec_areas.py: metro regions
and districts about the size of the Lower Mainland, the North included)."""
import base64
import gzip
import json

_cache = {}


def world():
    """{country code: {'name': ..., 'regions': {region: [[area, lat, lon, population, district?], ...]}}} - loaded once."""
    if "w" not in _cache:
        import aa_world
        w = json.loads(gzip.decompress(base64.b85decode("".join(aa_world.DATA))).decode("utf-8"))
        try:
            import ec_areas
            regions = w.setdefault("CA", {"name": "Canada", "regions": {}})["regions"]
            for prov, areas in ec_areas.AREAS.items():
                have = {a[0] for a in regions.get(prov, [])}
                regions[prov] = [[n, la, lo, 0] for n, la, lo in areas if n not in have] + regions.get(prov, [])
        except ImportError:
            pass
        _cache["w"] = w
    return _cache["w"]


def countries():
    """[(name, code)] sorted by name."""
    return sorted(((c["name"], cc) for cc, c in world().items()), key=lambda x: x[0].lower())


def regions(cc):
    return sorted(world().get(cc, {}).get("regions", {}), key=str.lower)


def areas(cc, region):
    """[(name, lat, lon)] - the curated areas first, then towns by size."""
    return [(a[0], a[1], a[2]) for a in world().get(cc, {}).get("regions", {}).get(region, [])]


def make(cc, region, name):
    """The stored form of a chosen area: a dict with what the sources need; None when it isn't in the list."""
    for a in world().get(cc, {}).get("regions", {}).get(region, []):
        if a[0] == name:
            return {"country": cc, "country_name": world()[cc]["name"], "region": region, "name": a[0], "lat": a[1], "lon": a[2],
                    "district": a[4] if len(a) > 4 else ""}
    return None


def label(a): return f"{a['name']}, {a['region']}, {a.get('country_name', a['country'])}"
