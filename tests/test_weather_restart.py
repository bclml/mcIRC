import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Weather warnings and restarts: a warning that is still active must not be announced again (NEW + CLEARED) every time mcIRC restarts,
and Environment Canada's '... ENDED' notice is not an active warning.  Uses a throw-away log file; nothing is sent."""
import asyncio, tempfile
from unittest import mock

import emergency_agent as ea

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# the log as older versions wrote it today: NEW lines without {id:}, CLEAR lines keyed by title
OLD_LOG = """2026-10-04 11:27:30 - INFO - Broadcasting NEW to Channel Index 7: [Weather Warning: Vancouver Island] YELLOW ADVISORY - FOG; YELLOW ADVISORY - FOG ENDED
2026-10-04 11:27:31 - INFO - Broadcasting NEW to Channel Index 7: [Weather Warning: Sunshine Coast] YELLOW ADVISORY - FOG
2026-10-04 11:27:35 - INFO - Broadcasting CLEAR to Channel Index 7: [Weather Warning: Sunshine Coast] YELLOW ADVISORY - FOG {id:YELLOW ADVISORY - FOG}
2026-10-04 12:55:16 - INFO - Broadcasting NEW to Channel Index 7: [Weather Warning: Sunshine Coast] YELLOW ADVISORY - FOG
"""
log = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8")
log.write(OLD_LOG); log.close()

def restart_and_scan(scan):
    """Like a restart: forget everything, rebuild from the log, then run one scan.  Returns what would have been broadcast."""
    ea.active_weather_alerts.clear(); ea.active_traffic_alerts.clear()
    sent = []
    with mock.patch.object(ea, "LOG_FILE_PATH", log.name), mock.patch.object(ea, "BROADCAST_PACING_SECONDS", 0), \
            mock.patch.object(ea, "broadcast_via_cli", lambda src, title, desc, is_clear=False, forced_region=None, guid=None:
                              (sent.append(("CLEAR" if is_clear else "NEW", src, title)),
                               open(log.name, "a", encoding="utf-8").write(f"x - INFO - Broadcasting {'CLEAR' if is_clear else 'NEW'} to Channel Index 7: [{src}] {title}"
                                                                            + (f" {{id:{guid}}}" if guid else "") + "\n"))):
        ea.reload_active_alerts_from_log()
        asyncio.run(ea.process_scraped_alerts(scan, ea.active_weather_alerts))
    return sent

# what scrape_weather_warnings produces now for the two regions (the 'ENDED' notice is no longer counted)
live = {"EC_REGION_Vancouver Island_YELLOW ADVISORY - FOG": ("Weather Warning: Vancouver Island", "YELLOW ADVISORY - FOG", ""),
        "EC_REGION_Sunshine Coast_YELLOW ADVISORY - FOG": ("Weather Warning: Sunshine Coast", "YELLOW ADVISORY - FOG", "")}
sent = restart_and_scan(live)
ok("after a restart, warnings still in effect are NOT announced again (old log lines without an id)", sent == [], sent)
sent = restart_and_scan(live)
ok("...and again after the next restart", sent == [], sent)
sent = restart_and_scan({k: v for k, v in live.items() if "Sunshine" in k})
ok("a warning that really ended is cleared once", [(k, src) for k, src, _ in sent] == [("CLEAR", "Weather Warning: Vancouver Island")], sent)
sent = restart_and_scan({k: v for k, v in live.items() if "Sunshine" in k})
ok("...and stays cleared after a restart", sent == [], sent)
new = dict(live, **{"EC_REGION_Lower Mainland_ORANGE WARNING - RAINFALL": ("Weather Warning: Lower Mainland", "ORANGE WARNING - RAINFALL", "")})
sent = restart_and_scan(new)
ok("a genuinely new warning is still announced", ("NEW", "Weather Warning: Lower Mainland", "ORANGE WARNING - RAINFALL") in sent, sent)
new_lines = [l for l in open(log.name, encoding="utf-8") if "Lower Mainland" in l]
ok("...and logged with its id, so the next restart recognises it", new_lines and "{id:EC_REGION_Lower Mainland_ORANGE WARNING - RAINFALL}" in new_lines[-1], new_lines[-1:])

# the scraper ignores 'ENDED' notices
FEED = ("<feed><entry><title>YELLOW ADVISORY - FOG, Greater Victoria</title></entry>"
        "<entry><title>YELLOW ADVISORY - FOG ENDED, East Vancouver Island</title></entry></feed>")
class R:
    status_code = 200
    content = FEED.encode()
with mock.patch.object(ea.requests, "get", lambda *a, **k: R()), mock.patch.object(ea, "WEATHER_LOCATIONS", {"Vancouver Island": {"feeds": ["x"]}}), \
        mock.patch.object(ea, "check_regions_match", lambda *a, **k: True), \
        mock.patch.object(ea, "process_scraped_alerts", mock.AsyncMock()) as proc:
    asyncio.run(ea.scrape_weather_warnings())
scan = proc.call_args[0][0]
ok("an '... ENDED' notice is not counted as an active warning", list(scan) == ["EC_REGION_Vancouver Island_YELLOW ADVISORY - FOG"], scan)
os.unlink(log.name)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
