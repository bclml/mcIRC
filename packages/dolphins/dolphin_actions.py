"""The Dolphins addon's fun actions: one-line jokes sent to the channel in front about a person ('slaps @[Bob] around a bit with a large
trout'), offered in the right-click menu on a name.  The list is yours to change in the addon's settings; {nick} is the person."""
import tkinter as tk
from tkinter import messagebox, ttk

MAX_CHARS = 120               # a MeshCore message (meshcore_io.MESH_MSG_MAX_CHARS)
NAME_ROOM = 20                # room left for the person's name when checking the length
DEFAULTS = [
    ("Slap with a large trout", "slaps @[{nick}] around a bit with a large trout 🐟"),
    ("Send a pod of dolphins", "🐬 🐬 🐬 sends a pod of dolphins to @[{nick}] 🐬"),
    ("Dolphins swim circles", "sends a pod of dolphins to swim circles around @[{nick}] until they get dizzy 🐬"),
    ("Dolphin rescue", "sends a pod of dolphins to rescue @[{nick}] from a boring conversation 🐬"),
    ("Dolphin backflips", "sends dolphins to do high-flying backflips over @[{nick}] 🐬"),
    ("Splash with cold water", "has the dolphins splash @[{nick}] with cold water 🌊"),
    ("Off to a tropical island", "sends a pod of dolphins to carry @[{nick}] away to a tropical island 🏝"),
    ("Clue-by-four", "hits @[{nick}] with a clue-by-four. Now go read the help files 📖"),
    ("Water balloon", "launches a heat-seeking water balloon at @[{nick}]'s head 🎈"),
    ("Drop an anvil", "drops an anvil on @[{nick}], cartoon style 💥"),
    ("Wild penguins", "summons a pack of wild penguins to peck at @[{nick}]'s shoes 🐧"),
    ("Fix their antenna", "turns @[{nick}]'s antenna the right way up 📡"),
    ("Fresh battery", "hands @[{nick}] a freshly charged battery 🔋"),
]


def defaults(): return [{"label": l, "text": t} for l, t in DEFAULTS]


def clean(actions):
    """The saved list, with anything broken left out (old or hand-edited settings)."""
    out = []
    for a in actions if isinstance(actions, list) else []:
        if isinstance(a, dict) and str(a.get("label", "")).strip() and "{nick}" in str(a.get("text", "")):
            out.append({"label": str(a["label"]).strip()[:40], "text": str(a["text"]).strip()})
    return out


def line(action, nick):
    """The message for this person (names can't break out of the @[...] mention)."""
    nick = "".join(c for c in nick if c not in "[]@").strip()[:32]
    return action["text"].replace("{nick}", nick)


def problem(label, text):
    """Why this action can't be saved, or None."""
    if not label.strip(): return "Give it a name for the menu."
    if "{nick}" not in text: return "The message needs {nick} where the person's name goes."
    if len(text.replace("{nick}", "x" * NAME_ROOM)) > MAX_CHARS: return f"Too long for one mesh message (at most {MAX_CHARS} characters with a {NAME_ROOM}-letter name)."
    return None


def find(actions, words):
    """The action whose number (1, 2, ...) or name matches."""
    words = words.strip().lower()
    if words.isdigit() and 1 <= int(words) <= len(actions): return actions[int(words) - 1]
    return next((a for a in actions if a["label"].lower() == words), None) or next((a for a in actions if words and words in a["label"].lower()), None)


