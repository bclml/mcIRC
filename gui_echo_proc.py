"""Send-and-listen process for channel messages.  Started by mcIRC (gui_echo.py); not meant to be run by hand.

Sends one channel message, then stays connected for --seconds and counts the copies of that message the radio hears again: a repeater that
passed it on.  If none was heard and --resend is set, it sends the message once more (with a new timestamp, so repeaters don't drop it as a
duplicate) and listens again.  One JSON line per event:

    {"event": "sent", "timestamp": 1791140000}
    {"event": "repeat", "path": "a1b2", "snr": 7.5}      a repeater passed our message on (path = the repeaters it went through)
    {"event": "resent", "timestamp": 1791140012}
    {"event": "done", "repeats": 2, "resent": false}
    {"event": "error", "message": "...", "sent": false}

Only our own message is compared; nothing else that is heard is printed."""
import argparse
import asyncio
import json
import sys
import time

import gui_seriallines  # noqa: F401  - opens the USB port without holding the board's button down (must come before meshcore)
from meshcore import MeshCore, EventType


def out(**kw):
    print(json.dumps(kw), flush=True)


def is_our_echo(log, name, text, timestamps):
    """True when a heard packet (RX log entry, decrypted by the library) is our own channel message coming back from a repeater."""
    if log.get("payload_type") != 5: return False
    msg = log.get("message")
    if msg is None or log.get("sender_timestamp") not in timestamps: return False
    return msg == f"{name}: {text}" or (msg.endswith(": " + text) and msg.split(": ", 1)[0] == name)


async def run(a):
    sent = False
    try:
        if a.serial: mc = await MeshCore.create_serial(a.serial, a.baud)
        elif a.tcp: mc = await MeshCore.create_tcp(a.tcp, a.port)
        else: return out(event="error", message="no connection given", sent=False)
    except Exception as e:
        return out(event="error", message=f"{type(e).__name__}: {e}", sent=False)
    if mc is None: return out(event="error", message="could not connect", sent=False)
    try:
        name = (mc.self_info or {}).get("name", "")
        await mc.commands.get_channel(a.chan)                   # the library needs the channel's key to read the copies it hears
        mc.set_decrypt_channel_logs(True)
        stamps, paths = set(), set()

        async def on_rx(ev):
            log = ev.payload or {}
            if is_our_echo(log, name, a.text, stamps):
                key = log.get("path", "")
                if key in paths: return
                paths.add(key)
                out(event="repeat", path=key, size=log.get("path_hash_size", 1), snr=log.get("snr"))

        mc.subscribe(EventType.RX_LOG_DATA, on_rx)

        async def send(label):
            ts = int(time.time())
            while ts in stamps: ts += 1
            stamps.add(ts)
            res = await mc.commands.send_chan_msg(a.chan, a.text, timestamp=ts)
            if res is None or res.type == EventType.ERROR: raise RuntimeError(f"the node refused the message: {getattr(res, 'payload', res)}")
            out(event=label, timestamp=ts)

        await send("sent")
        sent = True
        await asyncio.sleep(a.seconds)
        resent = False
        if not paths and a.resend:
            await send("resent")
            resent = True
            await asyncio.sleep(a.seconds)
        out(event="done", repeats=len(paths), resent=resent)
    except Exception as e:
        out(event="error", message=f"{type(e).__name__}: {e}", sent=sent)
    finally:
        try: await mc.disconnect()
        except Exception: pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--tcp")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--chan", type=int, required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--seconds", type=int, default=6)
    ap.add_argument("--resend", type=int, default=0)
    a = ap.parse_args()
    try:
        asyncio.run(run(a))
    except Exception as e:
        out(event="error", message=f"{type(e).__name__}: {e}", sent=False)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
