import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import os, sys, time, types, tkinter as tk
from unittest import mock
BASE = ROOT
sys.path.insert(0, BASE); os.chdir(BASE)
import mcIRC as g, meshcore_io as io, gui_nodes, gui_sounds, gui_themes, gui_commands as gc

results = []
def check(label, cond, detail=""):
    results.append(bool(cond)); print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))

root = tk.Tk(); app = g.App(root, demo=True); root.update()
def drain():
    while not app.q.empty():
        it = app.q.get_nowait(); getattr(app, "_h_" + it[0])(*it[1:])
def pump(t=0.4):
    end = time.time() + t
    while time.time() < end: root.update(); drain(); time.sleep(0.02)
def key(prefix_hex, fill="0"): return (prefix_hex + fill * 64)[:64]

# ================= left tree = Status + channels only; people on the top bar =================
top = {i: app.tree.get_children(i) for i in app.tree.get_children()}
check("window tree has only Status and Channels", list(top) == ["Status", "Channels"], str(list(top)))
check("private windows live on the top bar only", all(n.startswith("@") for n in app.buttons) and not any(n.startswith("@") for n in app.tree.get_children("Channels")))

# ================= the double-window bug =================
app.connected = True
# (a) a named window is open (key known); a DM arrives from the same device, key only
FR = key("3ddcdf846ab8")
app.nodes.touch_contact({"public_key": FR, "adv_name": "Frenchie's Science Cap", "type": 1, "adv_lat": 49.1, "adv_lon": -122.8})
w1 = app.open_query("Frenchie's Science Cap", FR)
before = len([n for n in app.windows if n.startswith("@")])
app._dm_in("Hi", "3ddcdf846ab8", {"snr": 13.5, "hops": 0}); pump(0.2)
check("(a) DM from a known key lands in the named window - no second window", len([n for n in app.windows if n.startswith("@")]) == before and "@3ddcdf84" not in app.windows)
check("(a) the message is in that window", "Hi" in w1.text.get("1.0", "end"))

# (b) unknown sender first (key-only window), name resolves later while a named window already exists
app.close_window("@Frenchie's Science Cap"); app.nodes.db.execute("delete from nodes where public_key=?", (FR,)); app.nodes.db.commit()
app._dm_in("first hello", "3ddcdf846ab8", {"snr": 1, "hops": 0}); pump(0.1)
check("(b) unknown sender gets a key-named window", "@3ddcdf84" in app.windows)
named = app._new_private("Frenchie's Science Cap", None)            # user opens the same device by name (key not known to the window yet)
named.write([("[10:00] <me> earlier chat with the named window\n", "text")])
io.fetch_incoming_messages = io.fetch_incoming_messages
gui_nodes.fetch_radio_contacts = lambda: {FR: {"public_key": FR, "adv_name": "Frenchie's Science Cap", "type": 1, "adv_lat": 0, "adv_lon": 0, "last_advert": 1, "lastmod": 1}}
app._name_lookups.clear(); app.lookup_sender_name("3ddcdf846ab8"); pump(0.6)
names = [n for n in app.windows if n.startswith("@")]
check("(b) after the lookup there is ONE window for the device", "@3ddcdf84" not in app.windows and names.count("@Frenchie's Science Cap") == 1, str(names))
body = app.windows["@Frenchie's Science Cap"].text.get("1.0", "end")
check("(b) both histories survive in that window", "first hello" in body and "earlier chat" in body)
check("(b) the buttons list the device once", [b for b in app.buttons if "Frenchie" in b or "3ddcdf84" in b] == ["@Frenchie's Science Cap"])

