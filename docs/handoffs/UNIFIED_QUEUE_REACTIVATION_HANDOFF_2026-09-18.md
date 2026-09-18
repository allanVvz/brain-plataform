# Handoff - fila unificada e reativacao Tock Fatal

Data: 2026-09-18.

## Entregue em producao

- Fila `Disparos` global, sem filtro por lead ou historico; pendentes e previews
  aparecem em vermelho e mensagens enviadas que aguardam resposta em verde.
- Acoes simples por linha e em lote: pausar, retomar, corrigir/gerar resposta,
  enviar preview e `Reativar cliente`.
- `Reativar cliente` nunca reenvia o outbound original. Cria uma nova mensagem
  `proactive`, com proof e chave propria; o operador revisa o preview e envia.
- O banco recebeu a migration 146 e os servicos control-plane, transport e
  conversation-runtime foram publicados pelo manifesto `941571d`.
- O dashboard Vercel publicou o mesmo commit.
- A publicacao Tock ativa e a v38, checksum
  `sha256:3aa4cd2d4a7c50389534ab9cb7c372474030b3852eaaa4c851fc8b7f14d6a28a`.
  Ela declara horario `08:00-20:00 America/Sao_Paulo`, Rule, copy de aviso e
  a copy de reativacao da manha.

## Garantias da reativacao manual

O RPC revalida atomicamente: outbound original entregue, ausencia de inbound
mais novo, ausencia de opt-out, bloqueio do provedor, campanha cancelada e
handoff. A mensagem proativa tem proof de Copy/Rule publicados e se torna
obsoleta se o contexto mudar antes do envio.

## Validacao e evidencia

- Migration: Actions run `35327896110` (sucesso).
- Runtime/canario interno: run `35329080989` (sucesso).
- Auditoria de mensagens: run `35329735853`; zero outbound de agente sem
  proof e zero orfaos de processamento. Oito `dead_letter` Tock ja existiam
  antes da release e nao foram mutados.
- WA Validator: sessao interna `014b2cf4-fb69-4cda-93fa-189df60c68af` teve
  `technical_pass=true`, com uma decisao/proof/outbound interno por turno.
  A qualidade falhou somente em `customer_name_question_once`.

## Divida tecnica

`UMQ-001` esta registrada em `docs/roadmaps/technical-debt.md`: o avaliador
marca a pergunta de nome como falha apesar de a evidencia registrar uma unica
emissao. Corrigir o criterio do WA Validator sem alterar o comportamento de
mensagens.

## O que ainda nao existe: reativacao automatica as 08:00

O GraphBundle v38 declara a hora e a copy, mas nenhum worker produtivo cria
proativamente a reativacao matinal. O worker existente de inactivity recovery
e deliberadamente somente de recuperacao de inbound travado e nao pode enviar
proativos. Portanto, hoje a alternativa segura e usar a acao em lote da fila:
selecionar mensagens verdes aguardando resposta, `Reativar cliente`, revisar
os previews e `Enviar`.

Para automacao futura, implementar um unico worker as 08:00 que use o mesmo
`lead_buffer`, `system_events` e proof publicados: uma chave idempotente por
outbound-origem/dia, nova mensagem `proactive` (nunca replay), e cancelamento
atomico por inbound novo, opt-out, handoff, bloqueio do provedor ou campanha
cancelada. Isso requer uma migration aditiva, testes WA internos e release de
runtime antes de habilitar envios reais.
