"""Advert listener process.  Started by mcIRC (gui_adverts.py) in the idle time between polls; not meant to be run by hand.

Connects to the node, asks for the contacts that changed since the last one mcIRC knows (so adverts missed while the port was in use are caught
up), then stays connected for --seconds and prints one JSON line per event as it happens:

    {"event": "ready"}
    {"event": "advert", "public_key": "..."}              a node advertised (the details follow a moment later)
    {"event": "contact", "contact": {...}}                a contact that was added or changed on the radio (name, type, position, ...)
    {"event": "new_contact", "contact": {...}}            an advert waiting for approval (the node is in manual-add mode)
    {"event": "rx", "path": "a1b2", "size": 1, "type": "GRP_TXT", "route": "FLOOD", "snr": 7.5, "rssi": -80, "length": 60}
                                                          a packet the radio heard: its kind, route and signal only - an ADVERT
                                                          (public, signed by its node) also with "packet": its bytes in hex (map uploader);
                                                          with --raw every packet has it (packet upload addon: as heard on the air)
    {"event": "msg", "payload": {...}}                    with --messages: a message the node had waiting, as meshcli's .sync_msgs prints
                                                          it (handed straight to mcIRC's message window; nothing else is done with it)
    {"event": "error", "message": "..."}
    {"event": "sent", "id": 7, "ok": true, "error": ""}   with --commands: the answer to a send mcIRC asked for (below)

With --commands mcIRC sends messages through this connection instead of stopping it (Bluetooth reconnects take seconds): one JSON line per
send on stdin - {"id": 7, "cmd": "chan", "idx": 3, "text": "..."} or {"id": 7, "cmd": "msg", "to": "<public key (prefix)>", "text": "..."} -
and over Bluetooth any other meshcli command: {"id": 7, "cmd": "cli", "args": [".infos", ".ver"]} -> {"event": "cli", "id": 7, "stdout": "...",
"stderr": "..."}, what meshcli itself would have printed (run by meshcli's own code on this connection).

Apart from --messages (the messages mcIRC fetches anyway, so it can stay connected and keep listening), no message text is read here."""
import argparse
import asyncio
import contextlib
import io
import json
import logging
import sys
import threading
import time

import gui_seriallines  # noqa: F401  - opens the USB port without holding the board's button down (must come before meshcore)
from meshcore import MeshCore, EventType


REAL_STDOUT = sys.stdout                    # (a meshcli command's own printing is captured while it runs - our events never are)


def out(**kw):
    REAL_STDOUT.write(json.dumps(kw) + "\n")
    REAL_STDOUT.flush()


