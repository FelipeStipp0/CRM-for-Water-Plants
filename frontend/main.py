import builtins
import os

import flet as ft
from datetime import datetime
import time
from pathlib import Path
import traceback


# Mantem o handle do Job Object vivo enquanto o processo existir.
_wmapp_job_handle = None


_BRANDED_CLIENT_NAME = "Saneo"  # nome do exe e da pasta no LOCALAPPDATA


_LANG_EN_US = 1033  # Mesma lang usada pelo Flet ao gravar resources do flet.exe


def _patch_exe_icon(exe_path: str, ico_path: str) -> None:
    """Substitui RT_ICON + RT_GROUP_ICON do exe pelo conteudo do .ico.

    Implementacao baseada no que o 'flet pack' faz oficialmente em
    flet_cli/__pyinstaller/win_utils.py::update_flet_view_icon:
      - grava no RT_GROUP_ICON ID 101 (convencao IDI_APP_ICON do Flutter)
      - usa language code 1033 (en-US) - sem isso o Windows insere o nosso
        icone *ao lado* da entry 1033 existente em vez de substituir, e o
        Flet original continua aparecendo na taskbar.
      - tambem reseta MAINICON e ID 1 para casos onde o Explorer leia outro.
    """
    import struct
    import win32api

    with open(ico_path, "rb") as f:
        ico = f.read()

    # ICONDIR header: reserved(2), type(2), count(2)
    _, ico_type, count = struct.unpack_from("<HHH", ico, 0)
    if ico_type != 1 or count == 0:
        raise RuntimeError("ICO invalido")

    # Enumera todos os RT_GROUP_ICON existentes para limpar cada um.
    existing_group_names: list = []
    try:
        h_read = win32api.LoadLibraryEx(exe_path, 0, 2)  # LOAD_LIBRARY_AS_DATAFILE
        try:
            for name in win32api.EnumResourceNames(h_read, 14):
                existing_group_names.append(name)
        finally:
            win32api.FreeLibrary(h_read)
    except Exception:
        pass

    # ID 101 e o mais importante: e o que o Flutter Windows runner carrega
    # via LoadImage(MAKEINTRESOURCE(IDI_APP_ICON)) no init da janela.
    for fallback in (101, "MAINICON", 1):
        if fallback not in existing_group_names:
            existing_group_names.append(fallback)

    handle = win32api.BeginUpdateResource(exe_path, False)
    try:
        group = struct.pack("<HHH", 0, 1, count)
        for i in range(count):
            off = 6 + i * 16
            (width, height, colors, _r, planes, bpp,
             bytes_in_res, image_offset) = struct.unpack_from(
                "<BBBBHHII", ico, off
            )
            icon_id = i + 1
            image = ico[image_offset:image_offset + bytes_in_res]
            win32api.UpdateResource(handle, 3, icon_id, image, _LANG_EN_US)
            # GRPICONDIRENTRY tem 14 bytes: troca image_offset por ID(2 bytes).
            group += struct.pack(
                "<BBBBHHIH",
                width, height, colors, 0, planes, bpp, bytes_in_res, icon_id,
            )
        for name in existing_group_names:
            try:
                # Lang 1033 = en-US, mesma que o Flet usa ao gravar.
                # Sem essa lang o Windows trata como "neutral" e mantem a
                # entry 1033 original do Flet ao lado, com prioridade.
                win32api.UpdateResource(handle, 14, name, group, _LANG_EN_US)
            except Exception:
                pass
        win32api.EndUpdateResource(handle, False)
    except Exception:
        try:
            win32api.EndUpdateResource(handle, True)  # discard
        except Exception:
            pass
        raise


def _patch_exe_version_info(
    exe_path: str,
    product_name: str = "Saneo",
    file_description: str = "Saneo - Sistema de Saneamiento",
    company_name: str = "Saneo",
) -> None:
    """Reescreve strings de VERSIONINFO do exe (ProductName, FileDescription,
    CompanyName). Sem isso o Windows mostra 'Flet' como nome da aplicacao em
    varios lugares (tooltip da taskbar, gerenciador de tarefas, Properties).

    Le a estrutura VS_VERSIONINFO bruta via win32api.LoadResource, faz um
    parse manual para sobrescrever os valores das chaves desejadas, e
    grava de volta com BeginUpdateResource. Trabalho 100% binario - nao
    depende de pefile/PyInstaller que so existem em build time."""
    import struct
    import win32api

    try:
        h_read = win32api.LoadLibraryEx(exe_path, 0, 2)  # LOAD_LIBRARY_AS_DATAFILE
    except Exception:
        return

    try:
        try:
            existing = win32api.LoadResource(h_read, 16, 1, _LANG_EN_US)
        except Exception:
            try:
                names = win32api.EnumResourceNames(h_read, 16)
                if not names:
                    return
                existing = win32api.LoadResource(h_read, 16, names[0], _LANG_EN_US)
            except Exception:
                return
    finally:
        win32api.FreeLibrary(h_read)

    if not existing:
        return

    overrides = {
        "ProductName": product_name,
        "FileDescription": file_description,
        "CompanyName": company_name,
        "InternalName": product_name,
        "OriginalFilename": f"{product_name}.exe",
    }

    new_blob = _patch_version_info_blob(existing, overrides)
    if new_blob is None or new_blob == existing:
        return

    handle = win32api.BeginUpdateResource(exe_path, False)
    try:
        win32api.UpdateResource(handle, 16, 1, new_blob, _LANG_EN_US)
        win32api.EndUpdateResource(handle, False)
    except Exception:
        try:
            win32api.EndUpdateResource(handle, True)
        except Exception:
            pass


