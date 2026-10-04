import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import sys, os, tkinter as tk
BASE = ROOT
sys.path.insert(0, BASE); os.chdir(BASE)
import mcIRC as g, gui_platform

root = tk.Tk(); app = g.App(root, demo=True)
sb = app.switchbar

def shot(name): pass          # (screenshots are only for looking at the result by hand)

def run():
    res = []
    ok = lambda label, cond, d="": (res.append(bool(cond)), print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {d}" if d else "")))
    root.update()
    ok("switchbar holds only private windows", sorted(sb.buttons) == ["@Alice", "@Bob"], str(sorted(sb.buttons)))
    ok("unread DM button is red", sb.buttons["@Alice"]["bg"] == "#ff2020")
    ok("buttons are small (Tahoma 8, narrow)", (gui_platform.UI_FONT_NAME.lower() in str(sb.buttons["@Alice"]["font"]).lower() or not gui_platform.IS_WIN) and sb.buttons["@Alice"].winfo_reqwidth() < 90, f"{sb.buttons['@Alice'].winfo_reqwidth()}px wide")
    ok("starts docked at top, just under the toolbar", sb.dock == "top" and sb.host.winfo_y() >= app.toolbar.winfo_y() + app.toolbar.winfo_height() - 2)
    shot("sw_top")
    for where in ("bottom", "left", "right"):
        sb.set_dock(where); root.update()
        host = sb.host
        pos = {"bottom": host.winfo_y() > app.paned.winfo_y(), "left": host.winfo_x() < app.paned.winfo_x(), "right": host.winfo_x() > app.paned.winfo_x()}[where]
        ok(f"dock {where}", sb.dock == where and pos and len(sb.buttons) == 2, f"host at ({host.winfo_x()},{host.winfo_y()}) {host.winfo_width()}x{host.winfo_height()}")
        shot(f"sw_{where}")
    sb.xy = (300, 220); sb.set_dock("float"); root.update()
    ok("float as a separate small window", sb.dock == "float" and sb.win is not None and sb.win.winfo_exists() and len(sb.buttons) == 2, f"win {sb.win.winfo_width()}x{sb.win.winfo_height()}")
    shot("sw_float")
    # zone logic used by drag & drop
    rx, ry = root.winfo_rootx(), root.winfo_rooty(); W, H = root.winfo_width(), root.winfo_height()
    zones = {sb._zone(rx + W // 2, ry + 5): "top", sb._zone(rx + W // 2, ry + H - 5): "bottom", sb._zone(rx + 5, ry + H // 2): "left", sb._zone(rx + W - 5, ry + H // 2): "right",
             sb._zone(rx + W // 2, ry + H // 2): "float", sb._zone(rx - 50, ry + 50): "float"}
    ok("drag-and-drop zones (top/bottom/left/right/middle/outside)", all(k == v for k, v in zones.items()), str(zones))
    # a real simulated drag of the grip to the left edge
    grip = sb.host.winfo_children()[0]
    class E: pass
    e = E(); e.x_root, e.y_root = sb.win.winfo_rootx() + 4, sb.win.winfo_rooty() + 4
    sb._drag_start(e); e.x_root, e.y_root = rx + 6, ry + H // 2; sb._drag_move(e); root.update()
    ok("drop hint shown while dragging near an edge", sb.hint is not None)
    sb._drag_end(e); root.update()
    ok("dropping at the left edge docks it left", sb.dock == "left" and sb.win is None, sb.dock)
    sb.set_dock("top")
    app.close_window("@Alice"); app.close_window("@Bob"); root.update()
    ok("empty bar stays (so it can be moved) and shows a hint", sb.buttons == {} and sb.host.winfo_exists())
    app._dm_in("hello", f"{5+16:02x}"*32, {"snr": 9.0, "hops": 1}); root.update()
    ok("new DM adds a red button again", "@Alice" in sb.buttons and sb.buttons["@Alice"]["bg"] == "#ff2020")
    ok("toolbar uses icon buttons", all(w.cget("image") for w in app.toolbar.winfo_children() if isinstance(w, tk.Button) and not w.cget("text")), "")
    wm = app.root.nametowidget(app.root["menu"])
    ok("menu bar mirrors mIRC (File View Tools Addons Window Help)", [wm.entrycget(i, "label") for i in range(1, wm.index("end") + 1)] == ["File", "View", "Tools", "Addons", "Window", "Help"])
    print("\nALL PASSED" if all(res) else f"\n{res.count(False)} FAILED")
    root.destroy()
root.after(1500, run); root.mainloop()