async def run(a):
    try:
        if a.serial: mc = await MeshCore.create_serial(a.serial, a.baud)
        elif a.tcp: mc = await MeshCore.create_tcp(a.tcp, a.port)
        elif a.ble: mc = await MeshCore.create_ble(a.ble)
        else: return out(event="error", message="no connection given")
    except Exception as e:
        return out(event="error", message=f"{type(e).__name__}: {e}")
    if mc is None: return out(event="error", message="could not connect")

    emit = {"on": a.lastmod > 0}          # with nothing known yet the first full load is silent: those contacts are not "new adverts"
    if a.lastmod > 0:
        try: mc._lastmod = a.lastmod      # only fetch what changed since then
        except Exception: pass
    mc.auto_update_contacts = True         # the library re-reads changed contacts by itself after every advert / path update

    async def on_contacts(ev):
        if emit["on"]:
            for c in (ev.payload or {}).values(): out(event="contact", contact=c)

    async def on_new(ev): out(event="new_contact", contact=ev.payload)
    async def on_advert(ev): out(event="advert", public_key=ev.payload.get("public_key", ""))

    mc.subscribe(EventType.CONTACTS, on_contacts)
    mc.subscribe(EventType.NEW_CONTACT, on_new)
    mc.subscribe(EventType.ADVERTISEMENT, on_advert)

    async def on_rx(ev):                    # every packet the radio heard: kind, route, signal - never message content (map signals, packet monitor)
        d = ev.payload or {}
        extra = {"packet": d.get("payload", "")} if (a.raw or d.get("payload_typename") == "ADVERT") else {}   # adverts (public, signed) - all with --raw
        out(event="rx", path=d.get("path", "") if d.get("path_len", 0) > 0 else "", size=d.get("path_hash_size", 1), type=d.get("payload_typename", ""),
            route=d.get("route_typename", ""), snr=d.get("snr"), rssi=d.get("rssi"), length=d.get("payload_length"), **extra)
    if getattr(EventType, "RX_LOG_DATA", None) is not None: mc.subscribe(EventType.RX_LOG_DATA, on_rx)      # (older meshcore libraries don't have it)

    drain_lock = asyncio.Lock()

    async def drain():                      # --messages: fetch what the node has waiting, like meshcli's .sync_msgs, and pass it straight on
        async with drain_lock:
            while True:
                res = await mc.commands.get_msg()
                if res is None or res.type in (EventType.NO_MORE_MSGS, EventType.ERROR): return
                out(event="msg", payload=res.payload)           # printed at once: the node has already let go of it

    async def on_waiting(ev): asyncio.ensure_future(drain())     # the node says a message arrived: no need to wait for mcIRC's next poll

    cli_lock = asyncio.Lock()

    async def run_cli(cid, args):           # a meshcli command on this connection, its output captured as meshcli would print it
        from meshcore_cli.meshcore_cli import process_cmds
        from meshcore import logger as mc_logger
        async with cli_lock:
            buf, ebuf = io.StringIO(), io.StringIO()
            h = logging.StreamHandler(ebuf)
            mc_logger.addHandler(h)
            try:
                with contextlib.redirect_stdout(buf):
                    await process_cmds(mc, [str(x) for x in args])
            except Exception as e:
                ebuf.write(f"Error: {type(e).__name__}: {e}\n")
            finally:
                mc_logger.removeHandler(h)
            out(event="cli", id=cid, stdout=buf.getvalue(), stderr=ebuf.getvalue())

    async def handle(c):                    # --commands: a message mcIRC sends through this connection
        cid = c.get("id")
        try:
            if c.get("cmd") == "cli": return await run_cli(cid, c.get("args") or [])
            if c.get("cmd") == "chan":
                r = await mc.commands.send_chan_msg(int(c["idx"]), str(c["text"]))
            elif c.get("cmd") == "msg":
                key = str(c.get("to", "")).lower()
                contact = mc.get_contact_by_key_prefix(key) if key else None
                if contact is None:                 # only changed contacts were read at the start: read them all once
                    await mc.commands.get_contacts(lastmod=0)
                    contact = mc.get_contact_by_key_prefix(key)
                if contact is None: return out(event="sent", id=cid, ok=False, error="unknown destination (err_code_not_found)")
                r = await mc.commands.send_msg(contact, str(c["text"]))
            else:
                return out(event="sent", id=cid, ok=False, error="unknown command")
            ok = r is not None and r.type != EventType.ERROR
            out(event="sent", id=cid, ok=ok, error="" if ok else f"the node refused it: {getattr(r, 'payload', '')}")
        except Exception as e:
            out(event="sent", id=cid, ok=False, error=f"{type(e).__name__}: {e}")

    if a.commands:
        loop = asyncio.get_running_loop()
        def read_commands():
            for line in sys.stdin:
                try: c = json.loads(line)
                except ValueError: continue
                if isinstance(c, dict): asyncio.run_coroutine_threadsafe(handle(c), loop)
        threading.Thread(target=read_commands, daemon=True).start()
    if a.messages: mc.subscribe(EventType.MESSAGES_WAITING, on_waiting)
    try:
        await mc.commands.get_contacts(lastmod=a.lastmod)       # catch-up (silent when mcIRC knew nothing)
        emit["on"] = True
        out(event="ready")
        if a.messages: await drain()                            # anything that came in while the port was in use
        await asyncio.sleep(max(1, a.seconds - 2))
    finally:
        try: await mc.disconnect()
        except Exception: pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--tcp")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--ble", help="Bluetooth address of the node")
    ap.add_argument("--commands", action="store_true", help="read sends from stdin (JSON lines) and do them over this connection")
    ap.add_argument("--lastmod", type=int, default=0)
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--raw", action="store_true", help="every packet whole (as heard on the air) - only while an addon asks for it")
    ap.add_argument("--messages", action="store_true", help="also fetch incoming messages as they arrive (mcIRC shows them; nothing else reads them)")
    a = ap.parse_args()
    try:
        asyncio.run(run(a))
    except Exception as e:
        out(event="error", message=f"{type(e).__name__}: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
