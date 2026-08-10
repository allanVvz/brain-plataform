# Brain AI na VPS Hostinger

Este e o runbook oficial do backend de producao. O dashboard continua na Vercel e chama a API pelo rewrite same-origin `/api-brain`.

## Arquitetura e portas

- Publicas: Caddy em TCP `80`, TCP/UDP `443`.
- Auditoria no host: API ligada somente a `127.0.0.1:8080`.
- Somente na rede Docker: Postgres, PostgREST, Storage e Kong.
- Estado persistente: `postgres-data`, `storage-data`, `local-storage`, `vault-data`, `caddy-data` e `caddy-config`.
- `migrate` aplica o bootstrap legacy e as 47 migrations com ledger; `api` e `workers` so iniciam depois de sucesso.
- `api` e `workers` usam a mesma imagem imutavel. Workers executam `python -m workers.runner --all`.

## 1. Preparar DNS e host

Crie registros A/AAAA de `api.<dominio>` e `storage.<dominio>` para a VPS antes do primeiro start do Caddy. Requisitos minimos: 2 vCPU, 8 GB RAM, 100 GB de disco, Docker Engine, plugin Compose e Git.

No firewall Hostinger e no UFW permita somente SSH, HTTP e HTTPS:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
```

Confirme `PasswordAuthentication no`, `PermitRootLogin no` em `sshd_config`, valide com `sshd -t` e somente entao recarregue o SSH. Mantenha uma segunda sessao aberta durante essa mudanca para evitar lockout.

## 2. Configurar secrets e imagens

```bash
cp .env.compose.example .env.compose
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
python3 infra/generate_keys.py --write .env.compose
```

Edite `.env.compose` e defina:

- senhas aleatorias e distintas em `POSTGRES_PASSWORD`, `AI_BRAIN_AUTH_SECRET` e `AI_BRAIN_WEBHOOK_TOKEN`;
- `API_DOMAIN`, `STORAGE_DOMAIN`, `ACME_EMAIL` e `SUPABASE_PUBLIC_URL`;
- `ALLOWED_ORIGINS` somente com o dashboard/site aprovados;
- opcionalmente um `ALLOWED_ORIGIN_REGEX` ancorado ao projeto de preview da Vercel;
- `API_IMAGE=ghcr.io/<owner>/<repo>/brain-api`;
- `MIGRATE_IMAGE=ghcr.io/<owner>/<repo>/brain-migrate`;
- chaves de provedores, se usadas.

Opcional: observabilidade de LLM/agentes (dashboards Grafana lendo
`agent_logs`/`system_events`/`n8n_executions` diretamente, sem infra nova
além do proprio Grafana). Desligado por padrao — passo a passo completo
(variaveis, DNS, verificacao) em
[`OBSERVABILITY_GRAFANA_SETUP.md`](OBSERVABILITY_GRAFANA_SETUP.md).

Valide antes de iniciar:

```bash
python3 ops/vps/validate_env.py .env.compose
docker compose --env-file .env.compose config >/dev/null
```

Nunca copie `api/.env` para a VPS. O contexto da imagem exclui `.env*`; `.env.compose` permanece apenas no host.

## 3. Primeiro boot e admin

Para build local inicial:

```bash
docker compose --env-file .env.compose up -d --build
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose logs migrate api workers
curl http://127.0.0.1:8080/health/ready
```

Para criar o primeiro admin, preencha temporariamente `AI_BRAIN_SEED_ADMIN_EMAIL` e `AI_BRAIN_SEED_ADMIN_PASSWORD`, execute:

```bash
docker compose --env-file .env.compose up --force-recreate seed-admin
```

Remova imediatamente a senha de `.env.compose`. Nao existe login de desenvolvimento no bootstrap de producao.

## 4. Vercel e CORS

No projeto Vercel com root `dashboard`, configure:

```text
API_INTERNAL_BASE_URL=https://api.<dominio>
NEXT_PUBLIC_API_BASE_URL=/api-brain
```

Nao configure `SUPABASE_SERVICE_KEY` ou segredos do backend na Vercel. O Storage publico recebe apenas `/storage/v1/*`; PostgREST nao e publicado nesse dominio.

## 5. Ensaio de migracao

Execute pelo menos uma restauracao integral antes da virada:

1. No ambiente fonte, rode `bash ops/vps/audit.sh` e guarde a saida.
2. Gere um backup com `BACKUP_ROOT=/caminho/seguro bash ops/vps/backup.sh`.
3. Transfira o diretorio fechado com `rsync -a --checksum` ou `scp` por SSH.
4. Na VPS, execute `bash ops/vps/restore.sh <diretorio> --confirm-destructive-restore`.
5. Rode `bash ops/vps/audit.sh` e compare tamanho, personas, usuarios, nodes, edges, RAG entries/chunks, assets e orphan edges.
6. Valide login, isolamento 403 entre personas, leitura/upload de asset, menu publico e processamento dos workers.

O restore e destrutivo no destino e exige a flag literal. Nunca o execute no ambiente fonte.

## 6. Virada em ate 30 minutos

Antes da janela, deixe imagens, DNS, TLS e restore de ensaio prontos.

1. No fonte, execute `BACKUP_ROOT=/caminho/seguro bash ops/vps/cutover-export.sh`. Caddy/API/workers param e as escritas ficam bloqueadas.
2. Transfira o novo backup com checksum.
3. Restaure na VPS e execute migrations pendentes.
4. Rode a auditoria e os testes abaixo.
5. Atualize `API_INTERNAL_BASE_URL` na Vercel e publique/promova o dashboard.
6. Mantenha o fonte parado, mas intacto, ate aprovacao final.

Rollback da virada: restaure as variaveis anteriores da Vercel e suba novamente Caddy/API/workers no ambiente antigo. Nao destrua nenhum volume antigo durante a janela.

## 7. CI/CD e rollback de versao

O workflow `deploy-production.yml`, em push para `main`, compila/testa, builda o dashboard, valida Compose, publica duas imagens GHCR com tag igual ao SHA e chama `ops/vps/deploy.sh` por SSH.

GitHub Secrets obrigatorios:

- `VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_APP_DIR`;
- `GHCR_USERNAME`, `GHCR_TOKEN` com leitura dos pacotes privados.

Proteja o environment GitHub `production` com aprovadores. O deploy grava tags saudaveis em `.deploy/`. Se o readiness falhar, volta automaticamente aos containers da tag anterior. Rollback manual:

```bash
bash ops/vps/rollback.sh
# ou uma tag especifica
bash ops/vps/rollback.sh <commit-sha>
```

Migrations de producao precisam permanecer retrocompativeis com a imagem anterior; rollback de container nao desfaz schema.

## 8. Backup, retencao e monitoramento

Agende como root (ajuste caminhos):

```cron
15 2 * * * cd /opt/brain-ai && BACKUP_ROOT=/var/backups/brain-ai bash ops/vps/backup.sh >> /var/log/brain-backup.log 2>&1
*/5 * * * * cd /opt/brain-ai && bash ops/vps/monitor.sh || /usr/local/bin/notify-brain-ops
```

O backup mantem 7 diarios e 4 semanais (hard links no mesmo filesystem) e inclui Postgres, Storage, arquivos locais e vault. Configure tambem snapshot da VPS e copie backups para outro host/bucket. O monitor falha para containers parados/unhealthy, disco >=85%, memoria >=90% ou backup com mais de 26 horas.

Teste a restauracao regularmente; backup sem restore comprovado nao atende o gate de liberacao.

## 9. Validacao de release

```bash
bash ops/vps/audit.sh
curl https://api.<dominio>/health
curl https://api.<dominio>/health/ready
curl https://api.<dominio>/api/menu/<persona_slug>
curl https://<dashboard>/api-brain/health
docker compose --env-file .env.compose logs --tail=200 workers
```

Confirme ainda:

- apenas `22`, `80` e `443` acessiveis externamente;
- certificado valido nos dois dominios;
- cookie de login `HttpOnly`, `Secure`, `SameSite=Lax` e logout removendo a sessao;
- usuario nao admin recebe 403 para persona nao atribuida, sem nomes vazados;
- upload e leitura pelo dominio de Storage;
- webhook `/process` rejeitando token ausente/invalido e aceitando `X-Webhook-Token` valido;
- contagens e vinculos do grafo/RAG iguais ao fonte e zero edges orfas;
- worker sem duplicacao observavel;
- deploy de teste e rollback manual executados ao menos uma vez.

## 10. Troca para dominio definitivo

Crie o DNS definitivo, adicione temporariamente as novas origens ao CORS, atualize `API_DOMAIN`, `STORAGE_DOMAIN`, `SUPABASE_PUBLIC_URL` e `API_INTERNAL_BASE_URL` na Vercel, recrie Caddy/API/workers e valide. Depois remova os dominios temporarios do CORS e do DNS. URLs de assets sao geradas com `SUPABASE_PUBLIC_URL`, portanto nao expõem `kong:8000`.
