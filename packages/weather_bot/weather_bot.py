"""Weather bot 2.0: now part of Area alerts.  Its commands - wx <place>, gwx, aqi, sun, moon, solar, sf, hfcond, satpass, airplanes,
rain, aurora, channels, status, contact - and the rain warning are answered by Area alerts (2.1 and later, Settings > Weather commands).
This version only hands over: it installs Area alerts when it isn't (from the packages that come with mcIRC - nothing from the internet),
switches it on - Area alerts then adds this addon's settings (every node's) to its own, without switching its alert checks on - and
switches itself off.  Its settings stay where they are; nothing is removed."""
from gui_addons import AddonBase

NEW = "area_alerts"


class Addon(AddonBase):
    title = "Weather bot"
    version = "2.0.0"
    author = "mcIRC"
    description = ("Now part of Area alerts: switching this on moves its settings (channels, place, commands, rain warning) into Area alerts' "
                   "'Weather commands', installs and switches on Area alerts if needed, and switches this addon off. Nothing is removed.")
    tick_seconds = 0

    def on_load(self):
        self.api.after(800, self.hand_over)

    def hand_over(self):
        api = self.api
        if not hasattr(api, "install_addon"):          # still running an mcIRC from before the update: the next start finishes it
            return api.log("The Weather bot is now part of Area alerts - restart mcIRC to finish moving your settings there.", "warn")
        try:
            if not api.addon_installed(NEW): api.install_addon(NEW)
        except Exception as e:
            return api.log(f"Weather bot: couldn't install Area alerts ({e}) - Tools > Addons > Browse online catalog.", "warn")
        api.set("handed_over", True)                   # it was switched on: Area alerts answers its commands from now on
        if not api.addon_enabled(NEW): api.set_addon_enabled(NEW, True)     # Area alerts takes the settings over when it starts
        api.set_addon_enabled("weather_bot", False)
        api.log("The Weather bot is now part of Area alerts: your settings are moved there and this addon is switched off "
                "(Addons > Area alerts > Settings > Weather commands).", "info")

    def channels_used(self): return []
