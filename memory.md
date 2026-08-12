# Brain Platform Memory

Updated: 2026-08-12

## Handoff atual — WA Validator em produção

### Limites e autorizações

- Operação exclusivamente em produção. Não executar Docker local.
- Testar conversas somente pelo WA Validator direto/interno, nunca por
  WhatsApp real.
- Manter transporte, binding Aurora e IAs pausados durante toda a validação.
- Implementação, push, deploy e testes diretos desta correção foram autorizados.
- A migration 117 já foi autorizada e aplicada. Nenhuma migration nova é
  necessária para a correção atual.
- Limpeza de retenção não foi autorizada e permanece apenas em dry-run.
- Não retomar binding ou IA sem autorização explícita posterior.

### Produção antes do próximo push

- Branch `main`; release publicado
  `989f16bb362a17c578e93621ee9501d9d45ef23a`.
- API: `https://api.vzforeal.com`; VPS: `/opt/brain-ai`.
- Última migration aplicada: `117_wa_validator_queue_and_retention.sql`.
- `WA_VALIDATOR_RUN_ENABLED=false` e
  `WA_VALIDATOR_RETENTION_ENABLED=false`.
- Persona Aurora: `96e0d69f-9abd-406a-bbb9-3e7977f24ec8`.
- Binding Aurora: `6386bc58-ade9-44c4-9211-0f59f23ffca5`, ativo e
  `connection_status=safety_paused`; owner `n8n_agents`, contrato
  `conversation_v3`.
- Workflow n8n: `k5JWkvpQyb8EB3Vw`, ativo; checksum do template
  `sha256:bf0c5a10bd2dd4652235f393cd317bb952108f5b3236e9d58466b044336921ad`.
- Graph Aurora publicado: versão 51, checksum
  `sha256:532a0379dd0f3ef500222170bc7bf45f78e2a866619d6b2e27dbd6f1b868b35a`.

### Implementação já publicada

- Bootstrap escopado por persona, 25 sessões no máximo e janela móvel de 12h;
  usa publicação Graph v3 ativa com fallback v2.
- `POST /wa-validator/run-direct` enfileira em `wa_validator_sessions`; o worker
  processa a conversa longa fora do event loop da API.
- Leads/conversas sintéticos são filtrados no banco para 12h.
- Erros do cliente preservam endpoint, status HTTP e request ID; apenas GET de
  bootstrap repete uma vez em `502/503/504`.
- Workflow aceita `branch_action=add` e recebe memória completa:
  `active_branch_node_ids`, `facts_by_key` e `known_facts`.
- Runtime reconcilia resposta literal ao primeiro campo pendente, preserva fatos
  compartilhados e separa fatos específicos por serviço.
- `switch` substitui serviço e `add` preserva múltiplos ramos ativos.
- Existência de serviço pode ser provada pelo ramo; agenda/data/horário não.
- Validator encerra em qualificação completa sem exigir handoff.
- Outbound de lead validador canônico é persistido de forma inerte, sem
  destinatário ou ID externo, e cada inbound admite uma decisão/proof/outbound.
- Auditor aceita normalização string respaldada pelo proof e distingue o ramo
  em foco do conjunto completo de ramos ativos.
- Repetir a mesma pergunta é permitido enquanto o campo continuar pendente. Se
  o campo foi respondido/persistido e a pergunta se repete, a validação falha.

### Evidência produtiva concluída

- Dry-run de retenção: `safe=true`; 57 sessões, 74 leads, 283 mensagens, 755
  buffers, 350 proofs e 58 ledgers candidatos; zero IDs inseguros. Nada removido.
- Bootstrap após otimização: 143.856–244.074 ms.
- Pintura: sessão `5f27a06c-70c6-4cbd-a76f-e6855b1975e4`, lead 151,
  `technical_pass=true`, `quality_pass=true`, 9 turnos, qualificação completa.
- Troca Pintura → PPF: sessão `9f9a7ffe-e01a-4656-915d-516209ad8dfa`, lead 152.
  A troca foi concluída corretamente: somente PPF ativo, `servico=ppf`, fatos
  compartilhados preservados e pergunta ainda pendente repetida. O usuário
  confirmou que essa troca é sucesso; o teste antigo é que parou indevidamente.
