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
from pydantic import BaseModel

from app.config import get_settings
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, UserProfileUpdate, UserAdminUpdate, Token, PasswordChange
from app.utils.security import (
    verify_password,
    get_password_hash,
    generate_temp_password,
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


# Escopos que arrastam outros: conceder o escopo "pai" já libera tudo o que aquele
# modo de trabalho precisa para funcionar. O Modo Caja é um app inteiro (busca de
# cliente, cobro, recibo, histórico, reativação, factura electrónica) — exigir que
# o master marque cinco caixinhas extras só faz o cajero tomar 403 no meio do
# atendimento. Isto NÃO é gravado no usuário: `user.scopes` continua ["caja"], que
# é o que o frontend usa para decidir o boot em tela cheia.
SCOPES_IMPLICITOS: dict[str, tuple[str, ...]] = {
    "caja": ("clients", "payments", "readings", "cutoff", "sifen"),
}


def escopos_efetivos(scopes: list[str]) -> set[str]:
    """Expande os escopos do usuario com os que eles arrastam."""
    efetivos = set(scopes)
    for scope in scopes:
        efetivos.update(SCOPES_IMPLICITOS.get(scope, ()))
    return efetivos


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

        concedidos = escopos_efetivos(current_user.scopes)
        if any(scope in concedidos for scope in required_scopes):
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

    # A senha é gerada AQUI, não escolhida pelo master. Ele não deve conhecer a
    # credencial de outra pessoa — e com o convite por email ativo, seria a senha
    # dele viajando por email. O usuário troca no primeiro acesso.
    senha = generate_temp_password()
    user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(senha),
        full_name=user_data.full_name,
        role=user_data.role,
        scopes=user_data.scopes,
        must_change_password=True,
    )
    await user.insert()

    # Convite por email. Best-effort: o usuário já está criado e falha de email
    # não pode desfazer isso. Mas se não foi, ALGUÉM precisa da senha — devolvemos
    # ao master só nesse caso, para ele repassar por outro canal. No caminho feliz
    # o master nunca a vê.
    from app.middleware.org_context import get_org_slug
    from app.services.email import enviar_convite_operador
    enviado = False
    try:
        enviado = await enviar_convite_operador(
            para=user.email, nombre=user.full_name,
            org_slug=get_org_slug() or "", username=user.username,
            senha_temporal=senha, convidado_por=current_user.full_name,
        )
    except Exception as err:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error("[register] convite nao enviado: %s", err)

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
        invite_sent=enviado,
        temp_password=None if enviado else senha,
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


# Catálogo de escopos — FONTE ÚNICA. A UI monta os checkboxes a partir daqui, em
# vez de manter uma lista paralela: era assim que "Caja" acabou gravando o escopo
# `payments` (o operador ia parar em Pagamentos em vez do Modo Caja), que `caja` e
# `sifen` nunca puderam ser concedidos, e que `settings` aparecia sem existir —
# Configuración é gateada por role master, não por escopo.
SCOPES_DISPONIVEIS: list[dict] = [
    {"scope": "clients", "label": "Clientes"},
    {"scope": "readings", "label": "Lecturas"},
    {"scope": "invoices", "label": "Facturación"},
    {"scope": "payments", "label": "Pagos"},
    {"scope": "caja", "label": "Modo Caja (cajero)"},
    {"scope": "cutoff", "label": "Corte y reactivación"},
    {"scope": "finance", "label": "Finanzas"},
    {"scope": "sponsors", "label": "Subsidios"},
    {"scope": "sifen", "label": "Facturación electrónica"},
    {"scope": "*", "label": "Acceso total"},
]


@router.get("/scopes")
async def listar_scopes(
    current_user: Annotated[User, Depends(get_current_master)],
):
    """Escopos concedíveis. A UI usa isto para montar a tela de permissões."""
    return SCOPES_DISPONIVEIS


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


