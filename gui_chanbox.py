"""The channel list used in addon settings: the chosen channels as a row of names, each with a x to remove it, and an 'Add' button that
offers the node's channels (and 'All channels' / 'Other...').  Replaces typing '#test, #buds' in one box - the value is still stored
the same way ('#test, #buds' in a StringVar), so saved settings don't change.

    channel_box(parent, var, choices=lambda: ["#weather", ...], all_option=True)"""
import re
import tkinter as tk
from tkinter import simpledialog

ALL = "all"


def parse(text):
    """'#test.#buds, Public all' -> ['#test', '#buds', 'Public', 'all'] (each once, in order)."""
    out = []
    for part in re.split(r"[,;.\s]+", text or ""):
        p = part.strip()
        if not p: continue
        if p.lower() in ("all", "*"): p = ALL
        elif p.lower() in ("public", "#public"): p = "Public"
        elif not p.startswith(("#", "@")): p = "#" + p
        if p.lower() not in (o.lower() for o in out): out.append(p)
    return out


def _node_channels():
    try:
        import meshcore_io as io
        return ["Public"] + sorted(("#" + n.lstrip("#") for n in io.CHANNEL_INDEX_BY_NAME if n.lstrip("#").lower() != "public"), key=str.lower)
    except Exception:
        return ["Public"]


def channel_box(parent, var, choices=None, all_option=False, public=True, bg=None, max_items=None, empty="(none)"):
    """A frame showing var's channels with x buttons and an 'Add' menu; writes the list back to var as '#a, #b'."""
    bg = bg or parent.cget("bg")
    frame = tk.Frame(parent, bg=bg)
    state = {"busy": False}

    def current(): return parse(var.get())

    def write(items):
        state["busy"] = True
        try: var.set(", ".join(items))
        finally: state["busy"] = False
        render()

    def remove(name): write([c for c in current() if c != name])

    def add(name):
        items = [c for c in current() if c != ALL] if name != ALL else []
        if name.lower() not in (c.lower() for c in items): items.append(name)
        if max_items: items = items[-max_items:]
        write(items)

    def other():
        name = simpledialog.askstring("Add a channel", "Channel name (for example #weather):", parent=frame.winfo_toplevel())
        if name and name.strip():
            for n in parse(name): add(n)

    def fill(menu):
        menu.delete(0, "end")
        have = {c.lower() for c in current()}
        names = [n for n in (choices() if choices else _node_channels()) if (public or n != "Public") and n.lower() not in have]
        for n in names: menu.add_command(label=n, command=lambda n=n: add(n))
        if all_option and ALL not in have:
            if names: menu.add_separator()
            menu.add_command(label="All channels", command=lambda: add(ALL))
        if names or all_option: menu.add_separator()
        menu.add_command(label="Other channel...", command=other)

    def render():
        if not frame.winfo_exists(): return
        for w in frame.winfo_children(): w.destroy()
        items = current()
        for name in items:
            chip = tk.Frame(frame, bg="#e8eef7", bd=1, relief="solid")
            chip.pack(side="left", padx=(0, 3), pady=1)
            tk.Label(chip, text="All channels" if name == ALL else name, bg="#e8eef7").pack(side="left", padx=(4, 0))
            tk.Button(chip, text="×", bd=0, bg="#e8eef7", activebackground="#f2c6c6", padx=3, pady=0, cursor="hand2",
                      command=lambda n=name: remove(n)).pack(side="left")
        if not items: tk.Label(frame, text=empty, bg=bg, fg="#777").pack(side="left", padx=(0, 4))
        mb = tk.Menubutton(frame, text="Add ▾", relief="raised", padx=6, pady=0, bg=bg)
        menu = tk.Menu(mb, tearoff=0)
        menu.configure(postcommand=lambda: fill(menu))
        mb.configure(menu=menu)
        mb.pack(side="left", padx=2)

    var.trace_add("write", lambda *a: None if state["busy"] else render())   # changed elsewhere ('Same channel for all', 'Clear all')
    render()
    return frame
