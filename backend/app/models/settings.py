"""
Modelo de Configuracoes do Sistema.

IMPORTANTE: O sistema usa TARIFA UNICA GLOBAL.
Nao existe diferenciacao de valores por tipo de cliente.
A unica diferenciacao financeira e o Subsidio (Sponsor)
aplicado no momento do pagamento.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from beanie import Document
from pydantic import Field

from app.models.types import MongoDecimal


class SystemSettings(Document):
    """
    Configuracoes globais do sistema.
    Deve existir apenas um documento desta colecao.
    """

    # Identificador unico (sempre "default")
    key: str = "default"

    # Dados da Junta
    nombre_junta: str = "Junta de Saneamiento"
    ruc_junta: Optional[str] = None
    direccion_junta: Optional[str] = None
    telefono_junta: Optional[str] = None
    actividad: Optional[str] = "Servicio de Agua Potable"

    # ========== TARIFA UNICA GLOBAL ==========
    # ATENCAO: Uma unica tarifa para todos os clientes
    tarifa_base: MongoDecimal = Decimal("25000")  # Valor fixo unico
    consumo_minimo: int = 15  # Franquia em m3 incluida na tarifa base
    valor_excedente_m3: MongoDecimal = Decimal("1500")  # Por m3 acima do minimo

    # Subsidio padrao (%) - usado quando cliente tem sponsor
    subsidio_porcentagem_padrao: int = Field(default=50, ge=0, le=100)

    # Faturamento
    dia_geracao_faturas: int = Field(default=1, ge=1, le=28)
    dias_vencimiento: int = 15  # Dias apos emissao para vencimento
    valor_minimo_emissao: MongoDecimal = Decimal("0")
    gerar_sem_leitura_valor_minimo: bool = False
    matching_prioridade: List[str] = Field(
        default=["numero_medidor", "ci_ruc", "nombre_completo"]
    )

    # Corte
    meses_atraso_corte: int = 3  # Meses de atraso para gerar aviso
    dias_prazo_aviso: int = 15  # Dias de prazo no aviso de corte
    taxa_reativacao: MongoDecimal = Decimal("50000")
    multa: MongoDecimal = Decimal("0")  # Multa/recargo aplicado na Orden de Corte

    # ========== FACTURACIÓN ELECTRÓNICA (SIFEN) ==========
    # Afetação de IVA da ÁGUA (default global da junta; ajustável).
    # afectacion: 1=Gravado, 3=Exento ; tasa: 0/5/10
    # Fatura CONSUMO usa estes valores; fatura AVULSA usa o IVA por item.
    iva_afectacion_agua: int = 1
    iva_tasa_agua: int = 10

    # WhatsApp
    whatsapp_alias: Optional[str] = None

    # ========== ATENDIMENTO E DADOS BANCÁRIOS ==========
    # Campos variáveis usados nas notificações de corte (antes hardcoded no PDF).
    # horario_atencion: ex. "8 a 12 horas, de lunes a viernes"
    horario_atencion: Optional[str] = None
    banco_nombre: Optional[str] = None
    # Tipo de alias bancário paraguaio: CI | CELULAR | EMAIL | RUC
    alias_tipo: Optional[str] = None
    alias_valor: Optional[str] = None

    # Logo da empresa (armazenada como base64 para evitar dependência de filesystem/CDN)
    logo_base64: Optional[str] = None
    logo_mime: Optional[str] = None  # "image/png", "image/jpeg", etc.

    # Metadata
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "settings"
        use_state_management = True

    @classmethod
    async def get_instance(cls) -> "SystemSettings":
        """
        Retorna as configuracoes do sistema.
        Cria um documento padrao se nao existir.
        """
        settings = await cls.find_one(cls.key == "default")
        if not settings:
            settings = cls()
            await settings.insert()
        return settings
