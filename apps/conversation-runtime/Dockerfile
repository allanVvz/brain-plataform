FROM python:3.12-slim

ARG SOURCE_SHA=unknown
ARG BRAIN_CONTRACTS_SHA=unknown
ARG GRAPH_RAG_LOCAL_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 \
    SOURCE_SHA=${SOURCE_SHA} BRAIN_CONTRACTS_SHA=${BRAIN_CONTRACTS_SHA} \
    BRAIN_CONTRACTS_VERSION=3.0.0 \
    BRAIN_CONVERSATION_TEMPLATE_PATH=/opt/brain/n8n/persona-conversation-template.json

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY packages/brain-contracts /packages/brain-contracts
COPY packages/brain-shared /packages/brain-shared
RUN pip install --no-cache-dir /packages/brain-contracts /packages/brain-shared
COPY apps/conversation-runtime/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN mkdir -p /opt/brain/fastembed-cache \
    && python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${GRAPH_RAG_LOCAL_EMBEDDING_MODEL}', cache_dir='/opt/brain/fastembed-cache')" \
    && chown -R appuser:appuser /opt/brain/fastembed-cache
ENV FASTEMBED_CACHE_PATH=/opt/brain/fastembed-cache \
    HF_HUB_OFFLINE=1
COPY --chown=appuser:appuser apps/conversation-runtime/api/ /app/
COPY --chown=appuser:appuser apps/conversation-runtime/n8n/ /opt/brain/n8n/
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS:-1} --timeout ${GUNICORN_TIMEOUT:-120}"]
