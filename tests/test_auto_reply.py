import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import importlib.util, sys, tkinter as tk
from unittest import mock
sys.path.insert(0, ROOT)
spec = importlib.util.spec_from_file_location("ar", os.path.join(ROOT, "packages", "auto_reply", "auto_reply.py"))
ar = importlib.util.module_from_spec(spec); spec.loader.exec_module(ar)

results = []
def check(label, cond, detail=""):
    results.append(bool(cond)); print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))

clock = [1000.0]
ar.time.time = lambda: clock[0]
CHANNELS = ["Public", "#bot-van", "#kod-bot", "#drivebc", "#weather"]
def make(rules=None, **settings):
    store, sent = dict(settings), []
    if rules is not None: store["rules"] = rules
    api = mock.MagicMock()
    api.get = lambda k, d=None: store.get(k, d)
    api.set = lambda k, v: store.__setitem__(k, v)
    api.send = lambda ch, text: sent.append((ch, text))
    api.channels = lambda: CHANNELS
    a = ar.Addon(api); a.on_load()
    return a, sent, store
def msg(channel, text, nick="Bob", hops=2, dm=False, snr=7.5): return {"channel": channel, "nick": nick, "text": text, "hops": hops, "snr": snr, "dm": dm}
def talk(a, sent, *args, **kw):
    clock[0] += 60; before = len(sent); a.on_message(msg(*args, **kw)); return sent[before:]
R = lambda **kw: {"name": kw.pop("name", "r"), "enabled": True, "match": "exact", "listen": "", "reply_to": "", "cooldown": 20, "reply": "ok", **kw}

# ---------- default rule ----------
a, sent, _ = make()
check("default rule: 'test' answered in the same channel", talk(a, sent, "Public", "test") == [("Public", "@Bob Test received, 2 hops")])
check("'t' + case-insensitive; chat ignored", talk(a, sent, "#drivebc", "T", nick="Al") != [] and talk(a, sent, "Public", "testing 123") == [] and talk(a, sent, "Public", "hello") == [])
check("direct messages ignored", talk(a, sent, "@Bob", "test", dm=True) == [])
check("hops 255 means direct (0 hops)", talk(a, sent, "Public", "test", nick="Di", hops=255)[0][1] == "@Di Test received, 0 hops")

# ---------- the #kod-bot behaviour, now just two rules ----------
kod = [R(name="Test here", triggers="test, t", listen="#kod-bot", reply="@{sender} Test received, {hops} hops"),
       R(name="Test elsewhere", triggers="test, t", reply="@{sender} Test should be made in #kod-bot")]
a, sent, _ = make(kod)
check("rules: test on #kod-bot -> normal reply there", talk(a, sent, "#kod-bot", "test") == [("#kod-bot", "@Bob Test received, 2 hops")])
check("rules: test elsewhere -> told to use #kod-bot (first match wins, later skipped)", talk(a, sent, "Public", "test") == [("Public", "@Bob Test should be made in #kod-bot")] and len(talk(a, sent, "#kod-bot", "test", nick="Z")) == 1)

# ---------- channels: heard on / reply to ----------
a, sent, _ = make([R(triggers="!traffic", listen="Public, #bot-van", reply_to="#drivebc", reply="@{sender} see #drivebc")])
check("heard on Public -> reply goes to a DIFFERENT channel", talk(a, sent, "Public", "!traffic") == [("#drivebc", "@Bob see #drivebc")])
check("not heard on an unlisted channel", talk(a, sent, "#weather", "!traffic") == [])
a, sent, _ = make([R(triggers="x", listen=" public ,  #BOT-van ")])
check("listen list ignores case, spaces and '#'", talk(a, sent, "Public", "x") != [] and talk(a, sent, "#bot-van", "x", nick="B") != [] and talk(a, sent, "#kod-bot", "x", nick="C") == [])
a, sent, _ = make([R(triggers="ping", reply="pong", reply_to="Public, #bot-van, #kod-bot, #drivebc, #weather")])
check("reply to several channels, capped at 3", [c for c, _ in talk(a, sent, "Public", "ping")] == ["Public", "#bot-van", "#kod-bot"])

# ---------- match styles + placeholders ----------
a, sent, _ = make([R(triggers="!say", match="starts with", reply="@{sender} you said: {text} ({keyword})")])
check("starts with: {text} is the rest, {keyword} the match", talk(a, sent, "Public", "!say hello there") == [("Public", "@Bob you said: hello there (!say)")])
check("starts with: must be a whole word", talk(a, sent, "Public", "!sayonara") == [] and talk(a, sent, "Public", "!say", nick="K")[0][1] == "@K you said:  (!say)")
a, sent, _ = make([R(triggers="traffic, road closed", match="contains", reply="check #drivebc, {sender}")])
check("contains: whole words/phrases anywhere", talk(a, sent, "Public", "any Traffic on hwy 1?") != [] and talk(a, sent, "Public", "is the road closed today", nick="M") != [] and talk(a, sent, "Public", "trafficking", nick="N") == [])
a, sent, _ = make([R(triggers="!t, !traffic", match="starts with", reply="LONG", cooldown=0), ])
check("longer keyword is matched first", talk(a, sent, "Public", "!traffic now")[0][1] == "LONG")
a, sent, _ = make([R(triggers="a", reply="{sender} {channel} {nope} {}")])
check("unknown / positional placeholders never crash", talk(a, sent, "Public", "a")[0][1].startswith("Bob Public {nope}") or len(sent) == 1, str(sent))

