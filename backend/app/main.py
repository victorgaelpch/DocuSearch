"""FastAPI application entrypoint for DocuSearch AI."""

from __future__ import annotations

from collections.abc import Callable

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.app.api.admin import router as admin_router
from backend.app.api.ask import router as ask_router
from backend.app.api.auth import router as auth_router
from backend.app.api.documents import router as documents_router
from backend.app.api.errors import ApiError, api_error_handler
from backend.app.api.evaluation import router as evaluation_router
from backend.app.api.search import router as search_router
from backend.app import __version__
from backend.app.config import Settings
from backend.app.observability import Metrics, RequestLogMiddleware, configure_logging
from backend.app.security import SecurityMiddleware
from backend.app.web import mount_frontend


def create_app(settings: Settings | None = None, *, encoder_factory: Callable | None = None) -> FastAPI:
    """Crea la aplicación; los servicios de datos se inicializan en la primera petición.

    ``encoder_factory`` permite sustituir el modelo de embeddings (pruebas).
    """
    application = FastAPI(
        title="DocuSearch AI",
        description="API base del buscador y gestor de documentos.",
        version=__version__,
    )
    application.state.settings = settings or Settings.from_env()
    application.state.encoder_factory = encoder_factory
    application.state.metrics = Metrics()
    configure_logging()

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Basic health check without external services or GPU."""
        return {"status": "ok"}

    @application.get("/health/ready", tags=["system"])
    def ready() -> JSONResponse:
        """Preparación para servir (DOC-40): componentes esenciales y opcionales, sin datos privados."""
        import importlib.util

        from backend.app.api.documents import get_document_service_for_app
        from backend.app.documents.ocr import find_tessdata
        from backend.app.nlp import embeddings

        state = application.state
        checks: dict[str, bool] = {}
        try:
            get_document_service_for_app(application).repository.count_documents()
            checks["database"] = True
        except Exception:  # noqa: BLE001
            checks["database"] = False
        probe = state.settings.paths.root / ".ready"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            checks["data_dir_writable"] = True
        except OSError:
            checks["data_dir_writable"] = False
        checks["lexical_model"] = importlib.util.find_spec("es_core_news_sm") is not None
        checks["admin_account"] = state.settings.admin_password_hash is not None
        essential = all(checks.values())
        optional = {
            "semantic": state.encoder_factory is not None or embeddings.semantic_available(),
            "ocr": find_tessdata() is not None,
            "rag_configured": bool((os.environ.get("DOCUSEARCH_RAG_PROVIDER") or "").strip() not in ("", "off")),
        }
        return JSONResponse(
            {"status": "ready" if essential else "not_ready", "essential": checks, "optional": optional},
            status_code=200 if essential else 503,
        )

    @application.get("/version", tags=["system"])
    def version() -> dict[str, str]:
        """Versión instalada (DOC-35)."""
        return {"name": "DocuSearch AI", "version": __version__}

    application.add_exception_handler(ApiError, api_error_handler)
    application.include_router(auth_router)
    application.include_router(documents_router)
    application.include_router(search_router)
    application.include_router(admin_router)
    application.include_router(evaluation_router)
    application.include_router(ask_router)
    mount_frontend(application)
    application.add_middleware(SecurityMiddleware)
    application.add_middleware(RequestLogMiddleware)  # el más externo: identifica todo, incluidos los rechazos
    return application


app = create_app()
