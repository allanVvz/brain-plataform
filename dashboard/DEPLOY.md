# Deploy Vercel + Cloud Run

Este dashboard usa Next.js com proxy `/api-brain/*` para o backend publicado no Cloud Run.

## Frontend na Vercel

Configure no projeto da Vercel:

```env
NEXT_PUBLIC_API_URL=https://SEU-BACKEND-CLOUD-RUN.run.app
NEXT_PUBLIC_SUPABASE_URL=https://SEU-PROJETO.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=SEU_SUPABASE_ANON_KEY
NEXT_PUBLIC_SUPABASE_ANON_KEY=SEU_SUPABASE_ANON_KEY
```

Notas:
- `NEXT_PUBLIC_API_URL` e o nome canonico atual.
- O frontend ainda aceita o legado `NEXT_PUBLIC_AI_BRAIN_URL` como fallback, mas deploy novo deve usar `NEXT_PUBLIC_API_URL`.
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` e opcional quando `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` estiver presente.
- Nao use `SUPABASE_SERVICE_KEY` no frontend.
- Se voce alterar envs na Vercel, faca novo deploy do frontend. A mudanca nao entra em um deploy ja pronto.

Deploy:

```bash
cd dashboard
npm install
npm run build
vercel --prod
```

## Backend no Cloud Run

Configure no Cloud Run:

```env
SUPABASE_URL=https://SEU-PROJETO.supabase.co
SUPABASE_SERVICE_KEY=SEU_SERVICE_ROLE_KEY
ALLOWED_ORIGINS=https://SEU_FRONT.vercel.app,http://localhost:3000
VAULT_SOURCE_MODE=github
GITHUB_VAULT_REPO=owner/ai-brain-vault
GITHUB_VAULT_BRANCH=main
GITHUB_VAULT_ROOT=
GITHUB_TOKEN=SEU_TOKEN_READ_ONLY
```

Notas criticas:
- `SUPABASE_SERVICE_KEY` precisa ser a `service_role` real do Supabase.
- Se voce usar a `anon key` no lugar da `service_role`, `GET /health/ready` pode ate responder `200`, mas o login tende a falhar porque `app_users` pode voltar vazio no fluxo de auth.
- Inclua todos os dominios Vercel realmente usados em `ALLOWED_ORIGINS`, por exemplo o dominio estavel e eventuais dominios temporarios de producao/preview.

Deploy:

```bash
gcloud run deploy ai-brain-api \
  --source ./api \
  --region us-central1 \
  --allow-unauthenticated
```

## Ordem recomendada

1. Publique ou atualize o backend no Cloud Run.
2. Valide `GET /health` e `GET /health/ready` no backend.
3. Configure `NEXT_PUBLIC_API_URL` na Vercel apontando para a URL do Cloud Run.
4. Publique o frontend na Vercel.

## Diagnostico rapido

Use estes sintomas para identificar o ponto da falha:

- `GET /api-brain/health` falha:
  o frontend nao esta chegando no backend correto. Revise `NEXT_PUBLIC_API_URL`.
- `GET /api-brain/health` responde `200`, mas `POST /api-brain/auth/login` responde `500` ou `503`:
  o backend chegou no Supabase mas falhou no fluxo de auth. Revise `SUPABASE_SERVICE_KEY`, logs do Cloud Run e disponibilidade do Supabase.
- `GET /api-brain/auth/me` responde `401` na pagina `/login` antes de autenticar:
  isso e esperado.
- `POST /api-brain/auth/login` responde `401` com `Email/usuario ou senha invalidos.`:
  a infra esta funcional; o problema e credencial do usuario.

## Comandos de verificacao

Backend:

```bash
curl https://SEU-BACKEND.run.app/health
curl https://SEU-BACKEND.run.app/health/ready
```

Logs do Cloud Run em tempo real:

```bash
gcloud beta run services logs tail ai-brain-api --region us-central1
```

Fallback sem streaming:

```bash
gcloud run services logs read ai-brain-api --region us-central1 --limit 100
```

## Validacao final

Depois do deploy:
1. Abrir `/login`.
2. Tentar autenticar e confirmar `POST /api-brain/auth/login -> 200`.
3. Confirmar `GET /api-brain/auth/me -> 200` apos o login.
4. Abrir `/knowledge/graph`, `/messages` e `/pipeline`.
5. Confirmar que as chamadas `/api-brain/*` nao retornam erro de configuracao.
