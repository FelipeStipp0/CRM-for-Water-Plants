"""
Internal PDF preview renderer (PDF -> PNG base64 pages).
"""
from __future__ import annotations

import base64
from io import BytesIO
from typing import Any


def render_pdf_preview_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int = 6,
    scale: float = 1.4,
) -> dict[str, Any]:
    """
    Render PDF pages to PNG base64 strings for in-app preview.

    Requires `pypdfium2` installed in the frontend runtime.
    """
    if not pdf_bytes:
        raise ValueError("PDF vazio para preview.")

    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Preview interno indisponivel: instale a dependencia 'pypdfium2'."
        ) from exc

    document = pdfium.PdfDocument(pdf_bytes)
    total_pages = len(document)
    render_count = min(max(1, int(max_pages)), total_pages) if total_pages else 0
    pages_base64: list[str] = []

    for page_index in range(render_count):
        page = document.get_page(page_index)
        bitmap = None
        try:
            bitmap = page.render(scale=max(0.5, float(scale)))
            image = bitmap.to_pil()
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            pages_base64.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
        finally:
            if bitmap is not None:
                try:
                    bitmap.close()
                except Exception:
                    pass
            try:
                page.close()
            except Exception:
                pass

    try:
        document.close()
    except Exception:
        pass

    return {
        "pages": pages_base64,
        "total_pages": total_pages,
        "rendered_pages": len(pages_base64),
    }

