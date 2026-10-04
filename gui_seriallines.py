"""Keeps the board's button released while mcIRC talks to the radio over USB.

On ESP32 boards with the usual auto-programming circuit (Heltec V3 and most others), DTR on + RTS off pulls GPIO0 low - and GPIO0 is the
board's user / PRG button.  The meshcore library opens the port with pyserial's defaults (DTR on) and then switches RTS off, so for as long
as any program held the port, the firmware saw its button held down:
  - under 1.2 s: a click (the screen goes to its next page);
  - 1.2 s or more: a long press - ENTER on whatever page the screen showed (hibernate = the node switched itself off and stopped answering,
    Bluetooth on/off, send advert, ...), or, in the first 8 seconds after a reboot, the 'CLI rescue' console (the port only echoes text).
Importing this module makes every serial port open with DTR and RTS both off: GPIO0 and EN stay high, no button, no reset."""
import serial

_original = getattr(serial, "_mcirc_original_serial_for_url", serial.serial_for_url)      # the real one, even if this module is loaded twice
serial._mcirc_original_serial_for_url = _original


def serial_for_url(url, *args, **kwargs):
    do_not_open = kwargs.pop("do_not_open", False)
    port = _original(url, *args, do_not_open=True, **kwargs)
    try:
        port.dtr = False                       # set before opening: pyserial applies them as the port opens
        port.rts = False
    except Exception:
        pass
    if not do_not_open: port.open()
    return port


serial.serial_for_url = serial_for_url
