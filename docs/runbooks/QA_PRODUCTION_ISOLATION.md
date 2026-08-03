# Isolamento QA e producao

## Estado atual

- Producao: dashboard Vercel e backend `https://api.vzforeal.com`.
- QA temporario: Docker Compose local com `.env.compose`.
- Segunda VPS: pre-requisito pendente para QA persistente; nao simular QA em producao.

## Auditoria dos projetos Vercel (2026-08-03)

A conta Vercel (`allanulise027-3939s-projects`) tem dois projetos que podem ser confundidos por causa dos aliases de deploy, mas nao sao o mesmo produto nem QA/producao do mesmo app:

| Projeto Vercel | Alias observado | O que e | Origem |
|---|---|---|---|
| `brain-plataform` | `brain-plataform-plum.vercel.app` | **Este repositorio** (`dashboard/`, pacote `ai-brain-dashboard`). E o dashboard de producao descrito em `dashboard/DEPLOY.md` e `VPS_PRODUCTION_RUNBOOK.md`. Nao existe hoje um projeto Vercel dedicado a QA — QA persistente segue sendo so Docker local (`.env.compose`), conforme o restante deste runbook. |
| `north-portal` | `north-portal-navy.vercel.app` | Produto separado (portal admin/cliente: kanban, planos, aprovacoes, documentos). Usa Supabase direto no browser (`NEXT_PUBLIC_SUPABASE_*`, `SUPABASE_SERVICE_ROLE_KEY`). Nao esta na lista `ALLOWED_ORIGINS` do backend `api/` e nao compartilha arquitetura com este repo. |

Os apelidos `-plum` e `-navy` sao sufixos aleatorios que a Vercel atribui por projeto (nao indicam ambiente). Nenhum dos dois projetos deve ser tratado como "QA" e "producao" do mesmo app.

## Erro encontrado: dominio do backend divergente entre docs e producao real

- Docs (`README.md`, `dashboard/DEPLOY.md`, `VPS_PRODUCTION_RUNBOOK.md`) descrevem o backend de producao como `https://api.vzforeal.com`.
- A variavel `API_INTERNAL_BASE_URL` configurada no projeto Vercel `brain-plataform` (Production) aponta para `https://lpapi.vzforeal.com` — dominio que nao aparece em nenhum doc do repo.
- Validacao (2026-08-03):
  - `https://lpapi.vzforeal.com/health` -> `200 OK` (`{"status":"ok","service":"api",...}`). E o backend real, ativo.
  - `https://api.vzforeal.com/health` -> falha no handshake TLS. DNS resolve para o mesmo IP (`179.197.233.12`) do `lpapi.vzforeal.com`, mas o Caddy nao serve certificado/site block para esse host.
  - Confirmado via SSH na VPS (`/opt/brain-ai/.env.compose`): `API_DOMAIN=lpapi.vzforeal.com`. O Caddy (`infra/Caddyfile`, bloco `{$API_DOMAIN}`) so emite certificado ACME e faz proxy para o host configurado ali — por isso `api.vzforeal.com` fica sem TLS valido.
  - `ALLOWED_ORIGINS` na VPS inclui `brain-plataform.vercel.app`, `brain-plataform-plum.vercel.app` e a preview `git-main`, mas nao inclui `north-portal-navy.vercel.app` (reforca que sao produtos diferentes).

Causa provavel: a VPS foi provisionada originalmente sob `lpapi.vzforeal.com` (esse host tambem aparece no `known_hosts` local de quem administra a VPS) e a "troca para dominio definitivo" (`VPS_PRODUCTION_RUNBOOK.md`, secao 10) para `api.vzforeal.com` foi documentada mas nunca executada — DNS de `api.vzforeal.com` foi criado, porem `API_DOMAIN` no `.env.compose` e o `API_INTERNAL_BASE_URL` na Vercel continuam apontando para o dominio antigo.

### Correcao aplicada (2026-08-03)

Executada em modo dual-domain para nao derrubar o webhook Meta/WhatsApp (persona `baita-conveniencia`, `META_WHATSAPP_PHONE_NUMBER_ID=949967854877404`), cujo Callback URL cadastrado na Meta ainda aponta para `lpapi.vzforeal.com`:

