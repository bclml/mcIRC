"""Map tiles the way OpenStreetMap's tile usage policy asks (operations.osmfoundation.org/policies/tiles): every request names the app
and how to reach its makers (tkintermapview's own 'TkinterMapView' is blocked - the map showed 'Access blocked' tiles), the single
tile.openstreetmap.org address, one kept-alive connection, and tiles kept on disk (tile_cache/, 7 days) so the same ones aren't asked for
again.  A refusal (403 / 429 ...) is never kept and never drawn as a map: the tile stays blank and Status says why, once."""
import io
import os
import threading
import time

from gui_common import BASE_DIR

OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
CACHE_DIR = os.path.join(BASE_DIR, "tile_cache")
KEEP_DAYS = 7
_lock = threading.Lock()
_session = None
_warned = set()
_refused_until = 0.0        # after a refusal: no tile is asked for for a while (asking again at once would only hammer a server that said no)
BACK_OFF = 600
on_refused = None           # set by the map window: fn(status code) - said once per code


def user_agent():
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as f: v = f.read().strip()
    except OSError: v = "?"
    return f"mcIRC/{v} (MeshCore chat client; +https://github.com/bclml/mcIRC)"


def _cache_path(url):
    """tile_cache/<z>/<x>/<y>.png for an OpenStreetMap tile; None for anything else (not kept)."""
    if not url.startswith(OSM_TILES.split("{")[0]): return None
    parts = url.split("?")[0].rstrip("/").split("/")[-3:]
    if len(parts) != 3 or not all(p.replace(".png", "").isdigit() for p in parts): return None
    return os.path.join(CACHE_DIR, parts[0], parts[1], parts[2])


class _Reply:
    """What tkintermapview reads: .raw (a file) and .status_code."""
    def __init__(self, data, status=200): self.raw, self.content, self.status_code = io.BytesIO(data), data, status


class _Requests:
    """Stands in for the 'requests' module inside tkintermapview: get() with our name, the disk cache and one session."""
    def __getattr__(self, name):
        import requests
        return getattr(requests, name)

    def get(self, url, stream=False, headers=None, timeout=20, **kw):
        global _session, _refused_until
        path = _cache_path(url)
        if path and os.path.exists(path) and time.time() - os.path.getmtime(path) < KEEP_DAYS * 86400:
            with open(path, "rb") as f: return _Reply(f.read())
        if time.time() < _refused_until: raise OSError("the tile server refused tiles a moment ago - waiting")
        import requests
        with _lock:
            if _session is None:
                _session = requests.Session()
                _session.headers["User-Agent"] = user_agent()
        r = _session.get(url, timeout=timeout, **kw)
        if r.status_code != 200 or not r.headers.get("Content-Type", "image").startswith("image"):
            if r.status_code in (403, 418, 429, 503): _refused_until = time.time() + BACK_OFF
            if r.status_code not in _warned:
                _warned.add(r.status_code)
                if on_refused: on_refused(r.status_code)
            raise OSError(f"tile server answered {r.status_code}")        # tkintermapview then leaves the tile blank
        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".part"
                with open(tmp, "wb") as f: f.write(r.content)
                os.replace(tmp, path)
            except OSError: pass
        return _Reply(r.content)


def install(map_widget_module, widget=None):
    """Make tkintermapview fetch tiles this way (its module's 'requests'), and point a map at the one OpenStreetMap address."""
    map_widget_module.requests = _Requests()
    if widget is not None:
        try: widget.set_tile_server(OSM_TILES, max_zoom=19)
        except Exception: pass
