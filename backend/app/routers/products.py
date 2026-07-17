"""
Endpoints do catálogo de produtos/serviços.

CRUD simples usado pela fatura manual avulsa e pela facturación electrónica.
Código sequencial automático (Counter "product_code") se não for informado.
"""

from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.product import Product
from app.models.invoice import Counter
from app.routers.auth import require_scopes
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse

router = APIRouter(dependencies=[Depends(require_scopes("invoices"))])


def _to_response(p: Product) -> ProductResponse:
    return ProductResponse(
        id=str(p.id), codigo=p.codigo, descripcion=p.descripcion,
        precio_unitario=p.precio_unitario, iva_tasa=p.iva_tasa,
        iva_afectacion=p.iva_afectacion, unidad=p.unidad, activo=p.activo,
        created_at=p.created_at, updated_at=p.updated_at,
    )


async def _next_codigo() -> str:
    seq = await Counter.get_next("product_code")
    return f"{seq:04d}"


@router.get("/", response_model=List[ProductResponse])
async def listar_produtos(activo: Optional[bool] = Query(default=None)):
    query = Product.find()
    if activo is not None:
        query = Product.find(Product.activo == activo)
    produtos = await query.sort("codigo").to_list()
    return [_to_response(p) for p in produtos]


@router.post("/", response_model=ProductResponse, status_code=201)
async def criar_produto(body: ProductCreate):
    codigo = (body.codigo or "").strip() or await _next_codigo()
    if await Product.find_one(Product.codigo == codigo):
        raise HTTPException(status_code=400, detail=f"Código '{codigo}' ya está en uso.")
    p = Product(
        codigo=codigo, descripcion=body.descripcion.strip(),
        precio_unitario=body.precio_unitario, iva_tasa=body.iva_tasa,
        iva_afectacion=body.iva_afectacion, unidad=body.unidad, activo=body.activo,
    )
    await p.insert()
    return _to_response(p)


@router.patch("/{product_id}", response_model=ProductResponse)
async def atualizar_produto(product_id: PydanticObjectId, body: ProductUpdate):
    p = await Product.get(product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    data = body.model_dump(exclude_unset=True)
    if "codigo" in data:
        novo = (data["codigo"] or "").strip()
        if novo and novo != p.codigo:
            if await Product.find_one(Product.codigo == novo):
                raise HTTPException(status_code=400, detail=f"Código '{novo}' ya está en uso.")
            p.codigo = novo
        data.pop("codigo")
    for k, v in data.items():
        setattr(p, k, v)
    p.updated_at = datetime.utcnow()
    await p.save()
    return _to_response(p)


@router.delete("/{product_id}", status_code=204)
async def desativar_produto(product_id: PydanticObjectId):
    """Soft delete: marca como inativo (não remove — pode estar em faturas)."""
    p = await Product.get(product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    p.activo = False
    p.updated_at = datetime.utcnow()
    await p.save()