# ---------- rule order, enabled, cooldown, burst, on/off ----------
a, sent, _ = make([R(name="off", triggers="test", enabled=False, reply="OFF-RULE"), R(name="on", triggers="test", reply="ON-RULE")])
check("a switched-off rule is skipped, the next one answers", talk(a, sent, "Public", "test") == [("Public", "ON-RULE")])
a, sent, _ = make([R(triggers="test", cooldown=20)])
clock[0] += 100; a.on_message(msg("Public", "test")); n1 = len(sent)
clock[0] += 5;  a.on_message(msg("Public", "test")); n2 = len(sent)
clock[0] += 5;  a.on_message(msg("Public", "test", nick="Amy")); n3 = len(sent)
clock[0] += 30; a.on_message(msg("Public", "test")); n4 = len(sent)
check("cooldown per person: ignored within 20s, others answered, answered again after", (n1, n2, n3, n4) == (1, 1, 2, 3), str((n1, n2, n3, n4)))
clock[0] += 0.5; a.on_message(msg("Public", "test", nick="Cat")); a.on_message(msg("Public", "test", nick="Dan"))
check("burst protection: replies never closer than 2s", len(sent) == 3)
a, sent, store = make()
a.toggle(); check("switched OFF: silent", store["enabled"] is False and talk(a, sent, "Public", "test") == [])
a._command("on"); check("/autoreply on works", talk(a, sent, "Public", "test") != [])

# ---------- the Options page ----------
root = tk.Tk(); root.withdraw()
a, sent, store = make([R(name="one", triggers="aaa", reply="r1"), R(name="two", triggers="bbb", reply="r2")])
page = a.build_options(tk.Frame(root)); root.update()
check("page lists the saved rules", [a.tree.item(i, "values")[1] for i in a.tree.get_children()] == ["one", "two"])
a.tree.selection_set("0"); a.move(1); root.update()
check("Move down reorders", [r["name"] for r in a.rules] == ["two", "one"] and a.tree.selection() == ("1",))
a.move(1); check("Move down at the end does nothing", [r["name"] for r in a.rules] == ["two", "one"])
a.tree.selection_set("0"); a.delete_rule(); check("Delete removes the rule", [r["name"] for r in a.rules] == ["one"])
a.add_rule(); dlg = [w for w in root.winfo_children() if isinstance(w, ar.RuleDialog)][0]
dlg.v["triggers"].set("!bridge, !tunnel"); dlg.v["match"].set("starts with"); dlg.v["reply"].set("Massey is open, {sender}"); dlg.v["listen"].set("Public")
menu = tk.Menu(root, tearoff=0); dlg._fill_picker(menu, "reply_to")
check("channel picker offers the known channels", [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)] == CHANNELS)
dlg._toggle("reply_to", "#drivebc", True); dlg._toggle("reply_to", "#weather", True); dlg._toggle("reply_to", "#drivebc", False)
check("ticking/unticking channels edits the list", dlg.v["reply_to"].get() == "#weather", dlg.v["reply_to"].get())
dlg.ok(); root.update()
check("OK adds the new rule (name defaults to first keyword)", len(a.rules) == 2 and a.rules[1]["name"] == "!bridge" and a.rules[1]["reply_to"] == "#weather" and a.rules[1]["match"] == "starts with")
a.tree.selection_set("1"); a.edit_rule(); dlg = [w for w in root.winfo_children() if isinstance(w, ar.RuleDialog)][-1]
dlg.v["reply"].set("edited {sender}"); dlg.v["cooldown"].set("5"); dlg.ok()
check("Edit changes the rule in place", a.rules[1]["reply"] == "edited {sender}" and a.rules[1]["cooldown"] == 5.0)
with mock.patch.object(ar.messagebox, "showerror") as err:
    a.add_rule(); bad = [w for w in root.winfo_children() if isinstance(w, ar.RuleDialog)][-1]
    bad.ok()
    check("a rule without keywords/reply is refused", err.called and len(a.rules) == 2)
    bad.v["triggers"].set("x"); bad.v["reply"].set("y"); bad.v["cooldown"].set("abc"); bad.ok()
    check("a non-numeric cooldown is refused", err.call_count == 2 and len(a.rules) == 2)
    bad.destroy()
a.enabled_var.set(False); a.apply_options()
check("Apply saves rules + on/off", store["enabled"] is False and [r["name"] for r in store["rules"]] == ["one", "!bridge"] and a.button.config.called)
root.destroy()

print("\nALL PASSED" if all(results) else f"\n{results.count(False)} FAILED of {len(results)}")
sys.exit(0 if all(results) else 1)
