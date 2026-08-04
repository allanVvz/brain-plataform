# Workflows locais do runtime WhatsApp

Os exports entram **inativos**. Para importar no n8n local:

```powershell
docker compose --env-file .env.compose --profile workflow-bootstrap run --rm n8n-import
```

`persona-conversation-template.json` é a única fonte canônica para criação e
ressincronização dos workflows `n8n_agents`. O provisionador substitui apenas
persona, agente, webhook e credencial. Prompt, políticas, campos e conhecimento
vêm do Graph JSON publicado e dos `context_cards`; nunca existe função ou
template específico por cliente.

Os exports com nomes de personas são legados de auditoria e não são importados
nem usados pelo provisionador. O bootstrap local importa somente os workflows
de transporte `whatsapp-*`; workflows de conversa são criados pela plataforma.

Depois de revisar URLs e credenciais locais, ative manualmente apenas os fluxos
necessários. Nenhum arquivo contém token Meta, telefone, preço, produto, prompt
comercial ou URL de produção. O contrato é sempre
`phone_number_id -> binding` no Brain.
