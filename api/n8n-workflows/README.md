# Workflows locais do runtime WhatsApp

Os exports entram **inativos**. Para importar no n8n local:

```powershell
docker compose --env-file .env.compose --profile workflow-bootstrap run --rm n8n-import
```

`persona-conversation-template.json` é o molde sem fatos comerciais.
`baita-vitoria.json` fixa somente os identificadores de binding
`baita-conveniencia`, `vitoria`, `conversation_v1` e `n8n_agents`; todo
conteúdo vem do Graph JSON v2 publicado. O endpoint `decide` usa
`deterministic_v1` enquanto não houver provedor de modelo configurado.

Depois de revisar URLs e credenciais locais, ative manualmente apenas os fluxos
necessários. Nenhum arquivo contém token Meta, telefone, preço, produto, prompt
comercial ou URL de produção. O contrato é sempre
`phone_number_id -> binding` no Brain.
