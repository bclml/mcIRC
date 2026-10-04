"""meshcli (meshcore-cli) as mcIRC runs it: the same program and arguments, but the USB port is opened without holding the board's button
down (see gui_seriallines.py).  Started by meshcore_io; not meant to be run by hand."""
import sys

import gui_seriallines  # noqa: F401  - must come before meshcore opens the port

from meshcore_cli.meshcore_cli import cli

if __name__ == "__main__":
    sys.argv[0] = "meshcli"
    cli()
