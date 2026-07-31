# Dashboard na Vercel

O dashboard usa exclusivamente o proxy same-origin `/api-brain`. No projeto Vercel, com root directory `dashboard`, configure:

```text
API_INTERNAL_BASE_URL=https://api.vzforeal.com
NEXT_PUBLIC_API_BASE_URL=/api-brain
```

`API_INTERNAL_BASE_URL` e server-only. Nenhum segredo do backend ou `SERVICE_ROLE_KEY` deve ser criado na Vercel. O navegador recebe apenas o prefixo relativo `/api-brain`.

Valide depois da publicacao:

```bash
curl https://<dashboard>/api-brain/health
curl https://<dashboard>/api-brain/health/ready
```

O deploy do backend e o plano de rollback estao em [`../docs/VPS_PRODUCTION_RUNBOOK.md`](../docs/VPS_PRODUCTION_RUNBOOK.md).
