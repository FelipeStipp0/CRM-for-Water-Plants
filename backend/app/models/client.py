"""
Modelo de Cliente (assinante do servico de agua).

IMPORTANTE: O tipo_tarifa e apenas para CATEGORIZACAO.
Todos os clientes pagam a mesma tarifa base global.
A diferenciacao financeira e feita via Subsidio no pagamento.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class ClientCategory(str, Enum):
    """
    Categoria do cliente (apenas para classificacao).
    NAO AFETA o valor da tarifa - todos pagam tarifa unica.
    """
    RESIDENCIAL = "RESIDENCIAL"
    COMERCIAL = "COMERCIAL"
    SOCIAL = "SOCIAL"


class ClientStatus(str, Enum):
    """Status do cliente no sistema."""
    ATIVO = "ATIVO"
    INATIVO = "INATIVO"
    CORTADO = "CORTADO"


class Client(Document):
    """
    Cliente/assinante do servico de agua.
    Contem dados pessoais, localizacao e informacoes do servico.
    """

    # Dados pessoais
    nombre_completo: Indexed(str)
    ci_ruc: Indexed(str, unique=True)
    telefono: Optional[str] = None
    celular: Optional[str] = None

    # Localizacao (usado para rotas de leitura)
    direccion: str
    manzana: Indexed(str) = ""
    lote: str = ""

    # GPS e Foto da instalacao (capturados pelo app mobile)
    instalacao_latitude: Optional[float] = None
    instalacao_longitude: Optional[float] = None
    foto_medidor_url: Optional[str] = None

    # Dados do servico
    numero_medidor: str = "SIN_MEDIDOR"
    categoria: ClientCategory = ClientCategory.RESIDENCIAL
    status: ClientStatus = ClientStatus.ATIVO

    # ========== SPONSOR ==========
    # Marca este cliente como sponsor (pode subsidiar/pagar por outros)
    is_sponsor: bool = False

    # ========== SUBSIDIO / ALUGUEL (cliente com pagador externo) ==========
    # sponsor_id preenchido: fatura direcionada ao sponsor.
    # Tres cenarios possiveis:
    #   1. SUBSIDIO SOCIAL: sponsor cobre parte da conta (assistencia social)
    #   2. ALUGUEL, DONO PAGA: is_aluguel=True + sponsor_id preenchido
    #      - fatura vai para o dono/proprietario (sponsor)
    #      - TODO: notificacao dupla via WhatsApp — dono recebe aviso de conta
    #        do inquilino a pagar; inquilino recebe aviso de que a conta foi
    #        enviada ao responsavel. Implementar no modulo de notificacoes.
    #   3. ALUGUEL, MORADOR PAGA: is_aluguel=True + sponsor_id=None
    #      - inquilino paga diretamente, sponsor_id nao se aplica
    #      - is_aluguel serve apenas como flag informativa/relatorio
    sponsor_id: Optional[PydanticObjectId] = None  # ID do cliente sponsor (deve ser is_sponsor=True)
    subsidio_porcentagem: Optional[int] = Field(default=None, ge=0, le=100)
    # Se None, usa o valor padrao de SystemSettings.subsidio_porcentagem_padrao
    is_aluguel: bool = False  # True = imovel alugado; dono paga se sponsor_id preenchido

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "clients"
        use_state_management = True
        indexes = [
            [("manzana", 1), ("lote", 1)],  # Indice composto para rotas
            [("sponsor_id", 1)],  # Para buscar clientes de um sponsor
        ]

    def __repr__(self) -> str:
        return f"Client(nombre={self.nombre_completo}, medidor={self.numero_medidor})"

    @property
    def has_sponsor(self) -> bool:
        """Verifica se cliente tem sponsor."""
        return self.sponsor_id is not None
