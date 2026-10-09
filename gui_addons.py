"""Addon framework for the mIRC-style GUI.

An addon is one Python file in the `addons/` folder (files starting with `_` are ignored) that defines a
subclass of AddonBase.  See addons/_example_addon.py for a commented template.  Hooks run on the GUI thread,
so do slow work (anything that talks to the radio or the network) through `self.api.run_background(...)`.
A crashing addon is isolated: the error is printed in the status window and the GUI keeps running."""
import contextlib, copy, importlib.util, os, threading, traceback

ADDON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addons")


class AddonBase:
    title = ""          # shown in the Addons dialog (defaults to the file name)
    version = "1.0"
    author = ""
    description = ""
    tick_seconds = 0    # >0: on_tick() is called about every this many seconds

    def __init__(self, api): self.api = api

    def on_load(self): """The addon was enabled/loaded (also called when the GUI starts)."""
    def on_unload(self): """The addon is being disabled/reloaded - stop threads, release things here."""
    def on_connect(self): """Connected to the node (also called on load if already connected)."""
    def on_disconnect(self): """The connection to the node ended."""
    def on_message(self, msg): """A chat message arrived. msg: dict(channel, channel_idx, nick, text, snr, hops, raw)."""
    def on_tick(self): """Called every `tick_seconds` seconds."""
    def on_packet(self, pkt): """The main radio heard a packet: dict(t, type, route, path, snr, rssi, length) - for an advert also 'packet' (hex)."""
    def on_demo(self): """Only in `--demo` mode: fill your windows / map layers with fake data."""
    def on_theme(self, theme): """The colours changed (Options: colour theme or skin).  theme: dict of colours, see gui_themes.py."""
    def build_options(self, parent):
        """Return a tk.Frame (child of `parent`) to show as this addon's page in Options, or None."""
        return None
    def apply_options(self): """Options OK/Apply was pressed - read your widgets and store them via self.api.set()."""


def _node_ctx(api, node):
    """api.for_node(node), or nothing for an api object without it."""
    f = getattr(api, "for_node", None)
    return f(node) if f else contextlib.nullcontext()


