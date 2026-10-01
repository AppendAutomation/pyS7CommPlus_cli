# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for pyS7commplus_cli.

Builds a one-file standalone executable.  Bundles:
  * the vendored pyS7commplus library and the vendored (Python-3.8 back-ported)
    s7commplus V3 backend, both sitting next to this spec;
  * the backend's runtime data files - the Family-0 .bin tables and the
    zlib_dicts/*.xml compression dictionaries, which it loads from disk via
    __file__, so they must keep their package-relative paths in the bundle;
  * the cryptography package (its binary extension + data).

Build (Windows 7, Python 3.8):
    python -m PyInstaller --clean -y pyS7commplus_cli.spec
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
here = os.path.abspath(os.getcwd())

# Backend runtime data files, kept at their package-relative destinations.
datas = []
for sub in ("session_auth/family0/_generated/data", "zlib_dicts"):
    d = os.path.join("s7commplus", *sub.split("/"))
    for fn in os.listdir(os.path.join(here, d)):
        if fn.endswith((".bin", ".xml")):
            datas.append((os.path.join(d, fn), d))

# cryptography ships a compiled extension + metadata.
cz_datas, cz_binaries, cz_hidden = collect_all("cryptography")
datas += cz_datas

hiddenimports = cz_hidden + collect_submodules("s7commplus") + collect_submodules("pyS7commplus")

a = Analysis(
    ["pyS7commplus_cli.py"],
    pathex=[here],
    binaries=cz_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="pyS7commplus_cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
)
