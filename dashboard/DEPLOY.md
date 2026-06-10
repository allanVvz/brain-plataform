# Docker Deploy / Local Run

This project is now operated locally through Docker Compose. The backend is a
separate service from the database, so you can audit each layer independently.

## Services

- `db` - local Postgres
- `storage` - local storage API
- `rest` - local PostgREST
- `kong` - local gateway
- `migrate` - bootstrap + migrations
- `api` - FastAPI backend on `localhost:8080`
- `workers` - background jobs in a separate container

## Start

```bash
python infra/generate_keys.py --write .env.compose
docker compose --env-file .env.compose up -d --build
```

## Audit

```bash
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose logs -f db api workers
curl http://localhost:8080/health
curl http://localhost:8080/api/menu/baita-conveniencia
```

## Dashboard Environments

For Sofia QA from `localhost:3000`, point the dashboard at the host backend:

```env
API_INTERNAL_BASE_URL=http://127.0.0.1:8001
NEXT_PUBLIC_API_BASE_URL=/api-brain
```

Switch targets without editing ports by hand:

```powershell
# QA backend on the host
.\scripts\set-dashboard-env.ps1 -Target local-qa

# Docker backend
.\scripts\set-dashboard-env.ps1 -Target docker

# Vercel build target; backend must be public, not localhost
.\scripts\set-dashboard-env.ps1 -Target vercel -BackendUrl https://YOUR-BACKEND-DOMAIN
```

Then run:

```bash
cd dashboard
npm run dev:local
```

## Docker Deploy

```powershell
.\scripts\deploy-docker.ps1
```

The script switches the dashboard to `http://localhost:8080`, starts the Docker
services, and checks `/health`.

## Vercel Deploy

```powershell
.\scripts\deploy-vercel.ps1 -BackendUrl https://YOUR-BACKEND-DOMAIN -Prod
```

The Vercel backend URL must be publicly reachable. A local Docker URL such as
`localhost:8080` will not work from Vercel.
