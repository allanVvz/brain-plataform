# Isolamento QA e producao

## Estado atual

- Producao: dashboard Vercel e backend servido em dois dominios permanentes, `https://api.vzforeal.com` e `https://lpapi.vzforeal.com` (decisao final, ver secao "Decisao final sobre dominios" abaixo — nao e mais um estado transitorio).
- QA temporario (docker local no laptop, sem persistencia): continua existindo como esta descrito na secao "Operacao local" abaixo, sem mudanca.
- QA persistente: ver secao "QA persistente (mesma VPS)" abaixo. **Substitui** a nota antiga que pedia uma segunda VPS — decisao revertida explicitamente pelo dono do produto em 2026-08-06: QA persistente roda na mesma VPS da producao.

## QA persistente (mesma VPS)

Decisao de 2026-08-06: em vez de uma segunda VPS, o QA persistente roda como
um segundo projeto Docker Compose (`brain-ai-qa`) na mesma VPS da producao
(`brain-ai`), com API e banco proprios e isolados, compartilhando apenas
`n8n`/Evolution com a producao (consequencia aceita: QA nao tem fluxo de
WhatsApp automatizado de ponta a ponta — so dashboard, API, grafo e banco).

- **Branch**: `qa`, criada a partir da `main`. Sem deploy automatico em push
  — o workflow `.github/workflows/deploy-qa.yml` so roda via
  `workflow_dispatch` (`action: up|down|refresh-db`). Essa e a feature flag
  pedida: push em `qa` nao consome nada na VPS; so um disparo manual liga o
  stack para uma sessao de teste, e `action: down` desliga tudo de novo
  (containers removidos, so os volumes de dado ficam em disco).
- **Layout na VPS**: segundo checkout em `/opt/brain-ai-qa`, `.env.compose`
  proprio com `COMPOSE_PROJECT_NAME=brain-ai-qa`, dominios
  `api-qa.vzforeal.com`/`storage-qa.vzforeal.com`, segredos gerados
  separados (`infra/generate_keys.py --write .env.compose`).
- **`ENVIRONMENT=production` no `.env.compose` de QA** (nao `qa`) —
  `api/utils/env.py` so trata `ENVIRONMENT=production` como modo estrito
  (cookie seguro, validacao obrigatoria). Como este QA e exposto
  publicamente em HTTPS na mesma VPS da producao, precisa da mesma postura
  de seguranca; o isolamento vem do dominio/banco/segredos separados, nao
  desse valor. O `ENVIRONMENT=qa` que ja existia em `.env.compose.example`
  continua servindo so para o QA local efemero no laptop (secao acima),
  sem exposicao publica.
- **Rede compartilhada `edge`**: o Caddy da producao (unico a segurar as
  portas 80/443 da VPS) alcanca o `api`/`kong` do stack de QA por uma rede
  Docker externa `edge`, com aliases qualificados por projeto
  (`api-brain-ai-qa`, `kong-brain-ai-qa`) — ver `docker-compose.yml` e
  `infra/Caddyfile`. Criada automaticamente (idempotente) por
  `ops/vps/deploy.sh` e `ops/vps/deploy-qa.sh`.
- **Refresh do banco**: `ops/vps/qa-refresh-db.sh`, agendado via crontab da
  VPS (`0 4 * * * /opt/brain-ai-qa/ops/vps/qa-refresh-db.sh >> /var/log/brain-ai-qa-refresh.log 2>&1`).
  `pg_dump -Fc` da producao seguido de `pg_restore --clean --if-exists
  --no-owner` no banco de QA — snapshot completo, nao replicacao continua
  (QA precisa poder rodar migrations/mutacoes proprias sem quebrar). So
  le da producao, nunca escreve. No-op se o stack de QA estiver desligado.
