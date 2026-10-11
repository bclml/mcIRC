"""Instant node updates from adverts.

meshcli runs one short process per command, and the node only tells a connected program about adverts while that program is connected.  So in
the idle time between message polls this module keeps a small listener process (gui_advert_proc.py) connected and reads its events as they
arrive: a node that advertises shows up in the node list / map and a key-only private window gets its real name within about a second.

The listener holds the radio only while nothing else needs it: as soon as any other part of mcIRC wants the port (sending a message, a
repeater command, the next poll) the listener is stopped, and anything it missed is caught up from the radio's contact list the next time it
starts.  Messages mcIRC sends while it listens go through the listener's own connection (send_through) instead of stopping it.  Works
over USB, WiFi/TCP and Bluetooth; on Bluetooth (each new connection takes seconds) one listening stretch lasts 10 minutes."""
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import types

import gui_diag
import meshcore_io as io

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_advert_proc.py")
MAX_FAILURES = 3
LISTEN_SECONDS = 60          # one listening stretch when messages come in through it too
BLE_LISTEN_SECONDS = 600     # ... over Bluetooth: each new connection costs seconds, and sends go through the listener anyway
SEND_TIMEOUT = 20            # seconds to wait for the listener to say a send went out


def helper_args(conn):
    """meshcli-style connection arguments -> listener arguments, or None when listening isn't possible (nothing set)."""
    if not conn: return None
    a = list(conn)
    try:
        if a[0] == "-s":
            out = ["--serial", a[1]]
            if "-b" in a: out += ["--baud", a[a.index("-b") + 1]]
            return out
        if a[0] == "-t":
            return ["--tcp", a[1]] + (["--port", a[a.index("-p") + 1]] if "-p" in a else [])
        if a[0] == "-a" and a[1].strip():
            return ["--ble", a[1].strip()]
    except (IndexError, ValueError):
        return None
    return None


