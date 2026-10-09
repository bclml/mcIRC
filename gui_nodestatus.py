"""The status bar's node part: one status per node (the main one, then each node from Options > More nodes), each with its battery, and
warnings when "connected" is not the whole story - a low battery (the radio may not transmit), or messages no repeater passes on.

A node can answer mcIRC perfectly (USB, Wi-Fi) while its radio no longer gets anything out - a flat battery does exactly that - so the
battery is read every few minutes and the repeats of our own messages are watched."""
import tkinter as tk

import meshcore_io as io

BATTERY_EVERY = 5 * 60          # seconds between battery reads per node
LOW_MV = 3500                   # below this a LiPo-powered node may stop transmitting (it still answers USB / Wi-Fi)
OK_MV = 3600                    # ... and back to normal above this (no flapping around one value)
UNHEARD_WARN = 3                # this many messages in a row nobody repeated (after repeats were heard before): warn
STATE_TEXT = {"connecting": "connecting...", "connected": "connected", "down": "NOT RESPONDING", "stopped": "not connected"}


def describe_connection(args):
    """'-t 192.168.1.57 -p 5000' -> 'Wi-Fi 192.168.1.57'; '-s COM4' -> 'USB COM4'; '-a ...' -> 'Bluetooth'."""
    a = list(args or [])
    if a[:1] == ["-t"] and len(a) > 1: return f"Wi-Fi {a[1]}"
    if a[:1] == ["-s"] and len(a) > 1: return f"USB {a[1]}"
    if a[:1] in (["-a"], ["-d"]): return "Bluetooth"
    return " ".join(a)


def battery_mv(conn_args, lock=None, health=None):
    """The node's battery in millivolts, or None when it doesn't report one (no battery, or an answer without it)."""
    res = io.execute_mesh_command(list(conn_args) + [".get", "stats_core"], timeout=30, retries=0, lock=lock, health=health)
    for d in io.json_docs(f"{res.stdout}\n{res.stderr}"):
        if isinstance(d, dict) and d.get("battery_mv"):
            try: return int(d["battery_mv"])
            except (TypeError, ValueError): return None
    return None


class NodeStatusMixin:
    """The App's side.  The status bar has self.sb_state (main node) and self.sb_nodes (a frame for the other nodes)."""

    def _ns(self):
        if not hasattr(self, "_node_stat"):
            self._node_stat = {"main": {"state": "stopped", "detail": "", "mv": None, "low": False}}
            self._node_labels, self._unheard, self._heard_any = {}, 0, False
        return self._node_stat

    def _status_text(self, key):
        s = self._ns()[key]
        text = {"connecting": "Connecting...", "connected": f"Connected ({s['detail']})" if s["detail"] else "Connected",
                "down": "NOT RESPONDING", "stopped": "Not connected"}.get(s["state"], s["state"]) if key == "main" \
            else f"{key}: {STATE_TEXT.get(s['state'], s['state'])}"
        if s["mv"] and s["state"] in ("connected", "down"): text += f" · {s['mv'] / 1000:.2f} V" + (" LOW" if s["low"] else "")
        if key == "main" and self._unheard >= UNHEARD_WARN and s["state"] == "connected": text += " · not heard"
        return text

    def _status_bad(self, key):
        s = self._ns()[key]
        return s["state"] == "down" or s["low"] or (key == "main" and self._unheard >= UNHEARD_WARN and s["state"] == "connected")

    def show_node_status(self, key="main"):
        """Redraws one node's part of the status bar."""
        if not hasattr(self, "sb_state"): return
        text, colour = self._status_text(key), ("#c00000" if self._status_bad(key) else "#000000")
        if key == "main":
            self.sb_state.config(text=text, fg=colour)
            return
        lab = self._node_labels.get(key)
        if lab is None or not lab.winfo_exists():
            lab = self._node_labels[key] = tk.Label(self.sb_nodes, bg=self.sb_state["bg"], relief="sunken", anchor="w", padx=4)
            lab.pack(side="left", padx=(2, 0))
        lab.config(text=text, fg=colour)

    def set_node_state(self, key, state, detail=None):
        s = self._ns().setdefault(key, {"state": "stopped", "detail": "", "mv": None, "low": False})
        s["state"] = state
        if detail is not None: s["detail"] = detail
        if state == "stopped": s["mv"], s["low"] = None, False
        if key == "main" and state != "connected": self._unheard = 0
        self.show_node_status(key)

    def drop_node_status(self, key):
        """A node taken out of More nodes: its part of the status bar goes."""
        self._ns().pop(key, None)
        lab = self._node_labels.pop(key, None)
        if lab is not None:
            try: lab.destroy()
            except tk.TclError: pass

    def _h_battery(self, key, mv):
        s = self._ns().get(key)
        if s is None or not mv: return
        s["mv"] = mv
        name = "Your node" if key == "main" else f"Node '{key}'"
        if not s["low"] and mv < LOW_MV:
            s["low"] = True
            self.status_line(f"*** {name}'s battery is low ({mv / 1000:.2f} V): it may still answer here but stop getting messages out "
                             "on the air. Charge it or plug it in.", "error")
        elif s["low"] and mv > OK_MV:
            s["low"] = False
            self.status_line(f"*** {name}'s battery is fine again ({mv / 1000:.2f} V).", "info")
        self.show_node_status(key)

    def note_repeats(self, result):
        """After a watched send (gui_echo): count the messages in a row nobody repeated.  Only once repeats were heard this session -
        where no repeater is in range, silence is normal."""
        self._ns()
        if not result or not result.get("sent"): return
        if result.get("repeats"):
            if self._unheard >= UNHEARD_WARN: self.status_line("*** Repeaters pass your messages on again.", "info")
            self._heard_any, self._unheard = True, 0
        elif self._heard_any:
            self._unheard += 1
            if self._unheard == UNHEARD_WARN:
                self.status_line(f"*** Your last {UNHEARD_WARN} messages were not repeated by anyone, though repeaters heard you earlier. "
                                 "The node answers, but its radio may not be getting out - check its battery and antenna.", "error")
        self.show_node_status("main")
