# One-shot migration runner for the self-hosted stack.
# Applies docs/qa legacy bootstrap + supabase/migrations/*.sql to the db service.
# Build context is the repo root (needs scripts/, supabase/, docs/qa/).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install "psycopg2-binary>=2.9"

WORKDIR /app
COPY scripts/apply_migrations.py scripts/apply_migrations.py
COPY supabase/migrations supabase/migrations
COPY docs/qa docs/qa

CMD ["python", "scripts/apply_migrations.py"]
