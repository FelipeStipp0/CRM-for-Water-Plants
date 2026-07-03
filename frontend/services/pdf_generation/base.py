"""
Base primitives for ReportLab PDF generators.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


class PDFGenerator:
    """Base class for lightweight PDF generation."""

    def __init__(self, page_size: Any = A4):
        self.default_page_size = page_size
        self._buffer = BytesIO()

    def create_canvas(self, page_size: Any = None) -> canvas.Canvas:
        self._buffer = BytesIO()
        return canvas.Canvas(self._buffer, pagesize=page_size or self.default_page_size)

    def finalize(self, pdf_canvas: canvas.Canvas) -> bytes:
        pdf_canvas.save()
        content = self._buffer.getvalue()
        self._buffer.close()
        return content
