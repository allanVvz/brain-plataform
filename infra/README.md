# Infraestrutura self-hosted

A definicao oficial e [`docker-compose.yml`](../docker-compose.yml), configurada por `.env.compose`. Ela executa Postgres/pgvector, PostgREST, Supabase Storage, Kong, migrations, API, workers e Caddy; o dashboard permanece na Vercel.

```bash
cp .env.compose.example .env.compose
python3 infra/generate_keys.py --write .env.compose
python3 ops/vps/validate_env.py .env.compose
docker compose --env-file .env.compose up -d --build
```

O runbook completo esta em [`docs/VPS_PRODUCTION_RUNBOOK.md`](../docs/VPS_PRODUCTION_RUNBOOK.md).
