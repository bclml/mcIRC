"""More than one node at once (Options > More nodes): for example one radio on 909 MHz and one on 915 MHz, both in one chat window.

The first node (Options > Connect) works exactly as before.  Every extra node has its own connection (USB, Wi-Fi or Bluetooth), its own radio
lock and health, its own channel list and its own polling thread; its windows carry its label: 'Status [915]', 'Public [915]', '#weather [915]',
grouped under the node in the window tree.  Private chats stay on the top bar whatever node they come from: each private window remembers which
node the person is on, and replies go back through that node.  Addons only see the nodes ticked in their settings (default: the main node)."""
import logging
import os
import threading
import time

import gui_nodestatus
import meshcore_io as io

POLL_SECONDS = 15
CONTACTS_EVERY = 10 * 60


def conn_args(cfg):
    """meshcli connection arguments for an extra node's settings."""
    mode = cfg.get("mode", "usb")
    if mode == "usb": return ["-s", cfg.get("port", "")] + (["-b", str(cfg["baud"])] if cfg.get("baud") else [])
    if mode == "ble": return ["-a", cfg.get("ble", "")]
    return ["-t", cfg.get("host", "")] + (["-p", str(cfg["tcp_port"])] if cfg.get("tcp_port") else [])


def tag(name, label): return f"{name} [{label}]"


def split_tag(name):
    """'Public [915]' -> ('Public', '915');  'Public' -> ('Public', None)."""
    if name.endswith("]") and " [" in name:
        base, _, label = name[:-1].rpartition(" [")
        return base, label
    return name, None


def channel_display(name, idx):
    return "Public" if idx == 0 else "#" + name.lstrip("#")


class ExtraNode:
    """One more radio: connection, lock, health, channels, and a thread that polls it for messages."""
    def __init__(self, app, cfg):
        self.app, self.cfg, self.label = app, dict(cfg), cfg["label"]
        self.lock, self.health = io._MeshLock(), io.RadioHealth()
        self.channels, self.info, self.connected = {}, {}, False
        self.stop_evt, self.thread = threading.Event(), None

    @property
    def args(self): return conn_args(self.cfg)
    def run_cmd(self, *args, timeout=40, retries=1):
        return io.execute_mesh_command(self.args + [str(a) for a in args], timeout=timeout, retries=retries, lock=self.lock, health=self.health)

    def say(self, text, tag_="info"): self.app.q.put(("call", lambda: self.app.node_status(self.label, text, tag_)))

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_evt.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"node-{self.label}")
        self.thread.start()

    def stop(self): self.stop_evt.set()

    def state(self, state):
        self.app.q.put(("call", lambda: self.app.set_node_state(self.label, state)))

    def _run(self):
        self.state("connecting")
        self.say(f"*** Connecting to node '{self.label}' ({' '.join(self.args)})...")
        while not self.stop_evt.is_set():                       # until it answers
            try:
                self.channels = io.channel_map(self.args, lock=self.lock, health=self.health)
                out = self.run_cmd(".infos")
                self.info = next((d for d in io.json_docs(out.stdout) if isinstance(d, dict)), {})
                break
            except io.Cancelled:
                return
            except Exception as e:
                self.say(f"*** Node '{self.label}' is not answering yet: {io.explain_failure(str(e))}. Still trying.", "warn")
                self.stop_evt.wait(15)
        if self.stop_evt.is_set(): return
        self.connected = True
        self.state("connected")
        freq = self.info.get("radio_freq")
        self.app.q.put(("call", lambda: self.app.node_connected(self.label)))
        self.say(f"*** Connected to node '{self.label}': {self.info.get('name', '?')}" + (f", {freq} MHz" if freq else "")
                 + f". Channels: {', '.join(channel_display(n, i) for n, i in sorted(self.channels.items(), key=lambda x: x[1]))}")
        last_contacts, last_battery, was_down = 0.0, 0.0, False
        try:
            while not self.stop_evt.is_set():
                try:
                    res = self.run_cmd(".sync_msgs", retries=1)
                    for kind, idx, text, nick, extra in io.parse_messages(f"{res.stdout}\n{res.stderr}"):
                        self.app.q.put(("xchat", self.label, kind, idx, text, nick, extra))
                    if was_down:
                        self.say(f"*** Node '{self.label}' answers again.")
                        self.state("connected")
                    was_down = False
                    if time.time() - last_battery > gui_nodestatus.BATTERY_EVERY:
                        last_battery = time.time()
                        mv = gui_nodestatus.battery_mv(self.args, lock=self.lock, health=self.health)
                        self.app.q.put(("battery", self.label, mv))
                    if time.time() - last_contacts > CONTACTS_EVERY:
                        last_contacts = time.time()
                        self.read_contacts()
                except io.Cancelled:
                    break
                except Exception as e:
                    if self.health.is_down and not was_down:
                        was_down = True
                        self.say(f"*** Node '{self.label}' is not answering: {io.explain_failure(str(e))}", "error")
                        self.state("down")
                self.stop_evt.wait(POLL_SECONDS)
        finally:
            self.connected = False
            self.state("stopped")
            self.app.q.put(("call", lambda: self.app.node_status(self.label, f"*** Disconnected from node '{self.label}'.", "info")))

    def read_contacts(self):
        """Its contacts go into mcIRC's node memory too, so private windows get names (touch_contact: the main node's list is left alone)."""
        out = self.run_cmd(".contacts", timeout=60)
        data = next((d for d in io.json_docs(out.stdout) if isinstance(d, dict)), {})
        for c in data.values():
            if isinstance(c, dict) and c.get("public_key"): self.app.nodes.touch_contact(c, via=self.label)

    def send_channel(self, idx, text):
        self.run_cmd(*(["public", text] if idx == 0 else ["chan", idx, text]))

    def send_dm(self, key, text):
        res = self.run_cmd("msg", key, text)
        out = f"{res.stdout}\n{res.stderr}"
        bad = [l.strip() for l in out.splitlines() if "unknown destination" in l.lower() or "err_code_not_found" in l.lower()]
        if bad: raise RuntimeError(bad[-1])


