"""
Printer manager - rasteriza via pypdfium2 e imprime via win32 GDI.
"""
from __future__ import annotations

import os
import tempfile
import threading

from config.local_settings import get_printer


class PrintError(Exception):
    """Raised when local print dispatch fails."""


class PrinterManager:
    """Handles local printer lookup and PDF dispatch via GDI."""

    def __init__(self):
        self._win32print = None
        self._win32ui = None
        self._win32con = None

    def _ensure_win32(self):
        if self._win32print is not None:
            return
        try:
            import win32print  # type: ignore
            import win32ui    # type: ignore
            import win32con   # type: ignore
        except Exception as exc:
            raise PrintError("pywin32 nao disponivel no ambiente.") from exc
        self._win32print = win32print
        self._win32ui = win32ui
        self._win32con = win32con

    def _cleanup_temp_later(self, path: str, delay_seconds: int = 30):
        def _cleanup():
            try:
                os.unlink(path)
            except Exception:
                pass
        t = threading.Timer(delay_seconds, _cleanup)
        t.daemon = True
        t.start()

    def get_default_printer(self) -> str:
        self._ensure_win32()
        return self._win32print.GetDefaultPrinter()

    def get_printer_name(self, printer_type: str) -> str:
        configured = get_printer(printer_type)
        if configured and configured != "(Nenhuma)":
            return configured
        return self.get_default_printer()

    def _write_temp_pdf(self, pdf_bytes: bytes, suffix_hint: str = "document") -> str:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in suffix_hint)[:40] or "document"
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{safe}.pdf") as f:
            f.write(pdf_bytes)
            return f.name

    def _rasterize(self, pdf_bytes: bytes, dpi: int = 300) -> list:
        """Rasteriza páginas PDF em imagens PIL via pypdfium2."""
        try:
            import pypdfium2 as pdfium  # type: ignore
        except Exception as exc:
            raise PrintError("pypdfium2 nao disponivel.") from exc

        scale = dpi / 72.0
        document = pdfium.PdfDocument(pdf_bytes)
        images = []
        try:
            for i in range(len(document)):
                page = document.get_page(i)
                try:
                    bm = page.render(scale=scale)
                    images.append(bm.to_pil().convert("RGB"))
                finally:
                    page.close()
        finally:
            document.close()
        return images

    def _print_images_gdi(self, images: list, printer_name: str, job_name: str):
        """Envia lista de imagens PIL para impressora via GDI (ctypes StretchDIBits)."""
        import struct
        import ctypes

        win32ui = self._win32ui
        win32con = self._win32con
        gdi32 = ctypes.windll.gdi32

        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)

        printer_w = hdc.GetDeviceCaps(win32con.HORZRES)
        printer_h = hdc.GetDeviceCaps(win32con.VERTRES)

        hdc.StartDoc(job_name)

        for img in images:
            hdc.StartPage()

            img_w, img_h = img.size
            scale = min(printer_w / img_w, printer_h / img_h)
            draw_w = int(img_w * scale)
            draw_h = int(img_h * scale)
            off_x = (printer_w - draw_w) // 2
            off_y = (printer_h - draw_h) // 2

            # Pixels BGR bottom-up com padding de linha para múltiplo de 4
            row_bytes = ((img_w * 3 + 3) // 4) * 4
            raw = img.tobytes("raw", "BGR")
            padded_rows = []
            for y in range(img_h - 1, -1, -1):
                row = raw[y * img_w * 3: (y + 1) * img_w * 3]
                padded_rows.append(row + b'\x00' * (row_bytes - len(row)))
            pixel_data = b"".join(padded_rows)

            bmi = struct.pack(
                "<IiiHHIIiiII",
                40,       # biSize
                img_w,    # biWidth
                img_h,    # biHeight (positivo = bottom-up)
                1,        # biPlanes
                24,       # biBitCount
                0,        # biCompression BI_RGB
                len(pixel_data),
                2835, 2835,  # pixels/metro
                0, 0,
            )

            # StretchDIBits(hdc, xDest, yDest, wDest, hDest, xSrc, ySrc, wSrc, hSrc, lpBits, lpBmi, iUsage, rop)
            gdi32.StretchDIBits(
                hdc.GetHandleAttrib(),
                off_x, off_y, draw_w, draw_h,
                0, 0, img_w, img_h,
                pixel_data, bmi,
                0,                    # DIB_RGB_COLORS
                0x00CC0020,           # SRCCOPY
            )

            hdc.EndPage()

        hdc.EndDoc()
        hdc.DeleteDC()

    def print_pdf(self, pdf_bytes: bytes, printer_type: str = "a4", job_name: str = "document"):
        """Imprime PDF rasterizando via pypdfium2 e enviando via win32 GDI."""
        if not pdf_bytes:
            raise PrintError("PDF vazio para impressao.")

        self._ensure_win32()
        printer_name = self.get_printer_name(printer_type)
        dpi = 203 if printer_type == "thermal" else 300

        print(f"[PrinterManager] imprimindo em {printer_name!r} dpi={dpi}")
        images = self._rasterize(pdf_bytes, dpi=dpi)
        if not images:
            raise PrintError("Nenhuma pagina gerada pelo rasterizador.")

        self._print_images_gdi(images, printer_name, job_name)
        print(f"[PrinterManager] ok — {len(images)} pagina(s) enviadas")

    def preview_pdf(self, pdf_bytes: bytes, file_name: str = "preview"):
        """Abre o PDF no leitor padrão do sistema."""
        if not pdf_bytes:
            raise PrintError("PDF vazio para visualizacao.")
        path = self._write_temp_pdf(pdf_bytes, suffix_hint=file_name)
        self._cleanup_temp_later(path, delay_seconds=300)
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:
            raise PrintError("Nao foi possivel abrir o PDF.") from exc


printer_manager = PrinterManager()
