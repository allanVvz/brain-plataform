# Local Docker Audit

This repository now runs the platform locally via Docker Compose as the primary operational target.

## Services

- `db`: Supabase Postgres local
- `storage`: Supabase storage API local
- `rest`: PostgREST local
- `kong`: Supabase gateway local
- `migrate`: one-shot migrations/bootstrap job
- `api`: FastAPI backend on `localhost:8080`
- `workers`: background jobs in a separate container
- `studio`: optional Supabase Studio on `localhost:3030`

## Bring-up

```bash
python infra/generate_keys.py --write .env.compose
# edit .env.compose as needed

docker compose --env-file .env.compose up -d --build
```

## Audit checks

```bash
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose logs -f db api workers
docker compose --env-file .env.compose exec api curl -s http://localhost:8080/health
curl -s http://localhost:8080/health
curl -s http://localhost:8080/api/menu/baita-conveniencia
```

## Auth

- Use the seed admin login only in local Docker.
- The shared admin token is QA-only and becomes available when `ENVIRONMENT=qa` and `AI_BRAIN_ADMIN_TEST_TOKEN` are set in the container environment.

## Dashboard wiring

- `API_INTERNAL_BASE_URL=http://localhost:8080`
- `NEXT_PUBLIC_API_BASE_URL=/api-brain`

## What is no longer the default

- The legacy cloud backend is no longer the operational backend target.
- Legacy cloud env files and cloud deploy scripts are archival references only.
