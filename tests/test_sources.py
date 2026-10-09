import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Addons from other people's GitHub repos: pinned to the reviewed commit, newer upstream versions shown as 'waiting for review', the
maintainer's list of reviews, and the daily script that opens the review pull requests.  Nothing is downloaded (fake GitHub)."""
import importlib.util, json, shutil, tempfile
from unittest import mock

import gui_addons as ga
import gui_sources as gs

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

SHA_OLD, SHA_NEW = "a" * 40, "b" * 40
ok("an addon of this project comes from this project", ga.source_raw({"name": "x", "path": "packages/x"}) == ga.RAW)
ok("an outside addon comes from its own repo at the reviewed commit",
   ga.source_raw({"name": "x", "repo": "alice/mc-addon", "ref": SHA_OLD}) == f"https://raw.githubusercontent.com/alice/mc-addon/{SHA_OLD}/")
for bad in ({"repo": "alice/mc-addon", "ref": "main"}, {"repo": "alice/mc-addon"}, {"repo": "../etc", "ref": SHA_OLD}):
    try: ga.source_raw(dict(bad, name="x")); refused = False
    except ValueError: refused = True
    ok(f"...never a branch, a missing pin or a strange repo name: {bad}", refused)

# installing from an outside repo (fake GitHub)
manifest = {"name": "hello_mesh", "title": "Hello", "version": "1.0.0", "files": {"hello_mesh.py": "addons/hello_mesh.py"}}
code = b"from gui_addons import AddonBase\nclass Addon(AddonBase):\n    title = 'Hello'\n"
asked = []
def fake_get(url, timeout=20):
    asked.append(url)
    if url.endswith("addon.json"): return json.dumps(manifest).encode()
    return code
entry = {"name": "hello_mesh", "version": "1.0.0", "repo": "alice/mc-addon", "ref": SHA_OLD, "path": ""}
with mock.patch.object(ga, "install_files", lambda m, files, origin: {"name": m["name"], "files": sorted(files), "origin": origin}):
    r = ga.install_from_catalog(entry, get=fake_get)
ok("it is downloaded from that repo at the pinned commit", all(u.startswith(f"https://raw.githubusercontent.com/alice/mc-addon/{SHA_OLD}/") for u in asked)
   and r["files"] == ["addons/hello_mesh.py"], (asked, r))
for wrong, why in (({"version": "1.1.0"}, "a different version"), ({"name": "other"}, "another addon")):
    m2 = dict(manifest, **wrong)
    try:
        with mock.patch.object(ga, "install_files", lambda *a: None): ga.install_from_catalog(entry, get=lambda u, timeout=20: json.dumps(m2).encode())
        refused = False
    except ValueError: refused = True
    ok(f"...refused when the pinned commit holds {why} than the catalog says", refused)

# 'waiting for review'
API = {f"{gs.API}/repos/alice/mc-addon/releases/latest": {"tag_name": "v1.1.0"},
       f"{gs.API}/repos/alice/mc-addon/commits/v1.1.0": {"sha": SHA_NEW}}
fake_api = lambda url, timeout=15: json.dumps(API[url]).encode()
ok("a newer upstream release is shown as waiting for review", gs.upstream_note(dict(entry, release="v1.0.0"), get=fake_api) == "v1.1.0 upstream (waiting for review)")
ok("...nothing when the pin is the newest", gs.upstream_note(dict(entry, ref=SHA_NEW, release="v1.1.0"), get=fake_api) == "")
ok("an addon that builds on an outside project follows that project", gs.watched({"name": "y", "upstream": {"repo": "bob/tool", "ref": SHA_OLD}}) == ("bob/tool", SHA_OLD, ""))
ok("our own addons follow nothing", gs.watched({"name": "z", "path": "packages/z"}) is None)
def no_releases(url, timeout=15):
    if url.endswith("/releases/latest"): raise OSError("HTTP Error 404: Not Found")
    return json.dumps([{"sha": SHA_NEW}]).encode()