1. `infra/Caddyfile` na VPS (`/opt/brain-ai/infra/Caddyfile`) teve o site block da API alterado de `{$API_DOMAIN} {` para `api.vzforeal.com, lpapi.vzforeal.com {` — os dois dominios ficam ativos e validos ao mesmo tempo. Backup salvo como `Caddyfile.bak-<timestamp>` no mesmo diretorio.
2. `docker compose --env-file .env.compose up -d --force-recreate caddy` na VPS (isso tambem recriou `migrate` e `api`, dependencias do `caddy`; `workers` nao foi afetado). Confirmado `https://api.vzforeal.com/health` e `https://lpapi.vzforeal.com/health` -> `200 OK`.
3. `API_INTERNAL_BASE_URL` do projeto Vercel `brain-plataform` (Production) atualizado para `https://api.vzforeal.com`.
4. Redeploy de producao disparado via `vercel redeploy` (rebuild a partir do deployment anterior, sem usar o working tree local que tem mudancas nao commitadas de outra feature). Confirmado `https://brain-plataform-plum.vercel.app/api-brain/health` -> `200 OK` atraves do novo dominio.

### Pendente (acao manual fora deste repo)

- `API_DOMAIN` no `.env.compose` da VPS **continua** `lpapi.vzforeal.com` (nao foi alterado) — o Caddyfile e que hoje serve os dois nomes. Isso e intencional ate o passo abaixo ser concluido.
- Atualizar o Callback URL do WhatsApp no Meta App Dashboard (app da persona `baita-conveniencia`) de `https://lpapi.vzforeal.com/webhooks/whatsapp` para `https://api.vzforeal.com/webhooks/whatsapp` e revalidar o challenge com `META_WHATSAPP_VERIFY_TOKEN`.
- So depois disso: remover `lpapi.vzforeal.com` do Caddyfile (voltar para `{$API_DOMAIN}` com `API_DOMAIN=api.vzforeal.com` no `.env.compose`), atualizar `ALLOWED_ORIGINS`/DNS se necessario, e recriar o Caddy mais uma vez.
- Segredos do Meta (`META_WHATSAPP_ACCESS_TOKEN`, `META_WHATSAPP_APP_SECRET`, `META_WHATSAPP_VERIFY_TOKEN`) foram impressos por engano no terminal durante o diagnostico (comando `grep` sem filtrar valores) — recomendado rotacionar por precaucao, mesmo sem exposicao a terceiros.

## Operacao local

```powershell
docker compose --env-file .env.compose up -d --build
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose logs db api workers
curl http://localhost:8080/health
curl http://localhost:8080/api/menu/baita-conveniencia
```

Use `ENVIRONMENT=qa` somente localmente para o admin token compartilhado. O dashboard usa `NEXT_PUBLIC_API_BASE_URL=/api-brain` e o rewrite local aponta para `API_INTERNAL_BASE_URL=http://localhost:8080`. Nunca aponte o dashboard de QA para o backend de producao.

## Campanhas

- Rollout 1 local: `BULK_CAMPAIGNS_ROLLOUT1_ENABLED=true`, ou o default de `ENVIRONMENT=qa`.
- Producao: flag ausente/false ate aprovacao do rollout; uma persona tambem pode ser bloqueada com `config.bulk_campaigns.enabled=false`.
- Rollout 1 nao envia; cria apenas imports, consents, previews e drafts.
- Testes de provider usam mock. Credenciais Meta/Evolution reais nao entram no QA local sem autorizacao explicita.

## Promocao

1. Validar migration, testes Python, build do dashboard e Docker local.
2. Confirmar backup e migration expand-first.
3. Publicar backend ainda com flag desabilitada.
4. Habilitar leitura/drafts em uma persona canario.
5. Somente a Entrega 2 habilita envio Meta; Evolution continua desabilitado.

## Incidente ou rollback

Desabilite a flag global e, se necessario, `personas.config.bulk_campaigns.enabled=false`. Pause campanhas antes de qualquer rollout com envio. Nao apague imports, consents, revisions, recipients ou eventos: sao trilha de auditoria. Outbounds ambiguos permanecem bloqueados para revisao. O envio individual e as conversas continuam operando.
