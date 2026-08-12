# Brain Platform Memory

Updated: 2026-08-12

## Handoff atual — WA Validator em produção

### Limites vigentes

- Operação exclusivamente em produção. Não executar Docker local.
- Conversas de teste somente pelo WA Validator direto/interno; nunca usar
  WhatsApp real.
- Binding/transporte Aurora e IAs permanecem pausados. Não retomar sem nova
  autorização explícita.
- Retenção permanece somente em dry-run. Nenhuma limpeza foi autorizada ou
  executada.
- Não há migration pendente desta correção; a última aplicada continua sendo
  `117_wa_validator_queue_and_retention.sql`.

### Produção atual

- Código de API e worker publicado no image imutável
  `44755c3384c93d28ae9be1532de0a6f755d71b2c`.
- API: `https://api.vzforeal.com`; diretório operacional: `/opt/brain-ai`.
- Persona Aurora: `96e0d69f-9abd-406a-bbb9-3e7977f24ec8`.
- Binding Aurora: `6386bc58-ade9-44c4-9211-0f59f23ffca5`, ativo apenas como
  configuração, `connection_status=safety_paused`, `metadata.safety_paused=true`,
  owner `n8n_agents`, contrato `conversation_v3`.
- `WA_VALIDATOR_RUN_ENABLED=false` e
  `WA_VALIDATOR_RETENTION_ENABLED=false`.
- Workflow n8n: `k5JWkvpQyb8EB3Vw`.
- Graph Aurora publicado: versão 51, checksum
  `sha256:532a0379dd0f3ef500222170bc7bf45f78e2a866619d6b2e27dbd6f1b868b35a`.

### Implementação concluída

- Bootstrap escopado por persona, últimas 12 horas e no máximo 25 sessões;
  reutiliza persona/routing/binding e carrega apenas o grafo necessário.
- `POST /wa-validator/run-direct` apenas enfileira; o worker executa a conversa
  fora do event loop da API. A UI reconhece `queued`, `running` e terminais.
- Leituras sintéticas são filtradas no banco por escopo canônico e janela de
  12 horas.
- Erros do cliente preservam endpoint, status HTTP e request ID; apenas GET de
  bootstrap repete uma vez em `502/503/504`; POST nunca é repetido.
- Workflow aceita `branch_action=add` e recebe `active_branch_node_ids`,
  `facts_by_key` e `known_facts`.
- O runtime reconcilia resposta literal ao primeiro campo pendente, incorpora
  todos os fatos antes de recalcular a pergunta, preserva fatos compartilhados
  e separa fatos específicos por serviço.
- `switch` substitui o serviço; `add` mantém os dois ramos. Menção incidental a
  serviço dentro da resposta de outro campo não muda o foco.
- Dúvida é respondida antes da retomada da qualificação. Existência do serviço
  pode ser provada pelo ramo publicado; agenda, data e horário não podem.
- Pergunta repetida é aceita somente quando o mesmo question node ainda
  corresponde a um campo pendente. Perguntar campo já conhecido continua
  reprovando.
- O Validator encerra assim que o proof indica qualificação completa, sem
  exigir handoff e sem avançar para agendamento.
- Auditoria agrega contratos de todos os ramos ativos, aceita normalizações
  string provadas e equivalência booleana canônica sem inverter o valor.
- Outbound de Validator é persistido de forma inerte: sem destinatário e sem
  ID externo real.
- `AGENTS.md` proíbe Docker local para esta operação e exige auditoria/dry-run
  em produção. A suíte padrão não possui testes skipados nem inicia Docker.

### Evidência de testes e release

- Suíte local sem Docker: `644 passed`, zero skips, três warnings conhecidos.
- Testes focados finais: `106 passed`; `py_compile` e `git diff --check` passam.
- CI do SHA `44755c3`: backend, frontend, migrações descartáveis, template,
  contratos, SBOM e scan da imagem aprovados.
- Deploy oficial `31569885034` concluído com sucesso; API e worker usam o mesmo
  image SHA.
- Dry-run final de retenção: `dry_run=true`, `safe=true`, corte móvel de 12h;
  nenhuma remoção foi executada.

### Cobertura produtiva do Validator

- Pintura: sessão `5f27a06c-70c6-4cbd-a76f-e6855b1975e4`, lead 151,
  `technical_pass=true`, `quality_pass=true`, qualificação completa.
- Troca Pintura → PPF: sessão `9f9a7ffe-e01a-4656-915d-516209ad8dfa`, lead 152.
  A troca foi concluída corretamente; somente PPF permaneceu ativo e os fatos
  compartilhados foram preservados. O usuário confirmou o comportamento como
  sucesso; a interrupção era do teste antigo.
- Adição Pintura + PPF final: sessão
  `6d9d742c-eb71-4889-9303-699fe39e10a9`, lead 159, estado `done`,
  `technical_pass=true`, `quality_pass=true`.
- Na sessão final, a dúvida “Vocês fazem pintura?” foi respondida e a pergunta
  de nome foi repetida legitimamente porque o campo ainda estava pendente.
- Pintura e PPF permaneceram ativos. Fatos compartilhados foram capturados uma
  vez; `missing_fields=[]`; `qualification_complete=true`; handoff semântico
  não foi exigido. O lead sintético foi colocado em handoff full após o teste.
- Exatamente 9 inbounds, 9 decisões, 9 proofs válidos, 9 commits completos e 9
  outbounds inertes: um conjunto por inbound, zero destinatários e zero IDs
  externos de provider.
- Bootstrap final: 190.352 ms. Durante a conversa: 87/87 health HTTP 200, zero
  falhas, máximo 41.828 ms e p95 15.499 ms. Checagem posterior: HTTP 200 em
  3.310 ms.
- Nenhum WhatsApp real foi enviado e não houve limpeza de dados.

### Estado de encerramento

- Os critérios funcionais de Pintura, troca para PPF e adição de PPF foram
  atendidos com o Validator interno.
- Binding/transporte e IAs continuam pausados; retenção continua desativada.
- Qualquer retomada de IA/transporte ou aplicação da limpeza exige revisão e
  autorização explícitas separadas.

### Alteração seguinte pronta para release

- Nova regra solicitada: o mesmo question node pode ser publicado no máximo
  duas vezes enquanto o campo estiver pendente. Na interação seguinte sem
  resposta válida, o backend persiste esse owner/campo como `status=unknown`
  (não respondido), mantém o campo em `missing_fields` e passa ao próximo campo
  perguntável sem inventar valor.
- `unknown` não conclui qualificação e não pode ser perguntado novamente. Uma
  informação espontânea posterior pode substituir `unknown` por `known` sem
  exigir marcador artificial de correção, desde que passe owner, evidência
  literal e schema publicados.
- A contagem usa o histórico persistido de question node e confirma mensagens
  recentes para compatibilidade com ledgers antigos que deduplicavam a lista.
- CI foi tornado sensível ao escopo: backend roda uma única suíte; frontend,
  Compose, SBOM/dependency audit e scan de imagem só rodam quando seus arquivos
  relevantes mudam. Commit apenas documental não instala dependências nem
  constrói imagem.
- CD não reinstala dependências nem repete testes/frontend: exige CI bem-sucedido
  para o mesmo SHA, repete apenas contratos sem dependências e preserva Compose,
  build imutável, backup e auditoria de produção.
- Verificação local sem Docker: 647 testes aprovados, zero skips; 125 focados
  aprovados após o ajuste final; sintaxe Python/YAML, anti-hardcode e diff check
  aprovados. Ainda não publicado neste ponto do handoff.
