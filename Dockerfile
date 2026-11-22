# DocuSearch AI — imagen local, solo CPU (DOC-41).
# Se construye y ejecuta en esta computadora; no se publica en ningún registro.
#   docker compose up -d --build        (ver docs/docker.md)
FROM python:3.12-slim

ARG WITH_OCR=1
ARG WITH_SEMANTIC=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DOCUSEARCH_DATA_DIR=/data \
    HF_HOME=/data/hf-cache

RUN if [ "$WITH_OCR" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
      && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
# Solo lo necesario para ejecutar: código, interfaz, demostración y resultados versionados.
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY backend ./backend
COPY frontend ./frontend
COPY demo ./demo
COPY evaluation ./evaluation
COPY corpus ./corpus

RUN python -m pip install -e ".[model]" \
    && if [ "$WITH_SEMANTIC" = "1" ]; then \
         python -m pip install torch --index-url https://download.pytorch.org/whl/cpu \
         && python -m pip install -e ".[semantic]"; \
       fi

# Usuario sin privilegios; los datos viven en el volumen /data, nunca en la imagen.
RUN useradd --create-home --uid 10001 docusearch && mkdir -p /data && chown docusearch:docusearch /data
USER docusearch
VOLUME ["/data"]
EXPOSE 8000

# Preparado = base de datos, carpeta de datos, modelo de spaCy y cuenta de Administrador.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).status == 200 else 1)"

# Dentro del contenedor escucha en todas sus interfaces; compose.yaml solo
# publica el puerto en 127.0.0.1 del equipo anfitrión.
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
