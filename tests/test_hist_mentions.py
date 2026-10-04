import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import sys, os, tempfile, tkinter as tk
sys.path.insert(0, ROOT)
import mcIRC, gui_logs, gui_themes
from tkinter import font as tkfont
d = tempfile.mkdtemp()
log = gui_logs.WindowLog("Public", d)
open(log.path, "w", encoding="utf-8").write(
    "[11:35] <Gundam> @[VE7LSE WIZ TAG ] like voice repeater  (SNR 12.0, 4 hops)\n"
    "[11:42] <VA7NH> @[Frenchie's Scence Cap] Sweet!  (SNR 1, 3 hops)\n"
    "[11:46] <samy> Good morning @all  (SNR 12.0, 4 hops)\n")
root = tk.Tk()
f = tkfont.Font(family="Courier New", size=10)
w = mcIRC.ChatWindow(root, "Public", "t", f, log, 50, gui_themes.get(None), "Frenchie's Scence Cap")
t = w.text
def ranges(tag): return [t.get(a, b) for a, b in zip(t.tag_ranges(tag)[::2], t.tag_ranges(tag)[1::2])]
print("mention:", ranges("mention")); print("mention_me:", ranges("mention_me"))
ok = ranges("mention_me") == ["@[Frenchie's Scence Cap]"] and "@[VE7LSE WIZ TAG ]" in ranges("mention") and "@all" in ranges("mention")
print("PASS" if ok else "FAIL"); root.destroy()