class MultiNodeMixin:
    """The App's side: start / stop the extra nodes with Connect / Disconnect, their windows, and routing what you type to the right node."""

    def extra_node_configs(self):
        return [c for c in self.settings.get("extra_nodes", []) if c.get("label") and c.get("enabled", True)]

    def start_extra_nodes(self):
        on = {c["label"] for c in self.extra_node_configs()}
        for label in [k for k in getattr(self, "_node_stat", {}) if k != "main" and k not in on]: self.drop_node_status(label)
        for cfg in self.extra_node_configs():
            n = self.extra_nodes.get(cfg["label"])
            if n is None or n.cfg != cfg: n = self.extra_nodes[cfg["label"]] = ExtraNode(self, cfg)
            self.node_window(cfg["label"])
            n.start()

    def stop_extra_nodes(self):
        for n in self.extra_nodes.values(): n.stop()

    # ---- choosing a node for settings and tools ----
    def node_choices(self):
        """[(key, text)] for 'which node' lists: the main node ('main') first, then every extra node (key = its label)."""
        out = [("main", f"Main node ({self.settings.get('node_name') or 'USB'})")]
        for c in self.settings.get("extra_nodes", []):
            n = self.extra_nodes.get(c.get("label"))
            name = (n.info.get("name") if n else None) or ""
            out.append((c["label"], f"{c['label']}{' (' + name + ')' if name else ''}"))
        return out

    def node_describe(self, key):
        """'main - 909 MHz, USB' / '915 - 915 MHz, Wi-Fi' for lists like the map's Heard by."""
        if key in (None, "", "main"):
            s, freq = self.settings, getattr(self, "main_freq", None)
            how = {"usb": "USB", "tcp": "Wi-Fi", "bluetooth": "Bluetooth"}.get(s.get("mode"), "")
        else:
            c = next((c for c in self.settings.get("extra_nodes", []) if c.get("label") == key), {})
            n = self.extra_nodes.get(key)
            freq = n.info.get("radio_freq") if n else None
            how = {"usb": "USB", "tcp": "Wi-Fi", "ble": "Bluetooth"}.get(c.get("mode"), "")
        bits = [f"{float(freq):g} MHz" if freq else "", how]
        return f"{key or 'main'} - " + ", ".join(b for b in bits if b) if any(bits) else (key or "main")

    def node_ready(self, key):
        if key in (None, "", "main"): return bool(self.connected)
        n = self.extra_nodes.get(key)
        return bool(n and n.connected)

    def node_target(self, key):
        """`with app.node_target(key):` - the node's settings / tools commands on this thread go to that node (gui_nodecfg, the MeshCore tools)."""
        n = None if key in (None, "", "main") else self.extra_nodes.get(key)
        if n is not None: return io.on_node(n.args, n.lock, n.health)
        cfg = next((c for c in self.settings.get("extra_nodes", []) if c.get("label") == key), None)
        return io.on_node(conn_args(cfg)) if cfg else io.on_node(None)

    # ---- windows ----
    def node_parent(self, label):
        iid = f"node:{label}"
        if hasattr(self, "tree") and not self.tree.exists(iid):
            self.tree.insert("", "end", iid=iid, text=f"Node {label}", open=True)
        return iid

    def remove_node(self, label, ask=True):
        """Right-click on 'Node <label>' > Remove: disconnects it, takes it out of Options > More nodes and closes its windows.
        Their log files stay in the logs folder, renamed '... removed <date>.old.txt' so they don't come back at the next start."""
        from tkinter import messagebox
        configured = any(c.get("label") == label for c in self.settings.get("extra_nodes", []))
        if ask and not messagebox.askyesno("Remove node", f"Remove node '{label}'?\n\n"
                                           + ("It is disconnected and taken out of Options > More nodes. " if configured else "")
                                           + "Its windows are closed (their history stays in the logs folder).", parent=self.root): return
        n = self.extra_nodes.pop(label, None)
        if n: n.stop()
        self.drop_node_status(label)
        self.settings["extra_nodes"] = [c for c in self.settings.get("extra_nodes", []) if c.get("label") != label]
        for name in [nm for nm in self.windows if split_tag(nm)[1] == label and not nm.startswith("@")]:
            w = self.windows.pop(name)
            if w.log:
                w.log.stamp("Session Close")
                try: os.replace(w.log.path, w.log.path[:-4] + time.strftime(" removed %Y-%m-%d %H%M.old.txt"))
                except OSError: pass
            w.frame.destroy()
            if self.tree.exists(name): self.tree.delete(name)
            if w is self.current: self.select_window("Status")
        if self.tree.exists(f"node:{label}"): self.tree.delete(f"node:{label}")
        self.save()

    def node_window(self, label):
        """The node's own Status window ('Status [915]')."""
        return self.add_window(tag("Status", label), f"Status of node '{label}'")

    def node_status(self, label, text, tag_="info"):
        w = self.node_window(label)
        w.write(self.stamp() + [(text, tag_)])
        self.mark_unread(w, "event")

    def node_connected(self, label):
        n = self.extra_nodes.get(label)
        if not n: return
        for name, idx in sorted(n.channels.items(), key=lambda x: x[1]):
            disp = channel_display(name, idx)
            w = self.add_window(tag(disp, label), f"{disp} on node '{label}'")
            w.node = label

    def _h_xchat(self, label, kind, idx, text, nick, extra):
        n = self.extra_nodes.get(label)
        if n is None: return
        if kind == "dm": return self._dm_in(text, extra.get("pubkey") or nick, extra, via=label)
        name = next((nm for nm, i in n.channels.items() if i == idx), f"Channel {idx}")
        win = tag(channel_display(name, idx), label)
        w = self.windows.get(win) or self.add_window(win, f"{channel_display(name, idx)} on node '{label}'")
        w.node = label
        bits = []
        if extra.get("snr") is not None: bits.append(f"SNR {extra['snr']}")
        hops = extra.get("hops")
        if hops is not None: bits.append("direct" if hops in (0, 255) else f"{hops} hops")
        self.chat_line(w, nick, text, "text", f"({', '.join(bits)})" if bits else "")
        self.addons.dispatch("on_message", {"channel": win, "channel_idx": idx, "nick": nick, "text": text, "node": label,
                                             "snr": extra.get("snr"), "hops": hops, "raw": extra.get("raw")})

    # ---- sending ----
    def send_extra_channel(self, window_name, text):
        """True when this window belongs to an extra node (the message went - or was refused - there)."""
        base, label = split_tag(window_name)
        if not label or label not in self.extra_nodes: return False
        n, w = self.extra_nodes[label], self.windows.get(window_name)
        idx = 0 if base == "Public" else next((i for nm, i in n.channels.items() if channel_display(nm, i) == base), None)
        if idx is None or not n.connected:
            self.status_line(f"*** Can't send to {window_name}: node '{label}' is not connected / has no such channel.", "error")
            return True
        if w: self.chat_line(w, n.info.get("name") or self.settings["node_name"], text, "self")
        self.bg(lambda: n.send_channel(idx, text), lambda r: isinstance(r, Exception) and self.unsent(w, text, io.explain_failure(str(r))))
        return True

    def send_extra_dm(self, w, key, text):
        n = self.extra_nodes.get(getattr(w, "node", None) or "")
        if n is None or not n.connected:
            self.status_line(f"*** Can't message {w.name[1:]}: node '{w.node}' is not connected.", "error")
            return
        self.chat_line(w, n.info.get("name") or self.settings["node_name"], text, "self")
        self.bg(lambda: n.send_dm(key, text), lambda r: isinstance(r, Exception) and self.unsent(w, text, io.explain_failure(str(r))))
