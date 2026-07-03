"""
Modelos ODM (Beanie) para MongoDB.
"""

from app.models.user import User
from app.models.client import Client
from app.models.reading import Reading
from app.models.invoice import Invoice, InvoiceItem
from app.models.payment import Payment, PaymentAllocation
from app.models.settings import SystemSettings

__all__ = [
    "User",
    "Client",
    "Reading",
    "Invoice",
    "InvoiceItem",
    "Payment",
    "PaymentAllocation",
    "SystemSettings",
]
