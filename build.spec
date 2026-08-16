# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Zombee Product Manager Desktop.

Build locally with:  pyinstaller build.spec
(Produces a Windows .exe only when run ON Windows -- see
.github/workflows/build-windows.yml for building via GitHub Actions instead,
which needs nothing installed locally.)
"""

import sys
from pathlib import Path

block_cipher = None

app_root = Path(SPECPATH)

a = Analysis(
    ['main.py'],
    pathex=[str(app_root)],
    binaries=[],
    datas=[
        (str(app_root / 'app' / 'locales'), 'app/locales'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='ZombeeProductManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_root / 'app' / 'assets' / 'icon.ico') if (app_root / 'app' / 'assets' / 'icon.ico').exists() else None,
)
