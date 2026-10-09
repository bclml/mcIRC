"""Daily (GitHub Actions, .github/workflows/upstream-check.yml): look for new versions of the outside projects the addon catalog follows,
and open one pull request per addon that moves its pin to the new version.  Merging the pull request is the maintainer's approval -
until then nobody gets the new code (see gui_sources.py).

  - an outside addon ("repo" + "ref" in addons-catalog.json): the pin, its release and its version (read from the repo's addon.json)
  - an addon that builds on an outside project ("upstream" in addons-catalog.json and in the package's upstream.json): the pin, plus a
    patch version bump of the package so installed copies are offered the update

Run locally with --dry-run to see what it would do.  Needs GH_TOKEN (the workflow's token) and git for the real thing."""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "addons-catalog.json")
LABEL = "upstream-update"
API = "https://api.github.com"


def api(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "mcIRC-upstream-check", "Accept": "application/vnd.github+json",
                                                      **({"Authorization": f"Bearer {os.environ['GH_TOKEN']}"} if os.environ.get("GH_TOKEN") else {})})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read().decode("utf-8"))


def raw(repo, ref, path):
    req = urllib.request.Request(f"https://raw.githubusercontent.com/{repo}/{ref}/{path}", headers={"User-Agent": "mcIRC-upstream-check"})
    with urllib.request.urlopen(req, timeout=30) as r: return r.read().decode("utf-8")


def latest(repo):
    """{'release', 'ref'} of the newest release (or of the default branch when the repo publishes none)."""
    try:
        tag = api(f"/repos/{repo}/releases/latest").get("tag_name", "")
        return {"release": tag, "ref": api(f"/repos/{repo}/commits/{tag}")["sha"]}
    except urllib.error.HTTPError as e:
        if e.code != 404: raise
    return {"release": "", "ref": api(f"/repos/{repo}/commits?per_page=1")[0]["sha"]}


def bump(version):
    parts = [int(x) for x in re.findall(r"\d+", version)[:3]] + [0, 0, 0]
    return f"{parts[0]}.{parts[1]}.{parts[2] + 1}"


def sh(*args, check=True):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check).stdout.strip()


def plan():
    """[(entry name, repo, old pin, new pin, release, what changes)] for every followed project with something newer."""
    with open(CATALOG, encoding="utf-8") as f: cat = json.load(f)
    out = []
    for e in cat["addons"]:
        if e.get("repo"): repo, old, kind = e["repo"], e.get("ref", ""), "outside"
        elif (e.get("upstream") or {}).get("repo"): repo, old, kind = e["upstream"]["repo"], e["upstream"].get("ref", ""), "upstream"
        else: continue
        new = latest(repo)
        if new["ref"] and new["ref"] != old: out.append((e["name"], repo, old, new["ref"], new["release"], kind))
    return out


def apply(name, repo, new_ref, release, kind):
    """Moves the pin in the catalog (and the package) - the change the pull request proposes."""
    with open(CATALOG, encoding="utf-8") as f: text = f.read()
    cat = json.loads(text)
    e = next(x for x in cat["addons"] if x["name"] == name)
    if kind == "outside":
        manifest = json.loads(raw(repo, new_ref, ((e.get("path") or "").strip("/") + "/addon.json").lstrip("/")))
        e["ref"], e["release"], e["version"] = new_ref, release, manifest.get("version", e.get("version"))
    else:
        e["upstream"].update(ref=new_ref, release=release)
        pkg = os.path.join(ROOT, e["path"])
        up_path = os.path.join(pkg, "upstream.json")
        with open(up_path, encoding="utf-8") as f: up = json.load(f)
        up.update(ref=new_ref, release=release)
        with open(up_path, "w", encoding="utf-8", newline="\n") as f: f.write(json.dumps(up, indent=2) + "\n")
        mpath = os.path.join(pkg, "addon.json")
        with open(mpath, encoding="utf-8") as f: manifest = json.load(f)
        old_v = manifest["version"]
        manifest["version"] = e["version"] = bump(old_v)
        with open(mpath, "w", encoding="utf-8", newline="\n") as f: f.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        main = os.path.join(pkg, name + ".py")
        with open(main, encoding="utf-8") as f: src = f.read()
        with open(main, "w", encoding="utf-8", newline="\n") as f: f.write(src.replace(f'version = "{old_v}"', f'version = "{manifest["version"]}"', 1))
    with open(CATALOG, "w", encoding="utf-8", newline="\n") as f: f.write(json.dumps(cat, indent=2, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    todo = plan()
    if not todo: return print("Every followed project is at its reviewed version.")
    if not args.dry_run:
        sh("gh", "label", "create", LABEL, "--color", "fbca04", "--description", "A followed outside project has a new version to review", "--force", check=False)
        open_branches = set(sh("gh", "pr", "list", "--label", LABEL, "--state", "open", "--json", "headRefName", "--jq", ".[].headRefName", check=False).split())
    for name, repo, old, new, release, kind in todo:
        what = release or new[:7]
        branch = f"upstream/{name}-{re.sub(r'[^A-Za-z0-9._-]', '-', what)}"
        print(f"{name}: {repo} {old[:7] or '(none)'} -> {what}")
        if args.dry_run or branch in open_branches: continue
        sh("git", "checkout", "-B", branch, "origin/master")
        apply(name, repo, new, release, kind)
        sh("git", "commit", "-am", f"Review: {name} - {repo} {what}")
        sh("git", "push", "-f", "origin", branch)
        body = (f"**{repo}** has a new version: **{what}**.  Merging this moves the reviewed pin of **{name}** to it, and everyone gets it with "
                f"Help > Check for updates.  Until then nobody gets the new code.\n\n"
                f"**What changed upstream:** https://github.com/{repo}/compare/{old or 'HEAD~10'}...{new}\n\n"
                "Before merging, check (or ask Claude to review the update):\n"
                "- [ ] what it sends over the mesh: only when asked? rate limited?\n"
                "- [ ] what it contacts on the internet, and what it sends there\n"
                "- [ ] files, passwords or keys it touches outside its own folder\n"
                "- [ ] the tests pass on this pull request\n")
        sh("gh", "pr", "create", "--base", "master", "--head", branch, "--label", LABEL, "--title", f"Review: {name} - {repo} {what}", "--body", body)
        sh("git", "checkout", "master")


if __name__ == "__main__":
    sys.exit(main())
