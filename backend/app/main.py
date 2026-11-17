"""FastAPI application entrypoint for DocuSearch AI."""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.documents import router as documents_router
from backend.app.api.search import router as search_router
from backend.app.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea la aplicación; los servicios de datos se inicializan en la primera petición."""
    application = FastAPI(
        title="DocuSearch AI",
        description="API base del buscador y gestor de documentos.",
        version="0.1.0",
    )
    application.state.settings = settings or Settings.from_env()

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Basic health check without external services or GPU."""
        return {"status": "ok"}

    application.include_router(documents_router)
    application.include_router(search_router)
    return application


app = create_app()
