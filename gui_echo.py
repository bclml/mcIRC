"""Heard repeats: send a channel message through gui_echo_proc.py, which stays connected for a few seconds and counts the repeaters that
pass the message on (like the "Heard 2 repeats" on a phone).  When none is heard it can send the message once more.

The helper holds the radio only while nobody else needs it: anyone who wants the port stops the watch early (no re-send then).
Bluetooth is not supported (reconnecting is too slow); mcIRC then sends the normal way."""
import json
import subprocess
import sys
import threading
import time

import meshcore_io as io
from gui_adverts import helper_args

HELPER = __file__.replace("gui_echo.py", "gui_echo_proc.py")


def supported(conn_args): return helper_args(conn_args) is not None


def send_watched(conn_args, idx, text, seconds=6, resend=True, on_event=None):
    """Sends `text` to channel `idx` and listens for its repeats.  -> {'sent', 'repeats', 'resent', 'interrupted', 'error'}.
    'sent' False means nothing went out (the caller can still send the normal way)."""
    result = {"sent": False, "repeats": 0, "resent": False, "interrupted": False, "error": ""}
    args = helper_args(conn_args)
    if args is None:
        result["error"] = "not supported on this connection"
        return result
    cmd = [sys.executable, HELPER] + args + ["--chan", str(idx), "--text", text, "--seconds", str(int(seconds)), "--resend", "1" if resend else "0"]
    with io.MESH_LOCK:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=io.NO_WINDOW, **io.UTF8)
        except OSError as e:
            result["error"] = f"cannot start the helper: {e}"
            return result
        previous = io.MESH_LOCK.on_contend
        def contend():                                      # somebody needs the radio: stop listening now (and never re-send then)
            result["interrupted"] = True
            try: proc.kill()
            except OSError: pass
            if previous: previous()
        io.MESH_LOCK.on_contend = contend
        watchdog = threading.Timer(seconds * 2 + 40, lambda: proc.poll() is None and proc.kill())      # a helper that hangs never keeps the radio
        watchdog.daemon = True
        watchdog.start()
        try:
            deadline = time.time() + seconds * 2 + 30
            for line in proc.stdout:
                ev = _parse(line)
                if not ev: continue
                kind = ev["event"]
                if kind in ("sent", "resent"): result["sent"] = True
                if kind == "resent": result["resent"] = True
                if kind == "repeat": result["repeats"] += 1
                if kind == "error":
                    result["error"] = ev.get("message", "error")
                    result["sent"] = result["sent"] or bool(ev.get("sent"))
                if on_event:
                    try: on_event(ev)
                    except Exception: pass
                if time.time() > deadline:
                    proc.kill()
                    break
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()
        finally:
            watchdog.cancel()
            io.MESH_LOCK.on_contend = previous
    return result


def _parse(line):
    line = (line or "").strip()
    if not line.startswith("{"): return None
    try: ev = json.loads(line)
    except ValueError: return None
    return ev if isinstance(ev, dict) and "event" in ev else None


def describe(r):
    """The note added to the message line: '(heard 2 repeats)', '(no repeat heard - sent again)', ..."""
    if not r.get("sent"): return ""
    n = r.get("repeats", 0)
    if n: return f"heard {n} repeat{'s' if n != 1 else ''}" + (" after sending again" if r.get("resent") else "")
    if r.get("resent"): return "no repeat heard, sent again"
    return "" if r.get("interrupted") else "no repeat heard"
