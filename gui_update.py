"""Check for and install new versions of the app from GitHub.

Safety rules (the whole point of this module):
  * Only files on the UPDATABLE allow-list are ever written.  Settings (gui_settings.json), node memory (nodes.db),
    logs/, installed addons (addons/*), backups and everything else the user owns are never touched, and nothing is deleted.
  * Every Python file in the download is syntax-checked BEFORE anything is written; any problem aborts the update.
  * Every file that gets replaced is first copied to backup/update-<old>-to-<new>-<time>/.
  * Files the user may have edited (EDITABLE, e.g. emergency_agent.py with its channel names and regions) are only
    replaced if they still match a version this updater wrote earlier; otherwise the new version is saved next to it
    as <name>.new and the user's file is kept."""
import fnmatch, hashlib, io, json, os, re, shutil, time, zipfile

from gui_addons import BASE_DIR, BRANCH, RAW, REPO, _http_get, vkey

STATE_PATH = os.path.join(BASE_DIR, "update_state.json")
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"

EXACT = {"mcIRC.py", "meshcore_io.py", "emergency_agent.py", "ec_areas.py", "Run_Agent.bat", "Run_GUI.bat", "Run_GUI.sh", "Run_GUI.command", "Make_Shortcut.bat", ".gitattributes", "requirements.txt", "pyproject.toml", "uv.lock", "How to run.txt", "README.md", "LICENSE",
         "VERSION", "CONTRIBUTING.md", "addons-catalog.json", "addons/_example_addon.py"}
GLOBS = ["gui_*.py", "packages/*", "docs/*", "assets/*", "scripts/*", "skins/*"]   # gui_*.py only at the top level; packages/ and docs/ at any depth
EDITABLE = {"emergency_agent.py"}


def local_version(base=BASE_DIR):
    try:
        with open(os.path.join(base, "VERSION"), encoding="utf-8") as f: return f.read().strip() or "0.0.0"
    except OSError: return "0.0.0"


REQUIRED = ("scripts/start_mcirc.ps1", "assets/mcIRC.ico", "assets/mcIRC.png")      # Run_GUI.bat and the window icon need these; see repair()


def _safe_rel(rel):
    """A path that stays inside the install folder: plain names joined by '/', never '..', '.', a drive letter, a backslash or an absolute path."""
    return bool(rel) and all(p not in (".", "..") and re.fullmatch(r"[A-Za-z0-9._ -]+", p) for p in rel.split("/"))


def updatable(rel):
    if not _safe_rel(rel): return False
    if rel in EXACT: return True
    if "/" not in rel: return fnmatch.fnmatch(rel, "gui_*.py")                     # gui_*.py only at the top level
    return any(fnmatch.fnmatch(rel, g) for g in GLOBS if "/" in g)                # packages/, docs/, assets/, scripts/ at any depth


def _sha(data): return hashlib.sha256(data).hexdigest()


def _state(path=STATE_PATH):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {"known": {}}


def check(get=_http_get, raw=RAW):
    """-> {'local','remote','newer'}; raises on network errors (callers decide whether to stay silent)."""
    remote = get(raw + "VERSION").decode("utf-8").strip()
    local = local_version()
    return {"local": local, "remote": remote, "newer": vkey(remote) > vkey(local)}


def missing_required(base=BASE_DIR):
    return [r for r in REQUIRED if not os.path.exists(os.path.join(base, *r.split("/")))]


def repair(get=_http_get, zip_url=ZIP_URL, base=BASE_DIR):
    """Versions up to 1.4.9 could not deliver assets/ and scripts/ (their updater only knew packages/ and docs/), so an app updated that way can be
    missing files that Run_GUI.bat and the window icon need.  This downloads the newest version and writes ONLY those missing files; nothing that
    exists is touched.  Returns the files written."""
    need = missing_required(base)
    if not need: return []
    zf = zipfile.ZipFile(io.BytesIO(get(zip_url, timeout=90)))
    names = [n for n in zf.namelist() if not n.endswith("/")]
    root = names[0].split("/")[0] + "/"
    wrote = []
    for rel in need:
        if root + rel in names and updatable(rel):
            path = os.path.join(base, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "wb") as f: f.write(zf.read(root + rel))
            os.replace(path + ".tmp", path)
            wrote.append(rel)
    return wrote


def apply_update(get=_http_get, zip_url=ZIP_URL, base=BASE_DIR, state_path=STATE_PATH, progress=lambda text: None):
    """Downloads and installs the newest version.  Returns {'old','new','updated','kept','added','backup'}.  Raises ValueError/OSError
    with a readable reason on any problem, in which case nothing has been changed."""
    progress("Downloading the newest version...")
    zf = zipfile.ZipFile(io.BytesIO(get(zip_url, timeout=90)))
    names = [n for n in zf.namelist() if not n.endswith("/")]
    root = names[0].split("/")[0] + "/"
    files = {n[len(root):]: zf.read(n) for n in names if n.startswith(root) and updatable(n[len(root):])}
    if "mcIRC.py" not in files or "VERSION" not in files: raise ValueError("the download doesn't look like mcIRC (no mcIRC.py / VERSION)")
    progress(f"Checking {len(files)} files...")
    for rel, data in files.items():
        if rel.endswith(".py"):
            try: compile(data, rel, "exec")
            except SyntaxError as e: raise ValueError(f"{rel} in the download has a syntax error ({e}); nothing was changed")
    old, new = local_version(base), files["VERSION"].decode("utf-8").strip()
    state = _state(state_path)
    known = state.setdefault("known", {})
    backup = os.path.join(base, "backup", f"update-{old}-to-{new}-{time.strftime('%Y%m%d-%H%M%S')}")
    result = {"old": old, "new": new, "updated": [], "kept": [], "added": [], "backup": backup}
    for rel, data in sorted(files.items()):
        path = os.path.join(base, *rel.split("/"))
        sha = _sha(data)
        if os.path.exists(path):
            with open(path, "rb") as f: cur = f.read()
            if cur == data: known.setdefault(rel, []).append(sha); continue
            if rel in EDITABLE and _sha(cur) not in known.get(rel, []):
                with open(path + ".new", "wb") as f: f.write(data)     # the user's file wins; the new one waits beside it
                known.setdefault(rel, []).append(sha)                   # if they adopt it, it counts as untouched next time
                result["kept"].append(rel)
                continue
            dest = os.path.join(backup, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(path, dest)
            result["updated"].append(rel)
        else: result["added"].append(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f: f.write(data)
        os.replace(tmp, path)
        known.setdefault(rel, []).append(sha)
    state["version"] = new
    with open(state_path, "w", encoding="utf-8") as f: json.dump(state, f, indent=2)
    progress("Done.")
    return result
