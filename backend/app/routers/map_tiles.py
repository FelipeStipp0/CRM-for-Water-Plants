"""
Proxy de tiles Mapbox Styles API + endpoints GeoJSON por org.

GeoJSON armazenado no Cloudflare R2: geojson/{org_slug}/manzanas.geojson
Cache em memória por org (invalidado no upload).
"""
import asyncio
import json
from datetime import date
from typing import Annotated

import httpx
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, HTTPException, Path as FPath, UploadFile, status
from fastapi.responses import JSONResponse, Response

from app.config import get_settings
from app.middleware.org_context import require_org_slug
from app.models.user import User
from app.routers.auth import get_current_active_user, get_current_master
from app.utils.r2 import get_r2_client, geojson_key, r2_get, r2_put

router = APIRouter()

_TILE_URL = (
    # 256px sem @2x: o TileLayer usa tileSize=256, então o @2x (512px) só gerava
    # ~4x mais bytes por tile e downscale na CPU do cliente — lentidão pura.
    "https://api.mapbox.com/styles/v1/{username}/{style_id}/tiles/256/{z}/{x}/{y}"
    "?access_token={token}"
)

_http_client: httpx.AsyncClient | None = None
_tile_cache: dict[str, bytes] = {}
_tile_semaphore: asyncio.Semaphore | None = None

# Cache GeoJSON em memória por org — invalidado no upload
_geojson_cache: dict[str, dict] = {}


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        _http_client = httpx.AsyncClient(timeout=15.0, follow_redirects=True, limits=limits)
    return _http_client


def get_semaphore() -> asyncio.Semaphore:
    global _tile_semaphore
    if _tile_semaphore is None:
        _tile_semaphore = asyncio.Semaphore(10)
    return _tile_semaphore


async def _load_geojson(org_slug: str) -> dict:
    """Carrega GeoJSON do R2 para a org, usando cache em memória."""
    if org_slug in _geojson_cache:
        return _geojson_cache[org_slug]

    r2 = get_r2_client()
    if r2 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="R2 não configurado no servidor.",
        )

    try:
        raw = r2_get(geojson_key(org_slug))
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no_geojson",
            )
        raise HTTPException(status_code=502, detail=f"Erro ao acessar R2: {e}")

    data = json.loads(raw.decode("utf-8"))
    _geojson_cache[org_slug] = data
    return data


def _compute_bounds(geojson: dict) -> dict:
    all_lats, all_lons = [], []
    for feature in geojson["features"]:
        for polygon in feature["geometry"]["coordinates"]:
            for pt in polygon[0]:
                all_lons.append(pt[0])
                all_lats.append(pt[1])

    min_lat, max_lat = min(all_lats), max(all_lats)
    min_lon, max_lon = min(all_lons), max(all_lons)
    return {
        "center_lat": (min_lat + max_lat) / 2,
        "center_lon": (min_lon + max_lon) / 2,
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }


# ------------------------------------------------------------------
# Tiles
# ------------------------------------------------------------------

@router.get("/tile-config")
async def tile_config(current_user=Depends(get_current_active_user)):
    """
    Retorna o template de URL de tiles DIRETO do Mapbox (CDN), para o cliente
    buscar os tiles sem passar pelo proxy do backend — elimina o salto duplo
    (Flet -> backend -> Mapbox -> backend -> Flet) que tornava o mapa lento.

    Exige autenticação para não expor o token publicamente.
    """
    settings = get_settings()
    if not settings.mapbox_token:
        raise HTTPException(status_code=503, detail="MAPBOX_TOKEN não configurado.")
    url = (
        f"https://api.mapbox.com/styles/v1/{settings.mapbox_username}/"
        f"{settings.mapbox_style}/tiles/256/{{z}}/{{x}}/{{y}}"
        f"?access_token={settings.mapbox_token}"
    )
    return {"url_template": url}


