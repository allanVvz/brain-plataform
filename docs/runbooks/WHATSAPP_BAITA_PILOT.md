# Piloto Baita / Vitoria

1. Faça backup de PostgreSQL, volume n8n, bindings e Graph JSON v2 publicado.
2. Preencha o `.env.compose` ignorado pelo Git, incluindo Meta, n8n e o token
   interno. `META_WHATSAPP_ACCESS_TOKEN` é lido somente pelo container n8n e
   nunca entra no workflow exportado. O contrato `conversation_v1` não consulta
   provedor de IA.
3. Suba a base com
   `docker compose --env-file .env.compose up -d --build`.
   Em uma rede que intercepte TLS do PyPI, use apenas localmente
   `PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org"`; o valor padrão vazio
   mantém a validação TLS normal.
4. Compile sem persistir:
   `docker compose exec -T api python scripts/publish_persona_documents.py baita-conveniencia --dry-run`.
5. Publique o Markdown canônico e confirme versão, checksum, 15 categorias,
   382 produtos ativos, 20 FAQs, entries/chunks e edges. O 383º documento tem
   preço inválido na fonte e permanece `pending_validation`, inativo.
6. Importe os gateways e `Baita — Vitoria` ainda inativos. Configure o binding
   com `mode=active`, `pipeline_contract=conversation_v1` e modo inicial
   `deterministic`, sem gravar telefone ou segredo no JSON.
   O modo `active` aceita todos os contatos recebidos pelo número vinculado;
   não há allowlist no WA Validator.
   Exemplo:

   ```powershell
   docker compose exec -T api python scripts/configure_persona_conversation.py `
     baita-conveniencia "Baita — Vitoria" `
     --phone-number-id <META_PHONE_NUMBER_ID> `
     --conversation-webhook-url http://n8n:5678/webhook/baita-conveniencia/conversation `
     --outbound-webhook-url http://n8n:5678/webhook/whatsapp/outbound `
     --mode active --conversation-mode deterministic --activate
   ```
7. Ative somente o número Meta da Baita. A Tock permanece inativa para IA.
8. Execute primeiro o cenário interno do WA Validator em `deterministic`.
   Depois altere para `n8n_agents` e repita o mesmo cenário/asserções.
9. Suba o runner real com
   `docker compose --env-file .env.compose --profile wa-validator up -d --build wa-validator`
   e autentique o perfil persistente do WhatsApp Web.
10. Execute o cenário real e confira `messages`, `agent_logs`, `system_events`,
    screenshots, IDs Meta, versão/checksum, carrinho, handoff e callbacks.

Gates obrigatórios: uma resposta por mensagem, nenhuma evidência fora do grafo,
SDR/Closer/Humano exercitados, total determinístico, pausa atômica e nenhuma
resposta da IA depois do handoff.

Rollback: desative o binding Baita e coloque a persona em rota exclusivamente
humana. Preserve histórico, carrinho, eventos e a versão publicada. Nunca
reative workflow, script, catálogo ou fallback hardcoded.