- **Scripts novos** (`ops/vps/`): `deploy-qa.sh`, `rollback-qa.sh`,
  `qa-down.sh`, `qa-refresh-db.sh`. `ops/vps/audit.sh` e reutilizado sem
  mudanca (ja e parametrizado por `ENV_FILE`, sem nada hardcoded de
  producao). `ops/vps/validate_env.py` ganhou
  `EXPECTED_COMPOSE_PROJECT_NAME` (default `brain-ai`, retrocompativel) para
  aceitar `brain-ai-qa`.

### Passos manuais pendentes (fora do repo)

1. DNS: `api-qa.vzforeal.com` e `storage-qa.vzforeal.com` -> IP da VPS.
2. Na VPS: `mkdir -p /opt/brain-ai-qa` + `.env.compose` de QA (ver acima).
3. GitHub: Environment `qa` com secrets `VPS_HOST`, `VPS_USER`,
   `VPS_SSH_KEY` (mesma VPS/chave da producao), `VPS_APP_DIR_QA=/opt/brain-ai-qa`.
4. Crontab da VPS com a linha do `qa-refresh-db.sh` acima.
5. `.env.compose` da **producao** ganha `API_DOMAIN_QA`/`STORAGE_DOMAIN_QA`
   (o Caddy compartilhado le essas variaveis; sem elas usa um placeholder
   `.invalid` que nunca resolve, entao a producao nunca quebra por falta
   dessas variaveis).

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

### Decisao final sobre dominios (2026-08-03)

O dono do produto decidiu **manter `lpapi.vzforeal.com` permanentemente**, em vez de migrar tudo para `api.vzforeal.com` e desativar o antigo. Isso fecha o que antes estava listado como "pendente":

- `API_DOMAIN` no `.env.compose` da VPS **continua e continuara** `lpapi.vzforeal.com` — nao ha plano de trocar. O Caddyfile serve os dois nomes (`api.vzforeal.com, lpapi.vzforeal.com`) de forma permanente, nao transitoria.
- Callback URL do WhatsApp no Meta App Dashboard **permanece** `https://lpapi.vzforeal.com/webhooks/whatsapp` — decisao explicita de nao mexer, ja que o dominio nao vai sair do ar. Nenhuma acao necessaria no Meta.
- `api.vzforeal.com` fica ativo como dominio alternativo/documentado (e o que a Vercel usa em `API_INTERNAL_BASE_URL`), mas ambos sao dominios de producao validos dali em diante — nao remover nenhum dos dois do Caddyfile/DNS sem nova decisao explicita.
- Rotacao dos segredos do Meta (`META_WHATSAPP_ACCESS_TOKEN`, `META_WHATSAPP_APP_SECRET`, `META_WHATSAPP_VERIFY_TOKEN`), que foram impressos por engano no terminal durante o diagnostico anterior (comando `grep` sem filtrar valores): **dono do produto optou por nao rotacionar.** Risco residual aceito e registrado aqui — se esses valores vazarem de fato (fora deste ambiente), a rotacao volta a ser necessaria.

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
- **Producao (desde 2026-08-03): `BULK_CAMPAIGNS_ROLLOUT1_ENABLED=true` globalmente**, aprovado e habilitado pelo dono do produto para todas as personas (nao ficou restrito a canario). Uma persona especifica ainda pode ser bloqueada individualmente com `config.bulk_campaigns.enabled=false`.
- Rollout 1 nao envia; cria apenas imports, consents, previews e drafts. **Nao existe nenhum caminho de codigo, no admin ou no portal do cliente, que envie mensagem real** — isso e a Entrega 2, ainda nao construida.
- Testes de provider usam mock. Credenciais Meta/Evolution reais nao entram no QA local sem autorizacao explicita.

## Release de 2026-08-03: bulk campaigns + Sofia agent harness + Disparos no portal do cliente

Merge de `feat/sofia-agent-harness` (que ja continha `feature/bulk-campaigns-rollout1`) em `main`, commit `ab16e57634dc2e644081543221f7c57d7bb1d74c`, com deploy completo em producao (nao ficou restrito a canario — decisao explicita do dono do produto).

