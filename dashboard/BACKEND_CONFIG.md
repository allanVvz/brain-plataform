# Frontend → backend Brain AI

O dashboard usa exclusivamente o prefixo same-origin `/api-brain/*`. O rewrite
do Next.js resolve esse prefixo no servidor através de `API_INTERNAL_BASE_URL`.

```text
browser → /api-brain/auth/me → Next.js/Vercel → API_INTERNAL_BASE_URL → backend aprovado
```

Em produção:

| Variável | Escopo | Valor |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | browser | `/api-brain` |
| `API_INTERNAL_BASE_URL` | server only | URL privada/final aprovada do backend |

- Nunca expor chaves do backend ou provedores de IA no browser.
- Nunca apontar o dashboard para backend local ou legado.
- Login e auditoria usam a sessão HTTP-only e as contas autorizadas de produção.
- A validação visual é feita contra o deployment Vercel e `/api-brain`; este
  repositório não autoriza uma stack Docker local.

O fluxo de release está em
[`docs/runbooks/RELEASE_ORCHESTRATION.md`](../docs/runbooks/RELEASE_ORCHESTRATION.md).
