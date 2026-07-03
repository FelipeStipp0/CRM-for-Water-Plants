"""
Ponto de entrada da aplicacao FastAPI.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.database import init_db, close_db
from app.middleware.etag import ETagMiddleware

logger = logging.getLogger(__name__)

async def _cutoff_cron():
    """Processa countdowns de corte expirados todos os dias às 06:00."""
    from datetime import datetime, timedelta
    from app.services.cutoff_service import CutoffService
    while True:
        now = datetime.now()
        next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            await CutoffService.process_expired_countdowns()
        except Exception as err:
            logger.error(f"[cutoff_cron] erro ao processar countdowns: {err}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicacao."""
    # Startup
    await init_db()
    cron_task = asyncio.create_task(_cutoff_cron())
    yield
    # Shutdown
    cron_task.cancel()
    try:
        await cron_task
    except asyncio.CancelledError:
        pass
    await close_db()


def create_app() -> FastAPI:
    """Factory para criar a instancia do FastAPI."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="API para gestao de juntas de saneamento",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Ordem importa: add_middleware empilha de fora para dentro
    # (ultimo adicionado = mais externo). Queremos ETag computando hash
    # do body cru, antes do GZip comprimir; logo, ETag entra primeiro
    # (fica interno) e GZip depois (fica externo, abrindo a resposta ja
    # com ETag setado).
    app.add_middleware(ETagMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # Registrar routers
    from app.routers import auth, clients, readings, invoices, payments, settings as settings_router, finance, sponsors, cutoff, upload, map_tiles
    from app.whatsapp.router import router as whatsapp_router

    app.include_router(auth.router, prefix="/auth", tags=["Autenticacao"])
    app.include_router(clients.router, prefix="/clients", tags=["Clientes"])
    app.include_router(readings.router, prefix="/readings", tags=["Leituras"])
    app.include_router(invoices.router, prefix="/invoices", tags=["Faturas"])
    app.include_router(payments.router, prefix="/payments", tags=["Pagamentos"])
    app.include_router(settings_router.router, prefix="/settings", tags=["Configuracoes"])
    app.include_router(finance.router, prefix="/finance", tags=["Financeiro"])
    app.include_router(sponsors.router, prefix="/sponsors", tags=["Sponsors"])
    app.include_router(cutoff.router, prefix="/cutoff", tags=["Corte"])
    app.include_router(cutoff.qr_router, prefix="/cutoff", tags=["Corte QR"])
    app.include_router(upload.router, prefix="/upload", tags=["Upload"])
    app.include_router(map_tiles.router, prefix="/map", tags=["Mapa"])
    app.include_router(whatsapp_router, prefix="/whatsapp", tags=["WhatsApp"])

    @app.get("/", tags=["Health"])
    async def root():
        """Health check."""
        return {"message": "A API está funcionando! (200)"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
