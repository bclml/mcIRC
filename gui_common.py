"""Shared settings, theme constants and helpers for the mIRC-style GUI (see mcIRC.py)."""
import gui_platform
import json, os, re, time

import meshcore_io as ea

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, "gui_settings.json")

DEFAULT_SETTINGS = {
    "mode": "usb", "port": "auto", "last_port": "", "baud": "", "ble_target": "", "tcp_host": "", "tcp_port": 5000, "node_name": "MyNode", "location": "Surrey",
    "poll_seconds": 20,
    "node_lat": 49.19, "node_lon": -122.85,
    "node_prune_days": 10,       # forget nodes not seen for this many days (0 = never)
    "node_sync_minutes": 5,      # how often to read the radio's contact list into long-term memory
    "radio_capacity": 350,       # how many contacts the radio itself can hold
    "prune_radio": False,        # also delete forgotten nodes from the radio itself
    "reboot_on_disconnect": True,  # reboot the node when mcIRC disconnects or closes (Options > Connect)
    "auto_reset_radio": True,    # if the radio stops answering for ~2 minutes, restart it by pulsing the USB reset line (CP210x / CH340 / FTDI boards only)
    "watch_repeats": True,        # after sending to a channel, listen a few seconds for repeaters passing it on ("heard 2 repeats"; USB and WiFi)
    "resend_unheard": True,       # ...and send it once more when no repeater was heard
    "advert_listen": True,       # between polls, listen for adverts so new / changed nodes show up at once (USB, Wi-Fi and Bluetooth; also messages - and sends go through it)
    "advert_notices": True,      # say in the Status window when a node is heard for the first time
    "show_time": True, "font_size": 10, "auto_connect": False,
    "bots_in_public": False,       # bots never post in Public (the channel everyone hears); their answers there go privately
    "check_updates": True,       # look for a newer version at startup (at most once a day)
    "last_update_check": 0,
    "theme": "Classic mIRC", "skin": "None", "highlight_words": "",
    "sounds_enabled": True, "sound_private": "Ding", "sound_mention": "Exclamation", "sound_highlight": "Question",
    "sound_channel": "None", "sound_custom": "", "closed_channels": [],
    "log_enabled": True,         # keep one .txt log per window in logs/
    "log_history": 200,          # how many log lines to show again after a restart
    "addons": {}, "addons_enabled": {},
    "extra_nodes": [],            # Options > More nodes: [{label, mode, port / host / ble, enabled}]
}

# Classic Windows / mIRC palette
BG = "#d4d0c8"
TEXT_BG = "#ffffff"
FONT_FAMILY = gui_platform.MONO_FONT_NAME
NICK_COLORS = ["#0000cc", "#009300", "#cc0000", "#7f007f", "#fc7f00", "#009393", "#7f0000", "#00007f", "#4b4b4b"]

# Display name -> (topic shown in the topic bar, purpose shown in the channel list)
CHANNELS = {
    "Public": "Public channel - tsunami/earthquake alerts and the weekly reminder",
    "#drivebc": "DriveBC highway incidents and closures (Open511) - checked every 60s",
    "#bcferries": "BC Ferries service notices and live departure delays - checked every 60s",
    "#bctransit": "BC Transit regional service alerts - checked every 60s",
    "#translink": "TransLink SkyTrain / SeaBus / major bus disruptions - checked every 60s",
    "#weather": "Environment Canada warnings and the daily 6AM/8AM forecasts",
    "#bot-van": "Test channel - send 'test' or 't' to check your signal reaches the node",
}

_EMOJI = {"\U0001F6A8": "[!]", "\U0001F30E": "[EQ]"}


FULL_UNICODE = False        # Tk draws characters beyond the BMP (emoji) - Tk 8.6.10 and later; set when the window starts (tk_full_unicode)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\u2190-\u21FF]+")


def tk_full_unicode(root):
    """Can this Tk draw emoji (characters beyond the BMP)?  Older ones on Windows drew garbage or nothing."""
    try: return tuple(int(x) for x in str(root.tk.call("info", "patchlevel")).split(".")[:3]) >= (8, 6, 10)
    except Exception: return False


