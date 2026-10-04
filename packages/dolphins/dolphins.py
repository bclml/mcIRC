"""/dolphins [nick]: a little pod of dolphins for the channel in front."""
import random
import re
import time

from gui_addons import AddonBase

MIN_GAP = 10          # seconds between two sends: the mesh is a tiny shared channel
PODS = [
    "~~~ 🐬 🐬 🐬 ~~~ a pod of dolphins leaps through the waves ~~~ 🐬 ~~~",
    "🐬 . 🐬 . 🐬 . 🐬  dolphins ride the bow wave",
    "~ ~ 🐬 ~ ~  splash!  🐬 ~ ~ 🐬 ~ ~ 🐬 ~ ~",
    "🌊 🐬 🌊 🐬 🌊 🐬 🌊 🐬  so long, and thanks for all the fish",
]
TO_ONE = "🐬 🐬 🐬 sends a pod of dolphins to @[{nick}] 🐬"


class Addon(AddonBase):
    title = "Dolphins"
    version = "1.0.3"
    author = "mcIRC"
    description = "/dolphins sends a pod of dolphins to the channel in front; /dolphins Nick sends them to one person."
    tick_seconds = 0

    def on_load(self):
        self._last = 0.0
        self.api.add_command("dolphins", self.cmd_dolphins, "/dolphins [nick]: send a pod of dolphins")

    def on_unload(self): pass

    def cmd_dolphins(self, arg):
        nick = re.sub(r"[\[\]@]", "", arg).strip()[:32]
        if time.time() - self._last < MIN_GAP: return self.api.notice(f"Easy there - one pod every {MIN_GAP} seconds.", "warn")
        if not self.api.send_current(TO_ONE.format(nick=nick) if nick else random.choice(PODS)): return self.api.notice("Open a channel or private window first - /dolphins sends to the window in front.", "warn")
        self._last = time.time()
