import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import sys, os, re, re
from unittest import mock
sys.path.insert(0, ROOT)
import tkinter as tk
import gui_donate as gd, mcIRC, gui_commands
B = ROOT
fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

src = open(os.path.join(B, "gui_donate.py"), encoding="utf-8").read()
ok("no PayPal.Me handle (a phone number) and no e-mail address in the donation code", not hasattr(gd, "PAYPAL_ME") and not re.search(r"paypal\.me/\d{6,}", src) and not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", src))
ok("units link is the $1 payment button with a quantity", gd.units_url() == "https://www.paypal.com/ncp/payment/TVFX47SD92LSE")
ok("subscription link is the hosted Subscribe button, in CAD", gd.subscribe_url().startswith("https://www.paypal.com/cgi-bin/webscr?") and "cmd=_s-xclick" in gd.subscribe_url()
   and "hosted_button_id=C2AYGMYMTKVZJ" in gd.subscribe_url() and "currency_code=CAD" in gd.subscribe_url())
root = tk.Tk(); app = mcIRC.App(root, demo=True); root.update()
opened = []
def texts(d): return " ".join(w.cget("text") for w in d.winfo_children() if isinstance(w, tk.Label))
def buttons(d): return [b for b in d.winfo_children()[2].winfo_children() if b.winfo_class() == "TButton"]
def open_dialog():
    app.command("donate"); root.update()
    return [w for w in root.winfo_children() if isinstance(w, gd.DonateDialog)][0]
with mock.patch("webbrowser.open", lambda u: opened.append(u)):
    d = open_dialog(); t = texts(d); bs = buttons(d)
    ok("says it is not mandatory and greatly appreciated", "NOT mandatory" in t and "greatly appreciated" in t)
    ok("explains PayPal opens in the browser and no card details are seen", "PayPal in your web browser" in t and "never sees" in t)
    ok("two choices: $1 units (1 to 100), and $1 CAD every month (cancel any time)", len(bs) == 2 and "1 to 100" in bs[0].cget("text") and "month" not in bs[0].cget("text").lower()
       and "every month" in bs[1].cget("text") and "cancel any time" in bs[1].cget("text") and "$1 CAD" in bs[1].cget("text"), [b.cget("text") for b in bs])
    ok("explains the monthly option can be stopped in PayPal", "stopped at any time" in t)
    ok("nothing opens until a button is pressed", not opened)
    bs[0].invoke(); root.update()
    ok("the first button opens the $1 x quantity page and closes the dialog", opened == [gd.units_url()] and not d.winfo_exists(), opened)
    d = open_dialog(); buttons(d)[1].invoke(); root.update()
    ok("the monthly button opens the PayPal subscription and closes the dialog", opened[-1] == gd.subscribe_url() and not d.winfo_exists(), opened)
    with mock.patch.object(gd, "SUBSCRIBE_URL", ""):
        d = open_dialog()
        ok("without a subscription link the monthly button and text are hidden", len(buttons(d)) == 1 and "month" not in texts(d).lower())
        d.destroy()
    d = open_dialog(); n = len(opened); d.winfo_children()[-1].invoke(); root.update()
    ok("'No thanks' opens nothing", len(opened) == n and not d.winfo_exists())
ok("/donate listed and toolbar icon exists", any(r[0] == "donate" for r in gui_commands.APP) and "donate" in app.icons)
ok("never appears on its own", not [w for w in root.winfo_children() if isinstance(w, gd.DonateDialog)])
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
