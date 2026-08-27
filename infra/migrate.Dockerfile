# One-shot migration runner for the self-hosted stack.
# Applies docs/qa legacy bootstrap + all supabase/migrations/*.sql to the db service.
# Build context is the repo root (needs scripts/, supabase/, docs/qa/).
FROM python:3.12-slim

ARG PIP_TRUSTED_HOST=""

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" pip install "psycopg2-binary>=2.9"

WORKDIR /app
COPY scripts/apply_migrations.py scripts/apply_migrations.py
COPY scripts/migration_manifest.py scripts/migration_manifest.py
COPY supabase/migrations supabase/migrations
COPY docs/qa docs/qa
RUN python scripts/migration_manifest.py create \
    --directory supabase/migrations --output /app/MIGRATION_MANIFEST.json

CMD ["python", "scripts/apply_migrations.py"]
