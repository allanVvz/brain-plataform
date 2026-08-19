# Exports n8n com nome de persona — DEPRECIADOS 2026-08-19

> SUPERSEDED BY `docs/roadmaps/AGENT_ROADMAP.md` e `AGENTS.md` §26.

Estes arquivos são fixtures de auditoria histórica. **Nunca** foram — e nunca
serão — fonte de runtime ou de provisionamento.

A única fonte canônica de workflow de conversa é
`api/n8n-workflows/persona-conversation-template.json`.

Movidos para cá porque agentes de IA os liam como se fossem template ativo,
gerando contexto contraditório. Nenhum código de produção os referencia
(verificado por grep em 2026-08-19: só docs históricos e permissões locais).