class AddonAPI:
    """What an addon gets as `self.api`.  Everything here is safe to call from the GUI thread; send() and
    run_background() are safe from any thread."""
    def __init__(self, app, name):
        self._app, self.name = app, name
        self.display = name   # the addon's human title once it is instantiated (shown in menus)
        self._commands, self._menu, self._layers, self._buttons, self._helps, self._actions = [], [], [], [], [], []
        self._items = []          # (label, fn) of this addon's Addons-menu entries
        self._ctx = threading.local()                      # which node's settings get/set use (see for_node)

    # -- settings (persisted in gui_settings.json under "addons") --
    # Each node can have its own settings ('_per_node': {'wifi 1': {key: value}}); what a node doesn't set comes from the defaults.  get/set
    # work on the node in context: the one a message came in on (on_message, reply), or the tab open in the settings window.
    def _store(self): return self._app.settings.setdefault("addons", {}).setdefault(self.name, {})
    def get(self, key, default=None):
        base = self._app.settings.setdefault("addons", {}).get(self.name, {})
        own = base.get("_per_node", {}).get(self.node_context() or "", {})
        if key in own: return own[key]
        value = base.get(key, default)
        seen = getattr(self._ctx, "seen", None)              # the settings window notes what a node inherits (to keep only real changes)
        if seen is not None and key not in seen: seen[key] = copy.deepcopy(value)
        return value
    def set(self, key, value):
        """Saved for the node in context when it is being set up on its own (its tab in the settings window) or already has this setting of
        its own; otherwise to the defaults (e.g. a list a bot keeps up to date while answering)."""
        node, store = self.node_context(), self._store()
        own = store.get("_per_node", {}).get(node or "", {})
        mine = node and (getattr(self._ctx, "own", False) or key in own)
        (store.setdefault("_per_node", {}).setdefault(node, {}) if mine else store)[key] = value
        self._app.save()
    def node_context(self):
        """The node whose settings get/set use right now ('main', an extra node's label), or None: the defaults for all nodes."""
        return getattr(self._ctx, "node", None)
    @contextlib.contextmanager
    def for_node(self, node, own=False):
        """with api.for_node('wifi 1'): ... - get uses that node's own settings (falling back to the defaults); with own=True (the node's
        tab in the settings window) set saves them as that node's own."""
        prev = (self.node_context(), getattr(self._ctx, "own", False))
        self._ctx.node, self._ctx.own = node, own
        try: yield self
        finally: self._ctx.node, self._ctx.own = prev
    def own_settings(self, node):
        """The settings this node has of its own ({} when it uses the defaults)."""
        return dict(self._store().get("_per_node", {}).get(node, {}))
    def clear_own_settings(self, node):
        if self._store().get("_per_node", {}).pop(node, None) is not None: self._app.save()

    # -- output --
    def log(self, text, level="info"): self._app.q.put(("call", lambda: self._app.status_line(f"*** [{self.name}] {text}", level)))
    def notice(self, text, level="info"):
        """A line in the window the person is looking at (Status if none), for answers to something they just did.  levels: info warn error"""
        def show():
            w = self._app.current or self._app.status
            w.write(self._app.stamp() + [(f"*** [{self.name}] {text}", level)])
        self._app.q.put(("call", show))
    def ensure_window(self, name, topic=""): return self._app.ensure_window(name, topic or f"Window of addon '{self.name}'")
    def write(self, window, text, tag="text"):
        """Write a line into a window (created on demand). tags: text info warn error new clear critical meta"""
        self._app.q.put(("call", lambda: self._app.ensure_window(window, "").write(self._app.stamp() + [(text, tag)])))

    # -- radio --
    @property
    def connected(self): return self._app.connected
    def channel_index(self, name):
        from gui_common import channel_index
        return channel_index(name)
    def send(self, channel, text):
        """Send `text` to a channel (display name like '#drivebc'/'Public', or an index). Runs in the background."""
        self._app.send_to(channel, text)
    def current_channel(self):
        """Display name of the channel window in front ('#drivebc', 'Public'), or None for Status / private windows."""
        w = self._app.current
        return w.name if w is not None and w is not self._app.status and not w.name.startswith("@") else None
    def reply(self, msg, text, private=None):
        """Answer a message where it came from: its channel, or the person for a direct message (msg as given to on_message).
        private=True (default: the addon's 'Send answers by private message' setting) answers a channel message privately instead."""
        if private is None:
            with self.for_node(msg.get("node") or "main"): private = bool(self.get("_reply_private", False))      # that node's choice
        if private and not msg.get("dm"):
            self._app.q.put(("call", lambda: self._app.reply_privately(msg, text)))
            return
        if msg.get("dm"):
            w = self._app.windows.get(msg["channel"])
            if w is not None: self._app.q.put(("call", lambda: self._app.send_dm(w, text)))
        else:
            self._app.send_to(msg["channel"], text)
    def node_position(self):
        """(lat, lon, node name) from Options > Node, for "near me" answers; lat/lon are 0 when not set."""
        s = self._app.settings
        try: return float(s.get("node_lat") or 0), float(s.get("node_lon") or 0), s.get("node_name", "")
        except (TypeError, ValueError): return 0.0, 0.0, s.get("node_name", "")
    def send_current(self, text):
        """Send `text` to the window in front: its channel, or the person of a private window.  False (nothing sent) for the Status window."""
        w = self._app.current
        if w is None or w is self._app.status: return False
        if w.name.startswith("@"): self._app.send_dm(w, text)
        else: self._app.send_to(w.name, text)
        return True
    def channels(self):
        """Names of the channel windows mcIRC knows right now (for pickers): 'Public', '#drivebc', ..."""
        return [n for n in self._app.windows if n != "Status" and not n.startswith("@")]
    def run_background(self, fn, done=None):
        """Run fn() on a worker thread; done(result_or_exception) is then called on the GUI thread."""
        self._app.bg(fn, done or (lambda r: None))
    def after(self, ms, fn): self._app.root.after(ms, fn)
    @property
    def nodes(self): return self._app.nodes
    @property
    def theme(self):
        """The colours in use right now (gui_themes.py keys: bg fg pane_bg pane_fg entry_bg sel_bg ...), skin colours included."""
        return dict(self._app.theme)
    def ui(self):
        """The main window's parts, for addons that restyle the look: root, toolbar, statusbar, paned, tree, nicklist, entry, topic.  Change colours and relief only;
        never destroy or re-pack them."""
        a = self._app
        return {k: getattr(a, k) for k in ("root", "toolbar", "statusbar", "paned", "tree", "nicklist", "entry", "topic") if hasattr(a, k)}

    # -- UI extension points (removed automatically when the addon is unloaded) --
    def add_command(self, name, fn, help=""):
        """Slash command: typing /name args calls fn(args_string)."""
        self._app.commands[name.lower()] = (fn, help, self.name)
        self._commands.append(name.lower())
    def add_menu_item(self, label, fn):
        """An entry in this addon's submenu of the Addons menu ('MeshCore tools > Node clock...').  Every switched-on addon has that
        submenu; mcIRC ends it with 'Settings...' and 'Switch off'."""
        self._items.append((label, fn))
        self._draw_menu()
    def _draw_menu(self):
        import tkinter as tk
        m = getattr(self._app, "addon_menu", None)
        if m is None: return
        for entry in self._menu:
            try: m.delete(entry)
            except Exception: pass
        self._menu = []
        sub = tk.Menu(m, tearoff=0)
        for label, fn in self._items: sub.add_command(label=label, command=fn)
        if self._items: sub.add_separator()
        sub.add_command(label="Settings...", command=self._open_settings)
        sub.add_command(label="Switch off", command=self._switch_off)
        m.add_cascade(label=self.display, menu=sub)
        self._menu.append(self.display)
    def show_text(self, title, text):
        """A small read-only window with lines of text (a list, a status).  text: a string, or a function returning one - then the window
        has a Refresh button.  Returns the window."""
        import tkinter as tk
        from tkinter import ttk
        win = tk.Toplevel(self._app.root)
        win.title(title); win.geometry("640x380")
        import gui_platform
        box = tk.Text(win, wrap="word", font=(gui_platform.EDITOR_FONT_NAME, 9))
        sb = ttk.Scrollbar(win, command=box.yview); box.config(yscrollcommand=sb.set)
        def fill():
            box.config(state="normal"); box.delete("1.0", "end")
            box.insert("end", text() if callable(text) else text); box.config(state="disabled")
        bar = tk.Frame(win); bar.pack(side="bottom", fill="x", padx=6, pady=6)
        if callable(text): ttk.Button(bar, text="Refresh", command=fill).pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        sb.pack(side="right", fill="y"); box.pack(side="left", fill="both", expand=True)
        fill()
        return win
    def _open_settings(self):
        import gui_addonsettings
        gui_addonsettings.open_settings(self._app, self.name, self._app.root)
    def _switch_off(self):
        def off():
            self._app.addons.set_enabled(self.name, False)
            self._app.status_line(f"*** {self.display} is switched off (Tools > Addons switches it back on).")
        self._app.root.after(0, off)          # not from inside its own menu, which is removed with it
    def add_toolbar_button(self, text, fn):
        """Returns the tk.Button so you can change its text/colour later."""
        import tkinter as tk
        b = tk.Button(self._app.toolbar, text=text, command=fn, bg=self._app.toolbar["bg"], relief="flat", overrelief="raised", padx=8, pady=2)
        b.pack(side="left", padx=1, pady=2)
        self._buttons.append(b)
        return b
    def add_switch(self, key="enabled", default=False, toggle=None):
        """An ON/OFF switch on the toolbar ('Fun bot: ON') for the setting `key`; toggle() is called instead of flipping it when the addon
        has to do more (connect, disconnect).  Hidden when the addon's settings say so ('Show its switch on the toolbar')."""
        self._switch = (key, default, toggle)
        self._draw_switch()
    def _draw_switch(self):
        sw, btn = getattr(self, "_switch", None), getattr(self, "_switch_btn", None)
        if not sw or not self.get("_toolbar", True):
            if btn is not None:
                if btn in self._buttons: self._buttons.remove(btn)
                btn.destroy()
                self._switch_btn = None
            return
        if btn is None:
            self._switch_btn = self.add_toolbar_button("", self._flip)
            self._tick_switch()
        self._paint_switch()
    def switch_on(self):
        key, default, _ = self._switch
        return bool(self.get(key, default))
    def _flip(self):
        key, default, toggle = self._switch
        if toggle: toggle()
        else: self.set(key, not self.get(key, default))
        self._paint_switch()
    def _paint_switch(self):
        btn = getattr(self, "_switch_btn", None)
        if btn is None or not btn.winfo_exists(): return
        on = self.switch_on()
        btn.config(text=f"{self.display}: {'ON' if on else 'OFF'}", fg="#006400" if on else "#555555")
    def _tick_switch(self):
        """Follows changes made elsewhere (its settings window, a command)."""
        btn = getattr(self, "_switch_btn", None)
        if btn is None or not btn.winfo_exists(): return
        self._paint_switch()
        self._app.root.after(1500, self._tick_switch)
    def add_name_action(self, label, fn, group=None):
        """An entry in the right-click menu on a name in the chat: label ('{nick}' becomes the name), fn(nick) is called.
        group: put it in a submenu with that title ('Fun') - for addons with many entries."""
        entry = (self.name, label, fn, group)
        if not hasattr(self._app, "name_actions"): self._app.name_actions = []
        self._app.name_actions.append(entry)
        self._actions.append(entry)
    def clear_name_actions(self):
        """Removes this addon's name-menu entries (to add an edited list again)."""
        for e in self._actions:
            if e in getattr(self._app, "name_actions", []): self._app.name_actions.remove(e)
        self._actions = []
    def want_raw_packets(self, on=True):
        """While on, on_packet() gets every packet the main radio hears whole ('packet', hex - as it went over the air), not only adverts."""
        wanted = self._app.__dict__.setdefault("raw_packets_wanted", set())
        (wanted.add if on else wanted.discard)(self.name)
    def sign_with_node(self, data):
        """The main node signs `data` (bytes) with its own key - the private key never leaves the radio.  -> signature hex.
        Blocks for a few seconds and holds the radio: call it from run_background.  Needs a USB or Wi-Fi connection."""
        import json as _json, subprocess, sys
        import gui_adverts
        import meshcore_io as io
        args = gui_adverts.helper_args(io.CONNECTION_ARGS)
        if args is None: raise RuntimeError("signing needs a USB or Wi-Fi connection to the node")
        with io.MESH_LOCK:
            r = subprocess.run([sys.executable, os.path.join(BASE_DIR, "gui_sign_proc.py")] + args + ["--hex", bytes(data).hex()],
                               capture_output=True, text=True, timeout=90, creationflags=io.NO_WINDOW, cwd=BASE_DIR)
        res = next((_json.loads(l) for l in reversed(r.stdout.splitlines()) if l.startswith("{")), {"error": r.stderr.strip()[-200:] or "no answer"})
        if "signature" not in res: raise RuntimeError(f"the node did not sign: {res.get('error')}")
        return res["signature"]
    def has_command(self, name):
        """True when a /command of that name exists already (another addon's, or mcIRC's own)."""
        return name.lower() in self._app.commands
    def add_map_layer(self, label, provider, color="#d32f2f"):
        """Adds a toggle to the map.  provider() -> list of (lat, lon, label) tuples, called on each map refresh."""
        key = label if label not in self._app.map_layers else f"{self.display}: {label}"
        self._app.map_layers[key] = (provider, color)
        self._layers.append(key)

    # -- bots: what each one answers, so 'bothelp' can list it --
    def add_bot_commands(self, provider):
        """provider(channel, dm) -> ['wx <place>', 'moon', ...]: the commands this addon answers right now in that channel (dm: private message)."""
        entry = (self, provider)
        if not hasattr(self._app, "bot_helps"): self._app.bot_helps = []
        self._app.bot_helps.append(entry)
        self._helps.append(entry)
    def disconnect(self):
        """Let go of the radio (e.g. before a firmware update).  Safe from any thread."""
        self._app.q.put(("call", self._app.disconnect))
    def add_extra_node(self, cfg):
        """Adds a node to Options > More nodes (replacing one with the same label) and connects it if mcIRC is connected."""
        nodes = [c for c in self._app.settings.get("extra_nodes", []) if c.get("label") != cfg["label"]]
        self._app.settings["extra_nodes"] = nodes + [dict(cfg)]
        self._app.save()
        if self._app.connected: self._app.q.put(("call", self._app.start_extra_nodes))
    def node_choices(self):
        """[(key, text)]: the main node ('main') and every node in Options > More nodes (key = its label) - for a 'which node' list."""
        return self._app.node_choices()
    def node_ready(self, key="main"):
        """True when that node is connected and answering."""
        return self._app.node_ready(key)
    def on_node(self, key="main"):
        """`with api.on_node(key):` inside a background job - meshcli commands for the node (meshcore_io.node_args()) go to that node."""
        return self._app.node_target(key)
    def refresh_channels(self):
        """Read the node's channels again (after a tool added / removed one): the channel windows follow.  Call from a background job."""
        import meshcore_io as io
        io.CHANNEL_INDEX_BY_NAME.clear()
        io.resolve_channel_indices()
        self._app.q.put(("channels",))
    @property
    def packet_log(self):
        """Packets the radio heard recently: [{t, type, route, path, size, snr, rssi, length}] (no content)."""
        return list(getattr(self._app, "packet_log", []))
    @property
    def log_dir(self):
        """The folder with the chat logs (<window>.txt) - read them, never write there."""
        return getattr(self._app, "log_dir", None)
    @property
    def signal_traces(self): return list(getattr(self._app, "signal_traces", []))
    def bot_names(self):
        """Titles of the loaded addons that registered bot commands (whether or not they answer anywhere right now)."""
        out = []
        for api, _ in getattr(self._app, "bot_helps", []):
            if api.display not in out: out.append(api.display)
        return out
    def bot_commands(self, channel, dm=False):
        """{addon title: [commands]} for everything the loaded bots answer in `channel` (only bots that answer something there)."""
        out = {}
        for api, provider in list(getattr(self._app, "bot_helps", [])):
            try: cmds = list(provider(channel, dm) or [])
            except Exception: cmds = []
            if cmds: out[api.display] = cmds
        return out

    def _cleanup(self):
        for e in self._helps:
            if e in getattr(self._app, "bot_helps", []): self._app.bot_helps.remove(e)
        self._helps = []
        self.clear_name_actions()
        self.want_raw_packets(False)
        for c in self._commands: self._app.commands.pop(c, None)
        for label in self._menu:
            try: self._app.addon_menu.delete(label)
            except Exception: pass
        for l in self._layers: self._app.map_layers.pop(l, None)
        for b in self._buttons:
            try: b.destroy()
            except Exception: pass
        self._commands, self._menu, self._layers, self._buttons, self._items = [], [], [], [], []
        self._switch_btn = None


