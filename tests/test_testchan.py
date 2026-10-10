import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import sys, types, importlib.util
from unittest import mock
sys.path.insert(0, ROOT)
import emergency_agent as ea, meshcore_io as io

results = []
def check(label, cond, detail=""):
    results.append(bool(cond)); print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))

sent = []
ea.execute_mesh_command = lambda args, **kw: sent.append(args) or types.SimpleNamespace(stdout="ok", stderr="", returncode=0)
io.CONNECTION_ARGS = ["-s", "COMX"]
io.CHANNEL_INDEX_BY_NAME.clear(); io.CHANNEL_INDEX_BY_NAME.update({"Public": 0, "kod-bot": 2, "drivebc": 3, "bot-van": 8})
n = [0]
def say(channel_idx, text="Bob: test", hops=2):
    """Simulate someone typing; returns the reply text sent (or None)."""
    n[0] += 1; before = len(sent); ea._recent_test_replies.clear()
    ea.handle_test_message({"type": "CHAN", "channel_idx": channel_idx, "text": text, "sender_timestamp": n[0], "path_len": hops, "SNR": 7.5})
    return sent[-1][-1] if len(sent) > before else None
def cfg(**kw):
    ea.TX["sources"]["Test reply"] = kw.get("on", True); ea.TX["muted"] = kw.get("muted", False)
    ea.TEST_CHANNEL, ea.TEST_WATCH = kw.get("channel", ""), kw.get("watch", [])
    ea.TEST_REPLY_TEXT, ea.TEST_REDIRECT_TEXT = kw.get("reply", ea.TEST_REPLY_DEFAULT), kw.get("redirect", ea.TEST_REDIRECT_DEFAULT)

cfg()
check("defaults: answers on any channel with the plain reply", say(0) == "@Bob Test received, 2 hops" and say(3) == "@Bob Test received, 2 hops")
check("'t' shorthand and case-insensitive", say(0, "Bob: T") is not None and say(0, "Bob: TEST") is not None)
check("normal chat is ignored", say(0, "Bob: testing the antenna") is None and say(0, "Bob: hello") is None)

cfg(channel="#kod-bot", redirect="@{sender} Test should be made in {channel}")
check("test channel set: test on the TEST channel gets the normal reply", say(2) == "@Bob Test received, 2 hops", str(say(2)))
check("test channel set: test on another channel is pointed to the test channel", say(0) == "@Bob Test should be made in #kod-bot" and say(3) == "@Bob Test should be made in #kod-bot")
cfg(channel="kod-bot")
check("channel name works with or without '#'", say(0) == "@Bob Please send test messages in #kod-bot")
cfg(channel="#bot-van", redirect="@{sender} go to {channel}")
check("other mesh: test channel changed to #bot-van", say(0) == "@Bob go to #bot-van" and say(8) == "@Bob Test received, 2 hops")

cfg(channel="#kod-bot", watch=["Public"])
check("watch list: only the listed channels are checked", say(0) is not None and say(3) is None and say(8) is None)
check("watch list: the test channel is always checked too", say(2) == "@Bob Test received, 2 hops")
cfg(watch=["Public", "#drivebc"])
check("watch list without a test channel", say(0) is not None and say(3) is not None and say(8) is None)
cfg(watch=["public ", " DRIVEBC"])
check("watch list ignores case, spaces and '#'", say(0) is not None and say(3) is not None and say(2) is None)
cfg(watch=["#nonexistent"])
check("unknown channel in the watch list just matches nothing", say(0) is None and say(3) is None)

cfg(on=False, channel="#kod-bot")
check("Test reply switched OFF: never answers", say(0) is None and say(2) is None)
cfg(muted=True, channel="#kod-bot")
check("master mute: never answers", say(0) is None and say(2) is None)
cfg(reply="@{sender} {snr} dB / {hops} hops here", on=True)
check("custom text with placeholders", say(0, hops=255) == "@Bob 7.5 dB / 0 hops here", str(say(0, hops=255)))
cfg(redirect="{bad placeholder}", channel="#x")
check("bad placeholder falls back safely instead of crashing", say(0) == "@Bob Test received")

# the addon wires the settings in
spec = importlib.util.spec_from_file_location("ba", os.path.join(ROOT, "packages", "broadcast_alerts", "broadcast_alerts.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
saved = {"test_channel": " #kod-bot ", "test_watch": "Public, #bot-van ,", "test_redirect": "@{sender} use {channel}", "test_reply": "@{sender} ok", "sources": {"Test reply": True}}
api = mock.MagicMock(); api.get = lambda k, d=None: saved.get(k, d)
a = m.Addon(api); a.apply_settings()
check("addon title is 'Traffic, transit and weather'", m.Addon.title == "Traffic, transit and weather")
print("\nALL PASSED" if all(results) else f"\n{results.count(False)} FAILED of {len(results)}")
sys.exit(0 if all(results) else 1)
