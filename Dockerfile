# guria-intake: API del chat + agente + generación de propuestas en PDF.
# Chromium va dentro de la imagen porque deck.py lo usa para imprimir el PDF.
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    CHROMIUM_BIN=/usr/bin/chromium \
    INTAKE_DB=/app/data/intake.db

# Dependencias primero: se cachean mientras no cambie el lock.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY *.py langgraph.json ./

# Charlas, borradores y PDFs: montar un volumen persistente acá.
VOLUME /app/data
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=4)"

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "3000"]