class AddonManager:
    def __init__(self, app):
        self.app, self.loaded, self.errors = app, {}, {}  # name -> (instance, api)
        self._last_tick = {}

    def discover(self):
        if not os.path.isdir(ADDON_DIR): return []
        return sorted(f[:-3] for f in os.listdir(ADDON_DIR) if f.endswith(".py") and not f.startswith("_"))

    def enabled_names(self):
        enabled = self.app.settings.setdefault("addons_enabled", {})
        return [n for n in self.discover() if enabled.get(n, False)]   # nothing is on until it is installed / enabled

    def load_all(self):
        for n in self.enabled_names(): self.load(n)

    def load(self, name):
        if name in self.loaded: return True
        try:
            _fresh_helpers(name)
            spec = importlib.util.spec_from_file_location(f"addon_{name}", os.path.join(ADDON_DIR, name + ".py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls = getattr(mod, "Addon", None) or next(c for c in vars(mod).values()
                                                       if isinstance(c, type) and issubclass(c, AddonBase) and c is not AddonBase)
            api = AddonAPI(self.app, name)
            inst = cls(api)
            api.display = inst.title or name
            self.loaded[name] = (inst, api)
            self.errors.pop(name, None)
            self._call(name, "on_load")
            if name in self.loaded: api._draw_menu()               # its Addons submenu, even with no entries of its own
            if name in self.loaded and getattr(inst, "switch", None):  # 'switch = "enabled"': an ON/OFF switch on the toolbar
                api.add_switch(inst.switch, getattr(inst, "switch_default", False), getattr(inst, "toggle", None))
            if self.app.connected: self._call(name, "on_connect")
            return True
        except Exception:
            self.errors[name] = traceback.format_exc()
            self.loaded.pop(name, None)
            try:
                import gui_diag
                gui_diag.event("addon", f"'{name}' failed to load:\n{self.errors[name]}")
            except Exception: pass
            self.app.status_line(f"*** Addon '{name}' failed to load: {self.errors[name].strip().splitlines()[-1]}", "error")
            return False

    def unload(self, name):
        if name not in self.loaded: return
        if self.app.connected: self._call(name, "on_disconnect")
        self._call(name, "on_unload")
        self.loaded.pop(name)[1]._cleanup()

    def reload(self, name):
        self.unload(name)
        return self.load(name)

    def set_enabled(self, name, on):
        self.app.settings.setdefault("addons_enabled", {})[name] = on
        self.app.save()
        (self.load if on else self.unload)(name)

    def _call(self, name, hook, *args):
        inst = self.loaded[name][0]
        try: return getattr(inst, hook)(*args)
        except Exception as e:
            tb = traceback.format_exc().strip().splitlines()
            self.app.status_line(f"*** Addon '{name}' error in {hook}(): {tb[-1]}", "error", log=False)
            try:
                import gui_diag            # where in the code; an on_message error's own text could quote a message, so not that one's
                gui_diag.failure("addon", f"'{name}' {getattr(inst, 'version', '')} {hook}()", e, with_message=hook != "on_message")
            except Exception: pass

    def nodes_for(self, name):
        """The nodes an addon works on: 'main' and/or extra node labels (its settings window, 'Use on these nodes')."""
        return list(self.app.settings.get("addons", {}).get(name, {}).get("_nodes", ["main"]))

    def dispatch(self, hook, *args):
        if hook == "on_message" and args and isinstance(args[0], dict):
            node = args[0].get("node") or "main"
            for name in list(self.loaded):
                if node in self.nodes_for(name):
                    with _node_ctx(self.loaded[name][1], node): self._call(name, hook, *args)       # it answers with that node's settings
            return
        if hook == "on_packet":                                                                      # packets come from the main radio
            for name in list(self.loaded):
                with _node_ctx(self.loaded[name][1], "main"): self._call(name, hook, *args)
            return
        for name in list(self.loaded): self._call(name, hook, *args)

    def tick(self, now):
        for name, (inst, _) in list(self.loaded.items()):
            if inst.tick_seconds and now - self._last_tick.get(name, 0) >= inst.tick_seconds:
                self._last_tick[name] = now
                self._call(name, "on_tick")

    def info(self, name):
        if name in self.loaded:
            i = self.loaded[name][0]
            return (i.title or name, i.version, i.author, i.description)
        return (name, "", "", self.errors.get(name, "").strip().splitlines()[-1] if name in self.errors else "(disabled)")


# ===================================================================================================================
# Installing / removing addon packages.  An addon is NOT shipped enabled: it lives as a package (a folder or .zip with
# an addon.json manifest, e.g. packages/broadcast_alerts) and is copied into place by "Install..." in the Addons dialog.
# ===================================================================================================================
import hashlib, json, shutil, time, zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ADDON_DIR, ".installed.json")
PROTECTED_ROOT = {"mcIRC.py", "meshcore_gui.py", "meshcore_io.py"}
PIP_MODULES = {"paho-mqtt": "paho.mqtt", "requests": "requests", "gtfs-realtime-bindings": "google.transit", "pyserial": "serial", "tkintermapview": "tkintermapview"}


