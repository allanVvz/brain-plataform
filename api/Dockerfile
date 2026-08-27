# Multi-stage production image for the AI Brain backend.
# Targets share a runtime base while API and workers contain only their own
# process dependencies.
# Build context is the repository root. Only api/ and the runtime SDR catalog
# are copied, so image contents stay tied to the release SHA.

# ── Builder ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ARG PIP_TRUSTED_HOST=""
ARG GRAPH_RAG_LOCAL_EMBEDDING_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY api/requirements.txt ./requirements.txt
RUN PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install -r requirements.txt
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${GRAPH_RAG_LOCAL_EMBEDDING_MODEL}', cache_dir='/opt/venv/fastembed-cache')"

# ── Runtime ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime-base

ARG SOURCE_SHA="unknown"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    FASTEMBED_CACHE_PATH=/opt/venv/fastembed-cache \
    PATH="/opt/venv/bin:$PATH"

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser

# Writable Obsidian vault dir for the kb-intake/Sofia save pipeline (VAULT_PATH).
# A fresh named volume mounted here inherits this ownership on first init.
RUN mkdir -p /data/vault && chown -R appuser:appuser /data

COPY --from=builder /opt/venv /opt/venv
RUN chown -R appuser:appuser /opt/venv/fastembed-cache

WORKDIR /app
# Make the application layer depend on the immutable release identity. This
# prevents a remote BuildKit cache from pairing a fresh image tag/digest with
# an older /app tree even when the source checkout changed.
RUN printf '%s' "${SOURCE_SHA}" > /image-source-sha
COPY --chown=appuser:appuser api/ /app/
COPY --chown=appuser:appuser docs/sdr/ /docs/sdr/
COPY --chown=appuser:appuser data/graph_bundles/ /data/graph_bundles/

FROM runtime-base AS api
USER appuser

EXPOSE 8080

# Lightweight liveness probe against the API's /health (no curl on slim).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health',timeout=4).status==200 else 1)"

CMD ["sh", "-c", "exec gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS:-1} --timeout ${GUNICORN_TIMEOUT:-120} --max-requests ${GUNICORN_MAX_REQUESTS:-1000} --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-100}"]

FROM runtime-base AS workers

ARG PIP_TRUSTED_HOST=""
ARG WHISPER_MODEL="small"
ENV WHISPER_CACHE_PATH=/opt/venv/whisper-cache

# Voice-note decoding is worker-only. We still bake the configured model so a
# first inbound audio after a rollout never depends on external egress.
COPY api/requirements-worker.txt /tmp/requirements-worker.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install -r /tmp/requirements-worker.txt \
    && rm -f /tmp/requirements-worker.txt \
    && python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8', download_root='/opt/venv/whisper-cache')" \
    && chown -R appuser:appuser /opt/venv/whisper-cache

USER appuser
CMD ["python", "-m", "workers.runner", "--all"]
