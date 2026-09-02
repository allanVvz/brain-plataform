# Claude Project Contract

## Ordem de precedência (resolve qualquer contradição)

```
1. docs/roadmaps/AGENT_ROADMAP.md   autoridade máxima
2. AGENTS.md                        regras operacionais de produção
3. PROJECT_REQUIREMENTS.md          contrato de produto
4. memory.md                        estado corrente (não é contrato)
5. docs/**                          referência
   docs/archive/**                  NUNCA ler; histórico morto
```

Quando dois arquivos se contradizem, vence o de menor número. Reporte o conflito
em vez de escolher em silêncio.

## Core Rules

- Graph JSON v2 é o contrato canônico publicado do grafo para a Graph UI.
- Acesso a persona deve ser validado em toda leitura e mutação escopada por
  persona.
- API keys de usuário ficam encriptadas no servidor e nunca vão para o browser.
- O output de site público é configurado em `personas.config.public_site` e
  renderizado a partir da memória/grafo da persona via `/api/menu/{persona_slug}`.
- Os formatos de site público são fixos por `public_site_formats`; as chaves
  iniciais são `cardapio`, `landing_page` e `catalogo_roupas`.
- O CTA público de WhatsApp usa `whatsapp_phone` e `whatsapp_message_template`.
  Não usar nem expor o `whatsapp_phone_number_id` do Meta/n8n para esse link.

## Runtime de conversa

- Runtime de conversa: `apps/conversation-runtime` e a unica fonte produtiva.
  Nao copiar implementacoes congeladas de `api/services` ou repositorios
  legados de volta para o microsservico.
- O dashboard/binding escolhe explicitamente `deterministic` ou `n8n_agents`.
  Alteracoes agentic nao podem compor FAQ, pergunta, resumo ou fallback
  deterministico; proof valida evidencia, isolamento, seguranca e exactly-once.
- Toda mudanca conversacional deve executar o teste-canario que prova a
  fronteira entre os dois motores e a preservacao byte a byte da reply agentic.

## Leitura obrigatória antes de mudanças maiores

- `docs/roadmaps/AGENT_ROADMAP.md`
- `AGENTS.md`
- `PROJECT_REQUIREMENTS.md`
- `memory.md`
- `docs/knowledge-flow.md`

## Não ler

`docs/archive/**` é histórico arquivado em 2026-08-19 porque contradizia o
estado atual. Nunca é fonte de verdade. O bloqueio está em
`.claude/settings.json` (`permissions.deny`).