# (c) opening by name while a key-only window exists reuses it
app.close_window("@Frenchie's Science Cap")
app.nodes.db.execute("delete from nodes"); app.nodes.db.commit()
app._dm_in("yo", "aabbccddeeff", {"snr": 1, "hops": 0}); pump(0.1)
app.nodes.touch_contact({"public_key": key("aabbccddeeff"), "adv_name": "Hilltop Rpt", "type": 2, "adv_lat": 49, "adv_lon": -123})
w = app.open_query("Hilltop Rpt", key("aabbccddeeff"))
check("(c) open by name renames the key-only window instead of making another", w.name == "@Hilltop Rpt" and "@aabbccdd" not in app.windows and sorted(n for n in app.windows if n.startswith("@")) == ["@Alice", "@Bob", "@Hilltop Rpt"], str([n for n in app.windows if n.startswith("@")]))
check("(c) repeater shows in repeater colour on the top bar", app.switchbar.items["@Hilltop Rpt"]["kind"] == 2 and str(app.buttons["@Hilltop Rpt"]["fg"]) in ("#1565c0",) or app.buttons["@Hilltop Rpt"]["bg"] != "")
check("(d) 8-hex key window names are recognised", app.KEY_NAME.match("@3ddcdf84") and not app.KEY_NAME.match("@Alice"))

# ================= @mentions and highlight words =================
parts, me, word = g.split_mentions("@[PMD - WizTag ] 4 hops, thanks @DemoNode and @Bob", "text", "DemoNode", ["thanks"])
tags = [(t, tg) for t, tg in parts if tg != "text"]
check("@[bracketed name] and @name are highlighted", ("@[PMD - WizTag ]", "mention") in tags and ("@Bob", "mention") in tags, str(tags))
check("an @mention of YOUR node gets the strong tag + flag", ("@DemoNode", "mention_me") in tags and me is True)
check("highlight words are underlined/flagged", ("thanks", "highlight") in tags and word is True)
parts, me, word = g.split_mentions("hello there", "text", "DemoNode", [])
check("plain text is untouched", parts == [("hello there", "text")] and not me and not word)
w = app.windows["Public"]; app.select_window("Public")
app.chat_line(w, "Joe", "@[VE7LSE WIZ TAG ] howdy @DemoNode", "text")
check("mentions get coloured tags in the window", w.text.tag_ranges("mention") and w.text.tag_ranges("mention_me"))

# ================= sounds =================
played = []
gui_sounds.play = lambda choice, custom="", bell=None: played.append(choice)
gui_sounds._last[0] = 0
app.settings.update(sounds_enabled=True, sound_private="Ding", sound_mention="Exclamation", sound_highlight="Question", sound_channel="None", highlight_words="bridge")
app.select_window("#drivebc")
app.chat_line(app.windows["Public"], "Zed", "hello @DemoNode", "text"); check("mention plays the mention sound", played == ["Exclamation"], str(played))
gui_sounds._last[0] = 0; app.chat_line(app.windows["Public"], "Zed", "the bridge is open", "text"); check("highlight word plays its sound", played[-1] == "Question")
gui_sounds._last[0] = 0; n = len(played); app.chat_line(app.windows["Public"], "Zed", "ordinary chatter", "text"); check("ordinary channel message: sound set to None -> silent", len(played) == n)
gui_sounds._last[0] = 0; app._dm_in("psst", key("0a0b0c0d0e0f"), {"snr": 1, "hops": 0}); check("private message plays the private sound", played[-1] == "Ding")
gui_sounds._last[0] = time.time(); n = len(played); app.chat_line(app.windows["Public"], "Zed", "@DemoNode again", "text"); check("cool-down stops back-to-back sounds", len(played) == n)
gui_sounds._last[0] = 0; app.settings["sounds_enabled"] = False; n = len(played); app.chat_line(app.windows["Public"], "Zed", "@DemoNode off", "text"); check("sounds switched off -> silent", len(played) == n)
app.settings["sounds_enabled"] = True
gui_sounds._last[0] = 0; n = len(played); app.chat_line(app.windows["Public"], "DemoNode", "my own words @DemoNode", "self"); check("your own messages never make a sound", len(played) == n)

# ================= themes =================
for name in gui_themes.THEMES:
    app.settings["theme"] = name; app.apply_theme(); root.update()
    t = gui_themes.THEMES[name]
    ok = (app.windows["Public"].text.cget("bg") == t["bg"] and str(app.nicklist.cget("bg")) == t["pane_bg"] and app.windows["Public"].text.tag_cget("mention_me", "background") == t["me_bg"])
    check(f"theme '{name}' recolours text, panes and tags", ok)
app.settings["theme"] = "Classic mIRC"; app.apply_theme()

# ================= slash commands =================
pop = app.cmd_popup
def sug(text, window="Public"):
    app.select_window(window); pop.update(text); root.update(); return [i[0].split(" ")[0] for i in pop.items]
