"""Traffic, transit and weather 2.0: now part of Area alerts.  Everything it did - DriveBC, BC Ferries, TransLink / BC Transit, Environment
Canada weather, earthquakes, tsunamis, 'route <address>', the map's DriveBC and earthquake layers, daily forecasts, the weekly reminder - is
in Area alerts (2.0 and later).  This version only hands over: it installs Area alerts when it isn't (from the packages that come with
mcIRC - nothing from the internet), switches it on - Area alerts then adds this addon's settings to its own - and switches itself off.
Its settings stay where they are; nothing is removed.  (The console bot, Run_Agent.bat / emergency_agent.py, is not affected.)"""
from gui_addons import AddonBase

NEW = "area_alerts"


class Addon(AddonBase):
    title = "Traffic, transit and weather"
    version = "2.0.0"
    author = "mcIRC"
    description = ("Now part of Area alerts: switching this on moves its settings (channels, alert types, areas, keys, route) into Area alerts, "
                   "installs and switches on Area alerts if needed, and switches this addon off. Nothing is removed.")
    tick_seconds = 0

    def on_load(self):
        self.api.after(800, self.hand_over)

    def hand_over(self):
        api = self.api
        if not hasattr(api, "install_addon"):          # still running an mcIRC from before the update: the next start finishes it
            return api.log("Traffic, transit and weather is now part of Area alerts - restart mcIRC to finish moving your settings there.", "warn")
        try:
            if not api.addon_installed(NEW): api.install_addon(NEW)
        except Exception as e:
            return api.log(f"Traffic, transit and weather: couldn't install Area alerts ({e}) - Tools > Addons > Browse online catalog.", "warn")
        if not api.addon_enabled(NEW): api.set_addon_enabled(NEW, True)     # Area alerts takes the settings over when it starts
        api.set_addon_enabled("broadcast_alerts", False)
        api.log("Traffic, transit and weather is now part of Area alerts: your settings are moved there and this addon is switched off "
                "(Addons > Area alerts > Settings).", "info")

    def channels_used(self): return []
