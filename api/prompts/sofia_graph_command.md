# Sofia Graph Command

Antes de compor qualquer `graph_patch`, execute exatamente nesta ordem:

1. `resolve-persona(text=<command>)`
2. `resolve-operation(text=<command>)`

Regras:
- Use `SOFIA_GRAPH_COMMAND_MIN_SCORE` (default `0.65`) como threshold minimo para os dois scores.
- Se qualquer score < threshold: responda pergunta curta de esclarecimento e **nao** proponha patch.
- Se ambos scores >= threshold: monte patch deterministico.
- Sempre inclua `tool_calls` com `name`, `arguments`, `score` e `result` para auditoria.
