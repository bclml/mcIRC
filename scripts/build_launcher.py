"""Builds mcIRC.exe (Windows): a small windowless launcher that starts mcIRC.py, with the mcIRC logo as its icon.

    python scripts/build_launcher.py

No compiler needed.  It uses the same trick pip uses for console scripts: a ready-made launcher stub (pip's vendored distlib `w64.exe`, Python Software
Foundation license), then the interpreter line `#!pythonw.exe` (found on PATH, like Run_GUI.bat does) and a zipped __main__.py
(scripts/launcher/launcher_main.py).  The icon (assets/mcIRC.ico) and version information are written into the stub's resources first, because changing
resources afterwards would drop the appended data.  Windows only."""
import ctypes
import io
import os
import struct
import sys
import zipfile
from ctypes import wintypes

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "mcIRC.exe")
ICON = os.path.join(BASE, "assets", "mcIRC.ico")
MAIN = os.path.join(BASE, "scripts", "launcher", "launcher_main.py")
INTERPRETER_LINE = b"#!pythonw.exe\n"
RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16
LANG = 0        # language-neutral, like the stub's own resources: ours must replace them, not sit beside them
STUB_GROUP_ICON, STUB_VERSION = 101, 102      # where the stub keeps its own (Python) icon group and version info


LAUNCHER_VERSION = "1.0.0"      # the exe only starts mcIRC.py, so it does not change with every mcIRC release (Help > About shows the program's version)


def _node(key, value=b"", children=(), text=False):
    """One VS_VERSIONINFO node: length, value length, type, key, padding, value, then each child on a 4-byte boundary."""
    data = bytes(1) * 6 + (key + chr(0)).encode("utf-16-le")
    data += bytes(1) * (-len(data) % 4) + value
    for child in children:
        data += bytes(1) * (-len(data) % 4) + child
    return struct.pack("<HHH", len(data), len(value) // 2 if text else len(value), 1 if text else 0) + data[6:]


def version_blob(version, strings):
    nums = [int(x) for x in (version.split(".") + ["0", "0", "0", "0"])[:4]]
    ms, ls = (nums[0] << 16) | nums[1], (nums[2] << 16) | nums[3]
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x10000, ms, ls, ms, ls, 0x3F, 0, 0x40004, 1, 0, 0, 0)
    table = _node("040904b0", children=[_node(k, (v + chr(0)).encode("utf-16-le"), text=True) for k, v in strings.items()])
    return _node("VS_VERSION_INFO", fixed, [_node("StringFileInfo", children=[table]),
                                            _node("VarFileInfo", children=[_node("Translation", struct.pack("<HH", 0x0409, 0x04B0))])])


def write_resources(exe, ico_path, version, strings):
    """The stub has icon frames 1-7, icon group 101 and version info 102 (all language-neutral); ours are written into the same slots, so they replace them."""
    k32 = ctypes.windll.kernel32
    k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
    k32.UpdateResourceW.restype = wintypes.BOOL
    k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    ico = open(ico_path, "rb").read()
    _, kind, count = struct.unpack_from("<HHH", ico, 0)
    assert kind == 1 and count, "not an .ico file"
    h = k32.BeginUpdateResourceW(exe, False)
    if not h: raise ctypes.WinError()
    def put(rtype, rname, data):
        buf = ctypes.create_string_buffer(data, len(data))
        if not k32.UpdateResourceW(h, rtype, rname, LANG, buf, len(data)): raise ctypes.WinError()
    group = struct.pack("<HHH", 0, 1, count)
    for i in range(count):
        w, hgt, colors, _r, planes, bits, size, offset = struct.unpack_from("<BBBBHHII", ico, 6 + 16 * i)
        put(RT_ICON, i + 1, ico[offset:offset + size])
        group += struct.pack("<BBBBHHIH", w, hgt, colors, 0, planes, bits, size, i + 1)
    put(RT_GROUP_ICON, STUB_GROUP_ICON, group)
    k32.UpdateResourceW(h, RT_VERSION, STUB_VERSION, LANG, None, 0)       # the stub's own (unused) version block
    put(RT_VERSION, 1, version_blob(version, strings))                    # Windows reads version info from resource 1
    if not k32.EndUpdateResourceW(h, False): raise ctypes.WinError()


def main():
    import pip._vendor.distlib as distlib
    stub = os.path.join(os.path.dirname(distlib.__file__), "w64.exe")          # windowed (no console) launcher, 64-bit
    tmp = OUT + ".tmp"
    with open(stub, "rb") as f, open(tmp, "wb") as g: g.write(f.read())
    version = LAUNCHER_VERSION
    write_resources(tmp, ICON, version, {
        "CompanyName": "bclml", "FileDescription": "mcIRC launcher (mIRC-style chat client for MeshCore)", "FileVersion": version,
        "InternalName": "mcIRC", "LegalCopyright": "MIT License - https://github.com/bclml/mcIRC", "OriginalFilename": "mcIRC.exe",
        "ProductName": "mcIRC", "ProductVersion": version})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(MAIN, "__main__.py")
    with open(tmp, "ab") as f: f.write(INTERPRETER_LINE + buf.getvalue())
    os.replace(tmp, OUT)
    print(f"wrote {OUT} ({os.path.getsize(OUT) // 1024} KB), launcher version {version}")


if __name__ == "__main__":
    if os.name != "nt": sys.exit("mcIRC.exe can only be built on Windows.")
    main()
