"""Addons from other people's GitHub repos, and the upstream projects some of our addons build on.

A catalog entry is pinned to the exact commit the maintainers reviewed: an outside addon by "repo" + "ref" (gui_addons.source_raw), an
addon that builds on an outside project by "upstream": {"repo", "ref", "release"}.  When that repo publishes something newer, nobody gets
it until the maintainers have reviewed it: a daily GitHub action (scripts/upstream_check.py) opens a pull request that moves the pin, and
merging it is the approval.  Meanwhile the catalog shows "1.2.0 upstream (waiting for review)", and the maintainer's own copy of mcIRC
lists the reviews waiting in its Status window."""
import json
import os

from gui_addons import BASE_DIR, REPO, _http_get

API = "https://api.github.com"
REVIEW_LABEL = "upstream-update"


def watched(entry):
    """(repo, reviewed ref, reviewed release) a catalog entry follows, or None."""
    if entry.get("repo"): return entry["repo"], entry.get("ref", ""), entry.get("release", "")
    up = entry.get("upstream") or {}
    return (up["repo"], up.get("ref", ""), up.get("release", "")) if up.get("repo") else None


def _json(url, get=_http_get):
    return json.loads(get(url, timeout=15).decode("utf-8"))


def latest(repo, get=_http_get):
    """{'release': tag or '', 'ref': commit} of the newest published release - or of the default branch for a repo without releases."""
    try:
        rel = _json(f"{API}/repos/{repo}/releases/latest", get)
        tag = rel.get("tag_name", "")
        ref = _json(f"{API}/repos/{repo}/commits/{tag}", get).get("sha", "")
        return {"release": tag, "ref": ref}
    except Exception as e:
        if "404" not in str(e): raise
    head = _json(f"{API}/repos/{repo}/commits?per_page=1", get)
    return {"release": "", "ref": head[0]["sha"] if head else ""}


def upstream_note(entry, get=_http_get):
    """'v1.2.0 upstream (waiting for review)' when the followed repo has something newer than the reviewed pin, else ''."""
    w = watched(entry)
    if not w: return ""
    repo, ref, release = w
    try: new = latest(repo, get)
    except Exception: return ""
    if not new["ref"] or new["ref"] == ref or (release and new["release"] == release): return ""
    return f"{new['release'] or new['ref'][:7]} upstream (waiting for review)"


def is_maintainer_copy(base=BASE_DIR):
    """True when this mcIRC is a git checkout of the project itself - the maintainer's copy (only there are reviews shown)."""
    try:
        with open(os.path.join(base, ".git", "config"), encoding="utf-8") as f: return REPO.lower() in f.read().lower()
    except OSError:
        return False


def pending_reviews(get=_http_get):
    """Open 'upstream-update' pull requests: [(title, url)]."""
    prs = _json(f"{API}/repos/{REPO}/pulls?state=open&per_page=50", get)
    return [(p.get("title", ""), p.get("html_url", "")) for p in prs if any(l.get("name") == REVIEW_LABEL for l in p.get("labels", []))]
