# Brain Platform Memory

Updated: 2026-08-11

## Handoff atual — WA Validator em produção

### Limites e autorizações

- A operação deste trabalho é exclusivamente em produção; não subir Docker local.
- Usar somente o WA Validator direto/interno, nunca WhatsApp real.
- Manter transporte e IAs pausados durante a validação.
- O usuário autorizou implementação, deploy, migration 117, sincronização do
  workflow, safety pause e testes diretos em produção.
- Limpeza de retenção não foi autorizada. Ela deve continuar somente em dry-run.
- Não retomar o binding ao final sem autorização explícita.

### Release em produção

- Branch: `main`.
- Release atualmente publicado: `666417ecbb286bc06297d93d0e1d068992d8635f`.
- API e workers usam a mesma imagem e estão saudáveis.
- Última migration aplicada: `117_wa_validator_queue_and_retention.sql`.
- `WA_VALIDATOR_RUN_ENABLED=false` e `WA_VALIDATOR_RETENTION_ENABLED=false`.
- Workflow canônico n8n Aurora: ID `k5JWkvpQyb8EB3Vw`, ativo, checksum de
  template `sha256:bf0c5a10bd2dd4652235f393cd317bb952108f5b3236e9d58466b044336921ad`.
- Publicação Graph Aurora: versão 51, checksum
  `sha256:532a0379dd0f3ef500222170bc7bf45f78e2a866619d6b2e27dbd6f1b868b35a`.
- Binding Aurora `6386bc58-ade9-44c4-9211-0f59f23ffca5` permanece em
  `connection_status=safety_paused`, razão `wa_validator_direct_release_test`.

### Implementação publicada

- Bootstrap escopado por persona, no máximo 25 sessões e janela móvel de 12h.
- Leads e conversas sintéticas filtrados no banco para as últimas 12h.
- `POST /wa-validator/run-direct` apenas enfileira; o processo `workers` executa
  sessões usando `wa_validator_sessions`, sem tabela nova.
- Erros de cliente preservam endpoint, HTTP status e request ID; somente GET de
  bootstrap repete uma vez em `502/503/504`.
- Workflow aceita `branch_action=add` e recebe `active_branch_node_ids`,
  `facts_by_key` e `known_facts`.
- Runtime reconcilia resposta literal válida ao primeiro campo pendente, mantém
  fatos compartilhados e separa fatos específicos por serviço.
- `switch` substitui o serviço; `add` preserva múltiplos ramos ativos.
- O ramo publicado pode provar existência do serviço, mas nunca agenda, data ou
  horário.
- O Validator encerra em `qualification_complete=true`, sem exigir handoff.
- Binding pausado só aceita bypass para lead de validação canônico com os três
  marcadores: `validation.is_validation=true`, `validation.session_id` e
  `lead_id=validator_*`; todo outbound permanece inerte.
- Migration 117 fornece fila, lock e retenção transacional idempotente, com
  abort total se qualquer vínculo real for detectado.

### Verificações concluídas

- Antes do primeiro deploy: `153 passed` focados; matriz backend
  `589 passed, 2 skipped`; dashboard `93 passed`; TypeScript e build passaram.
- Auditoria read-only de release passou para source/release/checksums,
  containers/health, grants/RLS, CAS, filas/outbounds, grafo e backup/restore.
- Dry-run real da migration 117 retornou `safe=true`: 57 sessões, 74 leads,
  283 mensagens, 755 buffers, 350 proofs e 58 ledgers candidatos; zero IDs
  inseguros. Nenhuma linha foi removida.
- Worker iniciou e executou o dry-run de retenção na inicialização.
- Filesystem da VPS estava em 78%; não limpar sem autorização própria.

### Sessão diagnóstica e bloqueio encontrado

- Sessão direta `10049e65-058c-4c2e-a3ff-4188ab4d8dec`, lead 149,
  `validator_10049e65`, Pintura.
- Primeiro inbound `2bcedbca-6968-432e-a543-d927f86d6ed4` passou com exatamente
  uma decisão, um proof válido e um outbound inerte.
- Segundo inbound `4165be0c-2d03-4e1c-b1d7-538e291d935d` terminou como
  `burst_superseded`, sem decisão/proof; a execução foi interrompida e os outros
  dois cenários não foram criados.
- Nenhum outbound tinha destinatário ou ID externo real; nenhum WhatsApp foi
  enviado.
- Causa: o inbound sintético direto nascia `buffered`. O worker podia reivindicá-lo
  e ele continuava elegível como irmão de burst no turno seguinte.

### Correção local atual — ainda não publicada

- `api/services/wa_validator_service.py` agora cria o buffer inbound direto como
  `waiting_human`, estado inerte para o transport worker.
- Depois que o audit v3 confirma exatamente um inbound, uma decisão, um proof
  válido, no máximo um outbound e `commit_state=completed`, o próprio Validator
  terminaliza o inbound como `sent`.
