"""The name list beside a channel: the names stay after a restart, and favorites come first ('+name', right after your own '@name').

A favorite is also starred on the node itself (MeshCore's contact flag bit 0, the star in the phone apps), and a star set on the
node (from the phone) makes the name a favorite in mcIRC too."""
import logging

import meshcore_io as ea
import gui_nodes

MAX_NAMES = 300                 # remembered names per window
FAV_FLAG = 0x01                 # MeshCore contact flags: bit 0 = favorite (meshcli change_flags; the phone apps' star)


def order(nicks, me, favorites):
    """The rows of the name list: (shown text, name).  '@me' first, then '+favorites', then everyone else - each part A-Z."""
    others = sorted(set(nicks) - {me}, key=str.lower)
    fav = {f.lower() for f in favorites}
    return ([("@" + me, me)] + [("+" + n, n) for n in others if n.lower() in fav]
            + [(n, n) for n in others if n.lower() not in fav])


def star_on_node(public_key, on):
    """Sets or clears the star (favorite flag) of one contact on the main node, keeping its other flags.  -> True when done."""
    contacts = gui_nodes.fetch_radio_contacts()
    c = next((c for k, c in contacts.items() if c.get("public_key", k) == public_key), None)
    if c is None: return False
    flags = int(c.get("flags") or 0)
    new = flags | FAV_FLAG if on else flags & ~FAV_FLAG
    if new != flags:
        with ea.MESH_LOCK: ea.execute_mesh_command(ea.CONNECTION_ARGS + ["change_flags", public_key, str(new)], timeout=60, retries=1)
    return True


class NickListMixin:
    """For the App: the name list, remembered names and favorites."""

    # ---- remembered names ----
    def restore_nicks(self, w):
        w.nicks |= set(self.settings.get("window_nicks", {}).get(w.name, []))

    def remember_nick(self, w, nick):
        if not nick or nick in w.nicks: return
        w.nicks.add(nick)
        saved = self.settings.setdefault("window_nicks", {})
        names = [n for n in saved.get(w.name, []) if n != nick] + [nick]
        saved[w.name] = names[-MAX_NAMES:]
        self.save()

    def forget_window_nicks(self, name):
        if self.settings.get("window_nicks", {}).pop(name, None) is not None: self.save()

    # ---- the list ----
    def refresh_nicks(self):
        self.nicklist.delete(0, "end")
        self.nick_rows = []
        if self.current is self.status or self.current is None: return
        self.nick_rows = order(self.current.nicks, self.settings["node_name"], self.favorites())
        for shown, _ in self.nick_rows: self.nicklist.insert("end", shown)

    def nick_at(self, index):
        rows = getattr(self, "nick_rows", [])
        return rows[index][1] if 0 <= index < len(rows) else self.nicklist.get(index).lstrip("@+")

    # ---- favorites ----
    def favorites(self): return list(self.settings.get("favorites", []))

    def is_favorite(self, nick): return nick.lower() in {f.lower() for f in self.favorites()}

    def set_favorite(self, nick, on, on_node=True):
        favs = [f for f in self.favorites() if f.lower() != nick.lower()] + ([nick] if on else [])
        self.settings["favorites"] = favs
        self.save()
        self.refresh_nicks()
        if not on_node: return
        node = self.nodes.find_by_name(nick)
        if node is None or not self.connected:
            return self.status_line(f"*** {nick} is {'a favorite' if on else 'no longer a favorite'} in mcIRC"
                                    + ("" if node else " (not a contact on your node, so nothing to star there)")
                                    + ("" if self.connected or not node else " - the node gets the star when it is connected and you set it again") + ".")
        key = node["public_key"]

        def work(): return star_on_node(key, on)

        def done(r):
            if isinstance(r, Exception): return self.status_line(f"*** Couldn't {'star' if on else 'unstar'} {nick} on the node: {r}", "warn")
            if not r: return self.status_line(f"*** {nick} is {'a favorite' if on else 'no longer a favorite'} in mcIRC (not on your node's contact list).")
            starred = set(self.settings.get("favorites_node", []))
            self.settings["favorites_node"] = sorted(starred | {nick} if on else starred - {nick})
            self.save()
            self.status_line(f"*** {nick} is {'a favorite - starred' if on else 'no longer a favorite - unstarred'} on the node too.")
        self.bg(work, done)

    def toggle_favorite(self, nick): self.set_favorite(nick, not self.is_favorite(nick))

    def favorites_from_node(self, starred):
        """After reading the node's contacts: stars added or removed on the node (e.g. from the phone) follow into mcIRC."""
        if starred is None: return
        before = set(self.settings.get("favorites_node", []))
        added, removed = starred - before, before - starred
        if not added and not removed: return
        favs = [f for f in self.favorites() if f not in removed]
        favs += [n for n in sorted(added) if n.lower() not in {f.lower() for f in favs}]
        self.settings["favorites"], self.settings["favorites_node"] = favs, sorted(starred)
        self.save()
        self.refresh_nicks()
        logging.info(f"Favorites from the node: +{len(added)} -{len(removed)}")