def vkey(version):
    """'1.10.2' -> (1, 10, 2) so versions compare numerically; junk compares lowest."""
    try: return tuple(int(p) for p in str(version).strip().lstrip("v").split("."))
    except ValueError: return (0,)


def _fresh_helpers(name):
    """Before an addon is (re)loaded, helper modules its package put next to the app (meshbot_common.py, ...) are read again: after an
    update the new addon must never run with the older copy still in memory."""
    import importlib, sys
    for dest in read_installed().get(name, {}).get("files", []):
        if "/" in dest or not dest.endswith(".py"): continue
        mod = sys.modules.get(dest[:-3])
        if mod is not None and getattr(mod, "__file__", None):
            try: importlib.reload(mod)
            except Exception: pass


def read_installed():
    try:
        with open(STATE_PATH, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}


def _write_installed(state):
    os.makedirs(ADDON_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f: json.dump(state, f, indent=2)


def _dest_ok(rel):
    """Where a package may put files: addons/<name>.py, or a plain <name>.py next to the app (the engine) - never core files."""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    if rel.startswith("/") or ".." in parts or not rel.endswith(".py") or len(parts) > 2: return False
    if len(parts) == 2: return parts[0] == "addons" and not parts[1].startswith("_")
    return parts[0] not in PROTECTED_ROOT and not parts[0].startswith(("gui_", "_"))


def _backup(path, label):
    if not os.path.exists(path): return
    dest = os.path.join(BASE_DIR, "backup", f"{label}-{time.strftime('%Y%m%d-%H%M%S')}", os.path.relpath(path, BASE_DIR))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(path, dest)


def _read_package(source):
    """-> (manifest, {dest: bytes}) from a folder / addon.json / .zip / single .py file; raises ValueError if unusable."""
    source = os.path.abspath(source)
    if source.lower().endswith(".py"):
        name = os.path.splitext(os.path.basename(source))[0]
        with open(source, "rb") as f: data = f.read()
        return {"name": name, "title": name, "version": "?", "files": {os.path.basename(source): f"addons/{name}.py"}}, {f"addons/{name}.py": data}
    if source.lower().endswith(".zip"):
        with zipfile.ZipFile(source) as zf:
            names = zf.namelist()
            root = next((n[:-len("addon.json")] for n in names if n.endswith("addon.json") and n.count("/") <= 1), None)
            if root is None: raise ValueError("this zip has no addon.json")
            manifest = json.loads(zf.read(root + "addon.json"))
            files = {}
            for src, dest in manifest["files"].items():
                if ".." in src.replace("\\", "/").split("/"): raise ValueError(f"unsafe path in package: {src}")
                files[dest] = zf.read(root + src)
        return manifest, files
    folder = os.path.dirname(source) if source.lower().endswith(".json") else source
    mpath = os.path.join(folder, "addon.json")
    if not os.path.exists(mpath): raise ValueError("no addon.json in that folder")
    with open(mpath, encoding="utf-8") as f: manifest = json.load(f)
    files, real_folder, real_base = {}, os.path.realpath(folder), os.path.realpath(BASE_DIR)
    for src, dest in manifest["files"].items():
        path = os.path.realpath(os.path.join(folder, src))
        inside = path.startswith(real_folder + os.sep) or (real_folder.startswith(real_base + os.sep) and path.startswith(real_base + os.sep))
        if not inside: raise ValueError(f"unsafe path in package: {src}")
        with open(path, "rb") as f: files[dest] = f.read()
    return manifest, files


def install_package(source):
    """Copies a package (folder / addon.json / .zip / .py) into place.  See install_files()."""
    manifest, files = _read_package(source)
    return install_files(manifest, files, os.path.abspath(source))


def install_files(manifest, files, origin):
    """Validates and writes a package given as (manifest, {dest: bytes}).  Returns {name, title, version, files, missing};
    raises ValueError with a readable reason.  Existing files that differ are backed up first."""
    name = manifest.get("name", "")
    if not name.isidentifier() or name.startswith("_"): raise ValueError(f"bad addon name '{name}'")
    if f"addons/{name}.py" not in files: raise ValueError(f"the package must provide addons/{name}.py")
    for dest, data in files.items():
        if not _dest_ok(dest): raise ValueError(f"the package wants to write '{dest}', which is not allowed")
        try: compile(data, dest, "exec")
        except SyntaxError as e: raise ValueError(f"{dest} has a syntax error: {e}")
    written = []
    for dest, data in files.items():
        path = os.path.join(BASE_DIR, *dest.split("/"))
        if os.path.exists(path):
            with open(path, "rb") as f: same = f.read() == data
            if same: written.append(dest); continue
            _backup(path, "addon-" + name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f: f.write(data)
        os.replace(tmp, path)
        written.append(dest)
    state = read_installed()
    state[name] = {"version": manifest.get("version", "?"), "title": manifest.get("title", name), "files": written, "package": origin}
    _write_installed(state)
    import importlib.util
    missing = [p for p in manifest.get("requires", []) if importlib.util.find_spec(PIP_MODULES.get(p, p.replace("-", "_"))) is None]
    return {"name": name, "title": manifest.get("title", name), "version": manifest.get("version", "?"), "files": written, "missing": missing}


def uninstall_package(name):
    """Deletes the addon file (the engine/support files stay: the console bot can still use them).  Settings are kept."""
    state = read_installed()
    path = os.path.join(ADDON_DIR, name + ".py")
    if os.path.exists(path):
        _backup(path, "removed-" + name)
        os.remove(path)
    state.pop(name, None)
    _write_installed(state)


def _install(self, source):
    info = install_package(source)
    self.set_enabled(info["name"], True)
    return info


def _uninstall(self, name):
    self.unload(name)
    self.app.settings.setdefault("addons_enabled", {}).pop(name, None)
    uninstall_package(name)
    self.app.save()


def _update_installed(self, repo_root=BASE_DIR):
    """After an app update: refresh installed addons whose package (in repo_root/packages) has a newer version.
    Their settings live in gui_settings.json and are never touched.  Returns [(name, old, new)]."""
    done = []
    for name, rec in read_installed().items():
        manifest_path = os.path.join(repo_root, "packages", name, "addon.json")
        if not os.path.exists(manifest_path): continue
        with open(manifest_path, encoding="utf-8") as f: new = json.load(f).get("version", "0")
        if vkey(new) > vkey(rec.get("version", "0")):
            was_loaded = name in self.loaded
            if was_loaded: self.unload(name)
            install_package(manifest_path)
            if was_loaded or self.app.settings.get("addons_enabled", {}).get(name): self.load(name)
            done.append((name, rec.get("version"), new))
    return done


def _installed_version(self, name):
    """The version of an installed addon: the running one if it is loaded, else what the install record says."""
    if name in self.loaded: return str(getattr(self.loaded[name][0], "version", "0"))
    return str(read_installed().get(name, {}).get("version", "0"))


def updates_available(installed, catalog):
    """installed: {name: version}.  -> [(name, old, new, entry)] for catalog entries newer than what is installed."""
    out = []
    for e in catalog:
        old = installed.get(e.get("name"))
        if old is not None and vkey(e.get("version", "0")) > vkey(old): out.append((e["name"], old, e["version"], e))
    return out


DEFAULT_ADDONS = ("node_tools",)       # installed and switched on in a brand-new setup (from the packages/ folder that ships with mcIRC)


def _install_defaults(self, packages_dir=None):
    """First start of a new setup: install the default addons from the local packages/ folder and switch them on.  -> names installed.
    Never touches an existing setup (the caller only runs this when there was no settings file yet)."""
    packages_dir = packages_dir or os.path.join(BASE_DIR, "packages")
    done = []
    for name in DEFAULT_ADDONS:
        manifest = os.path.join(packages_dir, name, "addon.json")
        if not os.path.exists(manifest) or name in self.discover(): continue
        try:
            install_package(manifest)
            self.app.settings.setdefault("addons_enabled", {})[name] = True
            done.append(name)
        except Exception as e:
            self.errors[name] = f"could not install the default addon: {e}"
    return done


AddonManager.install_defaults = _install_defaults
AddonManager.installed_version = _installed_version
AddonManager.install = _install
AddonManager.uninstall = _uninstall
AddonManager.update_installed = _update_installed


# ===================================================================================================================
# Catalog of tested addons (addons-catalog.json in the GitHub repo).  Only addons that have been reviewed and tested
# by a maintainer are listed; the GUI's "Browse addons..." shows them and installs a chosen one with a click.
# ===================================================================================================================
import posixpath, re, urllib.request

REPO = "bclml/mcIRC"
BRANCH = "master"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "mcIRC"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()


def fetch_catalog(raw=RAW, get=_http_get):
    """-> list of catalog entries: {name, title, version, author, description, path, tested}."""
    data = json.loads(get(raw + "addons-catalog.json").decode("utf-8"))
    return data.get("addons", [])


OUTSIDE_REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")      # GitHub owner/repo; never "..", "/" or "%"
COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def source_raw(entry, raw=RAW):
    """Where a catalog entry's files come from: this project, or - an addon kept in someone else's GitHub repo ('repo') - that repo at
    exactly the commit the maintainers reviewed ('ref').  A pinned commit can't change afterwards, so nobody gets unreviewed code."""
    repo = entry.get("repo")
    if not repo: return raw
    if not OUTSIDE_REPO_RE.fullmatch(repo) or not COMMIT_RE.fullmatch(str(entry.get("ref", ""))):
        raise ValueError(f"'{entry.get('name')}' must name its GitHub repo and the reviewed commit (40 hex characters)")
    return f"https://raw.githubusercontent.com/{repo}/{entry['ref']}/"


def install_from_catalog(entry, raw=RAW, get=_http_get):
    """Downloads one catalog entry's package - from this project or its own reviewed repo - and installs it (same checks as a local install)."""
    raw = source_raw(entry, raw)
    base = (entry.get("path") or "").strip("/")
    prefix = base + "/" if base else ""
    manifest = json.loads(get(f"{raw}{prefix}addon.json").decode("utf-8"))
    if entry.get("repo"):                                     # an outside repo must deliver exactly the reviewed addon
        if manifest.get("name") != entry.get("name"): raise ValueError(f"the repo's addon is '{manifest.get('name')}', not '{entry.get('name')}'")
        if str(manifest.get("version")) != str(entry.get("version")): raise ValueError(
            f"the reviewed commit has version {manifest.get('version')}, the catalog says {entry.get('version')}")
    files = {}
    for src, dest in manifest["files"].items():
        repo_path = posixpath.normpath(posixpath.join(base, src)) if base else posixpath.normpath(src)
        if repo_path.startswith("..") or repo_path.startswith("/"): raise ValueError(f"unsafe path in package: {src}")
        files[dest] = get(raw + repo_path)
    return install_files(manifest, files, raw + base)