@router.get("/tiles/{z}/{x}/{y}", include_in_schema=False)
async def map_tile_proxy(
    z: int = FPath(..., ge=0, le=22),
    x: int = FPath(..., ge=0),
    y: int = FPath(..., ge=0),
):
    cache_key = f"{z}/{x}/{y}"
    if cache_key in _tile_cache:
        return Response(
            content=_tile_cache[cache_key],
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    settings = get_settings()
    if not settings.mapbox_token:
        raise HTTPException(status_code=503, detail="MAPBOX_TOKEN não configurado.")

    url = _TILE_URL.format(
        username=settings.mapbox_username,
        style_id=settings.mapbox_style,
        z=z, x=x, y=y,
        token=settings.mapbox_token,
    )

    async with get_semaphore():
        try:
            resp = await get_http_client().get(url)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Erro ao buscar tile: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Tile não encontrado.")

    _tile_cache[cache_key] = resp.content
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/png"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ------------------------------------------------------------------
# GeoJSON
# ------------------------------------------------------------------

@router.get("/geojson/status", tags=["Mapa"])
async def geojson_status(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna se a org tem GeoJSON configurado no R2."""
    org_slug = require_org_slug()
    r2 = get_r2_client()
    if r2 is None:
        return {"has_geojson": False, "reason": "r2_not_configured"}
    try:
        r2_get(geojson_key(org_slug))
        return {"has_geojson": True}
    except ClientError:
        return {"has_geojson": False, "reason": "no_geojson"}


@router.get("/bounds", tags=["Mapa"])
async def get_geojson_bounds(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna centroide e bbox do GeoJSON da org."""
    org_slug = require_org_slug()
    geojson = await _load_geojson(org_slug)
    return _compute_bounds(geojson)


@router.get("/geojson", tags=["Mapa"])
async def get_manzanas_geojson(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna GeoJSON das manzanas da org. 404 com detail='no_geojson' se não houver."""
    org_slug = require_org_slug()
    geojson = await _load_geojson(org_slug)
    return JSONResponse(
        content=geojson,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.post("/geojson/upload", tags=["Mapa"], status_code=status.HTTP_201_CREATED)
async def upload_geojson(
    current_user: Annotated[User, Depends(get_current_master)],
    file: UploadFile = File(...),
):
    """
    Faz upload do GeoJSON da org para o R2.
    Aceita apenas application/json ou .geojson. Máx 20 MB.
    Requer role master.
    """
    org_slug = require_org_slug()

    content_type = file.content_type or ""
    filename = file.filename or ""
    if content_type not in ("application/json", "application/geo+json") \
            and not filename.endswith(".geojson"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato inválido. Envie um arquivo .geojson.",
        )

    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo muito grande. Máximo 20 MB.",
        )

    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JSON inválido.",
        )

    if data.get("type") != "FeatureCollection":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GeoJSON deve ser do tipo FeatureCollection.",
        )

    r2 = get_r2_client()
    if r2 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="R2 não configurado no servidor.",
        )

    r2_put(geojson_key(org_slug), raw, content_type="application/geo+json")

    # Invalida cache em memória
    _geojson_cache.pop(org_slug, None)

    return {
        "ok": True,
        "features": len(data.get("features", [])),
        "key": geojson_key(org_slug),
    }


# ------------------------------------------------------------------
# Edição de features (persiste no R2)
# ------------------------------------------------------------------

async def _save_geojson(org_slug: str, data: dict) -> None:
    """Salva GeoJSON atualizado no R2 e atualiza cache."""
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    r2_put(geojson_key(org_slug), raw, content_type="application/geo+json")
    _geojson_cache[org_slug] = data


@router.put("/geojson/feature/{feat_id}/code", tags=["Mapa"])
async def update_feature_code(
    feat_id: int,
    code: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Atualiza o CODE de uma feature pelo FeatId1. Persiste no R2."""
    org_slug = require_org_slug()
    geojson = await _load_geojson(org_slug)

    for feature in geojson["features"]:
        if feature["properties"].get("FeatId1") == feat_id:
            feature["properties"]["CODE"] = code
            await _save_geojson(org_slug, geojson)
            return {"ok": True, "feat_id": feat_id, "code": code}

    raise HTTPException(status_code=404, detail=f"Feature {feat_id} não encontrada.")


@router.post("/geojson/manzana/{manzana}/generate-codes", tags=["Mapa"])
async def generate_manzana_codes(
    manzana: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Gera CODEs sequenciais para lotes sem CODE. Persiste no R2."""
    org_slug = require_org_slug()
    geojson = await _load_geojson(org_slug)

    existing = set()
    for f in geojson["features"]:
        code = f["properties"].get("CODE") or ""
        if code.startswith(f"{manzana}-"):
            try:
                existing.add(int(code.split("-")[1]))
            except (IndexError, ValueError):
                pass

    counter = 1
    updated = []
    for feature in geojson["features"]:
        code = feature["properties"].get("CODE") or ""
        feat_id = feature["properties"].get("FeatId1")
        if not code or code == "None":
            while counter in existing:
                counter += 1
            new_code = f"{manzana}-{counter:02d}"
            feature["properties"]["CODE"] = new_code
            existing.add(counter)
            updated.append({"feat_id": feat_id, "code": new_code})
            counter += 1

    if updated:
        await _save_geojson(org_slug, geojson)

    return {"manzana": manzana, "updated": updated}


# ------------------------------------------------------------------
# Overdue por código (sem alterações)
# ------------------------------------------------------------------

@router.get("/overdue-by-code", tags=["Mapa"])
async def get_overdue_by_code(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna lotes com atraso calculado das faturas pendentes."""
    from app.models.client import Client
    from app.models.invoice import Invoice, InvoiceStatus

    today = date.today()

    pending = await Invoice.find(
        {"status": {"$in": [InvoiceStatus.PENDENTE.value, InvoiceStatus.PARCIAL.value]}}
    ).to_list()

    oldest_by_client: dict = {}
    for inv in pending:
        if inv.fecha_vencimiento and inv.fecha_vencimiento < today:
            cid = str(inv.client.ref.id)
            if cid not in oldest_by_client or inv.fecha_vencimiento < oldest_by_client[cid]:
                oldest_by_client[cid] = inv.fecha_vencimiento

    if not oldest_by_client:
        return []

    from beanie import PydanticObjectId
    client_ids = [PydanticObjectId(cid) for cid in oldest_by_client]
    clients = await Client.find({"_id": {"$in": client_ids}}).to_list()

    result = []
    for client in clients:
        cid = str(client.id)
        oldest = oldest_by_client.get(cid)
        if not oldest:
            continue
        months = (today.year - oldest.year) * 12 + (today.month - oldest.month)
        code = f"{client.manzana}-{client.lote}"
        result.append({
            "code": code,
            "client_id": cid,
            "meses_atraso": months,
            "fecha_vencimiento_mais_antiga": oldest.isoformat(),
        })

    return result
