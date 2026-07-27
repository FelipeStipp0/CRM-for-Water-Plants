# -*- mode: python ; coding: utf-8 -*-

import re
import sys
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
            # Pula dependencia OPCIONAL (`; extra == "..."`). Sem isto o walk trata
            # extra como obrigatoria e arrasta a pilha cientifica inteira: flet
            # declara numpy; pandas declara matplotlib e numba (-> llvmlite); daí
            # vem geopandas, PyKrige e OpenCV. Nada disso e importado pelo app,
            # e sozinho respondia por ~280 MB do bundle.
            if "extra ==" in dep:
                continue
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

# Pipeline de emissao (backend puro). Em dev o sifen_executor acha via sys.path
# porque `backend/` fica ao lado de `frontend/`; no app instalado nao existe esse
# vizinho, entao precisa vir bundlado — senao o PC se registra como dispositivo
# mas nunca consegue emitir (ExecutorIndisponivel).
_backend_dir = spec_dir.parent / "backend"
if _backend_dir.is_dir():
    if str(_backend_dir) not in sys.path:
        sys.path.insert(0, str(_backend_dir))
    for pkg in ("app.services.sifen", "app.models", "app.utils"):
        _collect_package(pkg)

# Explicit app assets required at runtime (window icon / branding).
assets_dir = spec_dir / "assets"
for asset_name in ("junta.ico", "junta.png", "saneo.png", "saneo-icon.png"):
    asset_path = assets_dir / asset_name
    if asset_path.exists():
        datas.append((str(asset_path), "assets"))

# --- nao distribuir codigo-fonte -------------------------------------------
# collect_all/collect_data_files copiam os .py dos pacotes como DADOS, alem de
# compila-los no PYZ. O efeito era o instalador carregar o fonte em texto puro —
# inclusive o de services/sifen_adapter, que e o modulo fechado. Aqui removemos
# fonte e docs dos pacotes LOCAIS; os modulos seguem funcionando porque vao como
# bytecode no PYZ (via collect_submodules/hiddenimports).
_PKGS_LOCAIS = ("services", "components", "views", "utils", "config", "app")
_EXT_FONTE = (".py", ".pyi", ".pyx", ".md", ".txt")

# Nunca copiar como dado, venha de onde vier. O adapter e um repo PRIVADO montado
# por junction dentro da arvore: coleta-lo como dado levava 44 arquivos para o
# instalador, incluindo o `.git` completo — historico, index e o config com a URL
# do repo. O modulo continua funcionando: vai como bytecode no PYZ.
_NUNCA = ("_adapter", "sifen_adapter", "/.git/", "/.git")


def _e_fonte_local(entry):
    origem, destino = str(entry[0]), str(entry[1]).replace("\\", "/")
    raiz = destino.split("/")[0]
    return raiz in _PKGS_LOCAIS and origem.lower().endswith(_EXT_FONTE)


def _e_proibido(entry):
    caminho = (str(entry[0]) + "|" + str(entry[1])).replace("\\", "/")
    return any(p in caminho for p in _NUNCA)


datas = [d for d in datas if not _e_fonte_local(d) and not _e_proibido(d)]
binaries = [b for b in binaries if not _e_proibido(b)]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Rede de seguranca: mesmo que algo volte a alcancar estes pacotes pela
    # arvore de dependencias, eles ficam fora. Nenhum e importado pelo app —
    # conferido com grep em services/ views/ components/ utils/ config/.
    # `flet_web` sao os assets do modo web; este app e desktop (flet_desktop).
    excludes=[
        "cv2", "scipy", "numba", "llvmlite", "pandas", "matplotlib",
        "geopandas", "pykrige", "imageio", "IPython", "notebook",
        "tkinter", "flet_web",
    ],
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
