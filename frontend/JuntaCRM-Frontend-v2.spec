# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

spec_dir = Path(globals().get("SPECPATH", Path.cwd()))
datas = []
assets_dir = spec_dir / "assets"
for asset_name in ("junta.ico", "junta.png", "saneo.png", "saneo-icon.png"):
    asset_path = assets_dir / asset_name
    if asset_path.exists():
        datas.append((str(asset_path), "assets"))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    name='junta-v2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(spec_dir / "assets" / "junta.ico"),
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
    upx=True,
    upx_exclude=[],
    name='junta-v2',
)
