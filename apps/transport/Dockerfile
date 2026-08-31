FROM python:3.12-slim

ARG SOURCE_SHA=unknown
ARG BRAIN_CONTRACTS_SHA=unknown
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 \
    SOURCE_SHA=${SOURCE_SHA} BRAIN_CONTRACTS_SHA=${BRAIN_CONTRACTS_SHA} \
    BRAIN_CONTRACTS_VERSION=3.0.0

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY packages/brain-contracts /packages/brain-contracts
COPY packages/brain-shared /packages/brain-shared
RUN pip install --no-cache-dir /packages/brain-contracts /packages/brain-shared
COPY apps/transport/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY --chown=appuser:appuser apps/transport/api/ /app/
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS:-1} --timeout ${GUNICORN_TIMEOUT:-120}"]
