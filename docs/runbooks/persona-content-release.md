# Publicacao de conteudo e retomada por persona

Este fluxo evita transformar uma mudanca de GraphBundle em manutencao global.
Ele se aplica quando nao ha mudanca de codigo, imagem de servico ou schema.

## Principio operacional

O trabalho caro e falivel acontece antes da pausa. Compilacao, validacao
estatica, diff e checksum nao desligam agentes. A pausa da persona so comeca
no apply; as demais personas continuam operando.

```text
bundle candidato
  -> compile + static public-site validation
  -> diff + checksums para revisao
  -> autorizacao de publicacao
  -> safety pause do binding alvo
  -> materializacao + ativacao CAS
  -> prova de /api/menu/{persona_slug}
  -> selecao canonica do backlog
  -> autorizacao de retomada
  -> retomada atomica do binding
```

Deploy de codigo, migration e limpeza continuam operacoes diferentes e exigem
autorizacao explicita propria. Elas nao devem ser introduzidas silenciosamente
numa publicacao de conteudo.

Toda migration posterior a `131_microservice_role_grants.sql` que exponha RPC
publica deve declarar `GRANT EXECUTE` para a role `brain_*` proprietaria e
executar `NOTIFY pgrst, 'reload schema'`. O workflow valida isso antes do plano;
um grant apenas para `service_role` nao atende os microsservicos isolados.

## Gates antes da pausa

Execute `ops/microservices/validate-graphbundle-plan.py` sobre o bundle e o
PublicationPlan. Para sites publicos, o gate tambem exige:

- uma unica Gallery;
- uma unica Brand publicada na Gallery;
- todos os ProductGroups publicados;
- exatamente os Products que possuem `uses_asset` para imagem publica;
- nenhum produto sem imagem no output.

Falha em qualquer gate encerra a operacao sem pausar a persona.

## Aplicacao e prova

O workflow `.github/workflows/publish-graphbundle.yml` confere a pausa somente
no binding ativo da persona alvo. Depois da ativacao, prove pelo endpoint
publico o par `version + checksum` e as contagens esperadas de paginas,
audiencias, localizacoes, grupos e produtos.

Um HTTP 200 sozinho nao prova o site: a projecao pode estar estruturalmente
valida e semanticamente vazia.

## Retomada sem duplicidade

Use sempre `build_safety_paused_batch_candidates(binding_id)`. Esse filtro
consulta a mesma `resume_answer_window` do runtime para cada lead:

- elegiveis entram em lote idempotente, escalonado em horario comercial;
- stale/skipped permanecem em `waiting_human` e nunca geram outbound;
- se nao houver elegiveis, `resume_safety_paused_binding_v1` retira apenas a
  pausa, registra lote de zero itens e `system_event` na mesma transacao.

Nunca use um ID sentinela, altere `workflow_bindings` manualmente ou mova itens
stale para `retry` apenas para conseguir liberar o binding.

## Evidencia minima

Registre sem PII:

- SHA da fonte, run de publicacao, publication ID, version e checksum;
- persona ID e binding ID;
- contagens e IDs tecnicos de eligible/skipped;
- release batch ID e `item_count`;
- estado final do binding e contagens `waiting_human`/`processing`;
- HTTP e estrutura do endpoint publico.

O teste nao envia WhatsApp real. Mudanca de conversa usa somente WA Validator
direto/interno; publicacao de site nao deve inventar um E2E de mensagem.
