import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The same alert isn't broadcast twice: a transit agency rewording it ('#1 DTEX at 3:22 ...' -> '#1 DTEX 3:22 ...') is not sent again.
No radio."""
import importlib.util

sys.path[:0] = [os.path.join(ROOT, "packages", "area_alerts")]
import aa_sources as src

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

spec = importlib.util.spec_from_file_location("t_nr_area", os.path.join(ROOT, "packages", "area_alerts", "area_alerts.py"))
area = importlib.util.module_from_spec(spec); spec.loader.exec_module(area)
w = area.wording
ok("the same alert reworded has the same words", w("BC Transit: #1 DTEX at 3:22 is cancelled due to staff shortage.") == w("BC Transit: #1 DTEX 3:22 is cancelled due to staff shortage"))
ok("...but another time, route or stop is another alert", len({w("#1 DTEX 3:22 cancelled"), w("#1 DTEX 3:52 cancelled"), w("#10 DTEX 3:22 cancelled"),
                                                               w("#1 CCEX 3:22 cancelled")}) == 4)

class API:
    def __init__(self): self.s, self.lines = {"enabled": True, "broadcast": True}, []
    def get(self, k, d=None): return self.s.get(k, d)
    def set(self, k, v): self.s[k] = v
    def write(self, win, text): self.lines.append(text)
    def log(self, *a, **k): pass
    connected = False
a = area.Addon.__new__(area.Addon); a.api = API()
a.busy, a.unloaded, a.quiet_next, a.queue, a.sent_times, a.source_of, a.current = False, False, False, [], [], {}, []
a.drain = lambda: None
a._checked(([("Nanaimo", src.Alert("t1", "transit", "BC Transit: #1 DTEX at 3:22 is cancelled due to staff shortage.", ""))], []))
ok("a new alert is broadcast", [q.id for q in a.queue] == ["t1"])
a._checked(([("Nanaimo", src.Alert("t2", "transit", "BC Transit: #1 DTEX 3:22 is cancelled due to staff shortage", ""))], []))
ok("the agency rewords it (a new id): shown as '(again, not sent)', not broadcast again", [q.id for q in a.queue] == ["t1"]
   and a.api.lines[-1].startswith("(again, not sent)"), a.api.lines)
a._checked(([("Nanaimo", src.Alert("t3", "transit", "BC Transit: #1 DTEX 3:52 is cancelled due to staff shortage", ""))], []))
ok("another bus (3:52) is broadcast", [q.id for q in a.queue] == ["t1", "t3"])
a.api.s["sent_words"] = {k: v - area.SAME_WORDS - 1 for k, v in a.api.s["sent_words"].items()}
a._checked(([("Nanaimo", src.Alert("t4", "transit", "BC Transit: #1 DTEX 3:22 is cancelled due to staff shortage", ""))], []))
ok("...after 6 hours the same words count as new again", [q.id for q in a.queue][-1] == "t4")

# one earthquake near several of your areas: one alert, worded for the nearest area (not one per area)
q = lambda d, name: src.Alert("usgs:uw1", "quakes", f"Earthquake M3.3: 19 km ESE of Forks, Washington ({d} km from {name})", "USGS")
a.queue, a.api.lines = [], []
a._checked(([("Lower Mainland", q(170, "Lower Mainland")), ("Vancouver Island", q(80, "Vancouver Island")), ("Nanaimo", q(139, "Nanaimo")),
             ("Capital Regional District", q(80, "Capital Regional District (Victoria)")),
             ("Nanaimo", src.Alert("usgs:uw2", "quakes", "Earthquake M4.1: 30 km W of Port Alice (60 km from Nanaimo)", "USGS"))], []))
ok("one quake in four areas: queued once, plus the other quake", [x.id for x in a.queue] == ["usgs:uw1", "usgs:uw2"], [x.text for x in a.queue])
ok("...worded for the nearest area (the first of two equally near)", a.queue[0].text.endswith("(80 km from Vancouver Island)"), a.queue[0].text)
ok("...and shown once in the window", sum("Forks" in l for l in a.api.lines) == 1, a.api.lines)
a._checked(([("Sea to Sky", q(211, "Sea to Sky"))], []))
ok("...and not again at the next check from another area", [x.id for x in a.queue] == ["usgs:uw1", "usgs:uw2"])

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