ok("a repo without releases is followed by its newest commit", gs.latest("bob/tool", get=no_releases) == {"release": "", "ref": SHA_NEW})

# the maintainer's copy
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, ".git"))
open(os.path.join(tmp, ".git", "config"), "w").write('[remote "origin"]\n\turl = https://github.com/bclml/mcIRC.git\n')
ok("the maintainer's git checkout is recognised", gs.is_maintainer_copy(tmp) and not gs.is_maintainer_copy(tempfile.mkdtemp()))
prs = [{"title": "Review: hello_mesh - alice/mc-addon v1.1.0", "html_url": "u1", "labels": [{"name": "upstream-update"}]},
       {"title": "Some other PR", "html_url": "u2", "labels": []}]
ok("only the review pull requests are listed", gs.pending_reviews(get=lambda u, timeout=15: json.dumps(prs).encode()) == [("Review: hello_mesh - alice/mc-addon v1.1.0", "u1")])

# the daily script: what it proposes
spec = importlib.util.spec_from_file_location("upstream_check", os.path.join(ROOT, "scripts", "upstream_check.py"))
uc = importlib.util.module_from_spec(spec); spec.loader.exec_module(uc)
work = tempfile.mkdtemp()
os.makedirs(os.path.join(work, "packages", "bridge"))
cat = {"addons": [dict(entry, release="v1.0.0"), {"name": "bridge", "version": "1.0.0", "path": "packages/bridge", "upstream": {"repo": "bob/tool", "ref": SHA_OLD, "release": "v2.0"}},
                  {"name": "plain", "version": "1.0.0", "path": "packages/plain"}]}
open(os.path.join(work, "addons-catalog.json"), "w").write(json.dumps(cat))
open(os.path.join(work, "packages", "bridge", "upstream.json"), "w").write(json.dumps({"repo": "bob/tool", "ref": SHA_OLD, "release": "v2.0"}))
open(os.path.join(work, "packages", "bridge", "addon.json"), "w").write(json.dumps({"name": "bridge", "version": "1.0.0", "files": {}}))
open(os.path.join(work, "packages", "bridge", "bridge.py"), "w").write('class Addon:\n    version = "1.0.0"\n')
news = {"alice/mc-addon": {"release": "v1.1.0", "ref": SHA_NEW}, "bob/tool": {"release": "v2.1", "ref": "c" * 40}}
with mock.patch.object(uc, "ROOT", work), mock.patch.object(uc, "CATALOG", os.path.join(work, "addons-catalog.json")), \
     mock.patch.object(uc, "latest", lambda repo: news[repo]), mock.patch.object(uc, "raw", lambda repo, ref, path: json.dumps(dict(manifest, version="1.1.0"))):
    todo = uc.plan()
    ok("the daily check finds both followed projects with something newer (and ignores our own addons)",
       [(t[0], t[4], t[5]) for t in todo] == [("hello_mesh", "v1.1.0", "outside"), ("bridge", "v2.1", "upstream")], todo)
    for name, repo, old, new, release, kind in todo: uc.apply(name, repo, new, release, kind)
    after = {e["name"]: e for e in json.load(open(os.path.join(work, "addons-catalog.json")))["addons"]}
    ok("...the review moves an outside addon's pin, release and version", (after["hello_mesh"]["ref"], after["hello_mesh"]["release"], after["hello_mesh"]["version"]) == (SHA_NEW, "v1.1.0", "1.1.0"))
    up = json.load(open(os.path.join(work, "packages", "bridge", "upstream.json")))
    ok("...and for an addon built on it: the pin in the package, and a new version so installed copies update",
       up["ref"] == "c" * 40 and after["bridge"]["version"] == "1.0.1" and 'version = "1.0.1"' in open(os.path.join(work, "packages", "bridge", "bridge.py")).read())
shutil.rmtree(work, ignore_errors=True); shutil.rmtree(tmp, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