s = sug("/")
check("typing '/' lists commands above the input", pop.visible and "/help" in s and "/contacts" in s and "/reboot" in s and len(s) > 20, f"{len(s)} shown")
check("list narrows as you type", sug("/re")[:3] != [] and all(x.startswith("/re") for x in sug("/re")), str(sug("/re")[:8]))
w = app.windows["@Hilltop Rpt"]
s = sug("/", "@Hilltop Rpt")
check("in a repeater window the repeater CLI commands are offered", "/neighbors" in s and "/stats-core" in s and "/clock" in s and "/start" in s or "/start ota" in " ".join(i[0] for i in pop.items))
check("...and the same list does not offer repeater-only commands elsewhere", "/neighbors" not in sug("/", "Public"))
check("/get shows the setting names", any("/get radio" in i[0] for i in (pop.update("/get ") or pop.items)))
check("/set tx narrows to matching settings", [i[0].split()[1] for i in (pop.update("/set t") or pop.items)] == ["tx", "txdelay"] or "tx" in [i[0].split()[1] for i in pop.items])
pop.update("/rebo"); root.update(); pop.lb.selection_set(0); pop.navigated = True; pop.entry.delete(0, "end"); pop.entry.insert(0, "/rebo"); pop.accept()
check("Tab / selecting completes the command", app.entry.get() == "/reboot ", repr(app.entry.get()))
app.entry.delete(0, "end"); pop.hide()

sent = []
def fake_exec(args, **kw):
    sent.append(args); return types.SimpleNamespace(stdout="INFO:meshcore:x\nok: ver v1.16\n", stderr="", returncode=0)
io.execute_mesh_command = fake_exec; io.CONNECTION_ARGS = ["-s", "COMX"]
app.select_window("@Hilltop Rpt")
with mock.patch.object(gc.messagebox, "askyesno", return_value=True) as ask:
    app.command("ver"); pump(0.5)
    check("repeater window: /ver is sent to that repeater (cmd + wmt8)", sent and sent[-1][:2] == ["-s", "COMX"] and "cmd" in sent[-1] and "ver" in sent[-1] and sent[-1][-1] == "wmt8" and key("aabbccddeeff") in sent[-1], str(sent[-1]))
    check("...and the reply appears in that window, INFO noise removed", "ok: ver v1.16" in app.windows["@Hilltop Rpt"].text.get("1.0", "end") and "INFO:meshcore" not in app.windows["@Hilltop Rpt"].text.get("1.0", "end"))
    app.command("login s3cret"); pump(0.4)
    check("/login sends 'login <key> <pwd>' and the password is not shown in the window", "login" in sent[-1] and "s3cret" in sent[-1] and "s3cret" not in app.windows["@Hilltop Rpt"].text.get("1.0", "end"))
    app.command("clock sync"); pump(0.4)
    check("with a password cached, the next command logs in first", sent[-1][2:5] == ["login", key("aabbccddeeff"), "s3cret"] and "clock sync" in sent[-1])
    ask.reset_mock(); sent.clear(); app.command("reboot"); pump(0.4)
    check("dangerous commands (reboot) ask first", ask.called and any("reboot" in a for a in sent[-1]))
    ask.return_value = False; sent.clear(); ask.reset_mock(); app.command("erase"); pump(0.3)
    check("answering No sends nothing", ask.called and not sent)
    ask.return_value = True
    sent.clear(); app.command("clear stats"); pump(0.4)
    check("'/clear stats' is the repeater command...", sent and "clear stats" in sent[-1])
    app.windows["@Hilltop Rpt"].write([("junk\n", "text")]); sent.clear(); app.command("clear"); pump(0.2)
    check("...but plain '/clear' still clears the window", not sent and "junk" not in app.windows["@Hilltop Rpt"].text.get("1.0", "end"))
    sent.clear(); app.command("rpt custom text"); pump(0.4)
    check("/rpt sends raw text", sent and "custom text" in sent[-1])
    app.select_window("Public"); sent.clear(); app.command("contacts"); pump(0.5)
    check("elsewhere /contacts runs meshcli on your own node", sent and sent[-1] == ["-s", "COMX", "contacts"], str(sent[-1:]))
    sent.clear(); app.command("meshcli get name"); pump(0.4)
    check("/meshcli runs any command", sent and sent[-1] == ["-s", "COMX", "get", "name"])
    sent.clear(); app.command("reboot"); pump(0.4)
    check("outside a repeater window /reboot means YOUR node (asks first)", ask.called and sent and sent[-1] == ["-s", "COMX", "reboot"])
    app.select_window("@Alice"); sent.clear(); app.command("neighbors"); pump(0.3)
    check("a person's window is not treated as a repeater", not any("wmt8" in a for a in sent))
    sent.clear(); app.select_window("Public"); app.command("map"); pump(0.3); check("built-in /map still works anywhere", app.map_win is not None); app.map_win.destroy()

