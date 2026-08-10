# Ativar a observabilidade de LLM/agentes (Grafana)

Este documento é o complemento operacional do plano de observabilidade
(traces por turno em `agent_logs`, ligados por `trace_id`; ver migrations
`106`/`107` e `api/services/conversation_runtime.py::emit_turn_event`).
Cobre exatamente o que falta para deixar isso visível num dashboard.

## O que já está automatizado (nada disso precisa de passo manual)

- **Compose**: serviço `grafana` (`docker-compose.yml`, profile
  `observability`), com `mem_limit: 512m` e dependência em `migrate`
  concluir antes de subir.
- **Caddy**: bloco de site para `{$GRAFANA_DOMAIN}` já existe em
  `infra/Caddyfile` — Caddy emite o certificado TLS automaticamente (Let's
  Encrypt, mesmo mecanismo dos outros domínios) assim que o DNS apontar
  para a VPS. Nenhum comando de certificado a rodar.
- **Role de banco somente-leitura**: `db-bootstrap` (dentro do
  `docker-compose.yml`) cria a role `grafana_reader` (idempotente, roda em
  todo deploy) e só ativa login/senha nela quando `GRAFANA_PG_PASSWORD`
  está definida. A migration `107_grafana_reader_grants.sql` concede
  `SELECT` em `agent_logs`, `system_events`, `n8n_executions`, `messages`
  e `leads` — nunca `INSERT`/`UPDATE`/`DELETE`.
- **Datasource do Grafana**: `infra/grafana/provisioning/datasources/postgres.yaml`
  já aponta pro Postgres da VPS com a role acima, senha lida da variável de
  ambiente do próprio container — nenhum clique dentro do Grafana.
- **Dashboards**: `infra/grafana/dashboards/llm-observability.json`
  (custo por 100 mensagens/por conversa, tokens por modelo, latência
  p50/p95, taxa de erro, taxa de handoff, repair loops, cache hit/miss,
  qualidade — os dois últimos ficam vazios até as Fases condicionais/4)
  carregado via `infra/grafana/provisioning/dashboards/dashboards.yaml` —
  já aparece pronto no primeiro login, sem importar nada manualmente.
- **Deploy**: `ops/vps/deploy.sh` ativa o profile `observability`, faz
  `pull`/`up -d` do `grafana` e roda `db-bootstrap` novamente em todo
  deploy (correção aplicada nesta sessão — antes só rodava no primeiro
  boot da VPS, o que teria deixado a role `grafana_reader` inexistente
  numa VPS já em produção como a sua). `ops/vps/validate_env.py` bloqueia
  o deploy se `OBSERVABILITY_ENABLED=true` e faltar alguma variável abaixo.
  `deploy-production.yml` já leva `infra/grafana` no `scp` para a VPS.

## O que você precisa preencher

Edite `.env.compose` na VPS (nunca commitar este arquivo) e defina:

| Variável | O que é | Exemplo |
|---|---|---|
| `GRAFANA_DOMAIN` | Subdomínio dedicado ao Grafana, com DNS A/AAAA apontando pra VPS antes do deploy (mesmo padrão de `API_DOMAIN`/`N8N_DOMAIN`) | `grafana.seudominio.com` |
| `GRAFANA_ADMIN_USER` | Usuário de login do Grafana | `allanulisses` |
| `GRAFANA_ADMIN_PASSWORD` | Senha do usuário acima — **exposto publicamente por HTTPS, sem VPN/allowlist (decisão explícita sua)**, então vale a pena ser uma senha longa/aleatória de verdade, não uma curta e previsível | — |
| `GRAFANA_PG_PASSWORD` | Senha da role `grafana_reader` (interna, não é a mesma senha do admin do Grafana) — gere com `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` | — |
| `OBSERVABILITY_ENABLED` | Liga o profile inteiro | `true` |

> A senha de admin do Grafana que você me passou no chat (`allanulisses` /
> `Morada@;`) **não foi escrita em nenhum arquivo do repositório** — só
> vive no seu `.env.compose`, que nunca é commitado. Ela é curta e
> previsível para um login exposto publicamente sem outra camada de
> proteção; recomendo trocá-la por algo mais longo antes de ativar em
> produção, mas a escolha é sua — o valor que você definir em
> `GRAFANA_ADMIN_PASSWORD` é o que vale.

## Passos (na ordem)

1. **DNS**: crie o registro A/AAAA de `GRAFANA_DOMAIN` apontando para o IP
   da VPS (mesmo processo já usado para os outros domínios).
2. **Secrets**: edite `.env.compose` na VPS e defina as 5 variáveis da
   tabela acima.
3. **Deploy**: rode o deploy normal (`push` na `main`, que já dispara
   `deploy-production.yml` → `ops/vps/deploy.sh`, ou manualmente
   `bash ops/vps/deploy.sh <tag>` na VPS). Nenhum comando extra.
4. **Login**: acesse `https://<GRAFANA_DOMAIN>`, entre com
   `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`, abra a pasta
   "Brain/Aurora" → dashboard "Brain/Aurora — Observabilidade de LLM".

Nenhum passo manual dentro do container ou da interface do Grafana além
disso — o datasource e os dashboards já estarão lá no primeiro login.

## O que vai aparecer vazio no início (de propósito, não é bug)

- **Custo (USD)**: `cost_usd` fica `NULL` até você confirmar o preço real
  da DeepSeek em `api/services/model_pricing.py` (hoje só tem
  `confirmed: False` — ver comentário no arquivo). Assim que confirmar,
  todo turno novo passa a ter custo calculado; turnos antigos continuam
  sem custo (não há recomputação retroativa).
- **Cache hit/miss**: só preenche depois de confirmar o nome exato do
  campo de cache tokens na API da DeepSeek (Fase 1 condicional do plano).
- **Qualidade média**: reservado para a Fase 4 (deliberadamente adiada —
  precisa de escopo próprio, não é um botão a apertar).

## Verificação rápida depois do deploy

```bash
# na VPS
docker compose --env-file .env.compose --profile observability ps grafana
docker compose --env-file .env.compose exec db psql -U postgres -d brain \
  -c "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'grafana_reader';"
```

`rolcanlogin` deve ser `t` (true) depois que `GRAFANA_PG_PASSWORD` estiver
definida e o deploy tiver rodado.
