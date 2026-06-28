# Self-hosted AI Brain stack (Docker, single-host)

Runs the whole platform on one host without the retired cloud backend. The
data plane is the **self-hosted Supabase** data services (Postgres + PostgREST
+ Storage + Kong gateway); the app plane is our **api** and **workers** images.
The dashboard (Next.js) and `baita-cardapio` (Vite) stay on Vercel.

```
db (supabase/postgres) ─► storage-api ─► postgrest ─► kong ─┐  one SUPABASE_URL
                                                            ├─► api  (FastAPI/gunicorn)
                          migrate (one-shot: 43 migrations) ─┴─► workers (runner --all)
```

Auth is our own (`public.app_users` + `pgcrypto`), so GoTrue/Realtime are not run.

## Bring-up

```bash
cp .env.compose.example .env.compose
python infra/generate_keys.py --write .env.compose   # fills JWT_SECRET/ANON_KEY/SERVICE_ROLE_KEY
# edit .env.compose: POSTGRES_PASSWORD, OPENAI_API_KEY, ALLOWED_ORIGINS, SUPABASE_URL

docker compose --env-file .env.compose up -d --build
docker compose logs -f migrate     # should end with "MIGRATIONS APPLIED OK"
```

`migrate` runs once (legacy bootstrap + `supabase/migrations/*.sql`) and exits 0
before `api`/`workers` start. Buckets `assets-raw` / `assets-derived` are ensured
on API boot (`api/main.py` lifespan).

## Validate

```bash
curl http://localhost:8080/health                       # API liveness -> 200
curl http://localhost:8080/api/menu/<persona-slug>      # menu contract -> 200
docker compose logs workers                             # 4 workers started
```

## Operational notes (gotchas)

1. **JWT coherence** — `SERVICE_ROLE_KEY` (the API's `SUPABASE_SERVICE_KEY`) and
   `ANON_KEY` must be signed with the same `JWT_SECRET` as PostgREST/Storage.
   Always regenerate all three together with `generate_keys.py`. The service key
   must carry `role=service_role` (anon 404s on RLS-bypass routes).
2. **Public asset URLs** — Storage emits signed URLs as `${SUPABASE_URL}/storage/v1/...`.
   For images to render in the external cardapio/dashboard, set `SUPABASE_URL` to
   Kong's **public https domain** (front Kong with Caddy/Traefik for TLS), not the
   internal `http://kong:8000`.
3. **CORS** — `ALLOWED_ORIGINS` must list the dashboard + cardapio public origins.
4. **Backups** — persistent state lives in the `db-data` and `storage-data`
   volumes. Schedule `pg_dump` and a `storage-data` snapshot on the host.
5. **TLS internal** — `SUPABASE_SSL_VERIFY=false` is set so the API can reach Kong
   over plain http inside the compose network.

## Files

| Path | Role |
|------|------|
| `docker-compose.yml` | full stack definition |
| `api/Dockerfile` | multi-stage image for api + workers |
| `infra/migrate.Dockerfile` | one-shot migration runner image |
| `infra/kong.yml` | gateway routing `/rest/v1`, `/storage/v1` |
| `infra/generate_keys.py` | mint coherent JWT_SECRET/anon/service_role |
| `scripts/apply_migrations.py` | env-driven migration applier |
| `.env.compose.example` | config template |