- Em falha de prova, o inbound permanece inerte e nunca é liberado ao transporte.
- Regressões comportamentais em `tests/test_conversation_modes.py` cobrem o estado
  inicial inerte e a terminalização somente após proof; testes focados: `2 passed`.
- Matriz local completa após a correção: `630 passed, 43 skipped`; `py_compile`
  do serviço alterado passou. Docker local não foi iniciado.

### Próxima execução segura

1. Rodar a matriz local sem Docker e revisar diff/anti-hardcode.
2. Commitar e publicar a correção em produção pelo workflow imutável.
3. Confirmar release/health e manter o binding Aurora safety-paused.
4. Executar serialmente três novas sessões: Pintura; Pintura → PPF; Pintura + PPF.
   Parar imediatamente ao primeiro erro.
5. Em cada inbound provar exatamente uma decisão, um proof válido e no máximo um
   outbound inerte; auditar fatos, ramos, missing field, pergunta, tokens e graph
   checksum.
6. Aceitar apenas com zero 5xx, health aquecido abaixo de 500 ms durante o teste,
   bootstrap abaixo de 2 s, zero pergunta repetida, três qualificações completas
   sem handoff e nenhum envio real.
7. Manter binding pausado e retenção em dry-run. Cleanup e resume continuam fora
   do escopo autorizado.

### Gate de bootstrap após o release `36fa5e1`

- O preflight de aceite confirmou binding Aurora ativo e `safety_paused`, owner
  `n8n_agents`, contrato `conversation_v3` e retenção desabilitada.
- O gate parou antes de criar sessões porque bootstrap levou `2.885 s`.
- Cinco medições posteriores ficaram entre `2.380 s` e `3.925 s`.
- Perfil por etapa: persona/routing/binding/sessões levaram dezenas de ms; a
  leitura do Graph JSON v2 no storage levou `2.295–2.795 s` sozinha.
- Correção local pendente usa no bootstrap a publicação Graph v3 ativa, que é a
  autoridade do runtime e foi medida em `676 ms`; mantém fallback v2 somente
  para persona sem publicação v3.
- Contrato HTTP não muda. Testes de publicação ativa, fallback e runtime:
  `47 passed`. Nenhuma nova sessão foi criada por esse gate reprovado.

### Primeiro aceite após o release `e17c032`

- Bootstrap otimizado em produção: cinco medições entre `143.856 ms` e
  `244.074 ms`; preflight do driver: `283.576 ms`.
- Sessão Pintura `1ba751d4-59d9-4ba6-92d2-d5d193d7889b`, lead 150, parou no
  terceiro turno; os cenários de troca e adição não foram criados.
- Três inbounds provaram exatamente uma decisão, um proof válido, um outbound
  inerte e commit completo. Todos ficaram terminais `sent`.
- Health durante a sessão: 35/35 HTTP 200, máximo `47.224 ms`, p95 `43.073 ms`.
- Falha semântica: o modelo extraiu corretamente `nome_cliente=Beatriz` e avançou
  para `objective`, mas o template forneceu o ID externo do inbound enquanto o
  proof checker comparou com o ID interno projetado de `messages`.
- Correção local pendente normaliza `source_message_id` dos fatos para a
  identidade autoritativa do backend antes da prova. Owner, trecho literal,
  schema, overwrite e dependências continuam sendo validados.
- Testes focados de runtime/proof/Validator: `127 passed`.
- Nenhum destinatário ou ID externo de outbound real; nenhum WhatsApp enviado.

### Aceite após o release `91fc29b`

- Pintura concluiu: sessão `5f27a06c-70c6-4cbd-a76f-e6855b1975e4`, lead 151,
  `technical_pass=true`, `quality_pass=true`, 9 turnos, qualificação completa.
- Troca parou: sessão `9f9a7ffe-e01a-4656-915d-516209ad8dfa`, lead 152,
  `technical_pass=true`, falha exclusiva do auditor `question_advanced` no turno
  da troca. O cenário de adição não foi criado.
- Estado produtivo da troca estava correto: ramo ativo final somente
  `aurora-product-ppf`; `servico=ppf`; fatos compartilhados `nome_cliente` e
  `objective` preservados; pergunta pendente continuou `can_visit_in_person`.
- Causa: o auditor exigia mudar a pergunta após qualquer fato, embora uma troca
  de serviço não responda à pergunta compartilhada já pendente.
- Correção local pendente exige avanço apenas quando o fato pretendido responde
  ao campo da pergunta anterior. Pergunta realmente respondida e repetida ainda
  reprova. Testes focados do critério: `6 passed`.
- Health nos dois cenários: 143/143 HTTP 200, máximo `171.562 ms`, p95
  `49.243 ms`. Nenhum WhatsApp real; leads colocados em handoff full.
