# WhatsApp / n8n runtime

Meta mantém assinatura, IDs e callbacks. Brain mantém validação, histórico
canônico, grafo/RAG, carrinho, outbox, handoff, auditoria e
idempotência. O n8n mostra a orquestração de cada persona:

```text
Meta -> gateway -> Brain inbox
worker -> seletor deterministic | n8n_agents
       -> contexto Graph JSON v2
       -> classifier deterministic_v1
       -> rota SDR/CLOSER/HUMAN
       -> persistência/handoff
       -> Brain outbox -> gateway sender -> Meta
```

O roteamento é exclusivamente
`phone_number_id -> workflow_binding ativo -> persona_id`. Para a instância
Baita, `personas.process_mode` seleciona `deterministic` ou `n8n_agents` sem
alterar o contrato `conversation_v1`. No primeiro modo o worker chama
`context -> decide -> commit` diretamente; no segundo, o n8n orquestra os
mesmos endpoints. O workflow fixa apenas os identificadores da persona/agente;
não contém fatos ou prompts comerciais.

`lead_buffer` usa os estados `received`, `buffered`, `processing`,
`pending_send`, `sent`, `delivered`, `read`, `retry`, `dead_letter`,
`waiting_human` e `ignored`. Retries Meta são idempotentes por persona, número
comercial e `wamid`. O handoff grava carrinho/estágio, pausa a IA e move
trabalho pendente para `waiting_human` na mesma transação.

No modo `active`, todos os remetentes recebidos pelo número vinculado são
aceitos. Tokens permanecem em env/conexões seguras e não são exportados em
JSON. A primeira versão não usa modelo nem token de provedor de IA.