def _patch_version_info_blob(blob: bytes, overrides: dict) -> bytes | None:
    """Faz um parse local da VS_VERSIONINFO e substitui valores de string.

    Estrutura simplificada:
      VS_VERSIONINFO -> StringFileInfo -> StringTable -> String[]
    Cada nivel tem um header { wLength, wValueLength, wType, szKey(WCHAR*),
    Padding, Value }. szKey e UTF-16 terminada em NUL.
    Para sobrescrever uma string sem corromper o restante, no minimo
    precisariamos ajustar todos os wLength dos pais. Vamos fazer a forma
    pragmatica: encontrar a chave (UTF-16) e o valor seguinte; se o novo
    valor cabe no espaco do antigo, sobrescreve in-place sem mudar tamanhos.
    Se nao cabe, deixa o original (best-effort).

    Nao e perfeito, mas e suficiente pra Windows parar de mostrar 'Flet'."""
    out = bytearray(blob)

    for key, new_val in overrides.items():
        key_wchars = (key + "\x00").encode("utf-16-le")
        idx = bytes(out).find(key_wchars)
        if idx < 0:
            continue

        # Apos o szKey vem padding ate alinhamento DWORD, depois o Value (WCHAR*).
        val_start = idx + len(key_wchars)
        # Padding zero ate proximo offset multiplo de 4 (relativo ao inicio do struct,
        # nao do blob - mas como erro pequeno costuma ser de 0 ou 2 bytes, tentamos
        # avancar enquanto for byte nulo no inicio do alinhamento).
        while val_start % 4 != 0:
            val_start += 1
        if val_start >= len(out):
            continue

        # Encontra fim do Value: sequencia UTF-16 que termina em 0x0000.
        val_end = val_start
        while val_end + 1 < len(out):
            if out[val_end] == 0 and out[val_end + 1] == 0:
                val_end += 2
                break
            val_end += 2

        old_byte_len = val_end - val_start
        new_bytes = (new_val + "\x00").encode("utf-16-le")

        if len(new_bytes) <= old_byte_len:
            # Sobrescreve in-place, preenchendo o restante com zero.
            out[val_start:val_start + len(new_bytes)] = new_bytes
            for i in range(val_start + len(new_bytes), val_end):
                out[i] = 0
        # Se nao cabe, deixa o original. Pelo menos a chave principal
        # (FileDescription) costuma caber.

    return bytes(out)