class AdvertWatcher:
    def __init__(self, app):
        self.app, self.proc, self.failures, self.disabled = app, None, 0, False
        self.ready, self.pending, self.next_id, self.send_lock = False, {}, 0, threading.Lock()      # sends through the listener
        self.ready_evt = threading.Event()                 # set while the listener is connected (Bluetooth: commands wait for it a moment)
        self.conn_thread = None                            # the connection thread (it starts the listener: it never waits for it)
        self.yield_evt = threading.Event()                # "someone needs the radio": sticky, so a request that arrives while the listener is still starting isn't lost
        io.MESH_LOCK.on_contend = self.interrupt          # anyone who needs the radio makes the listener let go of it

    def interrupt(self, force=False):
        """Someone needs the radio: let go of it.  With sends already handed to the listener (they may be on the air), the listening loop
        lets them finish first (at most 5 s) and then stops it - unless force."""
        self.yield_evt.set()
        p = self.proc
        if p is not None and p.poll() is None:
            if not force:
                with self.send_lock:
                    if self.pending: return
            try: p.kill()
            except OSError: pass

    def enabled(self):
        return (bool(self.app.settings.get("advert_listen", True)) and not self.disabled and not io.HEALTH.is_down
                and helper_args(io.CONNECTION_ARGS) is not None)

    def listen(self, seconds, stop_evt, duty=None):
        """Use `seconds` of idle time listening (or just waiting when listening is off / unavailable).  Runs on the connection thread.
        duty(): called every few seconds while connected - the connection's routine jobs, done through the listener (Bluetooth)."""
        if not self.enabled():
            stop_evt.wait(seconds)
            return
        if not io.MESH_LOCK.acquire(False):                # the radio is busy right now
            stop_evt.wait(1)
            return
        self.yield_evt.clear()
        self.conn_thread = threading.current_thread()
        started = time.time()
        try:
            cmd = [sys.executable, HELPER] + helper_args(io.CONNECTION_ARGS) + ["--lastmod", str(self.app.nodes.max_lastmod()), "--seconds", str(int(seconds))]
            if getattr(self.app, "raw_packets_wanted", None): cmd.append("--raw")     # an addon wants every packet whole (api.want_raw_packets)
            cmd.append("--messages")                    # messages arrive through this connection too: no need to break it every poll
            cmd.append("--commands")                    # ... and messages mcIRC sends go out through it (send_through)
            try:
                self.proc = proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                                    creationflags=io.NO_WINDOW, **io.UTF8)
            except OSError as e:
                return self._failed(f"cannot start the advert listener: {e}", started, seconds, stop_evt)
            if self.yield_evt.is_set(): self.interrupt()
            lines = queue.Queue()
            def pump():
                for line in proc.stdout:
                    ev = self._parse(line) if '"event": "sent"' in line or '"event": "cli"' in line else None
                    if ev and ev["event"] in ("sent", "cli"): self._sent(ev)      # answered here: whoever waits may be the connection thread
                    else: lines.put(line)
                lines.put(None)
            threading.Thread(target=pump, daemon=True).start()
            deadline, got_ready, error, last_duty = started + seconds + 15, False, "", 0.0
            while not stop_evt.is_set() and time.time() < deadline and not self.yield_evt.is_set():
                if duty and self.ready and time.time() - last_duty >= 2:
                    last_duty = time.time()
                    try: duty()
                    except io.Cancelled: raise
                    except Exception as e: logging.debug(f"connection job failed: {e}")
                try: line = lines.get(timeout=0.3)
                except queue.Empty: continue
                if line is None: break
                ev = self._parse(line)
                if not ev: continue
                if ev["event"] == "ready":
                    got_ready = self.ready = True
                    self.ready_evt.set()
                elif ev["event"] == "error": error = ev.get("message", "error")
                elif ev["event"] == "sent": self._sent(ev)
                else: self._event(ev)
            interrupted = self.yield_evt.is_set()
            self.ready = False                             # no new sends through it from here on
            self.ready_evt.clear()
            end = time.time() + (5 if interrupted else SEND_TIMEOUT)      # sends already handed to it may be on the air: let them finish
            while time.time() < end and proc.poll() is None:
                with self.send_lock:
                    if not self.pending: break
                time.sleep(0.1)
            self.interrupt(force=True)
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: pass
            while True:                                    # what it printed before it stopped - above all messages the node has let go of
                try: line = lines.get(timeout=0.5)
                except queue.Empty: break
                if line is None: break
                ev = self._parse(line)
                if ev and ev["event"] in ("msg", "rx"): self._event(ev)
                elif ev and ev["event"] == "sent": self._sent(ev)
            self._fail_pending("the listener stopped before the radio answered")
            if error or (not got_ready and not interrupted and not stop_evt.is_set()):
                return self._failed(error or "the advert listener exited without connecting", started, seconds, stop_evt)
            self.failures = 0
            if interrupted or proc.returncode in (-9, 1):    # we were asked to let go: give the other user a moment
                stop_evt.wait(1.0)
        finally:
            self.ready = False
            self.ready_evt.clear()
            self._fail_pending("the listener stopped before the radio answered")
            self.proc = None
            io.MESH_LOCK.release()

    def _failed(self, why, started, seconds, stop_evt):
        self.failures += 1
        ble = (io.CONNECTION_ARGS or [""])[0] == "-a"            # Windows Bluetooth refuses a connection now and then: more patience, short pauses
        limit = MAX_FAILURES * 3 if ble else MAX_FAILURES
        gui_diag.event("adverts", f"listener failed ({self.failures}/{limit}): {why}")
        if self.failures >= limit:
            self.disabled = True
            logging.warning("Instant advert updates switched off for this session (the listener keeps failing); nodes are still read every few minutes.")
        stop_evt.wait(min(15, max(1, seconds - (time.time() - started))) if ble else max(1, seconds - (time.time() - started)))

    @staticmethod
    def _parse(line):
        line = line.strip()
        if not line.startswith("{"): return None
        try: ev = json.loads(line)
        except ValueError: return None
        return ev if isinstance(ev, dict) and "event" in ev else None

    def window(self, poll_seconds):
        """How long one listening stretch lasts: with messages coming in through it, a minute (each new connection costs the node a
        contact re-read and misses what is heard meanwhile) - over Bluetooth 10 minutes; otherwise the poll interval."""
        if not self.enabled(): return poll_seconds
        return max(poll_seconds, BLE_LISTEN_SECONDS if (io.CONNECTION_ARGS or [""])[0] == "-a" else LISTEN_SECONDS)

    # ---- sending through the listener's connection ----
    @staticmethod
    def bluetooth(): return (io.CONNECTION_ARGS or [""])[0] == "-a"

    def run_through(self, rest, timeout=30):
        """Over Bluetooth: any meshcli command run by the listener on its open connection (a new Bluetooth connection takes seconds, and
        would stop the listener).  -> a meshcli-like result, or None (then meshcli runs it as before)."""
        if not rest or rest[0] in ("chan", "public", "msg"): return self.send_through(rest)
        if not self.bluetooth() or rest[0] in ("reboot", "chat") or str(rest[0]).startswith("-"): return None
        if not self._wait_ready(): return None
        proc = self.proc
        if proc is None or proc.poll() is not None or proc.stdin is None: return None
        done, box = threading.Event(), {}
        with self.send_lock:
            self.next_id += 1
            cid = self.next_id
            self.pending[cid] = (done, box)
            try:
                proc.stdin.write(json.dumps({"id": cid, "cmd": "cli", "args": [str(a) for a in rest]}) + "\n")
                proc.stdin.flush()
            except (OSError, ValueError):
                self.pending.pop(cid, None)
                return None
        if not done.wait(max(10, timeout) + 5):
            self.pending.pop(cid, None)
            raise RuntimeError(f"the node did not answer within {max(10, timeout)} s")
        if box.get("error") and "stdout" not in box: raise RuntimeError(box["error"])
        return types.SimpleNamespace(returncode=0, stdout=box.get("stdout", ""), stderr=box.get("stderr", ""))

    def send_through(self, rest):
        """A channel message or private message (meshcli words: ['chan', idx, text], ['public', text], ['msg', key, text]) sent over the
        listener's open connection.  -> a meshcli-like result; None when the listener isn't connected (then meshcli does it as before).
        Never falls back after asking the listener: the message may already be out, and must not go twice."""
        if self.bluetooth(): self._wait_ready()
        proc = self.proc
        if not self.ready or proc is None or proc.poll() is not None or proc.stdin is None: return None
        if rest[:1] == ["public"] and len(rest) == 2: c = {"cmd": "chan", "idx": 0, "text": rest[1]}
        elif rest[:1] == ["chan"] and len(rest) == 3: c = {"cmd": "chan", "idx": int(rest[1]), "text": rest[2]}
        elif rest[:1] == ["msg"] and len(rest) == 3: c = {"cmd": "msg", "to": str(rest[1]), "text": rest[2]}
        else: return None
        done, box = threading.Event(), {}
        with self.send_lock:
            self.next_id += 1
            c["id"] = cid = self.next_id
            self.pending[cid] = (done, box)
            try:
                proc.stdin.write(json.dumps(c) + "\n")
                proc.stdin.flush()
            except (OSError, ValueError):
                self.pending.pop(cid, None)
                return None                                # it never got it: meshcli sends it instead
        if not done.wait(SEND_TIMEOUT):
            self.pending.pop(cid, None)
            raise RuntimeError("the radio did not confirm the message within 20 s")
        if box.get("ok"): return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        err = box.get("error") or "the radio refused the message"
        if "err_code_not_found" in err: return types.SimpleNamespace(returncode=0, stdout=f"Error: {err}", stderr="")    # (the private-message
        raise RuntimeError(err)                                                                                        # window re-adds the contact)

    def _wait_ready(self):
        """Bluetooth: while mcIRC is connected but the listener is (re)connecting, wait for it (up to 40 s) - a command of its own would
        open a second Bluetooth connection (seconds, and it stops the listener).  Not on the connection thread: that one starts it."""
        if self.ready: return True
        if threading.current_thread() is self.conn_thread or not getattr(self.app, "connected", False) or not self.enabled(): return False
        return self.ready_evt.wait(40)

    def _sent(self, ev):
        done, box = self.pending.pop(ev.get("id"), (None, None))
        if done is None: return
        if ev.get("event") == "cli": box.update(stdout=ev.get("stdout", ""), stderr=ev.get("stderr", ""))
        else: box.update(ok=bool(ev.get("ok")), error=ev.get("error", ""))
        done.set()

    def _fail_pending(self, why):
        with self.send_lock:
            items, self.pending = list(self.pending.values()), {}
        for done, box in items:
            box.update(ok=False, error=why)
            done.set()

    def _event(self, ev):
        kind = ev["event"]
        if kind == "msg":                                  # a message the node had waiting (--messages): the same way as from .sync_msgs
            payload = ev.get("payload")
            if isinstance(payload, dict):
                for k, idx, text, nick, extra in io.parse_messages(json.dumps(payload)): io._emit(k, idx, text, nick=nick, **extra)
            return
        if kind == "rx":                                   # a packet heard: kind, route, signal (map signals, packet monitor) - never its content
            self.app.q.put(("call", lambda e=ev: self.app.note_packet(e)))
            return
        gui_diag.count("adverts" if kind == "advert" else "advert_contacts")
        if kind == "advert":
            gui_diag.event("adverts", f"advert heard from {ev.get('public_key', '')}")
            return
        c = ev.get("contact") or {}
        if c.get("public_key"): self.app.q.put(("advert", kind, c))
