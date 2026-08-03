# Brain Platform

Plataforma local-first para dashboard, API e banco Postgres. O caminho oficial deste repositorio nao depende de servicos SaaS.

## Arquitetura Local

Servicos principais:

| Servico | Runtime | URL do host |
|---|---|---|
| Dashboard | Next.js | `http://localhost:3000` |
| API | FastAPI/Gunicorn | `http://localhost:8080` |
| Gateway Supabase-compatible | Kong -> PostgREST/Storage | `http://kong:8000` na rede Docker |
| Banco | Postgres + pgvector | `db:5432` na rede Docker |

Dentro da rede Docker, as URLs sao diferentes:

| Origem | Destino correto |
|---|---|
| Dashboard/Next server -> API | `http://api:8080` |
| API -> Supabase-compatible gateway | `http://kong:8000` |

Nao use `localhost` para chamadas entre containers. `localhost` dentro de um container aponta para o proprio container.

## Dev Docker

Subida completa:

```powershell
docker compose --env-file .env.compose up -d --build
```

Verificacoes:

```powershell
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose logs db api workers
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/health
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/api/menu/baita-conveniencia
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

O dashboard permanece na Vercel e o backend de producao atual e `https://api.vzforeal.com`, em uma VPS com Docker Compose e Caddy. Nao existe segunda VPS de QA. Enquanto ela nao for provisionada, QA persistente acontece somente no Docker local; producao nunca deve ser usada para simular QA. Features de campanhas permanecem desativadas/expand-first ate o rollout correspondente.

```powershell
copy .env.compose.example .env.compose
python infra/generate_keys.py --write .env.compose
docker compose --env-file .env.compose up -d --build
```

O procedimento completo de provisionamento, migracao em ate 30 minutos, backup, restore e rollback esta em
[`docs/VPS_PRODUCTION_RUNBOOK.md`](docs/VPS_PRODUCTION_RUNBOOK.md).
O isolamento temporario de QA e a operacao expand-first de campanhas estao em
[`docs/runbooks/QA_PRODUCTION_ISOLATION.md`](docs/runbooks/QA_PRODUCTION_ISOLATION.md) e
[`docs/architecture/BULK_CAMPAIGNS.md`](docs/architecture/BULK_CAMPAIGNS.md).

## Variaveis De URL

Use nomes diferentes para URLs internas e publicas:

| Variavel | Quem usa | Exemplo Docker |
|---|---|---|
| `API_INTERNAL_BASE_URL` | Next server/rewrite `/api-brain/*` | `https://api.vzforeal.com` em producao; `http://localhost:8080` local |
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
