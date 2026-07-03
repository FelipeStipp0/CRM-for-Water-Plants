"""
Endpoints de autenticacao.

Fluxo multi-tenant:
- Login recebe org_slug no form (campo client_id do OAuth2PasswordRequestForm)
- JWT carrega: sub (username), org (org_slug), role
- get_current_user ativa o database da org antes de buscar o usuario
"""

from datetime import timedelta
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from app.config import get_settings
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, UserProfileUpdate, Token, PasswordChange
from app.utils.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_access_token,
)

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    """
    Extrai e valida o usuario do token JWT.
    Ativa o database da org antes de buscar o usuario.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    username: str = payload.get("sub")
    org_slug: str = payload.get("org")

    if not username or not org_slug:
        raise credentials_exception

    # Ativa o database da org para este request
    from app.middleware.org_context import activate_org_db
    await activate_org_db(org_slug)

    user = await User.find_one(User.username == username)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inativo"
        )

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    """
    Exige usuario ativo SEM pendencia de troca de senha.
    Use em todos os endpoints protegidos normais.
    """
    if current_user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Troca de senha obrigatoria. Use POST /auth/change-password"
        )
    return current_user


async def get_current_master(
    current_user: Annotated[User, Depends(get_current_active_user)]
) -> User:
    """Exige role master (admin da org)."""
    if current_user.role != "master":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissao insuficiente. Requer role master."
        )
    return current_user


def require_scopes(*required_scopes: str) -> Callable:
    """
    Cria dependencia que exige pelo menos um dos escopos informados.
    Master sempre tem acesso total.
    """
    async def dependency(
        current_user: Annotated[User, Depends(get_current_active_user)]
    ) -> User:
        if current_user.role == "master" or "*" in current_user.scopes:
            return current_user

        if any(scope in current_user.scopes for scope in required_scopes):
            return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissao insuficiente para este modulo",
        )

    return dependency


@router.post("/token", response_model=Token)
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """
    Autentica usuario e retorna token JWT.

    O campo 'client_id' do formulario OAuth2 e usado para passar o org_slug.

    IMPORTANTE para Frontend:
    - Enviar: username, password, client_id=org_slug
    - Se must_change_password = True, forcar tela de troca de senha
    """
    org_slug = form_data.client_id
    if not org_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="org_slug e obrigatorio (campo client_id)",
        )

    # Ativa o database da org
    from app.middleware.org_context import activate_org_db
    from app.models.organization import Organization

    # Verifica se a org existe no wmapp_admin (ja inicializado no startup)
    org = await Organization.find_one(Organization.slug == org_slug)
    if not org or not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Organizacao nao encontrada ou inativa",
        )

    await activate_org_db(org_slug)

    user = await User.find_one(User.username == form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais invalidas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inativo"
        )

    settings = get_settings()
    access_token = create_access_token(
        data={"sub": user.username, "org": org_slug, "role": user.role},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
    )

    return Token(
        access_token=access_token,
        must_change_password=user.must_change_password,
        scopes=user.scopes,
        role=user.role,
        org_slug=org_slug,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    current_user: Annotated[User, Depends(get_current_master)],
):
    """
    Registra um novo operador na org. Requer role master.
    O novo usuario recebe must_change_password=True e deve trocar a senha no primeiro acesso.
    """
    existing = await User.find_one({
        "$or": [
            {"username": user_data.username},
            {"email": user_data.email}
        ]
    })
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username ou email ja cadastrado"
        )

    user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        role=user_data.role,
        scopes=user_data.scopes,
        must_change_password=True,
    )
    await user.insert()

    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        role=user.role,
        must_change_password=user.must_change_password,
        scopes=user.scopes,
        created_at=user.created_at,
    )


def _user_response(u: User) -> UserResponse:
    return UserResponse(
        id=str(u.id),
        username=u.username,
        email=u.email,
        full_name=u.full_name,
        is_active=u.is_active,
        role=u.role,
        must_change_password=u.must_change_password,
        scopes=u.scopes,
        phone=u.phone,
        position=u.position,
        language=u.language,
        avatar_base64=u.avatar_base64,
        avatar_mime=u.avatar_mime,
        created_at=u.created_at,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    """Retorna dados do usuario autenticado."""
    return _user_response(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    data: UserProfileUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Atualiza dados de perfil do usuario autenticado."""
    from datetime import datetime

    updates: dict = {}
    if data.full_name is not None:
        updates["full_name"] = data.full_name
    if data.phone is not None:
        updates["phone"] = data.phone
    if data.position is not None:
        updates["position"] = data.position
    if data.language is not None:
        updates["language"] = data.language
    if data.email is not None and data.email != current_user.email:
        existing = await User.find_one(User.email == data.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email ya está en uso"
            )
        updates["email"] = data.email

    if updates:
        updates["updated_at"] = datetime.utcnow()
        await current_user.update({"$set": updates})
        for k, v in updates.items():
            setattr(current_user, k, v)

    return _user_response(current_user)


@router.post("/me/avatar", response_model=UserResponse)
async def upload_avatar(
    current_user: Annotated[User, Depends(get_current_active_user)],
    file: UploadFile = File(...),
):
    """Faz upload de avatar em base64. Aceita PNG/JPG/WebP, máx 500 KB."""
    import base64
    from datetime import datetime

    content_type = file.content_type or ""
    if content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Formato invalido. Use PNG, JPG ou WebP.")

    raw = await file.read()
    if len(raw) > 500 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Imagem muito grande. Maximo 500 KB.")

    b64 = base64.b64encode(raw).decode()
    await current_user.update({"$set": {
        "avatar_base64": b64,
        "avatar_mime": content_type,
        "updated_at": datetime.utcnow(),
    }})
    current_user.avatar_base64 = b64
    current_user.avatar_mime = content_type

    return _user_response(current_user)


@router.delete("/me/avatar", response_model=UserResponse)
async def delete_avatar(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Remove o avatar do usuario."""
    from datetime import datetime
    await current_user.update({"$set": {"avatar_base64": None, "avatar_mime": None, "updated_at": datetime.utcnow()}})
    current_user.avatar_base64 = None
    current_user.avatar_mime = None
    return _user_response(current_user)


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    current_user: Annotated[User, Depends(get_current_master)],
):
    """Lista todos os usuarios da org. Requer role master."""
    users = await User.find_all().to_list()
    return [_user_response(u) for u in users]


@router.patch("/users/{username}/toggle-active", response_model=UserResponse)
async def toggle_user_active(
    username: str,
    current_user: Annotated[User, Depends(get_current_master)],
):
    """Ativa ou desativa um usuario da org. Requer role master."""
    if username == current_user.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e possivel desativar seu proprio usuario"
        )

    user = await User.find_one(User.username == username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado")

    from datetime import datetime
    new_active = not user.is_active
    await user.update({"$set": {"is_active": new_active, "updated_at": datetime.utcnow()}})
    user.is_active = new_active

    return _user_response(user)


@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Troca a senha do usuario autenticado.
    Acessivel mesmo quando must_change_password = True.
    """
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta"
        )

    if password_data.current_password == password_data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nova senha deve ser diferente da atual"
        )

    from datetime import datetime
    await current_user.update({
        "$set": {
            "hashed_password": get_password_hash(password_data.new_password),
            "must_change_password": False,
            "updated_at": datetime.utcnow(),
        }
    })

    return {"message": "Senha alterada com sucesso"}
