import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Map tiles as OpenStreetMap's tile policy asks: mcIRC's own name (tkintermapview's 'TkinterMapView' is blocked), tiles kept on disk,
a refusal never drawn or kept, and no asking again for a while after one.  No internet: a stand-in server."""
import shutil, tempfile, time, types

import gui_tiles

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 50
class Resp:
    def __init__(self, code, data=PNG, ctype="image/png"): self.status_code, self.content, self.headers = code, data, {"Content-Type": ctype}
class Session:
    def __init__(self): self.headers, self.asked, self.answer = {}, [], Resp(200)
    def get(self, url, timeout=20, **kw): self.asked.append(url); return self.answer

tmp = tempfile.mkdtemp()
gui_tiles.CACHE_DIR = tmp
sess = Session(); gui_tiles._session = sess
mod = types.SimpleNamespace(); gui_tiles.install(mod)
said = []; gui_tiles.on_refused = said.append
url = "https://tile.openstreetmap.org/8/40/87.png"

ok("requests carry mcIRC's name and how to reach it (not 'TkinterMapView')", gui_tiles.user_agent().startswith("mcIRC/") and "github.com/bclml/mcIRC" in gui_tiles.user_agent())
r = mod.requests.get(url, stream=True, headers={"User-Agent": "TkinterMapView"})
ok("a tile is fetched once and kept on disk", r.raw.read() == PNG and os.path.exists(os.path.join(tmp, "8", "40", "87.png")) and len(sess.asked) == 1)
mod.requests.get(url)
ok("...the next time it comes from the disk, not the server", len(sess.asked) == 1)
ok("the map is pointed at the one OpenStreetMap address", gui_tiles.OSM_TILES == "https://tile.openstreetmap.org/{z}/{x}/{y}.png")

sess.answer = Resp(403, b"<html>blocked</html>", "text/html")
try: mod.requests.get("https://tile.openstreetmap.org/8/41/87.png"); raised = False
except OSError: raised = True
ok("a refusal (403) is not drawn as a map tile, not kept, and Status is told once", raised and not os.path.exists(os.path.join(tmp, "8", "41", "87.png")) and said == [403], said)
n = len(sess.asked)
try: mod.requests.get("https://tile.openstreetmap.org/8/42/87.png")
except OSError: pass
ok("...after it, no tile is asked for for 10 minutes", len(sess.asked) == n and gui_tiles.BACK_OFF == 600)
gui_tiles._refused_until = time.time() - 1; sess.answer = Resp(200)
mod.requests.get("https://tile.openstreetmap.org/8/42/87.png")
ok("...then it asks again", len(sess.asked) == n + 1)
ok("tkintermapview's own error checks still work (requests.exceptions)", mod.requests.exceptions.ConnectionError is not None)
ok("the tile cache isn't committed", "tile_cache/" in open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read())
gui_tiles._session = None; gui_tiles.on_refused = None
shutil.rmtree(tmp, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
