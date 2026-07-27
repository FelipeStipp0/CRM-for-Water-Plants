"""
Endpoints do Titular — a pessoa por trás de uma ou mais ligações.

O que o operador faz por aqui: acha o titular, vê todas as casas dele e
acrescenta uma residência nova sem redigitar nome, documento e telefone.

A ligação continua sendo o `Client` (medidor, leitura, fatura, corte); o titular
só agrupa. Usa o escopo `clients` de propósito: quem cadastra cliente cadastra
titular, não faz sentido separar a permissão.
"""

from datetime import datetime
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.client import Client, ClientCategory
from app.models.titular import Titular
from app.models.user import User
from app.routers.auth import get_current_active_user, require_scopes
from app.routers.clients import client_to_response
from app.schemas.client import ClientResponse

router = APIRouter(dependencies=[Depends(require_scopes("clients"))])


# ------------------------------- schemas -------------------------------

class TitularIn(BaseModel):
    nombre_completo: str = Field(min_length=2, max_length=200)
    ci_ruc: str = Field(min_length=3, max_length=20)
    telefono: Optional[str] = None
    celular: Optional[str] = None
    email: Optional[str] = None
    observaciones: Optional[str] = None


class TitularUpdate(BaseModel):
    nombre_completo: Optional[str] = None
    ci_ruc: Optional[str] = None
    telefono: Optional[str] = None
    celular: Optional[str] = None
    email: Optional[str] = None
    observaciones: Optional[str] = None


class TitularOut(BaseModel):
    id: str
    nombre_completo: str
    ci_ruc: str
    es_contribuyente: Optional[bool] = None
    telefono: Optional[str] = None
    celular: Optional[str] = None
    email: Optional[str] = None
    observaciones: Optional[str] = None
    total_conexiones: int = 0
    created_at: datetime

    @classmethod
    def of(cls, t: Titular, total: int = 0) -> "TitularOut":
        return cls(
            id=str(t.id), nombre_completo=t.nombre_completo, ci_ruc=t.ci_ruc,
            es_contribuyente=t.es_contribuyente, telefono=t.telefono,
            celular=t.celular, email=t.email, observaciones=t.observaciones,
            total_conexiones=total, created_at=t.created_at,
        )


class ResidenciaIn(BaseModel):
    """Ligação nova de um titular já existente — só o que muda de casa para casa."""
    direccion: str = Field(min_length=5, max_length=300)
    manzana: str = Field(default="", max_length=10)
    lote: str = Field(default="", max_length=10)
    numero_medidor: str = Field(default="SIN_MEDIDOR", min_length=1, max_length=50)
    categoria: ClientCategory = ClientCategory.RESIDENCIAL
    # etiqueta opcional ("Casa 02", "Chalé") — some no nome se vazia
    etiqueta: Optional[str] = Field(default=None, max_length=60)
    is_aluguel: bool = False
    instalacao_latitude: Optional[float] = None
    instalacao_longitude: Optional[float] = None


# ------------------------------- endpoints -------------------------------

async def _get(titular_id: PydanticObjectId) -> Titular:
    t = await Titular.get(titular_id)
    if not t:
        raise HTTPException(404, "Titular no encontrado")
    return t


@router.get("/", response_model=List[TitularOut])
async def listar_titulares(
    current_user: Annotated[User, Depends(get_current_active_user)],
    q: Optional[str] = Query(None, description="nome ou documento"),
    limit: int = Query(50, ge=1, le=200),
):
    if q:
        busca = Titular.find({"$or": [
            {"nombre_completo": {"$regex": q, "$options": "i"}},
            {"ci_ruc": {"$regex": q, "$options": "i"}},
        ]})
    else:
        busca = Titular.find()
    titulares = await busca.sort(Titular.nombre_completo).limit(limit).to_list()
    # contagem em lote: um titular por request seria N+1 na tela de busca
    ids = [t.id for t in titulares]
    contagem = {}
    if ids:
        cur = Client.get_pymongo_collection().aggregate([
            {"$match": {"titular_id": {"$in": ids}}},
            {"$group": {"_id": "$titular_id", "n": {"$sum": 1}}},
        ])
        contagem = {d["_id"]: d["n"] async for d in cur}
    return [TitularOut.of(t, contagem.get(t.id, 0)) for t in titulares]


@router.get("/{titular_id}", response_model=TitularOut)
async def obter_titular(
    titular_id: PydanticObjectId,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    t = await _get(titular_id)
    total = await Client.find(Client.titular_id == t.id).count()
    return TitularOut.of(t, total)


@router.get("/{titular_id}/conexiones", response_model=List[ClientResponse])
async def listar_conexiones(
    titular_id: PydanticObjectId,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Todas as ligações do titular — é o «otras casas de esta persona»."""
    await _get(titular_id)
    clientes = await Client.find(Client.titular_id == titular_id).to_list()
    return [client_to_response(c) for c in clientes]


@router.post("/", response_model=TitularOut, status_code=status.HTTP_201_CREATED)
async def criar_titular(
    body: TitularIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    t = Titular(**body.model_dump())
    await t.insert()
    return TitularOut.of(t, 0)


@router.patch("/{titular_id}", response_model=TitularOut)
async def atualizar_titular(
    titular_id: PydanticObjectId,
    body: TitularUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    t = await _get(titular_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(t, k, v)
    t.updated_at = datetime.utcnow()
    await t.save()
    return TitularOut.of(t, await Client.find(Client.titular_id == t.id).count())


@router.post("/{titular_id}/residencias", response_model=ClientResponse,
             status_code=status.HTTP_201_CREATED)
async def agregar_residencia(
    titular_id: PydanticObjectId,
    body: ResidenciaIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Cria uma ligação nova para um titular existente.

    Nome, documento e contato vêm do titular — é justamente o que o operador não
    deveria redigitar. A etiqueta ("Casa 02") entra no nome da ligação, que é o
    que aparece nas listas de leitura e de corte.
    """
    t = await _get(titular_id)
    dados = body.model_dump()
    etiqueta = (dados.pop("etiqueta", None) or "").strip()

    cliente = Client(
        nombre_completo=f"{t.nombre_completo} - {etiqueta}" if etiqueta else t.nombre_completo,
        ci_ruc=t.ci_ruc,
        es_contribuyente=t.es_contribuyente,
        telefono=t.telefono,
        celular=t.celular,
        email=t.email,
        titular_id=t.id,
        **dados,
    )
    await cliente.insert()
    return client_to_response(cliente)