- Adição inicial: sessão `2d6b0b6c-c634-48b1-bd4d-92677de5da71`, lead 153. O
  turno “PPF também, além da pintura” passou e preservou Pintura + PPF.
- Nenhuma dessas sessões enviou WhatsApp real. Health permaneceu HTTP 200; no
  aceite Pintura/troca, máximo 171.562 ms e p95 49.243 ms.

### Bloqueio restante identificado na adição

- Última tentativa: sessão `3e592745-28ce-457c-a14b-397d71e27567`, lead 154.
- O add passou e o ledger manteve Pintura + PPF. A falha ocorreu mais tarde ao
  responder `condicao`: “Os bancos estão manchados e a pintura perdeu o brilho”.
- O matcher literal interpretou “pintura” como comando de foco, carregou o
  pacote Pintura em vez do PPF e gerou proof inválido por
  `cited_chunk_outside_package`.
- Health durante a tentativa: 90/90 HTTP 200, máximo 99.602 ms, p95 35.820 ms.
- O inbound permaneceu `waiting_human`, portanto inerte; nenhum envio real.

### Correção pronta no working tree

- `graph_agent_runtime_v3` agora suprime resolução de ramo quando a mensagem é
  resposta direta à última pergunta publicada de um campo não-serviço.
- Uma menção incidental a serviço dentro do valor não muda o foco. Marcadores
  explícitos como “na verdade, prefiro…” e “também quero…” continuam permitindo
  switch/add.
- O proof checker não foi afrouxado; o runtime mantém o pacote correto antes da
  decisão.
- `AGENTS.md` agora proíbe Docker local e define auditoria/dry-run/Validator
  interno em produção.
- A suíte padrão não produz skips nem inicia dependências: módulos SQL/live são
  opt-in por DSN/flags explícitos; dependência ausente falha quando habilitada.
- Validação local sem Docker: 638 testes coletados; `638 passed`, zero skips,
  três warnings conhecidos. Runtime/arquitetura focados: 80 passed.
- O primeiro CI do SHA `6d70c38` parou antes do deploy porque os 41 testes SQL
  explicitamente selecionados ficaram sem o antigo Postgres descartável. A
  correção mantém a suíte local sem Docker e permite apenas ao runner remoto,
  sob `CI=true`, provisionar seu banco isolado; indisponibilidade falha, não
  produz skip. Produção permaneceu no release anterior durante esse bloqueio.

### Próximos passos autorizados

1. Compilar/checar diff e anti-hardcode; commit e push único.
2. Acompanhar workflow oficial e confirmar SHA/health/binding pausado.
3. Executar uma nova sessão direta de adição Pintura + PPF, parando no primeiro
   erro.
4. Provar por inbound: uma decisão, um proof válido, no máximo um outbound
   inerte, commit completo, facts/owners, ramos ativos, primeiro missing field,
   pergunta, tokens e checksum do grafo.
5. Confirmar zero 5xx, health abaixo de 500 ms, bootstrap abaixo de 2 s,
   qualificação completa sem handoff e nenhum outbound real.
6. Manter binding pausado e retenção em dry-run. Não limpar dados.

### Aceite produtivo após o release `907d5ed`

- Auditoria read-only passou; API e worker no mesmo SHA, saudáveis, zero grants
  inseguros, zero conflito CAS/buffer crítico/outbound recente e backup válido.
- Sessão de adição `2826d664-d3a1-438e-a9b0-341daba4dd2a`, lead 155.
- Runtime concluiu corretamente: Pintura + PPF ativos, fatos compartilhados
  únicos, condição capturada apesar da palavra “pintura”, missing fields vazio e
  `qualification_complete=true`, sem handoff.
- Nove inbounds tiveram exatamente uma decisão, um proof válido, um outbound
  inerte e commit completo. Lead ficou em handoff full após o teste.
- Health: 86/86 HTTP 200, máximo 224.065 ms, p95 45.592 ms. Bootstrap 321.156 ms.
- Nenhum destinatário/ID externo real e nenhum WhatsApp enviado.
- Único falso negativo restante: a resposta determinística publicada de
  conclusão usa `fallback_used=true`; o auditor antigo a classificou como falha
  de reconciliação e marcou `quality_pass=false`, embora `technical_pass=true`.
- Correção local aceita fallback somente quando o proof é válido, não há campo
  pendente/pergunta e a qualificação já está completa. Fallback em turno
  incompleto continua reprovando.
