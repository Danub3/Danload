# -*- mode: python ; coding: utf-8 -*-
import re
with open('app.py', encoding='utf-8') as _f:
    _m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _f.read())
APP_VERSION = _m.group(1)

ctk_path = '/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/site-packages/customtkinter'

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[
        ('ffmpeg', '.'),
        ('ffprobe', '.'),
    ],
    datas=[
        (ctk_path, 'customtkinter'),
    ],
    hiddenimports=['customtkinter', 'yt_dlp', 'yt_dlp.extractor'],
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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Danload',
)
app = BUNDLE(
    coll,
    name='Danload.app',
    icon='egg.icns',
    bundle_identifier='com.daniel.danload',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': APP_VERSION,
        'CFBundleName': 'Danload',
        'CFBundleDisplayName': 'Danload',
    },
)
