"""Joining and leaving channels on the node, the IRC way: /join #name adds the channel to the node when it isn't there yet (a hashtag
channel: its key comes from its name, so everyone who joins #name shares it; or a private channel: /join #name <32-hex key>), /part
removes it.  Also from the window tree's right-click menus.  On an extra node's windows ('#test [915]') it works on that node."""
import re
from tkinter import messagebox, simpledialog

import gui_multinode
import meshcore_io as io

NAME_RE = re.compile(r"#?[A-Za-z0-9][A-Za-z0-9_-]{0,29}")
KEY_RE = re.compile(r"[0-9a-fA-F]{32}")


def norm(name): return (name or "").lstrip("#").strip().lower()


def read_slots(conn_args):
    """[(slot, name)] of every slot of the node (empty ones have name '')."""
    res = io.execute_mesh_command(list(conn_args) + [".get_channels"], timeout=40)
    docs = io.json_docs(f"{res.stdout}\n{res.stderr}")
    rows = next((d for d in docs if isinstance(d, list)), [d for d in docs if isinstance(d, dict)])
    return [(c.get("channel_idx"), c.get("channel_name", "")) for c in rows if isinstance(c, dict) and c.get("channel_idx") is not None]


def parse_join(arg):
    """'#test' / 'test' / '#club 0011..ff' -> (display name '#test', name for the node, key or None); ValueError with a hint."""
    parts = (arg or "").split()
    if not parts: raise ValueError("Type it like this: /join #name  (or /join #name <32-character key> for a private channel)")
    name, key = parts[0], parts[1] if len(parts) > 1 else None
    if norm(name) == "public": return "Public", None, None
    if not NAME_RE.fullmatch(name): raise ValueError("Channel names: letters, digits, - or _ (up to 30), e.g. /join #test")
    if key is not None and not KEY_RE.fullmatch(key): raise ValueError("A private channel's key is 32 characters, 0-9 and a-f")
    base = norm(name)
    return "#" + base, ("#" + base if key is None else base), (key.lower() if key else None)


class ChannelsMixin:
    """The App's side."""

    def _node_of(self, window):
        w = self.windows.get(window) if isinstance(window, str) else window
        return getattr(w, "node", None) if w is not None and not getattr(w, "name", "").startswith("@") else None

    def _channels_on(self, node):
        """{name: slot} the node is known to have."""
        if node: return dict(getattr(self.extra_nodes.get(node), "channels", {}) or {})
        return dict(io.CHANNEL_INDEX_BY_NAME)

    def _refresh_channels(self, node):
        """Re-reads the node's channels (runs in the background)."""
        if node:
            n = self.extra_nodes.get(node)
            if n is not None: n.channels = io.channel_map(n.args, lock=n.lock, health=n.health)
        else:
            io.CHANNEL_INDEX_BY_NAME.clear()
            io.resolve_channel_indices()

    def join_channel(self, arg, node=None):
        try: disp, on_node, key = parse_join(arg)
        except ValueError as e: return self.status_line(f"*** {e}", "error")
        window = gui_multinode.tag(disp, node) if node else disp
        if disp == "Public" or norm(disp) in {norm(n) for n in self._channels_on(node)}:
            if window in self.windows: return self.select_window(window)
        if not self.node_ready(node or "main"):
            return self.status_line("*** Connect first - the channel is added to the node." if not node else f"*** Node '{node}' is not connected.", "error")
        def work():
            with self.node_target(node or "main"):
                slots = read_slots(io.node_args())
                have = next((s for s, n in slots if n and norm(n) == norm(on_node)), None)
                if have is not None: return ("there", have)
                free = next((s for s, n in slots if s and not n), None)
                if free is None: raise RuntimeError("the node has no free channel slot - leave one first (/part)")
                io.execute_mesh_command(io.node_args() + ["set_channel", str(free), on_node] + ([key] if key else []), timeout=40)
            self._refresh_channels(node)
            return ("added", free)
        def done(r):
            if isinstance(r, Exception): return self.status_line(f"*** Couldn't join {disp}: {io.explain_failure(str(r))}", "error")
            closed = self.settings.setdefault("closed_channels", [])
            if window in closed: closed.remove(window)
            if node: self.node_connected(node)
            else: self._h_channels()
            what, slot = r
            self.status_line(f"*** Joined {disp}" + (f" - added to {'node ' + repr(node) if node else 'your node'} in slot {slot}"
                             + ("" if key else " (a hashtag channel: everyone who joins it shares it)") if what == "added" else "") + ".", "info")
            if window not in self.windows: self.add_window(window, f"{disp} on node '{node}'" if node else disp)
            self.select_window(window)
            self.save()
        self.status_line(f"*** Joining {disp}...", "info")
        self.bg(work, done)

    def part_channel(self, window=None, ask=True):
        """Removes a channel window's channel from its node, then closes the window."""
        window = window or (self.current.name if self.current is not None else "")
        base, node = gui_multinode.split_tag(window)
        if not base.startswith("#"):
            return self.status_line("*** /part works in a channel window (Public can't be removed from the node)." if base != "Public"
                                    else "*** Public can't be removed from the node.", "error")
        slot = next((i for n, i in self._channels_on(node).items() if norm(n) == norm(base)), None)
        if slot is None:
            self.close_window(window)
            return self.status_line(f"*** {base} isn't on {'node ' + repr(node) if node else 'your node'} - closed its window.", "info")
        if ask and not messagebox.askyesno("Leave channel", f"Remove {base} from {'node ' + repr(node) if node else 'your node'}?\n\n"
                                           "A hashtag channel can be joined again any time with /join. A private channel's key is gone "
                                           "unless you saved it (MeshCore tools > Channels > Copy key).", parent=self.root): return
        def work():
            with self.node_target(node or "main"):
                io.execute_mesh_command(io.node_args() + ["remove_channel", str(slot)], timeout=40)
            self._refresh_channels(node)
        def done(r):
            if isinstance(r, Exception): return self.status_line(f"*** Couldn't leave {base}: {io.explain_failure(str(r))}", "error")
            if window in self.windows: self.close_window(window)
            self.status_line(f"*** Left {base} - removed from {'node ' + repr(node) if node else 'your node'}.", "info")
        self.bg(work, done)

    def ask_join(self, node=None):
        arg = simpledialog.askstring("Join channel", "Channel to join, e.g. #test\n(for a private channel: #name and its 32-character key)", parent=self.root)
        if arg: self.join_channel(arg, node)
