# Brain Platform Memory

Updated: 2026-08-11

## Handoff atual — WA Validator, memória operacional e múltiplos serviços

### Limites operacionais autorizados

- Toda continuação operacional ocorre exclusivamente em produção.
- Não subir Docker local.
- Usar somente o Validator direto/interno; nunca enviar WhatsApp real.
- Transporte e IAs devem permanecer pausados quando necessários para o teste.
- Começar por auditoria read-only e dry-run.
- Em 2026-08-11 o usuário autorizou explicitamente deploy coordenado, migration
  117 e os testes WA Validator diretos em produção.
- Limpeza de retenção continua não autorizada e deve permanecer em dry-run.

### Objetivo

1. Escopar bootstrap por persona, 25 sessões e janela móvel de 12h.
2. Filtrar leads/conversas sintéticos no banco para as últimas 12h.
3. Fazer `POST /wa-validator/run-direct` apenas enfileirar; o processo
   `workers` executa a conversa longa usando `wa_validator_sessions`, sem tabela
   nova.
4. Preservar endpoint, status HTTP e request ID nos erros; repetir somente o GET
   de bootstrap, uma vez, em `502/503/504`.
5. Enviar ao workflow `active_branch_node_ids`, `facts_by_key` e `known_facts`,
   aceitando `branch_action=add`.
6. Reconciliar resposta literal ao último `missing_fields[0]` apenas quando ela
   satisfaz o schema e não é dúvida ou troca/adição de serviço.
7. Preservar fatos compartilhados uma vez e fatos de serviço por proprietário;
   `switch` substitui e `add` mantém ambos os ramos.
8. Permitir que o ramo ativo prove somente existência do serviço, nunca
   agenda, data ou horário.
9. Encerrar em `qualification_complete=true`, sem handoff ou pergunta extra.
10. Inventariar e remover, de forma transacional, somente artefatos sintéticos
    canônicos anteriores a 12h e com todos os outbounds comprovadamente inertes.

### Implementação local concluída, ainda não publicada

- `api/services/wa_validator_service.py`
  - bootstrap carrega uma persona/binding/routing/grafo e consulta no banco no
    máximo 25 sessões da persona nas últimas 12h;
  - execução direta é enfileirada e o worker recebe a sessão já claimada;
  - qualificação completa termina sem exigir handoff;
  - dúvida literal de existência aceita FAQ ou ramo ativo como evidência; termos
    de agenda/data/horário continuam exigindo evidência operacional específica;
  - removidos termos de marca/persona do comportamento genérico.
- `api/services/graph_proof_checker_v3.py`
  - hotfix de existência usa o branch ativo autoritativo quando publicações
    antigas não duplicam `branch_anchor_node_id` dentro do contrato;
  - o payload booleano exato `{available: true}` pode provar existência;
    payload com data/horário não é autorizado pelo ramo.
- `api/services/graph_agent_runtime_v3.py`
  - fatos conhecidos incluem todos os proprietários/ramos;
  - resposta direta válida vira fato do primeiro campo pendente;
  - perguntas com ou sem `?`, claims e mudanças de branch não viram fato;
  - próxima pergunta continua autoritativa em `missing_fields[0]`.
- `api/services/conversation_runtime.py`
  - binding safety-paused só pode processar um lead de validação quando todos os
    marcadores canônicos existem (`is_validation`, `session_id` e
    `lead_id=validator_*`);
  - o mesmo guard seleciona o caminho de outbound inerte, permitindo testar com
    transporte real pausado sem abrir bypass para leads comuns.
- `api/n8n-workflows/persona-conversation-template.json`
  - schema aceita `add` e envia ramos ativos, fatos agrupados e fatos conhecidos.
- `api/services/supabase_client.py`, `api/routes/leads.py`
  - filtros temporais são aplicados no banco antes de paginação;
  - sessões suportam filtro por persona/janela;
  - wrappers para enqueue, claim e retenção.
- `api/routes/wa_validator.py`
  - `run-direct` é síncrono e apenas enfileira;
  - GET `/wa-validator/retention` é admin e sempre `dry_run=True`; não existe
    parâmetro HTTP que permita aplicar limpeza.
