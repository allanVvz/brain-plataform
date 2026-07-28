# Runtime legado removido

Os exports `Tock Vitoria CRM Low` e `Kb Update Tock`, o catálogo/FAQ/copy Baita
em Python e o executor externo do WhatsApp foram removidos. O endpoint
`/process` permanece somente como compatibilidade de outras personas e nunca é
o modo selecionado do contrato `conversation_v1`.

O runtime Baita não consulta Sheets, vector store em memória, `chat_history` ou
`kb_entries`. Em falha, o único fallback permitido é handoff humano.
