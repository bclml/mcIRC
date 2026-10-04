"""CLI rescue console (Tools > CLI rescue console...).

MeshCore companion firmware has a recovery console: a long press of the board's button in the first 8 seconds after it starts switches the
USB port from the app protocol to plain text commands.  On boards with the usual auto-programming circuit (Heltec V3, ...) that button is
GPIO0, which DTR pulls low - so mcIRC can enter rescue mode by itself: restart the board (RTS), then 'press' the button (DTR) for 2 seconds.
Commands the console knows (companion firmware): ls <path>, cat <path>, rm <path>, set pin <number>, rebuild, erase, reboot."""
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import gui_health
import gui_platform
import meshcore_io as io
from gui_common import BG

HELP = ("ls UserData/   - list the node's files          cat <path>   - show a file\n"
        "rm <path>      - delete a file                  set pin <n>  - Bluetooth PIN\n"
        "rebuild        - repair: wipe the file system, then write back identity, settings, contacts, channels\n"
        "erase          - wipe EVERYTHING (identity, settings, contacts, channels)\n"
        "reboot         - leave rescue mode (normal start)")
DANGER = {"erase": "This wipes EVERYTHING on the node: its identity (other nodes will see a new node), settings, contacts and channels.",
          "rebuild": "This wipes the node's file system and then writes back its identity, settings, contacts and channels.\n"
                     "Use it when the node's storage is corrupted. Contacts or settings that cannot be read back are lost.",
          "rm": "This deletes a file on the node."}


def open_port(port, timeout=0.2):
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 115200, timeout
    s.dtr = False                                   # button released, not in reset
    s.rts = False
    s.open()
    return s


def enter_rescue(s, boot_wait=2.5, hold=2.0):
    """Restart the board and hold its button through the first seconds: the firmware starts its rescue console.  Returns what it printed."""
    s.rts = True                                    # EN low: reset
    time.sleep(0.15)
    s.rts = False
    time.sleep(boot_wait)
    s.dtr = True                                    # GPIO0 low: the button is held ...
    time.sleep(hold)
    s.dtr = False                                   # ... and released
    time.sleep(0.5)
    out = b""
    t0 = time.time()
    while time.time() - t0 < 1.0: out += s.read(4096)
    return out.decode("utf-8", "replace")


def in_rescue(s):
    """True when the port behaves like the rescue console (it echoes an empty line and answers 'unknown command')."""
    s.reset_input_buffer()
    s.write(b"\r")
    out, t0 = b"", time.time()
    while time.time() - t0 < 1.5: out += s.read(512)
    return b"unknown command" in out or b"CLI Rescue" in out


class RescueDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root, bg=BG)
        self.app, self.port, self.reader = app, None, None
        app.rescue_open = True                         # (mcIRC's automatic 'reboot out of rescue mode' stays away while this is open)
        self.title("CLI rescue console")
        self.geometry("760x520")
        conn = io.CONNECTION_ARGS or (["-s", app.settings.get("last_port", "")] if app.settings.get("last_port") else None)
        self.conn = conn
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=6, pady=4)
        tk.Label(top, text=f"Port: {conn[1] if conn and conn[0] == '-s' else '(no USB port known - connect once first)'}", bg=BG).pack(side="left")
        self.status = tk.Label(top, text="Not open", bg=BG, fg="#555")
        self.status.pack(side="right")
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=6)
        for text, cmd in (("Enter rescue mode", self.start), ("ls UserData/", lambda: self.send("ls UserData/")), ("ls", lambda: self.send("ls")),
                          ("Leave (reboot)", lambda: self.send("reboot"))):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)
        self.out = tk.Text(self, bg="#101010", fg="#d0ffd0", insertbackground="#d0ffd0", font=(gui_platform.MONO_FONT_NAME, 10), wrap="char")
        self.out.pack(fill="both", expand=True, padx=6, pady=4)
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=6, pady=(0, 6))
        self.entry = tk.Entry(row, font=(gui_platform.MONO_FONT_NAME, 10))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.send(self.entry.get()))
        ttk.Button(row, text="Send", command=lambda: self.send(self.entry.get())).pack(side="left", padx=4)
        self.write(HELP + "\n\n")
        self.protocol("WM_DELETE_WINDOW", self.close)

    def write(self, text):
        if not self.winfo_exists(): return
        self.out.insert("end", text)
        self.out.see("end")

    def start(self):
        ok, why = gui_health.reset_allowed(self.conn)
        if not ok: return messagebox.showerror("CLI rescue", f"Can't do this here: {why}", parent=self)
        if self.app.worker.running:
            if not messagebox.askokcancel("CLI rescue", "mcIRC has to let go of the radio first (it disconnects). Continue?", parent=self): return
            self.app.disconnect()
        self.status.config(text="Restarting the node and holding its button...")
        def work():
            deadline = time.time() + 20
            while self.app.worker.running and time.time() < deadline: time.sleep(0.2)
            with io.MESH_LOCK:
                if self.port is None: self.port = open_port(self.conn[1])
                text = enter_rescue(self.port)
                return text, in_rescue(self.port)
        def done(r):
            if isinstance(r, Exception):
                self.status.config(text="Failed")
                return self.write(f"\n[could not open the port: {r}]\n")
            text, ok = r
            self.write(text)
            self.status.config(text="In rescue mode" if ok else "Not in rescue mode")
            self.write("\n[the node is in rescue mode - type a command]\n" if ok else
                       "\n[the node did not enter rescue mode - this board may not wire its button to DTR; hold its button for 2 s right after pressing reset]\n")
            if ok: self._read()
        self.app.bg(work, done)

    def _read(self):
        if self.reader: return
        def loop():
            while self.port is not None:
                try: data = self.port.read(1024)
                except Exception: break
                if data: self.after(0, lambda d=data: self.write(d.decode("utf-8", "replace")))
        self.reader = threading.Thread(target=loop, daemon=True)
        self.reader.start()

    def send(self, line):
        line = (line or "").strip()
        if not line: return
        if self.port is None: return messagebox.showinfo("CLI rescue", "Press 'Enter rescue mode' first.", parent=self)
        word = line.split()[0]
        if word in DANGER and not messagebox.askyesno("CLI rescue", DANGER[word] + f"\n\nSend '{line}'?", icon="warning", parent=self): return
        if word == "erase" and not messagebox.askyesno("CLI rescue", "Really erase the whole node? This cannot be undone.", icon="warning", parent=self): return
        self.entry.delete(0, "end")
        try: self.port.write(line.encode("utf-8") + b"\r")
        except Exception as e: self.write(f"\n[send failed: {e}]\n")
        if word == "reboot":
            self.status.config(text="Rebooting - normal start")
            self.after(1500, self.close)

    def close(self):
        self.app.rescue_open = False
        p, self.port = self.port, None
        if p is not None:
            try: p.close()
            except Exception: pass
        self.destroy()
