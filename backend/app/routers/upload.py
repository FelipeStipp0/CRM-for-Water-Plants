"""
Endpoint de upload de fotos para Cloudflare R2 (S3-compatible).

Aceita imagens JPEG/PNG, extrai GPS do EXIF (se presente),
e envia ao bucket R2. Retorna URL publica + coordenadas GPS.

Se R2 nao estiver configurado, retorna 503.
"""

import io
from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app.config import get_settings
from app.models.user import User
from app.routers.auth import get_current_active_user, require_scopes
from app.utils.r2 import get_r2_client

router = APIRouter(dependencies=[Depends(require_scopes("readings"))])

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

TIPO_FOLDERS = {
    "medidor": "medidores",
    "lectura": "lecturas",
    "instalacao": "instalacoes",
    "corte": "cortes",
    "reativacao": "reativacoes",
}


class UploadResponse(BaseModel):
    url: str
    filename: str
    gps: Optional[dict] = None
    size_bytes: int


class GpsCoords(BaseModel):
    latitude: float
    longitude: float


def _get_s3_client():
    return get_r2_client()


def _extract_gps_from_exif(file_bytes: bytes) -> Optional[dict]:
    """Extrai coordenadas GPS dos metadados EXIF da imagem."""
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS

        image = Image.open(io.BytesIO(file_bytes))
        exif_data = image._getexif()
        if not exif_data:
            return None

        gps_info = {}
        for tag_id, value in exif_data.items():
            tag_name = TAGS.get(tag_id, tag_id)
            if tag_name == "GPSInfo":
                for gps_tag_id, gps_value in value.items():
                    gps_tag_name = GPSTAGS.get(gps_tag_id, gps_tag_id)
                    gps_info[gps_tag_name] = gps_value
                break

        if not gps_info:
            return None

        def _to_degrees(values) -> float:
            """Converte coordenada GPS EXIF (graus, minutos, segundos) para decimal."""
            d = float(values[0])
            m = float(values[1])
            s = float(values[2])
            return d + (m / 60.0) + (s / 3600.0)

        lat = gps_info.get("GPSLatitude")
        lat_ref = gps_info.get("GPSLatitudeRef")
        lon = gps_info.get("GPSLongitude")
        lon_ref = gps_info.get("GPSLongitudeRef")

        if not lat or not lon:
            return None

        latitude = _to_degrees(lat)
        longitude = _to_degrees(lon)

        if lat_ref == "S":
            latitude = -latitude
        if lon_ref == "W":
            longitude = -longitude

        return {"latitude": latitude, "longitude": longitude}

    except Exception:
        return None


@router.post("/photo", response_model=UploadResponse)
async def upload_photo(
    current_user: User = Depends(get_current_active_user),
    file: UploadFile = File(...),
    tipo: str = Query(..., pattern=r"^(medidor|lectura|instalacao|corte|reativacao)$"),
):
    """
    Upload de foto para R2.

    - Aceita JPEG/PNG, max 10MB
    - Extrai GPS do EXIF automaticamente
    - Retorna URL publica + coordenadas GPS (se disponiveis)
    """
    # Valida MIME type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de arquivo nao permitido: {file.content_type}. Use JPEG ou PNG.",
        )

    # Le o arquivo
    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo muito grande. Maximo: {MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # Verifica se R2 esta configurado
    s3 = _get_s3_client()
    if not s3:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servico de armazenamento (R2) nao configurado. Configure R2_ENDPOINT, R2_ACCESS_KEY e R2_SECRET_KEY.",
        )

    # Extrai GPS do EXIF
    gps = _extract_gps_from_exif(file_bytes)

    # Gera nome do arquivo
    ext = "jpg" if file.content_type == "image/jpeg" else "png"
    folder = TIPO_FOLDERS[tipo]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{folder}/{timestamp}_{uuid4().hex[:8]}.{ext}"

    # Upload para R2
    settings = get_settings()
    try:
        s3.put_object(
            Bucket=settings.r2_bucket_name,
            Key=filename,
            Body=file_bytes,
            ContentType=file.content_type,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erro ao enviar para R2: {str(e)}",
        )

    # Monta URL publica
    if settings.r2_public_url:
        url = f"{settings.r2_public_url.rstrip('/')}/{filename}"
    else:
        url = f"{settings.r2_endpoint.rstrip('/')}/{settings.r2_bucket_name}/{filename}"

    return UploadResponse(
        url=url,
        filename=filename,
        gps=gps,
        size_bytes=len(file_bytes),
    )
