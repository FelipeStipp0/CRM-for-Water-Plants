"""
WMApp Frontend - Auth Service
Servico de autenticacao com persistencia de sessao.
"""

from services.api_client import APIError, api
from config.local_settings import get_token, set_token, get_org_slug, set_org_slug


class AuthService:
    """Gerencia autenticacao do usuario."""

    def login(self, username: str, password: str, org_slug: str = "") -> dict:
        """
        Autentica usuario e armazena token.
        O token e persistido localmente para auto-login.
        org_slug identifica o banco da org (campo client_id do OAuth2).
        """
        slug = org_slug.strip() or get_org_slug()
        response = api.post(
            "/auth/token",
            form_data={
                "username": username,
                "password": password,
                "client_id": slug,
            },
        )

        token = response.get("access_token")
        api.token = token
        set_token(token)
        if slug:
            set_org_slug(slug)

        return response

    def logout(self) -> None:
        """Limpa token e encerra sessao. Preserva org_slug para facilitar re-login."""
        api.token = None
        set_token(None)

    def get_current_user(self) -> dict:
        """Retorna dados do usuario autenticado."""
        return api.get("/auth/me")

    def is_authenticated(self) -> bool:
        """Verifica se usuario esta autenticado."""
        return api.is_authenticated()

    def try_restore_session(self) -> bool:
        """
        Tenta restaurar sessao a partir do token salvo.
        Returns: True se sessao restaurada com sucesso.
        """
        saved_token = get_token()
        if not saved_token:
            return False

        api.token = saved_token
        try:
            self.get_current_user()
            return True
        except APIError:
            api.token = None
            set_token(None)
            return False
        except Exception as err:
            print(f"[AuthService] restore_session_error err={err}")
            api.token = None
            return False

    def change_password(self, current_password: str, new_password: str) -> dict:
        """
        Troca a senha do usuario.
        Necessario no primeiro login quando must_change_password=true.
        """
        return api.post(
            "/auth/change-password",
            data={
                "current_password": current_password,
                "new_password": new_password,
            },
        )

    def register(
        self,
        username: str,
        email: str,
        password: str,
        full_name: str,
        role: str = "operator",
        scopes: list[str] | None = None,
    ) -> dict:
        """Registra novo operador na org. Requer role master."""
        return api.post(
            "/auth/register",
            data={
                "username": username,
                "email": email,
                "password": password,
                "full_name": full_name,
                "role": role,
                "scopes": list(scopes or []),
            },
        )

    def update_profile(self, **fields) -> dict:
        """Atualiza dados de perfil do usuario autenticado."""
        return api.patch("/auth/me", data={k: v for k, v in fields.items() if v is not None})

    def upload_avatar(self, file_path: str) -> dict:
        """Faz upload de avatar. Retorna UserResponse atualizado."""
        return api.post_file("/auth/me/avatar", file_path=file_path, field="file")

    def delete_avatar(self) -> dict:
        """Remove avatar do usuario."""
        return api.delete("/auth/me/avatar")

    def list_users(self) -> list[dict]:
        """Lista todos os usuarios da org. Requer role master."""
        return api.get("/auth/users")

    def toggle_user_active(self, username: str) -> dict:
        """Ativa ou desativa um usuario. Requer role master."""
        return api.patch(f"/auth/users/{username}/toggle-active", data={})


# Instancia global
auth_service = AuthService()
