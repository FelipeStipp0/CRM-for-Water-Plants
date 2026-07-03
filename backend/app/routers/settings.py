"""
Endpoints de configuracoes do sistema.
"""

import base64
from datetime import datetime
from decimal import Decimal
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field, model_validator

from app.models.settings import SystemSettings
from app.models.user import User
from app.routers.auth import get_current_active_user, get_current_master, require_scopes

router = APIRouter(dependencies=[Depends(require_scopes("settings"))])


class SettingsResponse(BaseModel):
    """Schema de resposta das configuracoes."""

    # Dados da junta
    nombre_junta: str
    ruc_junta: Optional[str]
    direccion_junta: Optional[str]
    telefono_junta: Optional[str]
    actividad: Optional[str]

    # Tarifa unica global
    tarifa_base: Decimal
    consumo_minimo: int
    valor_excedente_m3: Decimal
    subsidio_porcentagem_padrao: int

    # Faturamento
    dia_geracao_faturas: int
    dias_vencimiento: int
    valor_minimo_emissao: Decimal
    gerar_sem_leitura_valor_minimo: bool
    matching_prioridade: List[str]

    # Corte
    meses_atraso_corte: int
    dias_prazo_aviso: int
    taxa_reativacao: Decimal
    multa: Decimal

    # WhatsApp
    whatsapp_alias: Optional[str]

    # Atendimento e dados bancários
    horario_atencion: Optional[str]
    banco_nombre: Optional[str]
    alias_tipo: Optional[str]
    alias_valor: Optional[str]

    # Logo
    logo_base64: Optional[str]
    logo_mime: Optional[str]

    updated_at: datetime


class SettingsUpdate(BaseModel):
    """Schema para atualizacao de configuracoes."""

    # Dados da junta
    nombre_junta: Optional[str] = None
    ruc_junta: Optional[str] = None
    direccion_junta: Optional[str] = None
    telefono_junta: Optional[str] = None
    actividad: Optional[str] = None

    # Tarifa unica global
    tarifa_base: Optional[Decimal] = Field(None, ge=0)
    consumo_minimo: Optional[int] = Field(None, ge=0)
    valor_excedente_m3: Optional[Decimal] = Field(None, ge=0)
    subsidio_porcentagem_padrao: Optional[int] = Field(None, ge=0, le=100)

    # Faturamento
    dia_geracao_faturas: Optional[int] = Field(None, ge=1, le=28)
    dias_vencimiento: Optional[int] = Field(None, ge=1, le=60)
    valor_minimo_emissao: Optional[Decimal] = Field(None, ge=0)
    gerar_sem_leitura_valor_minimo: Optional[bool] = None
    matching_prioridade: Optional[List[str]] = None

    @model_validator(mode='after')
    def validate_matching_prioridade(self):
        if self.matching_prioridade is not None:
            allowed = {"numero_medidor", "ci_ruc", "nombre_completo"}
            invalid = [f for f in self.matching_prioridade if f not in allowed]
            if invalid:
                raise ValueError(
                    f"matching_prioridade invalido: {invalid}. "
                    f"Valores permitidos: {sorted(allowed)}"
                )
        return self

    # Corte
    meses_atraso_corte: Optional[int] = Field(None, ge=1)
    dias_prazo_aviso: Optional[int] = Field(None, ge=1)
    taxa_reativacao: Optional[Decimal] = Field(None, ge=0)
    multa: Optional[Decimal] = Field(None, ge=0)

    # WhatsApp
    whatsapp_alias: Optional[str] = None

    # Atendimento e dados bancários
    horario_atencion: Optional[str] = None
    banco_nombre: Optional[str] = None
    alias_tipo: Optional[str] = None
    alias_valor: Optional[str] = None

    @model_validator(mode='after')
    def validate_alias_tipo(self):
        if self.alias_tipo:
            allowed = {"CI", "CELULAR", "EMAIL", "RUC"}
            if self.alias_tipo not in allowed:
                raise ValueError(
                    f"alias_tipo invalido: {self.alias_tipo}. "
                    f"Valores permitidos: {sorted(allowed)}"
                )
        return self