- `api/workers/wa_validator_worker.py`, `api/workers/runner.py`
  - worker dedicado reclama fila com processamento fora da API;
  - retenção roda em dry-run por padrão; apply exige
    `WA_VALIDATOR_RETENTION_ENABLED=true` e continua sujeito a autorização.
- `supabase/migrations/117_wa_validator_queue_and_retention.sql`
  - fila em `wa_validator_sessions`, `FOR UPDATE SKIP LOCKED`, sem tabela nova;
  - advisory lock e uma transação para inventário/limpeza;
  - preserva qualquer sessão/lead recente ou em `queued/starting/running`;
  - resolve IDs com `nullif`, incluindo metadado canônico e compatibilidade;
  - aborta toda a transação se houver identidade real, destinatário, ID externo,
    lock ou outbound em estado processável;
  - registra exatamente um evento agregado após apply.
- Dashboard
  - reconhece `queued`, usa janela de 12h na aba de validação;
  - todo erro recebe request ID gerado no cliente ou retornado pelo servidor;
  - bootstrap repete uma vez apenas em `502/503/504`; POST nunca repete.
- `docker-compose.yml`
  - worker recebe os gates do Validator e retenção, ambos `false` por padrão.

Arquivos novos:

- `api/workers/wa_validator_worker.py`
- `supabase/migrations/117_wa_validator_queue_and_retention.sql`
- `tests/test_wa_validator_queue_retention_contract.py`
- `tests/test_wa_validator_worker.py`

### Verificação local sem Docker

- `py_compile` dos módulos alterados: passou.
- Testes backend focados finais: `153 passed`.
- Matriz backend ampla equivalente ao deploy: `589 passed, 2 skipped`.
- Testes dashboard completos: `93 passed` em 23 arquivos.
- `npx tsc --noEmit`: passou.
- `npm run build` com `API_INTERNAL_BASE_URL=https://api.invalid`: passou; 38
  páginas estáticas geradas.
- Parse YAML do Compose: passou.
- `git diff --check`: passou; somente avisos esperados de CRLF do Windows.
- Busca anti-hardcode nos arquivos alterados: nenhum nome de cliente, marca,
  produto ou serviço específico influencia o runtime/template.
- Docker não foi iniciado.

### Auditoria read-only de produção

Ambiente:

- Dashboard: `https://brain-plataform-plum.vercel.app`.
- API: `https://api.vzforeal.com`.
- VPS: `/opt/brain-ai`.
- Release em execução: imagem/tag
  `da44d4902278f9f8e136893d5800000efc53efe5` para API e workers.
- Última migration aplicada: `116_reconcile_active_conversation_branches.sql`.
- A migration 117 e o código local ainda não estão publicados.

O script read-only `ops/vps/validate-production-release.sh` passou em:

- source SHA, release directory e checksums;
- containers/health;
- grants, RLS e Data API;
- zero CAS conflicts em 15m;
- zero buffers críticos e zero outbounds em 15m;
- zero divergência de checksum e zero publicação ativa sem checksum;
- backup de `2026-08-11T22:35:20Z` e evidência de restore controlado de
  `2026-08-11T20:48:46Z` com 4.694 registros.

Recursos observados: API ~688.5 MiB/1.5 GiB, workers ~422.2 MiB/1.5 GiB e
filesystem raiz em 78%.

Health público após as correções locais, sem execução do Validator:

- API `/health`: 10/10 HTTP 200, 0.152–0.368s.
- Proxy `/api-brain/health`: 10/10 HTTP 200, 0.167–0.535s.
- O gate de health durante uma conversa completa e bootstrap `<2s` não pode ser
  avaliado antes do release autorizado.

### Estado de transporte/IA — bloqueio atual

Bindings ativos observados em produção:

- `aurora`: Meta Cloud, `connected`, `safety_paused=false`,
  `decision_owner=n8n_agents`, `pipeline_contract=conversation_v3`.
- `tock-fatal`: Evolution, `connecting`, `safety_paused=false`,
  `decision_owner=deterministic`, `pipeline_contract=conversation_v1`.

Logo, o transporte não está pausado globalmente. Pausar binding ou IA é mutação
e não foi autorizado; nenhuma sessão de aceite pode começar enquanto o gate de
segurança aplicável não for explicitamente revisado/autorizado.

