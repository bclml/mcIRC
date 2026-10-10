"""Weather areas for the Traffic, transit and weather addon's Environment Canada warnings: about the size of the Lower Mainland, in every province and territory
(metro regions, regional districts / municipalities, census divisions, administrative regions; hub-and-district in the North).

An area is (name, lat, lon) at its centre.  The three original BC regions keep their own per-zone Environment Canada feeds (in
emergency_agent.WEATHER_FEEDS); every other area's warnings come from Environment Canada's national alerts service (GeoMet OGC API),
asked for the alerts that cover the area's centre and its surroundings."""
import requests

ALERTS_URL = "https://api.weather.gc.ca/collections/weather-alerts/items"
DEFAULT_AREAS = ["Lower Mainland", "Vancouver Island", "Sunshine Coast"]       # what the bot covered before areas could be chosen

AREAS = {
    "British Columbia": [
        ("Lower Mainland", 49.19, -122.85), ("Vancouver Island", 48.42, -123.36), ("Sunshine Coast", 49.47, -123.75),
        ("Metro Vancouver", 49.25, -123.10), ("Fraser Valley", 49.10, -122.30), ("Capital Regional District (Victoria)", 48.43, -123.37),
        ("Cowichan Valley", 48.78, -123.71), ("Nanaimo", 49.17, -123.94), ("Comox Valley", 49.69, -124.99), ("Sea to Sky (Squamish-Lillooet)", 49.70, -123.15),
        ("Central Okanagan (Kelowna)", 49.89, -119.50), ("North Okanagan (Vernon)", 50.27, -119.27), ("Okanagan-Similkameen (Penticton)", 49.49, -119.59),
        ("Thompson-Nicola (Kamloops)", 50.67, -120.33), ("Cariboo (Williams Lake)", 52.13, -122.14), ("Fraser-Fort George (Prince George)", 53.92, -122.75),
        ("Kitimat-Stikine (Terrace)", 54.52, -128.60), ("North Coast (Prince Rupert)", 54.31, -130.32), ("Peace River (Fort St. John)", 56.25, -120.85),
        ("East Kootenay (Cranbrook)", 49.51, -115.77), ("Central Kootenay (Nelson)", 49.49, -117.29),
    ],
    "Alberta": [
        ("Greater Calgary", 51.05, -114.07), ("Greater Edmonton", 53.55, -113.49), ("Red Deer", 52.27, -113.81),
        ("Lethbridge (Division No. 2)", 49.69, -112.84), ("Medicine Hat", 50.04, -110.68), ("Grande Prairie", 55.17, -118.80),
        ("Wood Buffalo (Fort McMurray)", 56.73, -111.38), ("Bow Valley (Banff-Canmore)", 51.09, -115.35), ("Lloydminster", 53.28, -110.01),
    ],
    "Saskatchewan": [
        ("Saskatoon Region", 52.13, -106.67), ("Regina Region", 50.45, -104.62), ("Prince Albert", 53.20, -105.75), ("Moose Jaw", 50.39, -105.53),
        ("Swift Current", 50.29, -107.80), ("Yorkton", 51.21, -102.46), ("North Battleford", 52.76, -108.29), ("La Ronge", 55.10, -105.28),
    ],
    "Manitoba": [
        ("Winnipeg Metro", 49.90, -97.14), ("Brandon", 49.85, -99.95), ("Southeast (Steinbach)", 49.53, -96.68), ("Interlake (Selkirk-Gimli)", 50.33, -96.95),
        ("Parkland (Dauphin)", 51.15, -100.05), ("Pembina Valley (Winkler-Morden)", 49.19, -97.94), ("Northern (Thompson)", 55.74, -97.86),
        ("The Pas-Flin Flon", 53.83, -101.25),
    ],
    "Ontario": [
        ("Toronto", 43.65, -79.38), ("Peel Region", 43.68, -79.76), ("York Region", 43.95, -79.45), ("Durham Region", 43.90, -78.94),
        ("Halton Region", 43.47, -79.85), ("Hamilton", 43.26, -79.87), ("Niagara Region", 43.08, -79.20), ("Waterloo Region", 43.46, -80.52),
        ("Middlesex County (London)", 42.98, -81.25), ("Windsor-Essex", 42.30, -82.95), ("Ottawa", 45.42, -75.70), ("Kingston", 44.23, -76.49),
        ("Simcoe County (Barrie)", 44.39, -79.69), ("Peterborough", 44.30, -78.32), ("Greater Sudbury", 46.49, -80.99), ("North Bay", 46.31, -79.46),
        ("Sault Ste. Marie", 46.52, -84.33), ("Thunder Bay", 48.38, -89.25), ("Muskoka", 45.04, -79.31), ("Timmins", 48.48, -81.33),
    ],
    "Quebec": [
        ("Greater Montreal (CMM)", 45.50, -73.57), ("Quebec City (CMQ)", 46.81, -71.21), ("Outaouais (Gatineau)", 45.48, -75.70),
        ("Laurentides (Saint-Jerome)", 45.78, -74.00), ("Lanaudiere (Joliette)", 46.02, -73.44), ("Estrie (Sherbrooke)", 45.40, -71.89),
        ("Mauricie (Trois-Rivieres)", 46.34, -72.54), ("Centre-du-Quebec (Drummondville)", 45.88, -72.48), ("Saguenay-Lac-Saint-Jean", 48.43, -71.07),
        ("Bas-Saint-Laurent (Rimouski)", 48.45, -68.52), ("Gaspesie", 48.83, -64.48), ("Abitibi-Temiscamingue (Rouyn-Noranda)", 48.24, -79.02),
        ("Cote-Nord (Sept-Iles)", 50.22, -66.38),
    ],
    "New Brunswick": [
        ("Southeast (Moncton)", 46.09, -64.77), ("Capital Region (Fredericton)", 45.96, -66.64), ("Fundy (Saint John)", 45.27, -66.06),
        ("Northwest (Edmundston)", 47.37, -68.33), ("Chaleur (Bathurst)", 47.62, -65.65), ("Greater Miramichi", 47.03, -65.50), ("Acadian Peninsula", 47.78, -64.95),
    ],
    "Nova Scotia": [
        ("Halifax Regional Municipality", 44.65, -63.58), ("Cape Breton (Sydney)", 46.14, -60.19), ("Annapolis Valley (Kentville)", 45.08, -64.50),
        ("South Shore (Bridgewater)", 44.38, -64.52), ("Northern Nova Scotia (Truro)", 45.36, -63.28), ("Yarmouth", 43.84, -66.12),
    ],
    "Prince Edward Island": [
        ("Queens County (Charlottetown)", 46.24, -63.13), ("Prince County (Summerside)", 46.39, -63.79), ("Kings County (Montague)", 46.17, -62.65),
    ],
    "Newfoundland and Labrador": [
        ("Avalon (St. John's)", 47.56, -52.71), ("Central (Gander)", 48.96, -54.61), ("Western (Corner Brook)", 48.95, -57.95),
        ("Burin Peninsula", 47.10, -55.20), ("Labrador (Happy Valley-Goose Bay)", 53.30, -60.33), ("Labrador West (Labrador City)", 52.94, -66.91),
    ],
    "Yukon": [("Whitehorse & area", 60.72, -135.05), ("Klondike (Dawson City)", 64.06, -139.43), ("Watson Lake", 60.06, -128.71)],
    "Northwest Territories": [("Yellowknife & North Slave", 62.45, -114.37), ("South Slave (Hay River)", 60.82, -115.79), ("Beaufort Delta (Inuvik)", 68.36, -133.72)],
    "Nunavut": [("Iqaluit & South Baffin", 63.75, -68.52), ("Kivalliq (Rankin Inlet)", 62.81, -92.09), ("Kitikmeot (Cambridge Bay)", 69.12, -105.06)],
}


