"""The program inside mcIRC.exe: start mcIRC.py from the folder the exe lives in.

Looks for the project's own virtual environment first (.venv, as created by `uv sync` / `uv run`), otherwise runs with the Python that started it.
If mcIRC cannot start, a message box says why (a windowless program has no console to print to)."""
import os
import sys
import traceback


def _message(text, title="mcIRC"):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        pass


def main():
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    script = os.path.join(here, "mcIRC.py")
    if not os.path.isfile(script):
        return _message(f"mcIRC.py was not found next to mcIRC.exe.\n\nKeep mcIRC.exe inside the mcIRC folder:\n{here}")
    venv = os.path.join(here, ".venv", "Scripts", "pythonw.exe")
    if os.path.isfile(venv) and os.path.normcase(sys.executable) != os.path.normcase(venv):
        import subprocess
        subprocess.Popen([venv, script] + sys.argv[1:], cwd=here)         # the project's own environment has the packages
        return
    os.chdir(here)
    sys.path.insert(0, here)
    sys.argv = [script] + sys.argv[1:]
    import runpy
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        if isinstance(e.code, str): _message(e.code)       # e.g. "mcIRC needs Tk..."
        raise
    except BaseException:
        err = traceback.format_exc()
        hint = ""
        if "ModuleNotFoundError" in err or "ImportError" in err:
            hint = "\n\nA Python package is missing. Open a command prompt in the mcIRC folder and run:\n    pip install -r requirements.txt"
        _message("mcIRC could not start.\n\n" + err[-1200:] + hint)


main()