Nos leads sintéticos auditados: 82 totais (81 Aurora, 1 VZ), 81 com
`ai_paused=true`; um lead recente Aurora (`lead_ref=146`) estava sem pause.

### Sessão recente que confirmou o hotfix incompleto publicado

Foi encontrada uma sessão criada em produção por outro processo, não por esta
sessão de Codex:

- session `586ab54e-32e5-4676-ba81-5696ffc072dc`, lead `146`;
- criada `2026-08-11T22:38:38Z`, fluxo `sdr_qualificacao_carro`, status `error`;
- falha: `doubt_answered_first,model_reconciled_without_fallback`;
- dúvida: existência do serviço; o modelo citou o branch ativo, mas o proof
  publicado rejeitou `claim_evidence_not_authorized:availability` porque o
  contrato publicado não duplicava `branch_anchor_node_id`;
- quatro buffers (dois inbound, dois outbound), sem destinatário; IDs inbound
  sintéticos e outbound sem ID externo; nenhum WhatsApp real;
- o patch local agora cobre exatamente a forma do contrato observada e possui
  testes que impedem usar branch como prova de agenda/data/horário.

### Dry-run manual de retenção

Inventário atual:

- 68 sessões: 46 `done`, 8 `error`, 13 `ready`, 1 `running`;
- 10 recentes e 57 antigas terminais candidatas;
- 7 leads sintéticos recentes e 75 antigos;
- dry-run refinado anterior: 57 sessões, 74 leads, 283 mensagens, 755 buffers,
  58 ledgers, 303 fatos e 350 proofs candidatos;
- zero destinatário/ID externo real detectado entre os candidatos.

Sessão stale preservada obrigatoriamente:

- `d122ada2-4a90-4e4d-8791-7eda317f691b`, lead `133`, Aurora;
- criada `2026-08-10T17:58:40Z`, ainda `running`;
- `handoff_level=full`, um inbound `dead_letter`, nenhum outbound;
- migration 117 local agora preserva sessão e lead não terminais mesmo antigos.

Nenhuma limpeza foi aplicada.

### Veredito antes do rollout autorizado

- Código local: testes e build aprovados.
- Produção: release autorizado, ainda aguardando execução do rollout.
- Nenhuma das três sessões finais foi executada por esta sessão.
- Motivos do stop:
  1. produção ainda está na migration 116 e no runtime inline antigo;
  2. transporte ativo não está safety-paused;
  3. há uma sessão stale `running` que requer decisão operacional explícita;
  4. deploy, migration, pause/resume, limpeza e testes finais não foram autorizados.

### Próximas etapas, cada uma com autorização explícita própria

1. Revisar o diff local e este handoff.
2. Autorizar deploy coordenado de backend/workers/dashboard/template, mantendo
   `WA_VALIDATOR_RUN_ENABLED=false` e retenção em dry-run.
3. Auditar a versão publicada e decidir/autorizar o pause de transporte/IA
   necessário antes de qualquer sessão.
4. Autorizar separadamente a migration 117, sem aplicar limpeza.
5. Executar o endpoint read-only de retenção e comparar IDs/contagens com o
   inventário manual.
6. Fazer backup e obter autorização separada antes de qualquer cleanup.
7. Autorizar exatamente três sessões diretas/internas: qualificação simples,
   troca de serviço e adição de segundo serviço.
8. Por inbound, provar uma decisão, um proof e no máximo um outbound inerte;
   registrar facts, ramos, primeiro missing field, pergunta, tokens, checksum e
   ausência de destinatário real.
9. Aceitar somente com zero 5xx, API health aquecido `<500ms` durante os testes,
   bootstrap `<2s`, zero repetição, três qualificações completas e nenhum
   handoff exigido pelo Validator para terminar.

### Comandos seguros para retomada

- Health: `curl.exe -sS https://api.vzforeal.com/health`
- Ready: `curl.exe -sS https://api.vzforeal.com/health/ready`
- Release audit read-only:
  `ssh root@api.vzforeal.com "cd /opt/brain-ai && bash ops/vps/validate-production-release.sh"`
- Não executar `.codex-run/run_safe_prod_validator.py` antes dos gates: ele
  cria sessão, lead, mensagens e proofs em produção.
