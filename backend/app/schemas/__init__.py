"""
Schemas Pydantic para validacao de entrada/saida da API.
"""

from app.schemas.user import UserCreate, UserResponse, Token, TokenData
from app.schemas.client import ClientCreate, ClientUpdate, ClientResponse, ClientSearch
from app.schemas.reading import ReadingCreate, ReadingBatch, ReadingResponse
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceItemCreate,
    InvoiceResponse,
    InvoiceSummary,
)
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentResult,
    AllocationDetail,
)

__all__ = [
    "UserCreate",
    "UserResponse",
    "Token",
    "TokenData",
    "ClientCreate",
    "ClientUpdate",
    "ClientResponse",
    "ClientSearch",
    "ReadingCreate",
    "ReadingBatch",
    "ReadingResponse",
    "InvoiceCreate",
    "InvoiceItemCreate",
    "InvoiceResponse",
    "InvoiceSummary",
    "PaymentCreate",
    "PaymentResponse",
    "PaymentResult",
    "AllocationDetail",
]