def settings_to_response(settings: SystemSettings) -> SettingsResponse:
    """Converte modelo para schema de resposta."""
    return SettingsResponse(
        nombre_junta=settings.nombre_junta,
        ruc_junta=settings.ruc_junta,
        direccion_junta=settings.direccion_junta,
        telefono_junta=settings.telefono_junta,
        actividad=settings.actividad,
        tarifa_base=settings.tarifa_base,
        consumo_minimo=settings.consumo_minimo,
        valor_excedente_m3=settings.valor_excedente_m3,
        subsidio_porcentagem_padrao=settings.subsidio_porcentagem_padrao,
        dia_geracao_faturas=settings.dia_geracao_faturas,
        dias_vencimiento=settings.dias_vencimiento,
        valor_minimo_emissao=settings.valor_minimo_emissao,
        gerar_sem_leitura_valor_minimo=settings.gerar_sem_leitura_valor_minimo,
        matching_prioridade=settings.matching_prioridade,
        meses_atraso_corte=settings.meses_atraso_corte,
        dias_prazo_aviso=settings.dias_prazo_aviso,
        taxa_reativacao=settings.taxa_reativacao,
        multa=settings.multa,
        whatsapp_alias=settings.whatsapp_alias,
        horario_atencion=settings.horario_atencion,
        banco_nombre=settings.banco_nombre,
        alias_tipo=settings.alias_tipo,
        alias_valor=settings.alias_valor,
        logo_base64=settings.logo_base64,
        logo_mime=settings.logo_mime,
        updated_at=settings.updated_at,
    )


@router.get("/", response_model=SettingsResponse)
async def get_settings(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna as configuracoes do sistema."""
    settings = await SystemSettings.get_instance()
    return settings_to_response(settings)


@router.patch("/", response_model=SettingsResponse)
async def update_settings(
    settings_data: SettingsUpdate,
    current_user: Annotated[User, Depends(get_current_master)],
):
    """
    Atualiza configuracoes do sistema.
    Requer permissao de superusuario.
    """
    settings = await SystemSettings.get_instance()

    update_data = settings_data.model_dump(exclude_unset=True)
    if update_data:
        update_data["updated_at"] = datetime.utcnow()
        await settings.update({"$set": update_data})
        await settings.sync()

    return settings_to_response(settings)


_ALLOWED_LOGO_MIME = {"image/png", "image/jpeg", "image/webp"}
_MAX_LOGO_BYTES = 500 * 1024  # 500 KB


@router.post("/logo", response_model=SettingsResponse)
async def upload_logo(
    current_user: Annotated[User, Depends(get_current_master)],
    file: UploadFile = File(...),
):
    """Faz upload da logo da empresa (PNG/JPG/WebP, máx 500 KB). Requer superusuário."""
    mime = file.content_type or ""
    if mime not in _ALLOWED_LOGO_MIME:
        raise HTTPException(status_code=415, detail=f"Tipo não suportado: {mime}. Use PNG, JPG ou WebP.")

    data = await file.read()
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail=f"Arquivo muito grande ({len(data)//1024} KB). Máx: 500 KB.")

    b64 = base64.b64encode(data).decode("ascii")
    settings = await SystemSettings.get_instance()
    await settings.update({"$set": {"logo_base64": b64, "logo_mime": mime, "updated_at": datetime.utcnow()}})
    await settings.sync()
    return settings_to_response(settings)


@router.delete("/logo", response_model=SettingsResponse)
async def delete_logo(
    current_user: Annotated[User, Depends(get_current_master)],
):
    """Remove a logo da empresa. Requer superusuário."""
    settings = await SystemSettings.get_instance()
    await settings.update({"$set": {"logo_base64": None, "logo_mime": None, "updated_at": datetime.utcnow()}})
    await settings.sync()
    return settings_to_response(settings)


@router.get("/tarifas")
async def get_tarifas(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna apenas as tarifas/configuracoes de calculo."""
    settings = await SystemSettings.get_instance()
    return {
        "tarifa_base": settings.tarifa_base,
        "consumo_minimo": settings.consumo_minimo,
        "valor_excedente_m3": settings.valor_excedente_m3,
        "subsidio_porcentagem_padrao": settings.subsidio_porcentagem_padrao,
    }
