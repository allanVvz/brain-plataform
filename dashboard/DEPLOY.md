# Dashboard Local-First

Este dashboard deve rodar contra a stack local/self-hosted do repositorio. Nao use servicos SaaS como caminho padrao de execucao.

## Dev Docker

Suba tudo a partir da raiz:

```powershell
docker compose up --build
```

URLs vistas pelo operador/browser:

- Dashboard: `http://localhost:3000`
- Backend: `http://localhost:8000`
- Gateway Supabase-compatible: `http://localhost:54321`

URLs vistas de dentro da rede Docker:

- Backend: `http://api:8000`
- Gateway Supabase-compatible: `http://supabase-gateway:8000`

## Variaveis Do Dashboard

Use variaveis separadas para evitar o erro de `localhost` dentro de container:

```env
API_INTERNAL_URL=http://api:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<local anon jwt>
```

`API_INTERNAL_URL` e usada pelo rewrite server-side do Next para `/api-brain/*`. `NEXT_PUBLIC_API_URL` e a URL publica vista pelo browser/host.

## Dev Fora Do Docker

Se rodar o dashboard direto no host:

```powershell
cd dashboard
npm install
npm run dev -- --hostname 0.0.0.0 --port 3000
```

Nesse caso `API_INTERNAL_URL=http://localhost:8000` porque o processo Next tambem roda no host.

## Producao Self-Hosted

Use o compose de producao:

```powershell
copy .env.prod.example .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

O build de producao usa `dashboard/Dockerfile` e nao executa `npm install` em runtime.

## Verificacao

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:3000/login
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8000/health/ready
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:54321/health
```

Login seed de dev:

```text
allan@brain.com
123456
```
