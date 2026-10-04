"""Runs every tests/test_*.py in its own process and prints a summary.   python tests/run_tests.py [name ...]

A test passes when it exits with code 0, prints no "[FAIL]" line and ends with PASS / ALL PASSED.  Tests that cannot run on this system are skipped, not failed:
the launcher tests are Windows only, and the GUI tests need a display (on Linux CI: `xvfb-run -a python tests/run_tests.py`).
The tests use fake radios only; they never touch a real node, the real settings, or the bot's real log."""
import os
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # test output contains emoji; Windows consoles often are not UTF-8

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WINDOWS_ONLY = {"test_cancel", "test_launcher"}                       # use .cmd stand-ins, tasklist, PowerShell, WinForms
NO_DISPLAY_OK = {"test_updater", "test_addon_helpers", "test_weather_restart", "test_diag", "test_portable", "test_install_update", "test_146", "test_health"}     # (the GUI ones are skipped without a display)


def has_display():
    if os.name == "nt" or sys.platform == "darwin": return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def run_one(name):
    t0 = time.time()
    env = dict(os.environ, MCIRC_NO_LOG_FILE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, name + ".py")], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, env=env, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return False, "timed out after 10 minutes", time.time() - t0
    out = p.stdout or ""                                                  # (stderr may hold deliberate tracebacks; it is shown only when a test fails)
    lines = [l for l in out.splitlines() if l.strip()]
    if p.returncode != 0 and not lines: lines = [l for l in (p.stderr or "").splitlines() if l.strip()]
    failed = [l for l in lines if l.startswith("[FAIL]")]
    passed = bool(lines) and (lines[-1].strip() in ("PASS", "ALL PASSED") or lines[-1].strip().endswith("ALL PASSED")) and not failed and p.returncode == 0
    return passed, "\n".join(failed[:8] + ((lines[-12:] + (p.stderr or "").splitlines()[-25:]) if not passed and not failed else [])), time.time() - t0


def main(argv):
    names = [os.path.splitext(f)[0] for f in sorted(os.listdir(HERE)) if f.startswith("test_") and f.endswith(".py")]
    if argv: names = [n for n in names if n in argv or n + ".py" in argv]
    results, skipped = [], []
    for n in names:
        if n in WINDOWS_ONLY and os.name != "nt": skipped.append((n, "Windows only")); continue
        if n not in NO_DISPLAY_OK and not has_display(): skipped.append((n, "needs a display (use xvfb-run)")); continue
        ok, detail, secs = run_one(n)
        results.append((n, ok))
        print(f"{'PASS' if ok else 'FAIL'}  {n}  ({secs:.0f}s)")
        if not ok: print("      " + detail.replace("\n", "\n      "))
        sys.stdout.flush()
    # the addon validators
    for pkg in sorted(os.listdir(os.path.join(ROOT, "packages"))):
        d = os.path.join(ROOT, "packages", pkg)
        if not os.path.isdir(d) or not os.path.exists(os.path.join(d, "addon.json")): continue
        r = subprocess.run([sys.executable, os.path.join(ROOT, "packages", "check_package.py"), d], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
                           env=dict(os.environ, MCIRC_NO_LOG_FILE="1"))
        ok = r.returncode == 0
        results.append((f"check_package {pkg}", ok))
        print(f"{'PASS' if ok else 'FAIL'}  check_package {pkg}")
        if not ok: print("      " + (r.stdout + r.stderr)[-600:].replace("\n", "\n      "))
    for n, why in skipped: print(f"SKIP  {n}  ({why})")
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)} passed, {len(bad)} failed, {len(skipped)} skipped")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
