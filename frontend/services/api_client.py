"""
WMApp Frontend - API Client
Cliente HTTP com gerenciamento de JWT e tratamento de erros.
"""
import time
from typing import Any, Callable, Optional

import httpx

from config.local_settings import get_api_url


class APIError(Exception):
    """Erro de API com codigo de status."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API Error {status_code}: {detail}")


class APIClient:
    """Cliente HTTP singleton para comunicacao com a API."""

    _instance: Optional["APIClient"] = None
    _token: Optional[str] = None
    _on_unauthorized: Optional[Callable[[], None]] = None
    _max_retries: int = 2

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.base_url = self._normalize_base_url(get_api_url())
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        )
        print(f"[API] base_url={self.base_url}")

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        normalized = (url or "").strip().rstrip("/")
        if not normalized:
            normalized = "http://127.0.0.1:8000"
        # Em Windows, localhost pode tentar IPv6 (::1) antes de IPv4 e gerar latencia constante.
        normalized = normalized.replace("://localhost:", "://127.0.0.1:")
        if normalized.endswith("://localhost"):
            normalized = normalized.replace("://localhost", "://127.0.0.1")
        return normalized

    def _refresh_base_url(self):
        current = self._normalize_base_url(get_api_url())
        if current != self.base_url:
            self.base_url = current
            print(f"[API] base_url_updated={self.base_url}")

    @property
    def token(self) -> Optional[str]:
        return self._token

    @token.setter
    def token(self, value: Optional[str]):
        self._token = value

    def set_unauthorized_handler(self, handler: Optional[Callable[[], None]]):
        """Registra callback para resposta 401 global."""
        self._on_unauthorized = handler

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _handle_response(self, response: httpx.Response) -> Any:
        if response.status_code == 401:
            had_token = bool(self._token)
            self._token = None
            if had_token and self._on_unauthorized:
                try:
                    self._on_unauthorized()
                except Exception as err:
                    print(f"[API] unauthorized_handler_error err={err}")
                raise APIError(401, "Sessão expirada. Faça login novamente.")
            try:
                detail = response.json().get("detail", "Credenciais inválidas")
            except Exception:
                detail = "Credenciais inválidas"
            raise APIError(401, str(detail))

        if response.status_code == 422:
            detail = response.json().get("detail", "Erro de validacao")
            raise APIError(422, str(detail))

        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, str(detail))

        if response.status_code == 204:
            return None

        return response.json()

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        form_data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        self._refresh_base_url()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            started = time.perf_counter()
            try:
                response = self._client.request(
                    method=method,
                    url=f"{self.base_url}{endpoint}",
                    params=params,
                    json=json_data,
                    data=form_data,
                    headers=headers,
                )
                print(
                    f"[API] {method} {endpoint} status={response.status_code} "
                    f"ms={(time.perf_counter()-started)*1000:.1f} attempt={attempt+1}"
                )
                return response
            except httpx.RequestError as exc:
                last_exc = exc
                print(
                    f"[API] {method} {endpoint} request_error "
                    f"ms={(time.perf_counter()-started)*1000:.1f} attempt={attempt+1} err={exc}"
                )
                if attempt < self._max_retries:
                    delay = 0.5 * (attempt + 1)
                    time.sleep(delay)
                    continue
                break
        # Detalhe técnico (URL/exceção) fica só no log acima; a mensagem que sobe
        # para a UI é genérica e amigável (status 0 = falha de conexão). Ver
        # utils.errors.friendly_error, que traduz isto para o usuário.
        print(f"[API] connection_failed base_url={self.base_url} detail={last_exc}")
        raise APIError(0, "connection_failed") from last_exc

    def get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        response = self._request_with_retry(
            "GET",
            endpoint,
            params=params,
            headers=self._headers(),
        )
        return self._handle_response(response)

    def get_with_total(self, endpoint: str, params: Optional[dict] = None) -> tuple[Any, int]:
        """GET que também retorna o X-Total-Count do header. Retorna (data, total)."""
        response = self._request_with_retry(
            "GET",
            endpoint,
            params=params,
            headers=self._headers(),
        )
        data = self._handle_response(response)
        total = int(response.headers.get("x-total-count", len(data) if isinstance(data, list) else 0))
        return data, total

    def post_file(self, endpoint: str, file_path: str, field: str = "file") -> Any:
        """POST multipart/form-data com um único arquivo."""
        import mimetypes
        mime, _ = mimetypes.guess_type(file_path)
        with open(file_path, "rb") as fh:
            data = fh.read()
        files = {field: (file_path.split("/")[-1].split("\\")[-1], data, mime or "application/octet-stream")}
        self._refresh_base_url()
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        response = self._client.post(
            f"{self.base_url}{endpoint}",
            files=files,
            headers=headers,
        )
        print(f"[API] POST_FILE {endpoint} status={response.status_code}")
        return self._handle_response(response)

    def post(self, endpoint: str, data: Optional[dict] = None, form_data: Optional[dict] = None) -> Any:
        if form_data:
            response = self._request_with_retry(
                "POST",
                endpoint,
                form_data=form_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        else:
            response = self._request_with_retry(
                "POST",
                endpoint,
                json_data=data,
                headers=self._headers(),
            )
        return self._handle_response(response)

    def put(self, endpoint: str, data: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        response = self._request_with_retry(
            "PUT",
            endpoint,
            json_data=data,
            params=params,
            headers=self._headers(),
        )
        return self._handle_response(response)

    def patch(self, endpoint: str, data: dict) -> Any:
        response = self._request_with_retry(
            "PATCH",
            endpoint,
            json_data=data,
            headers=self._headers(),
        )
        return self._handle_response(response)

    def delete(self, endpoint: str) -> Any:
        response = self._request_with_retry(
            "DELETE",
            endpoint,
            headers=self._headers(),
        )
        return self._handle_response(response)

    def is_authenticated(self) -> bool:
        return self._token is not None


api = APIClient()
