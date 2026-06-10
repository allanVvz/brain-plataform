# AI Brain

AI Brain e um dashboard Next.js + backend FastAPI para CRM, Knowledge Graph e RAG.

## Estado Operacional

A rota operacional atual e local-first, auditavel por Docker Compose.

Servicos principais:

| Servico | Papel | Porta |
|---|---|---|
| `db` | Postgres local com schemas usados pela aplicacao | `5432` |
| `storage` | API local de storage | interno |
| `rest` | PostgREST local | interno |
| `kong` | gateway local para REST/storage | `8000` |
| `migrate` | bootstrap e migrations | one-shot |
| `api` | FastAPI backend | `8080` |
| `workers` | jobs em processo separado | interno |
| `studio` | admin opcional | `3030` |

Comando oficial para subir a stack:

```powershell
docker compose --env-file .env.compose up -d --build
```

Auditoria minima:

```powershell
docker compose --env-file .env.compose ps
curl http://localhost:8080/health
curl http://localhost:8080/api/menu/baita-conveniencia
```

## Dashboard

O dashboard fica em `dashboard/` e deve chamar o backend sempre por `/api-brain`.

Variaveis locais esperadas em `dashboard/.env.local`:

```text
API_INTERNAL_BASE_URL=http://localhost:8080
NEXT_PUBLIC_API_BASE_URL=/api-brain
```

Subir localmente:

```powershell
cd dashboard
npm run dev:local
```

Validar proxy:

```powershell
curl http://localhost:3000/api-brain/health
```

## Auth

Todas as telas internas exigem login. A sessao fica em cookie HTTP-only.

Regras importantes:

- Em local Docker, `ENVIRONMENT` deve ser `qa`.
- `ENVIRONMENT=production` força cookie `Secure`; em `http://localhost:3000`, isso pode impedir o navegador de manter a sessao.
- O admin local atual deve ser criado ou resetado com `api/scripts/create_auth_user.py`.
- Senha nao deve ser versionada no repositorio.

Exemplo operacional:

```powershell
cd api
python scripts/create_auth_user.py --email admin@local.dev --username admin --password "<senha>" --role admin
```

## Producao

O frontend de producao esta no Vercel project `brain-plataform`.

O dashboard de producao usa o mesmo prefixo `/api-brain` do desenvolvimento. No Vercel, `API_INTERNAL_BASE_URL` precisa apontar para um backend HTTPS publico e aprovado. URLs locais como `localhost:8080` nao funcionam dentro do ambiente Vercel.

Antes de liberar para cliente:

1. Garantir que o alias de producao Vercel aponte para uma versao com `/login`.
2. Garantir que `API_INTERNAL_BASE_URL` de producao aponte para o backend final escolhido.
3. Criar/resetar o mesmo admin no banco local e no banco de producao.
4. Rodar `npm run build` em `dashboard/`.
5. Validar `GET /api-brain/health`, `GET /login`, `POST /api-brain/auth/login` e `GET /api-brain/auth/me` no dominio final.

## Estrutura

```text
api/        FastAPI backend
dashboard/  Next.js frontend
docker-compose.yml
```

Arquivos importantes:

- `api/requirements.txt`
- `dashboard/lib/api.ts`
- `dashboard/next.config.js`
- `.github/workflows/ci.yml`

## Knowledge Graph

Todo conhecimento que entra em KB/RAG precisa aparecer no grafo:

```text
knowledge_items / knowledge_intake_messages
-> validacao
-> knowledge_rag_entries / knowledge_rag_chunks quando aplicavel
-> knowledge_nodes
-> knowledge_edges
-> grafo/sidebar/agentes/chat-context
```

Se nao aparece no grafo, esta incompleto.