def _setup_branded_flet_client():
    """Substitui o flet.exe oficial por uma copia chamada Saneo.exe com
    nosso icone. O processo visivel na barra de tarefas e no gerenciador
    de tarefas passa a ser 'Saneo', nao 'flet'.

    Cacheia em %LOCALAPPDATA%/Saneo/client-{flet_version}/. So roda a copia
    pesada na primeira execucao apos atualizar o Flet.

    Tem que rodar ANTES de ft.run() - depois disso o subprocesso ja foi
    spawnado."""
    if os.name != "nt":
        return
    try:
        from flet_desktop import ensure_client_cached
        import flet_desktop as fd
    except Exception as err:
        _ORIGINAL_PRINT(f"[WMApp] flet_desktop_import_error err={err}")
        return

    try:
        cache_dir = ensure_client_cached()
    except Exception as err:
        _ORIGINAL_PRINT(f"[WMApp] flet_cache_error err={err}")
        return

    src_dir = Path(cache_dir) / "flet"
    src_exe = src_dir / "flet.exe"
    if not src_exe.exists():
        return

    icon_path = Path(__file__).resolve().parent / "assets" / "junta.ico"
    if not icon_path.exists():
        return

    # Versionado pela pasta do flet desktop (ex.: flet-desktop-full-0.84.0)
    version_tag = Path(cache_dir).name
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / _BRANDED_CLIENT_NAME
    out_dir = base / version_tag
    out_exe = out_dir / f"{_BRANDED_CLIENT_NAME}.exe"
    marker = out_dir / ".ready"

    need_build = (
        not marker.exists()
        or not out_exe.exists()
        or out_exe.stat().st_mtime < src_exe.stat().st_mtime
    )

    if need_build:
        try:
            import shutil
            # Limpa estado antigo (se houver) e recria do zero.
            if out_dir.exists():
                shutil.rmtree(out_dir, ignore_errors=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            # Copia todo o engine Flutter (DLLs, data, assets...) sem o exe.
            for item in src_dir.iterdir():
                if item.name.lower() == "flet.exe":
                    continue
                dst = out_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dst)
                else:
                    shutil.copy2(item, dst)
            # Copia o exe ja com o novo nome.
            shutil.copy2(src_exe, out_exe)
            try:
                _patch_exe_icon(str(out_exe), str(icon_path))
            except Exception as err:
                _ORIGINAL_PRINT(f"[WMApp] icon_patch_error err={err}")
            try:
                _patch_exe_version_info(str(out_exe))
            except Exception as err:
                _ORIGINAL_PRINT(f"[WMApp] versioninfo_patch_error err={err}")

            marker.write_text("ok", encoding="utf-8")
        except Exception as err:
            _ORIGINAL_PRINT(f"[WMApp] flet_rebrand_build_error err={err}")
            return

    # Monkey-patch: faz o Flet lancar nosso exe em vez do oficial.
    try:
        import subprocess
        import tempfile
        from flet.utils import random_string

        # FLET_HIDE_WINDOW_ON_START e bugado no Flet 0.80+ (issues #3223 e
        # #5216 do repo). A janela ainda aparece com o titulo default "Flet"
        # antes do page.title chegar. A solucao confiavel e via Win32: passa
        # STARTUPINFO com wShowWindow=SW_HIDE direto pro CreateProcess.
        # O Flutter usa o nCmdShow do WinMain ao chamar ShowWindow inicial,
        # entao a janela nasce escondida no nivel do SO - independe do Flet.
        # Quando Python eventualmente chama page.window.visible=True, o lado
        # Dart do Flet chama window.show() que revela com o titulo ja correto.
        def _build_hidden_startupinfo():
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            return si

        def _branded_open(page_url, assets_dir, _hidden):
            pid_file = str(
                Path(tempfile.gettempdir()).joinpath(random_string(20))
            )
            args = [str(out_exe), page_url, pid_file]
            if assets_dir:
                args.append(assets_dir)
            env = {**os.environ}
            env["FLET_HIDE_WINDOW_ON_START"] = "true"
            return (
                subprocess.Popen(
                    args, env=env, startupinfo=_build_hidden_startupinfo()
                ),
                pid_file,
            )

        # asyncio.create_subprocess_exec nao aceita STARTUPINFO; envelopa
        # uma Popen sincrona para parecer asyncio.subprocess.Process (so
        # precisamos de .wait() awaitable - o resto da API que o Flet usa
        # delega direto pra Popen).
        class _AsyncPopen:
            def __init__(self, popen):
                self._popen = popen
                self.pid = popen.pid
                self.returncode = None

            async def wait(self):
                import asyncio
                rc = await asyncio.get_event_loop().run_in_executor(
                    None, self._popen.wait
                )
                self.returncode = rc
                return rc

            def terminate(self):
                try:
                    self._popen.terminate()
                except Exception:
                    pass

            def kill(self):
                try:
                    self._popen.kill()
                except Exception:
                    pass

        async def _branded_open_async(page_url, assets_dir, _hidden):
            import asyncio
            pid_file = str(
                Path(tempfile.gettempdir()).joinpath(random_string(20))
            )
            args = [str(out_exe), page_url, pid_file]
            if assets_dir:
                args.append(assets_dir)
            env = {**os.environ}
            env["FLET_HIDE_WINDOW_ON_START"] = "true"
            loop = asyncio.get_event_loop()
            popen = await loop.run_in_executor(
                None,
                lambda: subprocess.Popen(
                    args, env=env, startupinfo=_build_hidden_startupinfo()
                ),
            )
            return _AsyncPopen(popen), pid_file

        fd.open_flet_view = _branded_open
        fd.open_flet_view_async = _branded_open_async
    except Exception as err:
        _ORIGINAL_PRINT(f"[WMApp] flet_monkeypatch_error err={err}")


