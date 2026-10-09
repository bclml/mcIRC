"""Asks the node to sign 32 bytes with its own key (MeshCore companion signing) and prints {"signature": "<hex>"} or {"error": "..."}.
Started by the map uploader addon while it holds the radio; the private key never leaves the node."""
import argparse
import asyncio
import json
import sys

import gui_seriallines  # noqa: F401  - opens the USB port without holding the board's button down (must come before meshcore)
from meshcore import MeshCore, EventType


async def run(a):
    if a.serial: mc = await MeshCore.create_serial(a.serial, a.baud)
    elif a.tcp: mc = await MeshCore.create_tcp(a.tcp, a.port)
    else: return {"error": "no connection given"}
    if mc is None: return {"error": "could not connect"}
    try:
        ev = await mc.commands.sign(bytes.fromhex(a.hex))
        if ev.type == EventType.SIGNATURE:
            sig = ev.payload.get("signature")
            return {"signature": sig.hex() if isinstance(sig, (bytes, bytearray)) else str(sig)}
        return {"error": str(ev.payload.get("reason", ev.payload) if isinstance(ev.payload, dict) else ev.payload)}
    finally:
        try: await mc.disconnect()
        except Exception: pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--tcp")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--hex", required=True)
    a = ap.parse_args()
    try: res = asyncio.run(run(a))
    except Exception as e: res = {"error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res), flush=True)
    return 0 if "signature" in res else 2


if __name__ == "__main__":
    sys.exit(main())
