"""
Cliente Cloudflare R2 (S3-compatible) compartilhado.
Usado pelo módulo de upload de fotos e pelo módulo de GeoJSON.
"""

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings

_s3_client = None


def get_r2_client():
    """Retorna cliente S3 lazy-initialized. None se R2 não estiver configurado."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client

    settings = get_settings()
    if not all([settings.r2_endpoint, settings.r2_access_key,
                settings.r2_secret_key, settings.r2_bucket_name]):
        return None

    _s3_client = boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key,
        aws_secret_access_key=settings.r2_secret_key,
        region_name="auto",
    )
    return _s3_client


def r2_put(key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
    """Faz upload de bytes para o R2."""
    s3 = get_r2_client()
    settings = get_settings()
    s3.put_object(
        Bucket=settings.r2_bucket_name,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def r2_get(key: str) -> bytes:
    """
    Baixa objeto do R2.
    Lança botocore.exceptions.ClientError com code 'NoSuchKey' se não existir.
    """
    s3 = get_r2_client()
    settings = get_settings()
    response = s3.get_object(Bucket=settings.r2_bucket_name, Key=key)
    return response["Body"].read()


def r2_exists(key: str) -> bool:
    """Verifica se objeto existe no R2."""
    s3 = get_r2_client()
    if s3 is None:
        return False
    settings = get_settings()
    try:
        s3.head_object(Bucket=settings.r2_bucket_name, Key=key)
        return True
    except ClientError:
        return False


def geojson_key(org_slug: str) -> str:
    return f"geojson/{org_slug}/manzanas.geojson"
