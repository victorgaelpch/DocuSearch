"""FastAPI application entrypoint for DocuSearch AI."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from backend.app.api.auth import router as auth_router
from backend.app.api.documents import router as documents_router
from backend.app.api.errors import ApiError, api_error_handler
from backend.app.api.search import router as search_router
from backend.app.config import Settings
from backend.app.web import mount_frontend


def create_app(settings: Settings | None = None, *, encoder_factory: Callable | None = None) -> FastAPI:
    """Crea la aplicación; los servicios de datos se inicializan en la primera petición.

    ``encoder_factory`` permite sustituir el modelo de embeddings (pruebas).
    """
    application = FastAPI(
        title="DocuSearch AI",
        description="API base del buscador y gestor de documentos.",
        version="0.1.0",
    )
    application.state.settings = settings or Settings.from_env()
    application.state.encoder_factory = encoder_factory

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Basic health check without external services or GPU."""
        return {"status": "ok"}

    application.add_exception_handler(ApiError, api_error_handler)
    application.include_router(auth_router)
    application.include_router(documents_router)
    application.include_router(search_router)
    mount_frontend(application)
    return application


app = create_app()
