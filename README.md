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

## Producao Self-Hosted

O alvo oficial de producao e Docker self-hosted.

```powershell
copy .env.prod.example .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Antes de usar em producao real:

- Troque `POSTGRES_PASSWORD`.
- Troque `AI_BRAIN_AUTH_SECRET`.
- Gere novos JWTs locais e atualize `LOCAL_SUPABASE_JWT_SECRET`, `LOCAL_SUPABASE_ANON_KEY` e `LOCAL_SUPABASE_SERVICE_ROLE_KEY`.
- Configure `NEXT_PUBLIC_API_URL`, `PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL` e `ALLOWED_ORIGINS` com o dominio final.

## Variaveis De URL

Use nomes diferentes para URLs internas e publicas:

| Variavel | Quem usa | Exemplo Docker |
|---|---|---|
| `API_INTERNAL_URL` | Next server/rewrite `/api-brain/*` | `http://api:8000` |
| `NEXT_PUBLIC_API_URL` | Browser/host | `http://localhost:8000` |
| `SUPABASE_URL` | API | `http://supabase-gateway:8000` |
| `NEXT_PUBLIC_SUPABASE_URL` | Browser/host | `http://localhost:54321` |

O codigo pode usar `supabase-py`, `@supabase/ssr` e `@supabase/supabase-js` como bibliotecas cliente, mas elas devem apontar para a stack local/self-hosted.

## Storage Local

A API usa `LOCAL_STORAGE_DIR=/app/local-storage` no Docker. Arquivos enviados ficam no volume `brain_local_storage`, sem dependencia de Supabase Storage online.

## Legado SaaS

Arquivos antigos de deploy SaaS foram arquivados em `legacy/saas/`. Eles existem apenas como historico e nao fazem parte do fluxo oficial.

## Documentacao De Dominio

A documentacao do fluxo, hierarquia e grafo de conhecimento fica em `docs/knowledge-flow.md`.
