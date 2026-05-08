# Deploy na Vercel

Este dashboard usa Next.js com proxy `/api-brain/*` para o backend.

## Variaveis na Vercel (frontend)

Configure no projeto da Vercel:

```env
NEXT_PUBLIC_API_URL=https://SEU-BACKEND-CLOUD-RUN.run.app
NEXT_PUBLIC_SUPABASE_URL=https://SEU-PROJETO.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=SEU_SUPABASE_ANON_KEY
NEXT_PUBLIC_SUPABASE_ANON_KEY=SEU_SUPABASE_ANON_KEY
```

Notas:
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` e opcional (fallback).
- Nao use `SUPABASE_SERVICE_KEY` no frontend.
- Em desenvolvimento local, use `NEXT_PUBLIC_API_URL=http://localhost:8000` ou `http://127.0.0.1:8000`.
- Valide o backend com `/health` antes de depurar a UI de mensagens.

## Variaveis no Cloud Run (backend)

```env
ALLOWED_ORIGINS=https://SEU_APP.vercel.app,http://localhost:3000
SUPABASE_URL=https://SEU-PROJETO.supabase.co
SUPABASE_SERVICE_KEY=SEU_SERVICE_ROLE_KEY
VAULT_SOURCE_MODE=github
GITHUB_VAULT_REPO=owner/ai-brain-vault
GITHUB_VAULT_BRANCH=main
GITHUB_VAULT_ROOT=
GITHUB_TOKEN=SEU_TOKEN_READ_ONLY
```

## Passo a passo

No diretório `dashboard`:

```bash
npm install
npm run build
vercel --prod
```

## Validacao rapida

Depois do deploy:
1. Abrir `/knowledge/graph`.
2. Abrir `/messages`.
3. Confirmar chamadas para `/api-brain/*` sem erro de configuracao.