def find(name):
    """(province, name, lat, lon) of an area by its name, or None."""
    for prov, areas in AREAS.items():
        for a in areas:
            if a[0] == name: return (prov,) + a
    return None


def kind_of(p):
    """'YELLOW WARNING - SNOWFALL', 'SPECIAL WEATHER STATEMENT', 'YELLOW ADVISORY - FROST' - as the per-zone feeds title them."""
    short = (p.get("alert_short_name_en") or p.get("alert_name_en") or "").replace("(advisory)", "").strip().upper()
    kind = (p.get("alert_type") or "").upper()
    if kind == "STATEMENT": return f"{short} STATEMENT".strip()
    colour = (p.get("risk_colour_en") or "").upper()
    return f"{colour + ' ' if colour else ''}{kind} - {short}".strip(" -")


def alerts_near(lat, lon, get=None, d_lat=0.25, d_lon=0.35, timeout=15):
    """The Environment Canada alerts in force around (lat, lon) - an area about 50 km across: set of kinds (see kind_of).  Ended ones
    are left out.  get(url, params) -> parsed JSON (for tests)."""
    params = {"f": "json", "lang": "en", "limit": 200, "skipGeometry": "true", "bbox": ",".join(f"{v:.2f}".rstrip("0").rstrip(".") for v in (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)),
              "properties": "alert_type,risk_colour_en,alert_short_name_en,alert_name_en,status_en"}
    if get is None:
        def get(url, p):
            r = requests.get(url, params=p, timeout=timeout, headers={"User-Agent": "mcIRC"})
            r.raise_for_status()
            return r.json()
    data = get(ALERTS_URL, params)
    return {kind_of(f.get("properties", {})) for f in data.get("features", []) if (f.get("properties", {}).get("status_en") or "") != "ended"} - {""}
