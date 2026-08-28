FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY api/requirements-gateway.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt
COPY --chown=appuser:appuser api/gateway_main.py /app/gateway_main.py

USER appuser
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=8 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=4)"

CMD ["sh", "-c", "exec gunicorn -k uvicorn.workers.UvicornWorker gateway_main:app --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS:-2} --timeout 120"]