def _set_app_user_model_id(model_id: str = "Saneo.SistemaSaneamiento.1"):
    """SetCurrentProcessExplicitAppUserModelID — Windows usa o AppID pra
    agrupar entries da taskbar e pra escolher tooltip/icone do grupo.
    Sem isso, processos baseados em flet.exe podem ser agrupados como
    'Flet' mesmo depois de mudar titulo da janela. Sem efeito fora do
    Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p(model_id)
        )
    except Exception as err:
        try:
            _ORIGINAL_PRINT(f"[WMApp] appid_set_error err={err}")
        except Exception:
            pass


def _bind_to_job_kill_on_close():
    """No Windows, vincula o processo atual a um Job Object com
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. Quando o processo principal morre
    (por qualquer motivo, inclusive SIGKILL/TerminateProcess), o OS mata
    todos os filhos junto. Evita o orfao da janela Flutter "loading" que
    sobra quando a gente derruba o junta.exe pelo task manager.

    Precisa rodar ANTES de ft.run() — caso contrario a janela Flutter ja
    foi spawnada fora do job e nao herda."""
    global _wmapp_job_handle
    if os.name != "nt":
        return
    try:
        import win32job
        import win32api
        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation
        )
        info["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32job.SetInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation, info
        )
        win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
        _wmapp_job_handle = job
    except Exception as err:
        # Job object e best-effort — falha nao impede a aplicacao de subir.
        _ORIGINAL_PRINT_FOR_JOB = getattr(builtins, "print", print)
        _ORIGINAL_PRINT_FOR_JOB(f"[WMApp] job_bind_error err={err}")

_ORIGINAL_PRINT = builtins.print


def _wmapp_filtered_print(*args, **kwargs):
    """
    Silencia logs verbosos do app por padrao.
    Para reativar: WMAPP_DEBUG_LOGS=1
    """
    debug_enabled = str(os.getenv("WMAPP_DEBUG_LOGS", "0")).lower() in {"1", "true", "yes", "on"}
    if debug_enabled:
        _ORIGINAL_PRINT(*args, **kwargs)
        return
    if not args:
        return
    first = args[0]
    if isinstance(first, str) and first.startswith("["):
        return
    _ORIGINAL_PRINT(*args, **kwargs)


builtins.print = _wmapp_filtered_print

from components.sidebar import Sidebar
from components.status_bar import StatusBar
from components.theme import COLORS, SPACING
import i18n
from i18n import t
from services.auth_service import auth_service
from services.api_client import APIError, api
from components.splash_view import SplashView
from views.clients_view import ClientsView
from views.map_view import MapView
from views.cutoff_view import CutoffView
from views.finance_view import FinanceView
from views.invoices_view import InvoicesView
from views.login_view import LoginView
from views.payments_view import PaymentsView
from views.readings_view import ReadingsView
from views.profile_view import ProfileView
from views.about_view import AboutView
from views.settings_view import SettingsView
from views.sifen_view import SifenView
from views.sponsors_view import SponsorsView


class WMApp:
    """Aplicacao principal."""

    ROUTE_SCOPES = {
        "/clients": "clients",
        "/readings": "readings",
        "/invoices": "invoices",
        "/payments": "payments",
        "/cutoff": "cutoff",
        "/finance": "finance",
        "/sponsors": ("sponsors", "finance"),
        "/map": "clients",
        "/settings": "settings",
        "/profile": None,  # accesible por cualquier usuario autenticado
        "/about": None,    # accesible por cualquier usuario autenticado
    }

    # Tamanho da janela "pequena" usada durante boot/splash/login.
    SPLASH_WIDTH = SplashView.WINDOW_WIDTH
    SPLASH_HEIGHT = SplashView.WINDOW_HEIGHT
    # Tamanho de abertura do app principal apos login. Mantemos 1320x840
    # como "ideal" pra quem tem espaco, mas o min_* abaixo precisa respeitar
    # notebooks comuns (1366x768, 1280x720). Cromo do Windows costuma roubar
    # ~60-80px de altura — por isso o min_height fica em 640.
    MAIN_WIDTH = 1320
    MAIN_HEIGHT = 840
    MAIN_MIN_WIDTH = 1000
    MAIN_MIN_HEIGHT = 640

    def __init__(self, page: ft.Page):
        self.page = page
        self.current_user = None
        self.current_route = "/clients"
        self._settings_view = None
        self._profile_view = None
        self.splash: SplashView | None = None
        self.error_log_path = Path(__file__).resolve().parent / "runtime_errors.log"

        api.set_unauthorized_handler(self._handle_session_expired)
        self._setup_page()
        self._show_splash()
        self._try_auto_login()

    def _setup_page(self):
        """Configura a pagina. Comeca pequena (tamanho da splash)."""
        self.page.title = "Saneo - Sistema de Saneamiento"
        self.page.bgcolor = COLORS["bg_primary"]
        self.page.padding = 0
        self.page.spacing = 0
        # Janela comeca pequena para acomodar splash/login. Vira self.MAIN_*
        # depois que o usuario autentica em _enter_main_layout.
        self.page.window.width = self.SPLASH_WIDTH
        self.page.window.height = self.SPLASH_HEIGHT
        self.page.window.min_width = self.SPLASH_WIDTH
        self.page.window.min_height = self.SPLASH_HEIGHT
        self.page.window.resizable = False
        self.page.window.maximizable = False
        self._center_window()
        try:
            icon_path = Path(__file__).resolve().parent / "assets" / "junta.ico"
            if icon_path.exists():
                self.page.window.icon = str(icon_path)
        except Exception:
            pass

        self.snackbar = ft.SnackBar(content=ft.Text(""), bgcolor=COLORS["bg_elevated"])
        self.page.overlay.append(self.snackbar)
        try:
            self.page.on_error = self._on_page_error
        except Exception as err:
            print(f"[WMApp] page_on_error_hook_failed err={err}")

    def _center_window(self):
        """Centraliza a janela no monitor primario.

        page.window.center() existe em Flet 0.84 mas e bugado: chamado antes
        do primeiro paint nao surte efeito porque o Flutter ainda nao sabe
        as dimensoes finais. Usamos Win32 GetSystemMetrics(SM_CXSCREEN/
        SM_CYSCREEN) pra ler o tamanho real da tela primaria e setar
        window.left/top — funciona inclusive em DPI > 100% e em multi-monitor
        (cai no primario, que e o comportamento esperado de um app de boot)."""
        win_w = int(self.page.window.width or self.SPLASH_WIDTH)
        win_h = int(self.page.window.height or self.SPLASH_HEIGHT)

        screen_w, screen_h = (1920, 1080)
        try:
            if os.name == "nt":
                import ctypes
                user32 = ctypes.windll.user32
                # SM_CXSCREEN=0, SM_CYSCREEN=1 — tamanho do monitor primario
                # em pixeis virtuais (ja considerando DPI awareness).
                screen_w = int(user32.GetSystemMetrics(0))
                screen_h = int(user32.GetSystemMetrics(1))
        except Exception:
            pass

        try:
            self.page.window.left = max(0, (screen_w - win_w) // 2)
            self.page.window.top = max(0, (screen_h - win_h) // 2)
        except Exception:
            pass

    def _show_splash(self):
        """Renderiza a SplashView. Tem que ser sincrono — usuario precisa ver
        algo antes do auto_login potencialmente bloquear."""
        self.splash = SplashView()
        self.page.controls.clear()
        self.page.add(self.splash)
        try:
            self.page.update()
        except Exception:
            pass

    def _try_auto_login(self):
        """Dispara o fluxo de auto login no background — splash fica
        animando ate decidir entre main layout (sessao restaurada) ou
        tela de login. Roda em thread separada pra nao bloquear a UI."""
        def worker():
            self._auto_login_worker()

        if self.page:
            try:
                self.page.run_thread(worker)
                return
            except Exception:
                pass
        worker()

    def _auto_login_worker(self):
        # Caso 1: nao ha token persistido — vai direto pro login, sem animar.
        if not auth_service.try_restore_session():
            self._show_login()
            return

        # Caso 2: existe token. Mostra "Verificando sesion..." e tenta.
        if self.splash:
            self.splash.set_status(t("splash.checking_session"))

        try:
            user = auth_service.get_current_user()
        except APIError:
            print("[WMApp] auto_login_api_error")
            self._show_login()
            return
        except Exception as err:
            print(f"[WMApp] auto_login_unexpected_error err={err}")
            self._show_login()
            return

        if user.get("must_change_password"):
            auth_service.logout()
            self._show_login(t("app.must_change_password"))
            return

        # Sucesso: anima check, depois vai pro layout principal.
        self.current_user = user
        i18n.set_language(user.get("language"))
        self.current_route = self._first_allowed_route()
        if self.splash:
            self.splash.show_check(t("splash.welcome"), hold_ms=650)
        self._enter_main_layout()

    def _show_login(self, message: str | None = None):
        # Garante janela no tamanho da splash (sem maximizar para login).
        try:
            self.page.window.resizable = False
            self.page.window.maximizable = False
            self.page.window.width = self.SPLASH_WIDTH
            self.page.window.height = self.SPLASH_HEIGHT
            self._center_window()
        except Exception:
            pass
        self.page.controls.clear()
        self.splash = None
        self.page.add(LoginView(on_login_success=self._on_login_success))
        try:
            self.page.update()
        except Exception:
            pass
        if message:
            self.show_snackbar(message, error=True)

    def _on_login_success(self, user: dict):
        self.current_user = user
        i18n.set_language(user.get("language"))
        self.current_route = self._first_allowed_route()
        # Anima check rapido reusando uma splash temporaria, depois vai
        # pro layout principal.
        self.splash = SplashView()
        self.page.controls.clear()
        self.page.add(self.splash)
        try:
            self.page.update()
        except Exception:
            pass
        self.splash.show_check(t("splash.welcome"), hold_ms=550)
        self._enter_main_layout()
        self._start_sifen_coordinator()

    def _start_sifen_coordinator(self):
        """Liga o coordenador de emissão em background (só emite se este PC for permitido)."""
        try:
            from services.sifen_coordinator import get_coordinator
            get_coordinator().start()
        except Exception as err:  # noqa: BLE001
            print(f"[WMApp] sifen_coordinator_start_error err={err}")

    def _enter_main_layout(self):
        """Redimensiona pro tamanho do app principal e troca pro layout."""
        try:
            self.page.window.resizable = True
            self.page.window.maximizable = True
            self.page.window.min_width = self.MAIN_MIN_WIDTH
            self.page.window.min_height = self.MAIN_MIN_HEIGHT
            self.page.window.width = self.MAIN_WIDTH
            self.page.window.height = self.MAIN_HEIGHT
            self._center_window()
        except Exception:
            pass
        self.splash = None
        self._show_main_layout()

    def _user_has_scope(self, required_scope):
        if required_scope is None:
            return True
        if not self.current_user:
            return False
        if self.current_user.get("role") == "master":
            return True
        scopes = self.current_user.get("scopes", [])
        if "*" in scopes:
            return True
        if isinstance(required_scope, (tuple, list)):
            return any(scope in scopes for scope in required_scope)
        return required_scope in scopes

    def _allowed_routes(self) -> list[str]:
        routes = []
        for route, scope in self.ROUTE_SCOPES.items():
            if self._user_has_scope(scope):
                routes.append(route)
        return routes or ["/clients"]

    def _first_allowed_route(self) -> str:
        return self._allowed_routes()[0]

    def _show_main_layout(self):
        self.page.controls.clear()

        self.sidebar = Sidebar(
            on_navigate=self._navigate,
            current_route=self.current_route,
            allowed_scopes=self.current_user.get("scopes", []),
            is_superuser=self.current_user.get("role") == "master",
            on_logout=self._logout,
        )

        self.status_bar = StatusBar(
            username=self.current_user.get("full_name", self.current_user.get("username", "")),
        )
        self.nav_progress = ft.ProgressBar(visible=False, height=3, color=COLORS["accent_secondary"])

        self.content_area = ft.Container(expand=True)

        main_layout = ft.Column(
            [
                self.nav_progress,
                ft.Row(
                    [
                        self.sidebar,
                        ft.VerticalDivider(width=1, color=COLORS["border"]),
                        self.content_area,
                    ],
                    expand=True,
                    spacing=0,
                ),
                self.status_bar,
            ],
            spacing=0,
            expand=True,
        )

        self.page.add(main_layout)
        self._navigate(self.current_route)
        self.page.update()

        self._settings_view = SettingsView(
            show_snackbar=self.show_snackbar,
            on_printer_change=self._on_printer_change,
            current_user=self.current_user,
        )
        self._profile_view = ProfileView(
            show_snackbar=self.show_snackbar,
            current_user=self.current_user,
            on_user_update=self._on_user_update,
        )
        self.page.run_thread(self._settings_view.trigger_initial_load)

    def _on_user_update(self, user: dict):
        """Callback chamado quando o usuario atualiza seu perfil."""
        prev_language = (self.current_user or {}).get("language")
        self.current_user = user
        new_language = user.get("language")
        i18n.set_language(new_language)
        if hasattr(self, "status_bar"):
            self.status_bar.update_user(user.get("full_name") or user.get("username", ""))
        # Idioma mudou: reconstrói TODA a casca (sidebar, status bar e views) para
        # aplicar o i18n de forma consistente. Invalida os caches das views que
        # foram construídas no idioma anterior, senão "muda só uma vez".
        if new_language != prev_language:
            try:
                self._settings_view = None
                self._profile_view = None
                self._show_main_layout()
            except Exception as err:
                print(f"[WMApp] language_refresh_error err={err}")

    def _logout(self):
        auth_service.logout()
        self.current_user = None
        self.current_route = "/clients"
        self._settings_view = None
        self._profile_view = None
        self._show_login(t("app.session_closed"))

    def _handle_session_expired(self):
        """
        Handler global de 401.
        Mantem persistencia ate expirar e depois retorna ao login.
        """
        if self.current_user is None:
            return
        auth_service.logout()
        self.current_user = None
        self.current_route = "/clients"
        self._show_login(t("app.session_expired"))

    def _navigate(self, route: str):
        nav_started = time.perf_counter()
        required_scope = self.ROUTE_SCOPES.get(route)
        if not self._user_has_scope(required_scope):
            self.show_snackbar(t("app.permission_denied"), error=True)
            route = self._first_allowed_route()

        self.current_route = route

        if hasattr(self, "nav_progress"):
            self.nav_progress.visible = True
            try:
                self.nav_progress.update()
            except Exception as err:
                print(f"[WMApp] nav_progress_show_update_error err={err}")

        if hasattr(self, "sidebar"):
            self.sidebar.set_route(route)

        try:
            view = self._get_view(route)
            # Padroniza ciclo de refresh via navegacao.
            # Evita dependencia do timing do on_visible, que causava telas
            # sem dados em alguns fluxos, e também evita dupla carga.
            try:
                if hasattr(view, "on_visible"):
                    view.on_visible = None
            except Exception as err:
                print(f"[WMApp] disable_on_visible_error view={type(view).__name__} err={err}")
            self.content_area.content = view
            self.content_area.update()
            print(f"[WMApp] navigate_render route={route} ms={(time.perf_counter()-nav_started)*1000:.1f}")
            self._trigger_initial_view_load(view)
        except Exception as err:
            log_file = self._log_exception("navigate", err, route=route)
            self.content_area.content = self._build_runtime_error_view(
                route=route,
                error_message=str(err),
                log_file=log_file,
            )
            try:
                self.content_area.update()
            except Exception as err:
                print(f"[WMApp] content_area_update_error err={err}")
            self.show_snackbar(
                t("app.open_failed", route=route, log=log_file),
                error=True,
            )
        finally:
            if hasattr(self, "nav_progress"):
                self.nav_progress.visible = False
                try:
                    self.nav_progress.update()
                except Exception as err:
                    print(f"[WMApp] nav_progress_hide_update_error err={err}")

    def _trigger_initial_view_load(self, view: ft.Control):
        """
        Dispara carga inicial da view apos render.
        Evita bloquear o clique/navegacao no thread principal.
        """
        if not hasattr(view, "trigger_initial_load"):
            return

        def _run_and_log():
            started = time.perf_counter()
            try:
                view.trigger_initial_load()
            finally:
                print(
                    f"[WMApp] view_load_complete view={type(view).__name__} "
                    f"ms={(time.perf_counter()-started)*1000:.1f}"
                )

        try:
            self.page.run_thread(_run_and_log)
        except Exception as err:
            print(f"[WMApp] run_thread_load_error view={type(view).__name__} err={err}")
            try:
                _run_and_log()
            except Exception as fallback_err:
                print(f"[WMApp] direct_load_error view={type(view).__name__} err={fallback_err}")

    def _get_view(self, route: str) -> ft.Control:
        views = {
            "/clients": lambda: ClientsView(show_snackbar=self.show_snackbar),
            "/readings": lambda: ReadingsView(show_snackbar=self.show_snackbar),
            "/invoices": lambda: InvoicesView(show_snackbar=self.show_snackbar),
            "/payments": lambda: PaymentsView(show_snackbar=self.show_snackbar),
            "/cutoff": lambda: CutoffView(show_snackbar=self.show_snackbar),
            "/finance": lambda: FinanceView(show_snackbar=self.show_snackbar),
            "/sponsors": lambda: SponsorsView(show_snackbar=self.show_snackbar),
            "/map": lambda: MapView(),
            "/sifen": lambda: SifenView(
                show_snackbar=self.show_snackbar,
                current_user=self.current_user,
            ),
            "/settings": lambda: self._settings_view or SettingsView(
                show_snackbar=self.show_snackbar,
                on_printer_change=self._on_printer_change,
                current_user=self.current_user,
            ),
            "/profile": lambda: self._profile_view or ProfileView(
                show_snackbar=self.show_snackbar,
                current_user=self.current_user,
                on_user_update=self._on_user_update,
            ),
            "/about": lambda: AboutView(),
        }

        builder = views.get(route)
        if builder is None:
            return self._build_placeholder("404", t("app.page_not_found"))()
        return builder()

    def _build_placeholder(self, title: str, message: str):
        def builder():
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.CONSTRUCTION, size=64, color=COLORS["text_muted"]),
                        ft.Text(title, size=24, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                        ft.Text(message, color=COLORS["text_secondary"]),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                alignment=ft.Alignment(0, 0),
                expand=True,
            )

        return builder

    def _on_printer_change(self, printer_type: str, printer_name: str):
        if hasattr(self, "status_bar"):
            if printer_type == "thermal":
                self.status_bar.update_printers(thermal=printer_name)
            else:
                self.status_bar.update_printers(a4=printer_name)

    def show_snackbar(self, message: str, error: bool = False):
        # Recria o SnackBar a cada chamada: reabrir a mesma instância no Flet 0.84
        # nem sempre dispara de novo ("confirmação aparece só uma vez").
        sb = ft.SnackBar(
            content=ft.Text(message, color=COLORS["accent_error"] if error else COLORS["text_primary"]),
            bgcolor=COLORS["bg_elevated"],
        )
        try:
            # Limpa snackbars antigos do overlay para não acumular.
            self.page.overlay[:] = [c for c in self.page.overlay if not isinstance(c, ft.SnackBar)]
            self.page.overlay.append(sb)
            self.snackbar = sb
            sb.open = True
            self.page.update()
        except Exception:
            pass

    def _on_page_error(self, e):
        message = getattr(e, "data", None) or str(e)
        log_file = self._log_exception("page.on_error", RuntimeError(str(message)))
        self.show_snackbar(t("app.ui_error", log=log_file), error=True)

    def _log_exception(self, context: str, err: Exception, route: str | None = None) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trace = "".join(traceback.format_exception(type(err), err, err.__traceback__))
        header = f"[{timestamp}] context={context} route={route or '-'}\n"
        try:
            with open(self.error_log_path, "a", encoding="utf-8") as f:
                f.write(header)
                f.write(trace)
                f.write("\n")
        except Exception:
            pass
        return str(self.error_log_path)

    def _build_runtime_error_view(self, route: str, error_message: str, log_file: str) -> ft.Control:
        error_summary = t("app.route_error_summary", route=route, error=error_message, log=log_file)

        def copy_error(_):
            try:
                self.page.set_clipboard(error_summary)
                self.show_snackbar(t("app.error_copied"))
            except Exception:
                self.show_snackbar(t("app.error_copy_failed"), error=True)

        return ft.Container(
            expand=True,
            padding=SPACING["lg"],
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color=COLORS["accent_error"]),
                    ft.Text(t("app.render_error_title"), size=22, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    ft.Text(error_summary, color=COLORS["text_secondary"]),
                    ft.Row(
                        [
                            ft.Button(content=ft.Text(t("app.back")), on_click=lambda e: self._navigate(self._first_allowed_route())),
                            ft.Button(content=ft.Text(t("app.copy_error")), on_click=copy_error),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
        )


def _apply_window_branding_early(page: ft.Page):
    """Aplica titulo + icone Saneo na primeira coisa que a janela renderiza,
    para nao deixar o usuario ver o branding default 'Flet' por 1-2 segundos.

    Esconde a janela ate o setup do WMApp ficar pronto, depois mostra de uma
    vez ja com a UI no lugar. Tudo dentro de try/except — qualquer falha aqui
    e cosmetica e nao deve impedir a app de subir."""
    try:
        page.title = "Saneo - Sistema de Saneamiento"
    except Exception:
        pass
    try:
        page.bgcolor = COLORS["bg_primary"]
    except Exception:
        pass
    try:
        icon_path = Path(__file__).resolve().parent / "assets" / "junta.ico"
        if icon_path.exists():
            page.window.icon = str(icon_path)
    except Exception:
        pass
    try:
        page.window.visible = False
    except Exception:
        pass
    try:
        page.update()
    except Exception:
        pass


def _reveal_window(page: ft.Page):
    try:
        page.window.visible = True
        page.update()
    except Exception:
        pass


def main(page: ft.Page):
    _apply_window_branding_early(page)
    try:
        WMApp(page)
    finally:
        _reveal_window(page)


if __name__ == "__main__":
    # AppUserModelID antes de qualquer subprocesso — o Saneo.exe filho herda.
    _set_app_user_model_id()

    # JobObject precisa ser criado ANTES do ft.run() — caso contrario a janela
    # Flutter ja foi spawnada fora do job e nao herda o kill-on-close.
    _bind_to_job_kill_on_close()

    # Substitui o flet.exe pela copia branded "Saneo.exe" antes do ft.run.
    # Tem que ser nesta ordem: o monkey-patch precisa estar em pe quando
    # ft.run chamar open_flet_view internamente.
    _setup_branded_flet_client()

    # assets_dir habilita ft.Image(src="saneo.png") a partir de frontend/assets
    # (logo no sidebar e na tela de login). Funciona em dev e no bundle PyInstaller.
    _assets_dir = str(Path(__file__).resolve().parent / "assets")
    ft.run(main, assets_dir=_assets_dir)
