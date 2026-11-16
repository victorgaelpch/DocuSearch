"""FastAPI application entrypoint for DocuSearch AI.

Document ingestion and search endpoints will be added in subsequent issues.
"""

from fastapi import FastAPI

app = FastAPI(
    title="DocuSearch AI",
    description="API base del buscador y gestor de documentos.",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Basic health check without external services or GPU."""
    return {"status": "ok"}
