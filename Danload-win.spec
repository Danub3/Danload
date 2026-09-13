# -*- mode: python ; coding: utf-8 -*-
# Danload Windows PyInstaller spec
# Usage: pyinstaller Danload-win.spec --noconfirm
import os
import re
import shutil
import customtkinter
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

with open('app.py', encoding='utf-8') as _f:
    _m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _f.read())
APP_VERSION = _m.group(1)

ctk_path = os.path.dirname(customtkinter.__file__)
deno_path = shutil.which('deno.exe') or shutil.which('deno')
if not deno_path:
    raise SystemExit('Deno 2.3+ is required to build Danload with YouTube support')

hiddenimports = ['customtkinter', 'yt_dlp', 'yt_dlp.extractor']
hiddenimports += collect_submodules('yt_dlp_ejs')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[
        ('ffmpeg.exe', '.'),
        ('ffprobe.exe', '.'),
        (deno_path, '.'),
    ],
    datas=[
        (ctk_path, 'customtkinter'),
    ] + collect_data_files('yt_dlp_ejs'),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Danload',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    version='assets/windows_version_info.txt',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Danload',
)
