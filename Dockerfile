# protocol-to-data — container image for the Gradio app.
# Slim, wheels-only install, runs as a non-root user.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

WORKDIR /app

# Install dependencies first so the layer caches across source-only changes.
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

# App source.
COPY . .

# Drop root for runtime.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 7860

# Liveness for Docker/Compose (and Portainer) — no curl in the slim image, so use stdlib urllib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:7860/',timeout=4).status==200 else 1)" || exit 1

# The ANTHROPIC_API_KEY is provided at runtime (env_file / -e), never baked into the image.
ENTRYPOINT ["python", "app.py"]