def safe_text(text):
    """Text as the chat windows show it: emoji kept where Tk can draw them (an older Tk: swapped for plain text / left out); the
    invisible 'show as emoji' marks (U+FE0F / FE0E) dropped - Tk draws them as gaps."""
    text = text.replace("\ufe0f", "").replace("\ufe0e", "")
    if FULL_UNICODE: return text
    for k, v in _EMOJI.items(): text = text.replace(k, v)
    return re.sub(r'[\U00010000-\U0010FFFF]', '', text)


def tk_offset(text, i):
    """Tk 8.6 counts a character beyond the BMP (most emoji) as two: the index of text[i] as Tk counts it."""
    return i + sum(1 for ch in text[:i] if ord(ch) > 0xFFFF)


def insert_text(t, text, tags=()):
    """Inserts text at the end of a Text widget, emoji in the emoji font (the 'emoji' tag) so they show as pictures, not blobs."""
    tags = (tags,) if isinstance(tags, str) else tuple(tags)
    pos = 0
    for m in EMOJI_RE.finditer(text):
        if m.start() > pos: t.insert("end", text[pos:m.start()], tags)
        for run in re.findall("[𐀀-􏿿]+|[^𐀀-􏿿]+", m.group()):
            t.insert("end", run, tags + ("emoji" if ord(run[0]) > 0xFFFF else "symbol",))
        pos = m.end()
    if pos < len(text): t.insert("end", text[pos:], tags)


SETTINGS_PROBLEM = ""      # set by load_settings when gui_settings.json is there but couldn't be used: a line for the Status window
_SAVE_BLOCKED = False      # ...and it couldn't even be moved aside: save_settings never writes over it (defaults would replace everything)


def load_settings():
    """The saved settings over the defaults.  A file that is there but broken (half written, not JSON) is kept as gui_settings.json.broken-<time>
    and mcIRC starts with defaults; one that can't be opened (locked by OneDrive / antivirus) is left alone and never saved over this session."""
    global SETTINGS_PROBLEM, _SAVE_BLOCKED
    SETTINGS_PROBLEM, _SAVE_BLOCKED = "", False
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f: data = json.load(f)
        if not isinstance(data, dict): raise ValueError("it holds no settings")
        s.update(data)
    except FileNotFoundError:
        pass
    except ValueError as e:                                       # (bad JSON, bad UTF-8)
        aside = SETTINGS_PATH + time.strftime(".broken-%Y%m%d-%H%M%S")
        try:
            os.replace(SETTINGS_PATH, aside)
            SETTINGS_PROBLEM = (f"Your settings file couldn't be read ({e}). It was kept as {os.path.basename(aside)} and mcIRC started with "
                                "default settings.")
        except OSError:
            _SAVE_BLOCKED = True
            SETTINGS_PROBLEM = (f"Your settings file couldn't be read ({e}) or moved aside. mcIRC started with default settings and won't save "
                                "over it this session - copy gui_settings.json somewhere safe, then restart mcIRC.")
    except OSError as e:
        _SAVE_BLOCKED = True
        SETTINGS_PROBLEM = (f"Your settings file couldn't be opened ({e.strerror or e}). mcIRC started with default settings and won't save over it "
                            "this session - close whatever holds it (OneDrive sync, antivirus), then restart mcIRC.")
    return s


def save_settings(s):
    """Writes the whole file or nothing: a temp file next to it, then swapped in, so a crash or power cut mid-write can't leave half a file.
    -> False (nothing written) while load_settings couldn't read the file that is there."""
    if _SAVE_BLOCKED: return False
    data = json.dumps(s, indent=2)                                # (an error here leaves the file as it was)
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(5):
        try:
            os.replace(tmp, SETTINGS_PATH)
            return True
        except OSError as e:
            if isinstance(e, PermissionError) and attempt < 4:    # Windows: OneDrive or antivirus can hold the file for a moment
                time.sleep(0.1)
                continue
            try: os.remove(tmp)
            except OSError: pass
            raise


def _norm(name): return name.lstrip("#").strip().lower()


def channel_index(display):
    """Node channel index for a display name like '#drivebc' / 'Public', or None if unresolved."""
    if display == "Public": return 0
    for name, idx in ea.CHANNEL_INDEX_BY_NAME.items():
        if _norm(name) == _norm(display): return idx
    return None


def display_for_index(idx):
    if idx == 0: return "Public"
    for name, i in ea.CHANNEL_INDEX_BY_NAME.items():
        if i == idx: return "#" + name.lstrip("#")
    return f"#channel{idx}"
