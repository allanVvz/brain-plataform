# Brain Platform

Plataforma local-first para dashboard, API e banco Postgres. O caminho oficial deste repositorio nao depende de servicos SaaS.

## Arquitetura Local

Servicos principais:

| Servico | Runtime | URL do host |
|---|---|---|
| Dashboard | Next.js | `http://localhost:3000` |
| API | FastAPI/Gunicorn | `http://localhost:8000` |
| Gateway Supabase-compatible | Nginx -> PostgREST | `http://localhost:54321` |
| Banco | Postgres + pgvector | `localhost:54322` |

Dentro da rede Docker, as URLs sao diferentes:

| Origem | Destino correto |
|---|---|
| Dashboard/Next server -> API | `http://api:8000` |
| API -> Supabase-compatible gateway | `http://supabase-gateway:8000` |

Nao use `localhost` para chamadas entre containers. `localhost` dentro de um container aponta para o proprio container.

## Dev Docker

Subida completa:

```powershell
docker compose up --build
```

Login seed local:

```text
allan@brain.com
123456
```

Verificacoes:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:54321/health
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8000/health/ready
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:3000/login
```

Teste do proxy do dashboard:

```powershell
cd dashboard
npm run test:frontend-proxy
```

## Testes Locais

Use o Python do ambiente da API, nao o Python global:

```powershell
.\api\.venv\Scripts\python.exe -m pytest
.\api\.venv\Scripts\python.exe scripts\check_python_syntax.py
```

O `pytest` default roda apenas testes `tests/test_*.py`, que devem ser unitarios/contratuais e nao depender de Docker,
rede ou servicos externos. Testes `integration_*.py`, `e2e_*.py` e `smoke_*.py` ficam fora do default ate terem
markers/skips explicitos e ambiente local declarado.

## Producao Self-Hosted

O dashboard permanece na Vercel. O alvo oficial do backend e uma VPS com Docker Compose e Caddy.

```powershell
copy .env.compose.example .env.compose
python infra/generate_keys.py --write .env.compose
docker compose --env-file .env.compose up -d --build
```

O procedimento completo de provisionamento, migracao em ate 30 minutos, backup, restore e rollback esta em
[`docs/VPS_PRODUCTION_RUNBOOK.md`](docs/VPS_PRODUCTION_RUNBOOK.md).

## Variaveis De URL

Use nomes diferentes para URLs internas e publicas:

| Variavel | Quem usa | Exemplo Docker |
|---|---|---|
| `API_INTERNAL_BASE_URL` | Next server/rewrite `/api-brain/*` | `https://api.example.com` |
| `NEXT_PUBLIC_API_BASE_URL` | Browser | `/api-brain` |
| `SUPABASE_URL` | API/workers, rede Docker | `http://kong:8000` |
| `SUPABASE_PUBLIC_URL` | URLs de assets | `https://storage.example.com` |

O navegador nao acessa PostgREST diretamente nem recebe `SERVICE_ROLE_KEY`.

## Storage Local

A API usa `/data/local-storage`; Storage usa volume proprio e o vault usa `/data/vault`.

## Legado SaaS

Arquivos antigos de deploy SaaS foram arquivados em `legacy/saas/`. Eles existem apenas como historico e nao fazem parte do fluxo oficial.

## Documentacao De Dominio

A documentacao do fluxo, hierarquia e grafo de conhecimento fica em `docs/knowledge-flow.md`.
