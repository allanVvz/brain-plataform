# AI Brain - Memory

## DEPLOY FLOW DEFINITIVO

### 1) Frontend (Vercel)

Root correto:
- Se o projeto da Vercel aponta para `dashboard` diretamente: `Root Directory = .`
- Se o projeto da Vercel aponta para a raiz do repo: `Root Directory = dashboard`

Variaveis obrigatorias (Vercel Project Settings -> Environment Variables):
- `NEXT_PUBLIC_API_URL=https://<cloud-run-url>`
- `NEXT_PUBLIC_SUPABASE_URL=https://<seu-projeto>.supabase.co`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<anon-key>` (recomendado)

Importante:
- Variaveis `NEXT_PUBLIC_*` sao injetadas no build do Next.js.
- Mudou env publica -> precisa novo deploy.
- Frontend padronizado para usar `NEXT_PUBLIC_API_URL`.
- `NEXT_PUBLIC_AI_BRAIN_URL` esta deprecated e nao deve ser usada.

Problemas comuns:
- `useSearchParams() should be wrapped in a suspense boundary` em `/knowledge/graph`.
- Alias `@/` quebrado por `tsconfig` inconsistente.
- Env publica ausente no build.

Comandos:
```bash
cd dashboard
npm install
npm run build:check
vercel --prod
```

---

### 2) Backend (Cloud Run)

Abordagem escolhida:
- `requirements.txt` fica na **raiz**.
- Deploy do Cloud Run deve ser feito pela **raiz** do repo (`--source .`).
- Entrypoint app suportado:
  - `uvicorn main:app` (arquivo raiz `main.py` faz bridge para `api.main:app`)
  - ou `uvicorn api.main:app`

Comando de deploy:
```bash
gcloud run deploy ai-brain-api --source . --region us-central1 --allow-unauthenticated
```

Variaveis obrigatorias (Cloud Run):
- `ALLOWED_ORIGINS=https://<vercel-app>,http://localhost:3000`
- `SUPABASE_URL=https://<seu-projeto>.supabase.co`
- `SUPABASE_SERVICE_KEY=<service-role-key>`

Problemas comuns:
- `ModuleNotFoundError: fastapi` -> dependencias fora do `requirements.txt`.
- Worker failed to boot -> erro de import/env obrigatoria.
- `503` -> container nao subiu corretamente.

Comandos de validacao local backend:
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

### 3) Integracao Front <-> Backend

- Frontend consome backend via rewrite `/api-brain/*`.
- Rewrite usa `NEXT_PUBLIC_API_URL`.
- Em desenvolvimento, fallback local: `http://localhost:8000`.
- Em producao sem env, fallback proposital para destino invalido (`127.0.0.1:9`) + erro amigavel no frontend.

Arquivo-chave:
- `dashboard/next.config.js`

---

### 4) CORS

- Backend usa `CORSMiddleware`.
- `ALLOWED_ORIGINS` deve sempre incluir:
  - `http://localhost:3000`
  - dominio da Vercel em producao.

---

## PADRONIZACAO DE ENV

Frontend:
- Leitura centralizada em `dashboard/utils/env.ts`.
- API publica: somente `NEXT_PUBLIC_API_URL`.
- Supabase publica:
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (fallback: `NEXT_PUBLIC_SUPABASE_ANON_KEY`)

Backend:
- Leitura/validacao centralizada em `backend/utils/env.py`.
- Validacao estrita em runtime de producao:
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_KEY`
  - `ALLOWED_ORIGINS`

Seguranca:
- Nunca expor `SUPABASE_SERVICE_KEY` no frontend.

---

## ESTRUTURA DE PASTAS (CONSISTENTE)

```text
/ai-brain
  /dashboard              # Next.js frontend
  /api                    # rotas FastAPI
  /backend                # utilitarios backend (env, etc.)
  requirements.txt        # dependencias backend (raiz)
  main.py                 # bridge -> api.main:app
  memory.md               # guia operacional central
```

Racional:
- Mantivemos `requirements.txt` na raiz para evitar quebra do fluxo atual de Cloud Run com `--source .`.

---

## HARDENING IMPLEMENTADO

- `requirements.txt` inclui:
  - `fastapi`
  - `uvicorn[standard]`
  - `gunicorn`
- Startup backend valida env obrigatoria em producao e loga erro claro.
- Frontend retorna mensagem amigavel para backend offline/503.
- Script de validacao de env no frontend:
  - `dashboard/scripts/check-env.mjs`
  - `npm run build:check`

---

## CHECKLIST RAPIDO (10 MIN)

1. Configurar envs na Vercel.
2. Configurar envs no Cloud Run.
3. Deploy backend:
   ```bash
   gcloud run deploy ai-brain-api --source . --region us-central1 --allow-unauthenticated
   ```
4. Deploy frontend:
   ```bash
   cd dashboard
   npm install
   npm run build:check
   vercel --prod
   ```
5. Validar:
   - `/health` backend
   - Dashboard carregando sem erro `Backend nao configurado`
   - Aba `/knowledge/graph` sem erro de Suspense/prerender