# ================= right-click menus and closing =================
popped = []
tk.Menu.tk_popup = lambda self, x, y, entry="": popped.append(self)
def labels(m): return [m.entrycget(i, "label") for i in range(m.index("end") + 1) if m.type(i) not in ("separator",)]
app.show_window_menu("@Hilltop Rpt", 10, 10); lab = labels(popped[-1])
check("repeater menu: node info, login, status, neighbors, reboot, close", all(any(x in l for l in lab) for x in ("Node info", "Log in", "Status", "Neighbors", "Reboot", "Close")), str(lab))
app.show_window_menu("@Alice", 10, 10); lab = labels(popped[-1])
check("user menu: node info + close, no repeater actions", any("Node info" in l for l in lab) and "Close" in lab and not any("Reboot" in l for l in lab), str(lab))
app.show_window_menu("#drivebc", 10, 10); lab = labels(popped[-1])
check("channel menu: mark read, clear, log, close", all(x in lab for x in ("Mark as read", "Clear window", "Open log file", "Close")), str(lab))
app.show_window_menu("Status", 10, 10); check("Status menu has no Close", "Close" not in labels(popped[-1]))
app.close_window("Status"); check("Status cannot be closed", "Status" in app.windows)
app.close_window("#weather")
check("closing a channel removes it from the tree and remembers it", "#weather" not in app.windows and not app.tree.exists("#weather") and "#weather" in app.settings["closed_channels"])
app._h_channels()
check("a closed channel stays closed after reconnect", "#weather" not in app.windows)
app._h_chat("in", 7, "weather alert", "Zed", {"snr": 1, "hops": 1}) if False else None
io.CHANNEL_INDEX_BY_NAME["weather"] = 7
app._h_chat("in", 7, "storm warning", "Zed", {"snr": 1, "hops": 1}); check("a closed channel reopens when someone speaks", "#weather" in app.windows and "#weather" not in app.settings["closed_channels"])
app.close_window("@Hilltop Rpt"); check("closing a private window removes it from the top bar", "@Hilltop Rpt" not in app.buttons)
app.nicklist.delete(0, "end"); app.nicklist.insert("end", "Bob"); app.nicklist.insert("end", "Alice"); root.update()
e = types.SimpleNamespace(y=app.nicklist.bbox(1)[1] + 3, x_root=0, y_root=0); app._nick_menu(e)
check("nick-list menu: private message / node info / copy", any("Private message" in l for l in labels(popped[-1])) and any("Node info" in l for l in labels(popped[-1])), str(labels(popped[-1])))

# ================= options pages =================
app.open_options("Display"); root.update()
dlg = [x for x in root.winfo_children() if isinstance(x, g.OptionsDialog)][0]
check("Options has Display and Sounds pages", "Sounds" in dlg.frames and "Display" in dlg.frames)
dlg.vars["theme"].set("Night"); dlg.vars["highlight_words"].set("bridge, tunnel"); dlg.vars["sound_private"].set("Double beep")
check("Options Apply saves theme / words / sound choice", dlg.apply() and app.settings["theme"] == "Night" and app.settings["highlight_words"] == "bridge, tunnel" and app.settings["sound_private"] == "Double beep")
check("...and the theme is applied live", app.windows["Public"].text.cget("bg") == gui_themes.THEMES["Night"]["bg"])
dlg.destroy()

print("\nALL PASSED" if all(results) else f"\n{results.count(False)} FAILED of {len(results)}")
root.destroy()
sys.exit(0 if all(results) else 1)