class ActionsEditor:
    """The list in the addon's settings: add, edit, remove, move, reset.  items() is the edited list."""
    def __init__(self, parent, actions, bg):
        self.items_ = [dict(a) for a in actions]
        self.f = tk.Frame(parent, bg=bg)
        tk.Label(self.f, text="Fun actions (right-click a name > Fun)", bg=bg, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 0))
        tk.Label(self.f, text="Each sends one line to the window in front, about that person. {nick} is where the name goes.",
                 bg=bg, fg="#555", wraplength=460, justify="left").pack(anchor="w")
        row = tk.Frame(self.f, bg=bg)
        row.pack(fill="x", pady=4)
        self.lb = tk.Listbox(row, height=9, width=44, exportselection=False)
        self.lb.pack(side="left", fill="both", expand=True)
        self.lb.bind("<Double-1>", lambda e: self.edit())
        b = tk.Frame(row, bg=bg)
        b.pack(side="left", padx=6, anchor="n")
        for text, cmd in (("Add...", self.add), ("Edit...", self.edit), ("Remove", self.remove), ("Up", lambda: self.move(-1)),
                          ("Down", lambda: self.move(1)), ("Defaults", self.reset)):
            ttk.Button(b, text=text, command=cmd, width=10).pack(pady=1)
        self.fill()

    def items(self): return [dict(a) for a in self.items_]

    def fill(self, select=None):
        self.lb.delete(0, "end")
        for a in self.items_: self.lb.insert("end", a["label"])
        if select is not None and self.items_:
            self.lb.selection_set(max(0, min(select, len(self.items_) - 1)))

    def sel(self):
        s = self.lb.curselection()
        return s[0] if s else None

    def add(self):
        r = ActionDialog(self.f, {"label": "", "text": "@[{nick}] "}).result
        if r: self.items_.append(r); self.fill(len(self.items_) - 1)

    def edit(self):
        i = self.sel()
        if i is None: return
        r = ActionDialog(self.f, self.items_[i]).result
        if r: self.items_[i] = r; self.fill(i)

    def remove(self):
        i = self.sel()
        if i is not None: del self.items_[i]; self.fill(i)

    def move(self, d):
        i = self.sel()
        if i is None or not 0 <= i + d < len(self.items_): return
        self.items_[i], self.items_[i + d] = self.items_[i + d], self.items_[i]
        self.fill(i + d)

    def reset(self):
        if messagebox.askyesno("Fun actions", "Put back the original list? Your own actions are removed.", parent=self.f):
            self.items_ = defaults()
            self.fill()


class ActionDialog(tk.Toplevel):
    def __init__(self, parent, action):
        super().__init__(parent)
        self.title("Fun action")
        self.transient(parent.winfo_toplevel())
        self.result = None
        self.v_label, self.v_text = tk.StringVar(value=action.get("label", "")), tk.StringVar(value=action.get("text", ""))
        g = tk.Frame(self)
        g.pack(padx=12, pady=10)
        tk.Label(g, text="In the menu:").grid(row=0, column=0, sticky="w")
        tk.Entry(g, textvariable=self.v_label, width=40).grid(row=0, column=1, sticky="w", pady=2)
        tk.Label(g, text="Message:").grid(row=1, column=0, sticky="w")
        tk.Entry(g, textvariable=self.v_text, width=60).grid(row=1, column=1, sticky="w", pady=2)
        self.info = tk.Label(g, fg="#555", justify="left", wraplength=420)
        self.info.grid(row=2, column=1, sticky="w")
        self.v_text.trace_add("write", lambda *a: self.show())
        self.show()
        b = tk.Frame(self)
        b.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="OK", command=self.ok).pack(side="right", padx=4)
        self.grab_set()
        self.wait_window()

    def show(self):
        t = self.v_text.get()
        n = len(t.replace("{nick}", "x" * NAME_ROOM))
        self.info.config(text=f"Example: {line({'text': t}, 'Bob')}\n{n} / {MAX_CHARS} characters with a {NAME_ROOM}-letter name",
                         fg="#c00000" if n > MAX_CHARS or "{nick}" not in t else "#555")

    def ok(self):
        label, text = self.v_label.get().strip(), self.v_text.get().strip()
        why = problem(label, text)
        if why: return messagebox.showerror("Fun action", why, parent=self)
        self.result = {"label": label[:40], "text": text}
        self.destroy()