@router.patch("/users/{username}", response_model=UserResponse)
async def update_user(
    username: str,
    body: UserAdminUpdate,
    current_user: Annotated[User, Depends(get_current_master)],
):
    """
    Edita cargo, permissões e dados de um usuário. Requer master.

    É o caminho da promoção: um operador vira master, ou ganha/perde módulos,
    sem precisar recriar a conta (o que perderia o histórico dele).
    """
    user = await User.find_one(User.username == username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado")

    dados = body.model_dump(exclude_none=True)

    # Rebaixar a si mesmo tranca a org: sem master ninguém edita mais ninguém.
    if username == current_user.username and dados.get("role") == "operator":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No podés quitarte el rol master a vos mismo.",
        )
    if dados.get("role") == "master":
        dados["scopes"] = ["*"]          # master tem tudo por definição
    elif dados.get("role") == "operator" and not dados.get("scopes"):
        dados["scopes"] = [s for s in user.scopes if s != "*"]

    if dados.get("email") and dados["email"] != user.email:
        if await User.find_one(User.email == dados["email"]):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Email ya usado por otro usuario")

    from datetime import datetime
    dados["updated_at"] = datetime.utcnow()
    await user.update({"$set": dados})
    for k, v in dados.items():
        setattr(user, k, v)
    return _user_response(user)


@router.post("/users/{username}/reset-password", response_model=UserResponse)
async def reset_user_password(
    username: str,
    current_user: Annotated[User, Depends(get_current_master)],
):
    """
    Gera uma senha temporária nova e envia ao usuário. Requer master.

    É o que resolve "esqueci a senha" e "o convite não chegou" sem o master
    precisar conhecer a credencial. Ele só vê a senha se o email falhar.
    """
    user = await User.find_one(User.username == username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado")

    senha = generate_temp_password()
    from datetime import datetime
    await user.update({"$set": {
        "hashed_password": get_password_hash(senha),
        "must_change_password": True,
        "updated_at": datetime.utcnow(),
    }})
    user.must_change_password = True

    from app.middleware.org_context import get_org_slug
    from app.services.email import enviar_convite_operador
    enviado = False
    try:
        enviado = await enviar_convite_operador(
            para=user.email, nombre=user.full_name,
            org_slug=get_org_slug() or "", username=user.username,
            senha_temporal=senha, convidado_por=current_user.full_name,
        )
    except Exception as err:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error("[reset] envio falhou: %s", err)

    resp = _user_response(user)
    resp.invite_sent = enviado
    resp.temp_password = None if enviado else senha
    return resp


@router.delete("/users/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    username: str,
    current_user: Annotated[User, Depends(get_current_master)],
):
    """
    Remove um usuário. Requer master.

    Duas travas: não dá para se autoexcluir, nem para remover o último master —
    qualquer uma das duas deixaria a org sem quem administra.
    """
    if username == current_user.username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No podés eliminar tu propio usuario.")

    user = await User.find_one(User.username == username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado")

    if user.role == "master" and await User.find(User.role == "master").count() <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Es el último master: la organización quedaría sin administrador.")

    await user.delete()


class PasswordCheck(BaseModel):
    """Confirmação de identidade sem emitir token novo."""
    password: str


@router.post("/verify-password")
async def verify_own_password(
    body: PasswordCheck,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Confirma a senha do próprio usuário autenticado.

    Usado pela pausa do Modo Caja: o cajero sai do balcão com o turno aberto e a
    tela trancada, e quem destranca tem de ser ele — a gaveta continua no nome
    dele até o cierre. Não emite token nem muda nada; só responde sim ou não.

    Senha errada devolve **200 com `ok: false`**, não 401: o cliente trata 401
    como sessão expirada e derrubaria o login inteiro — errar a senha na tela de
    pausa não pode fechar o turno de quem só digitou torto.
    """
    ok = verify_password(body.password, current_user.hashed_password)
    return {"ok": bool(ok), "username": current_user.username}


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
