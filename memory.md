# AI Brain - Deploy e Operacao

## Estrutura oficial

```text
/ai-brain
  /dashboard      # frontend Next.js
  /api            # backend FastAPI
    main.py
    requirements.txt
    .env
  /docs
  /.gitignore
```

Regra:
- Nao usar `requirements.txt` na raiz.
- Dependencias Python ficam em `api/requirements.txt`.

## Rodar local

Frontend:
```bash
cd dashboard
npm install
npm run dev
```

Backend:
```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload
```

## Deploy

Frontend:
- Plataforma: Vercel
- Root Directory: `dashboard`

Backend:
- Plataforma: Cloud Run
- Source obrigatorio: `./api`

```bash
gcloud run deploy ai-brain-api \
  --source ./api \
  --region us-central1 \
  --allow-unauthenticated
```

## Variaveis de ambiente

Frontend (`dashboard/.env.local`):
- `NEXT_PUBLIC_API_URL=https://<cloud-run-url>`
- `NEXT_PUBLIC_SUPABASE_URL=https://<projeto>.supabase.co`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<anon-key>`
- opcional fallback: `NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>`

Backend (`api/.env`):
- `SUPABASE_URL=https://<projeto>.supabase.co`
- `SUPABASE_SERVICE_KEY=<service-role-key>`
- `ALLOWED_ORIGINS=https://<app-vercel>,http://localhost:3000`

## Notas criticas

- Frontend usa apenas `NEXT_PUBLIC_API_URL` para backend.
- Se `NEXT_PUBLIC_API_URL` faltar em producao, frontend falha com erro explicito.
- Backend valida env obrigatoria em runtime de producao.
- Entrypoint gunicorn do backend:
  - `gunicorn -k uvicorn.workers.UvicornWorker main:app`