O que foi ao ar:
- Import de leads, consentimento, audiences semanticas, preview/draft/pause/cancel de campanhas (admin, `/disparos`).
- Mesma funcionalidade de campanhas portada para o portal do cliente em `/clientes/[personaSlug]/disparos`, via rotas novas `GET/POST /portal/campaigns*` em `api/routes/portal.py` (resolvem por `persona_slug`, reusam `campaigns_service` sem duplicar logica). Import de lista nova continua exclusivo do admin — o portal do cliente so le imports ja existentes.
- Sofia agent harness (sessoes/runs/steps duraveis, RLS service-only, grants por ferramenta, QA gate antes de write/destructive).
- Migrations `087_campaign_delivery_one.sql`, `088_sofia_agent_harness.sql`, `089_fix_semantic_group_replay.sql` aplicadas em producao.

Validacao antes do deploy: suite completa do backend (366 passed, 2 skipped, 0 failed) e do dashboard (84 testes + build) rodada duas vezes — antes e depois do merge em `main` — sem regressao.

### Incidente no deploy automatico

O primeiro push para `main` **nao implantou** por causa de um secret do GitHub Actions quebrado:

```
Run appleboy/scp-action@v1.0.0
Error: can't connect without a private SSH key or password
```

Diagnostico: o secret `VPS_SSH_KEY` esta vazio ou com conteudo invalido. Investigando as chaves autorizadas na VPS (`~/.ssh/authorized_keys` do `root`), existe uma chave com comentario `brain-deploy` — feita de proposito para CI/CD — cujo par privado e `C:\Users\allan\.ssh\id_ed25519` nesta maquina local. Confirmado por teste real de SSH que essa chave autentica na VPS.

**Pendente (acao do dono do produto no GitHub, fora deste repo):** copiar o conteudo de `C:\Users\allan\.ssh\id_ed25519` para o secret `VPS_SSH_KEY` em Settings → Secrets and variables → Actions. Ate isso ser feito, deploys automaticos por push em `main` podem falhar na etapa de sincronizacao e precisar de re-run manual no GitHub Actions (o segundo run, sem nenhuma mudanca de secret, funcionou — sugerindo intermitencia, nao apenas ausencia total do secret).

O deploy desta release acabou concluido pelo proprio pipeline numa nova tentativa (sem intervencao manual no backend); nao foi necessario aplicar o workaround manual (scp + `ops/vps/deploy.sh` direto) que havia sido preparado como contingencia.

### Achado pendente: redirecionamento de login ignora tipo de conta

`dashboard/lib/session-routing.ts`, funcao `resolveSessionDestination`: para contas que nao sao `client`, um `next=` na URL de login e seguido sem validacao (`return target && target !== "/login" ? target : fallback`), diferente do que acontece para conta `client` (que passa por `authorizedClientTarget`). Isso fez uma conta admin (`allanulisses@hotmail.com`, `role=admin`, `account_type=internal` — configuracao correta) cair no portal do cliente apos logar, porque havia acessado uma URL `/clientes/...` antes e ficou com esse `next` pendente. Nao e bug de permissao/dado; e o login "lembrando" o destino anterior sem checar se faz sentido para o tipo de conta. Fix proposto e ainda nao aplicado (aguardando decisao do dono do produto).

## Promocao

1. Validar migration, testes Python, build do dashboard e Docker local.
2. Confirmar backup e migration expand-first.
3. Publicar backend ainda com flag desabilitada.
4. Habilitar leitura/drafts em uma persona canario.
5. Somente a Entrega 2 habilita envio Meta; Evolution continua desabilitado.

## Incidente ou rollback

Desabilite a flag global e, se necessario, `personas.config.bulk_campaigns.enabled=false`. Pause campanhas antes de qualquer rollout com envio. Nao apague imports, consents, revisions, recipients ou eventos: sao trilha de auditoria. Outbounds ambiguos permanecem bloqueados para revisao. O envio individual e as conversas continuam operando.
