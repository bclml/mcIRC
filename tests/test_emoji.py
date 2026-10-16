import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Emoji in the chat windows: shown (in an emoji / symbol font) where Tk can draw them, instead of being dropped - they showed as blobs.
What is sent or logged doesn't change."""
import tkinter as tk
import gui_common as gc

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk(); root.withdraw()
ok("Tk 8.6.10 and later draws emoji", gc.tk_full_unicode(root) is (tuple(int(x) for x in str(root.tk.call("info", "patchlevel")).split(".")[:3]) >= (8, 6, 10)))
line = "Thu ☀️ | \U0001F327️ rain \U0001F6A8"
gc.FULL_UNICODE = True
ok("shown: the emoji stay, only the invisible 'as emoji' marks (U+FE0F) go - Tk drew those as gaps", gc.safe_text(line) == "Thu ☀ | \U0001F327 rain \U0001F6A8")
gc.FULL_UNICODE = False
ok("an older Tk: as before (swapped for text / left out)", gc.safe_text(line) == "Thu ☀ |  rain [!]", repr(gc.safe_text(line)))
gc.FULL_UNICODE = True
t = tk.Text(root); t.tag_config("x")
gc.insert_text(t, "a \U0001F327 b ☀ c", "x")
ranges = lambda tag: [t.get(t.tag_ranges(tag)[i], t.tag_ranges(tag)[i + 1]) for i in range(0, len(t.tag_ranges(tag)), 2)]
ok("written with the emoji font (the 'emoji' tag) for the newer emoji, the symbol font for the older ones (the sun keeps its rays)",
   ranges("emoji") == ["\U0001F327"] and ranges("symbol") == ["☀"] and t.get("1.0", "end-1c") == "a \U0001F327 b ☀ c", (ranges("emoji"), ranges("symbol")))
ok("...the line's own tag stays on everything", ranges("x") == ["a \U0001F327 b ☀ c"])
s = "x \U0001F327 @Bob"
ok("positions after an emoji count it twice, as Tk does (mentions in old lines stay on the name)", gc.tk_offset(s, s.index("@")) == s.index("@") + 1)
t2 = tk.Text(root); t2.insert("end", s); i = gc.tk_offset(s, s.index("@"))
ok("...and that is where Tk has it", t2.get(f"1.{i}", f"1.{i + 4}") == "@Bob", t2.get(f"1.{i}", f"1.{i + 4}"))
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
