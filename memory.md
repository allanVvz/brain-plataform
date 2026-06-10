# Memory - AI Brain Login/Deploy Audit

Data: 2026-06-10
Branch local: `feat/docker-self-hosted-stack`
Commit local: `5e69887`

## Resumo Executivo

O login local falhava por dois motivos provaveis:

1. O frontend nao estava respondendo em `localhost:3000` no inicio da auditoria.
2. `.env.compose` estava com `ENVIRONMENT=production`, o que faz o backend marcar o cookie de sessao como `Secure`. Em `http://localhost:3000`, o navegador pode rejeitar esse cookie, entao o login parece funcionar mas a sessao nao persiste.

Corrigido localmente:

- `.env.compose`: `ENVIRONMENT=qa`.
- Front local iniciado com `npm run dev:local`.
- Proxy local validado em `http://localhost:3000/api-brain/health`.

Estado do deploy auditado:

- Projeto Vercel: `brain-plataform`
- Project ID: `prj_wG3cuvO6oKtY3HdBy8KjnCl1GtoS`
- Team ID: `team_BYL7O3PYN3R0yqJxvAVJzuOQ`
- O deploy preview mais recente esta `READY`, mas o alias de producao ainda esta desatualizado.
- Depois da correcao, `https://brain-plataform.vercel.app/login` retornou `200`.
- Depois da correcao, `https://brain-plataform.vercel.app/api-brain/health` retornou `200`.
- Deploy de producao validado: `dpl_6zvrLgiUXrEnrGctWp1yr8npkrp2`.
- O backend usado nesta validacao foi o Docker local exposto por tunnel HTTPS temporario.

Conclusao: login e `/api-brain` funcionam no dominio de producao enquanto o tunnel do backend local estiver ativo. Para operacao permanente, substituir o tunnel temporario por endpoint HTTPS estavel.

## Estado da Branch

Resultado depois de `git fetch origin`:

- Branch atual: `feat/docker-self-hosted-stack`
- `HEAD`: `5e69887`
- Em relacao a `origin/main`: `0 behind / 39 ahead`
- Em relacao a `origin/feat/docker-self-hosted-stack`: `0 behind / 3 ahead`

Commits locais ainda nao publicados no branch remoto:

- `5e69887 fix(kb-intake): prevent raw 500s on chat/save + post-LLM resilience boundary`
- `d0f47da fix: use full branch context for faq generation`
- `33adcb9 feat: stabilize criar graph json import`

Ha muitas alteracoes locais nao commitadas. O deploy de producao nao representa o estado local.

## Validacoes Executadas

Backend local:

```text
curl http://localhost:8080/health
-> 200 {"status":"ok","service":"api","workers_embedded":false}
```

Stack Docker:

```text
db       Up / healthy
storage  Up / healthy
rest     Up
kong     Up :8000
api      Up / healthy :8080
workers  Up
```

Frontend local antes de iniciar:

```text
curl http://localhost:3000/api-brain/health
-> falhou, nada escutando em :3000
```

Frontend local depois de iniciar:

```text
curl http://localhost:3000/api-brain/health
-> 200, resposta vinda do backend via proxy
```

Banco local:

```text
app_users:
- email: admin@local.dev
- username: admin
- role: admin
- is_active: true
```

## Credenciais Admin

Usuario admin local encontrado:

```text
email: admin@local.dev
username: admin
role: admin
```

A senha nao e recuperavel porque esta salva como hash forte em `app_users.password_hash`.

Para garantir a mesma credencial em local e producao, a senha precisa ser resetada nos dois ambientes com o mesmo valor. Nao gravar senha em `README.md`, `memory.md`, `.env.compose` ou qualquer arquivo versionado.

Comando para reset local:

```powershell
cd api
python scripts/create_auth_user.py --email admin@local.dev --username admin --password "<nova-senha-admin>" --role admin
```

Para producao, repetir o mesmo reset contra o banco/backend final de producao. Enquanto a producao ainda aponta para backend legado, a senha local e a senha de producao podem divergir.

## O Que Falta Para Producao Permanente

1. Decidir e configurar o backend final de producao.
2. Alterar `API_INTERNAL_BASE_URL` no Vercel para apontar para esse backend final.
3. Validar preview com `/login` 200 e `/api-brain/health` 200.
4. Publicar/promover no Vercel uma versao que contenha a rota `/login`.
5. Resetar/criar o mesmo admin no banco local e no banco de producao.
6. Garantir que `AI_BRAIN_AUTH_SECRET` seja estavel em producao; se mudar, todas as sessoes antigas invalidam.
7. Rodar build do dashboard:

```powershell
cd dashboard
npm run build
```

8. Validar no dominio final:

```text
GET  /login
GET  /api-brain/health
POST /api-brain/auth/login
GET  /api-brain/auth/me
```

## Limpeza de Stack Antiga

Feito nesta auditoria:

- `README.md` foi reescrito para remover a stack passada como caminho operacional.
- `README.md` agora aponta para Docker Compose local e Vercel como frontend.
- `AGENTS.md` teve as referencias operacionais finais a backend legado substituidas por backend final aprovado.
- `.env.compose` foi ajustado para `ENVIRONMENT=qa`.
- O `memory.md` anterior foi preservado como backup.

Estado apos a limpeza desta rodada:

- `.github/workflows/ci.yml` agora builda o dashboard com `API_INTERNAL_BASE_URL` e `NEXT_PUBLIC_API_BASE_URL=/api-brain`.
- `scripts/deploy-qa.sh`, `scripts/deploy-prod.sh` e `scripts/smoke-check.sh` foram aposentados/ajustados para o novo fluxo.
- A rota QA do dashboard passou a resolver backend por `API_INTERNAL_BASE_URL`.
- A aplicacao ainda tem nomes internos de compatibilidade herdados do cliente de dados antigo; a rota operacional nao deve expor conexoes diretas no dashboard nem usar cloud antiga.

## Observacoes De Seguranca

- `.env.compose` contem segredos reais e deve continuar fora do Git.
- Nao publicar senha admin em arquivos versionados.
- A producao atual ainda responder via backend legado precisa ser tratada como risco operacional ate ser substituida.
