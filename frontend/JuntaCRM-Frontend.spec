# -*- mode: python ; coding: utf-8 -*-

import re
from importlib import metadata
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

datas = []
binaries = []
hiddenimports = []
spec_dir = Path(globals().get("SPECPATH", Path.cwd()))


def _normalize_dist_name(name):
    return re.sub(r"[-_.]+", "-", (name or "").strip().lower())


def _extract_req_name(requirement_line):
    # Works for entries like: "python-jose[cryptography]>=3.3.0; python_version >= '3.9'"
    match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)", requirement_line or "")
    if not match:
        return None
    return match.group(1)


def _extend_unique(target, items):
    for item in items:
        if item not in target:
            target.append(item)


def _collect_package(package_name):
    # Broad collection to avoid runtime failures from dynamic imports.
    try:
        d, b, h = collect_all(package_name)
        _extend_unique(datas, d)
        _extend_unique(binaries, b)
        _extend_unique(hiddenimports, h)
    except Exception:
        pass

    try:
        _extend_unique(datas, collect_data_files(package_name))
    except Exception:
        pass

    try:
        _extend_unique(binaries, collect_dynamic_libs(package_name))
    except Exception:
        pass

    try:
        _extend_unique(hiddenimports, collect_submodules(package_name))
    except Exception:
        pass


def _dist_to_modules(dist):
    modules = set()
    try:
        top_level = dist.read_text("top_level.txt")
        if top_level:
            modules.update(
                line.strip()
                for line in top_level.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
    except Exception:
        pass

    # Fallback when top_level.txt is missing.
    if not modules:
        dist_name = dist.metadata.get("Name") or getattr(dist, "name", "")
        if dist_name:
            modules.add(dist_name.replace("-", "_"))

    return modules


def _load_root_distributions():
    requirements_file = spec_dir / "requirements.txt"
    root_dist_names = set()

    if requirements_file.exists():
        for raw_line in requirements_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            req_name = _extract_req_name(line)
            if req_name:
                root_dist_names.add(_normalize_dist_name(req_name))

    # Safety fallback in case requirements.txt is changed unexpectedly.
    root_dist_names.update(
        _normalize_dist_name(name)
        for name in (
            "flet",
            "httpx",
            "pydantic",
            "python-jose",
            "reportlab",
            "pywin32",
        )
    )

    return root_dist_names


def _collect_requirements_tree():
    installed = {}
    for dist in metadata.distributions():
        dist_name = dist.metadata.get("Name") or getattr(dist, "name", "")
        if dist_name:
            installed[_normalize_dist_name(dist_name)] = dist

    to_visit = list(_load_root_distributions())
    seen = set()

    while to_visit:
        dist_key = to_visit.pop()
        if dist_key in seen:
            continue
        seen.add(dist_key)

        dist = installed.get(dist_key)
        if not dist:
            continue

        for module_name in _dist_to_modules(dist):
            _collect_package(module_name)

        for dep in dist.requires or []:
            dep_name = _extract_req_name(dep)
            if dep_name:
                to_visit.append(_normalize_dist_name(dep_name))


_collect_requirements_tree()

# Explicit modules often loaded dynamically in windows runtime.
for pkg in ("pythoncom", "pywintypes"):
    _collect_package(pkg)

# Local project packages.
for pkg in ("components", "services", "services.pdf_generation", "views", "utils", "config"):
    _collect_package(pkg)

# Explicit app assets required at runtime (window icon / branding).
assets_dir = spec_dir / "assets"
for asset_name in ("junta.ico", "junta.png", "saneo.png", "saneo-icon.png"):
    asset_path = assets_dir / asset_name
    if asset_path.exists():
        datas.append((str(asset_path), "assets"))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
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
    name='junta',
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
    name='junta',
)
