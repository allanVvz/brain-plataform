# Tock Fatal — auditoria da fila e preparação de campanhas

Data da leitura: 2026-09-28 02:53 UTC. Escopo: Tock Fatal. Classificação do
trabalho local: `migration` (admissão atômica), `service` (control-plane e
transport) e `dashboard`. A única mutação de produção foi a limpeza de
conversa da lead Allan 231, autorizada especificamente pelo usuário.

## Evidência produtiva somente de leitura

- Workflow oficial `Audit production deploy messages`, execução
  [36369201723](https://github.com/allanVvz/brain-plataform/actions/runs/36369201723),
  `success`, workflow no SHA `448f91eb07c15ed74e12984be8df4fa873e2ddcb`.
  Esse SHA identifica o workflow, não comprova o digest ou SHA em execução na VPS.
- Persona `tock-fatal` ativa; binding ativo
  `ead9dbcd-8133-4fbf-b73c-248d0c4e9d08`, `connected`, sem
  `safety_paused`. Não havia pausa global de claims.
- O binding ativo tinha 51 inbounds em `waiting_human` e nenhum em estados
  recebidos, buffered, retry, processing ou awaiting_proof no instante da
  auditoria. O backlog real também incluía 10 `dead_letter`.
- A projeção operacional completa, paginada pelo RPC oficial na execução
  [36371501661](https://github.com/allanVvz/brain-plataform/actions/runs/36371501661),
  tinha 50 demandas: 8 `awaiting_customer` em 8 leads, 28 `blocked` em 19
  leads e 14 `technical_failure` em 14 leads. As 8 demandas são candidatas à
  reativação, mas ainda exigem dry-run individual de elegibilidade e proof.
- Na janela UTC 2026-09-27 02:00 a 2026-09-28 02:00, não houve inbound real
  novo; divergências de projeção e duplicações externas contadas pelo workflow
  foram zero. Não havia orphan em processamento há mais de 5 minutos nem
  outbound de agente sem proof nessa janela.
- O diagnóstico somente leitura
  [36370432254](https://github.com/allanVvz/brain-plataform/actions/runs/36370432254)
  confirmou gateway, control-plane, conversation-runtime e transport com
  `health/ready` 200, nos slots blue/green atuais. A execução
  [36371501661](https://github.com/allanVvz/brain-plataform/actions/runs/36371501661)
  chamou também `bash ops/vps/rollout-microservices.sh status` na VPS. O
  runtime ativo informou SHA `b38730a83982e489507ecdb2fec5b5e0f30748b7`
  e digest `sha256:2962ebb924dbf646b08c617965d6767b509a2b0e4a8c98ed59b78a015f343165`;
  o transport, SHA `1831078b1014cf1b43e98af7d75147e130dfb979` e digest
  `sha256:6b3e1d08e1dfc3765f16cc94e5c21632f74270b9834353748dc97b99ee9fcaaa`.
  O log mascarou parte do SHA do control-plane. O grafo
  ativo da Tock Fatal é publicação `2b46d7a2-fba9-4b92-aa2a-27fb53f55af4`,
  versão 38, checksum
  `sha256:3aa4cd2d4a7c50389534ab9cb7c372474030b3852eaaa4c851fc8b7f14d6a28a`.
  Readiness HTTP ainda não substitui a transação sintética do WA Validator.
- Os seis grupos semânticos da persona existem, mas todos têm zero membros,
  incluindo `atacado-revenda` (`f7be9ba9-6b2b-47a6-b3df-ea7e4cee01ae`) e
  `uso-proprio-varejo` (`758567a0-de65-4f1d-b7aa-dfafc23e6ed6`). Há 56
  consentimentos WhatsApp `granted` para `ofertas_e_novidades`, sem import ou
  campanha operacional listados. Há quatro templates `meta_cloud` locais
  `active`/`approved`: `reabordagem_sem_resposta_v1`,
  `reativacao_cliente_antigo_v1`, `interesse_nao_fechado_v1` e
  `aquecimento_leads_v1`. Aprovação local não comprova adequação da copy ao
  convite do catálogo.
- Dos 56 consentimentos válidos, 7 leads têm ramo `audience:tock-reseller`,
  25 têm `audience:tock-retail` e 24 não têm ramo identificável. A consulta
  [36373202049](https://github.com/allanVvz/brain-plataform/actions/runs/36373202049)
  não encontrou, entre as 7 revendas, sobreposição com a fila aguardando
  cliente, outbound proativo, campanha anterior ou opt-out. Isso é um
  inventário de candidatos, não um público congelado: os grupos têm zero
  membros. Os quatro templates existentes usam reabordagem genérica ou
  urgência de estoque e não correspondem ao convite de catálogo sem preço.
- O dry-run individual das oito demandas, execução
  [36371873951](https://github.com/allanVvz/brain-plataform/actions/runs/36371873951),
  encontrou sete linhas com binding indisponível. O diagnóstico
  [36372362269](https://github.com/allanVvz/brain-plataform/actions/runs/36372362269)
  confirmou que essas sete são ligadas a um binding Meta antigo `active=false`,
  embora `connected`; a oitava usa o binding ativo atual. Apenas a lead técnica 297
  passou pelos gates de leitura consultados; seu estado identifica o ramo
  `audience:tock-retail`. Nenhuma das oito tinha inbound novo, opt-out,
  handoff ou reativação prévia segundo esses gates. Não foi gerado preview.
- A consulta adicional
  [36374919030](https://github.com/allanVvz/brain-plataform/actions/runs/36374919030)
  confirmou que **as oito leads** agora apontam para o binding Meta ativo
  `ead9dbcd-8133-4fbf-b73c-248d0c4e9d08`. O bloqueio de sete no dry-run
  anterior verificava o binding histórico da fonte; o alvo atual está
  conectado. Isso amplia o conjunto potencial para oito, sujeito ao novo
  gate por lead e ao proof de cada preview.
- O WA Validator interno do varejo, execução
  [36371754827](https://github.com/allanVvz/brain-plataform/actions/runs/36371754827),
  usou o grafo ativo v38, produziu duas decisões e um outbound interno por
  inbound, ambos com proof válido e commit. A qualidade semântica falhou no
  segundo turno: `service_value_not_reused_as_field`. A inspeção
  [36372070107](https://github.com/allanVvz/brain-plataform/actions/runs/36372070107)
  confirmou `technical_pass=true`, `quality_pass=false`. Portanto a
  validação conversacional ainda não passou e não autoriza envios reais.
- O WA Validator interno de atacado, execução
  [36372289283](https://github.com/allanVvz/brain-plataform/actions/runs/36372289283),
  também terminou com `technical_pass=true`, `quality_pass=false` e o mesmo
  erro `service_value_not_reused_as_field`. A inspeção
  [36372628086](https://github.com/allanVvz/brain-plataform/actions/runs/36372628086)
  confirmou duas decisões, dois proofs válidos, dois commits e um outbound
  interno por inbound, ambos no grafo v38; o segundo turno não passou na
  avaliação semântica. Nenhum WhatsApp real foi enviado pelo teste.
- Uma leitura posterior do proof do segundo turno do varejo,
  [36373657405](https://github.com/allanVvz/brain-plataform/actions/runs/36373657405),
  confirmou `action=keep` sobre o ramo já ativo. O runtime ainda criou uma
  operação de serviço `keep` e marcou a frase inteira como evidência consumida,
  a mesma usada no fato `retail_need`. O código local agora mantém o foco do
  ramo sem consumir texto nem criar operação de serviço para `KEEP`. A
  regressão do fluxo em duas etapas e 23 testes relacionados passaram; essa
  correção está isolada no [draft PR 177](https://github.com/allanVvz/brain-plataform/pull/177)
  (SHA `8811214`, atualizado sobre `main`) e ainda não foi publicada nem
  validada na VPS candidata. Na branch do PR, 59 testes focados passaram.
- A leitura das funções de fila atuais encontrou um risco adicional:
  `list_actionable_message_queue_v1` e a admissão de reativação procuram
  inbound novo apenas no binding histórico da mensagem. Com sete fontes em
  binding inativo, uma resposta recebida pelo binding atual pode não retirar
  a demanda da fila. O envio dessas linhas fica bloqueado até a checagem
  atravessar os bindings da mesma lead e persona em preview e dispatch.

## Allan

O handoff de 2026-08-21 citava lead `33` para Allan na Tock Fatal. O workflow
oficial `Cleanup one production lead conversation`, execução
[36369395884](https://github.com/allanVvz/brain-plataform/actions/runs/36369395884),
foi chamado com `action=dry-run`, `scope=conversation`, persona `tock-fatal` e
nome esperado `Allan`. Ele encontrou `target_count=0` e falhou antes de
qualquer alteração. A busca de leitura na VPS por sufixo mascarado e nome
esperado encontrou uma única lead: `231`, execução
[36371269394](https://github.com/allanVvz/brain-plataform/actions/runs/36371269394).
O dry-run oficial de conversa da lead 231, execução
[36371361884](https://github.com/allanVvz/brain-plataform/actions/runs/36371361884),
passou com `target_count=1`, nome e persona confirmados, 53 buffers,
0 buffers ativos, 54 mensagens, 1 ledger, 1 jornada, 0 conversões,
0 memberships, 0 campaign recipients e 1 consentimento. O escopo de conversa
apagaria 53 mensagens operacionais e preservaria a mensagem imutável ligada
ao consentimento; também limparia buffers, ledger, jornada e quatro chaves
de estado de conversa. O workflow mascarou a contagem de proofs no log.
Após autorização específica do usuário, o workflow oficial
[36372693554](https://github.com/allanVvz/brain-plataform/actions/runs/36372693554)
repetiu o audit, obteve lock transacional e concluiu a limpeza. O pós-estado
confirmou 1 lead preservada, 0 buffers, 0 ledgers, 1 mensagem imutável de
consentimento e nenhuma chave de estado de conversa. Não houve pausa global.

## Código preparado

- Preview/draft podem usar membros do grupo semântico diretamente quando não
  houver import concluído. A origem e os destinatários deduplicados entram no
  checksum/snapshot; o preview mostra sobreposição com reativação e campanhas.
- O envio Meta exige template ativo da própria persona e provider, com ID Meta
  e aprovação local. O modo de texto simples foi removido das campanhas.
- A migration candidata `161_campaign_atomic_admission.sql` reserva
  capacidade e cria a outbox na mesma transação, com limite efetivo de até
  20/hora, 100/dia e uma primeira campanha por lead. O transporte revalida
  consentimento, público, resposta nova, reativação e template antes do
  provider. Capacidade esgotada deixa a linha elegível para o lote seguinte.
- A mesma migration candidata adiciona uma checagem final de reativação no
  transport: antes do provider, um inbound mais novo em qualquer binding da
  mesma lead/persona, opt-out, handoff ou proof sem publicação ativa bloqueia
  o outbound. Isso protege o dispatch das sete fontes antigas após eventual
  troca de binding; a projeção e a admissão da fila ainda precisam de correção
  para retirar essas linhas antes do preview.
- O control-plane candidato agora verifica, antes de cada preview de
  reativação, o binding **atual** da lead e qualquer inbound posterior à fonte
  em todos os bindings da mesma persona. O teste cobre uma fonte em binding
  aposentado com alvo ativo e bloqueio por resposta nova. A projeção do RPC
  continua mostrando a demanda histórica; o gate impede preview obsoleto.
- A migration ainda não foi executada em banco. O SQL passou apenas por parser
  PostgreSQL local; concorrência e índices precisam de validação em candidate
  isolado antes de qualquer cutover.

## Candidate do runtime em 28/09

O fix de ramo `KEEP` foi integrado em `main` no SHA
`a2d4c52c43ad11001de17ea648ff03f50d699cad`. A imagem imutável do
conversation-runtime tem digest
`sha256:057a2b1635291d7fa26ad1ed3268056af1a68ae018c73bc26585f10aac05b244`.
O manifesto incremental preservou byte a byte as entradas dos outros três
serviços. Após autorização específica de release, o workflow
[36376580277](https://github.com/allanVvz/brain-plataform/actions/runs/36376580277)
passou no preflight e iniciou o candidate isolado na VPS. O probe conversacional
sem commit falhou no caso `utzig-doubt-interrupting-name`: a resposta perguntou
novamente o nome, enquanto `question_kind` ficou nulo e o proof registrou
`reply_metadata_discarded:asked_field_key`. O candidate foi parado **antes**
de mover workers ou alterar a rota. Não houve canário pós-cutover nem envio real.

O status oficial de leitura
[36377046661](https://github.com/allanVvz/brain-plataform/actions/runs/36377046661)
confirmou conversation-runtime no slot green e `up to date` com a publicação
anterior, claims não pausados, `outbound_rows_15m=0` e
`unproved_agent_outbound_15m=0`. Control-plane continua `BEHIND` por desvio
anterior e não foi incluído nesta release. A operação foi encerrada sem
segundo redeploy corretivo. O gate do candidate precisa de correção e nova
revisão antes de outra release.

## Próximas decisões e gates

1. Identificar o ramo das sete demandas com fonte em binding histórico,
   validar a correção semântica no WA Validator e revalidar as oito
   linhas antes de gerar preview com proof e reconciliar envio/bloqueio por
   motivo.
2. Gerar previews com proof para as linhas elegíveis e validar via WA Validator
   interno, sem outbound WhatsApp. Só enviar após prova de idempotência,
   contexto varejo/atacado e rechecagem de cada linha. Nenhum envio ocorreu.
3. Usar a conversa limpa de Allan 231 para repetição controlada dos dois
   ramos somente quando o WA Validator semântico passar. O consentimento e
   a mensagem imutável permaneceram preservados.
4. Resolver a ausência de membros dos grupos semânticos antes de preparar
   destinatários segmentados. Primeira
   proposta de campanha: atacado/revenda com opt-in válido, convite ao catálogo
   sem preço. Copy candidata para revisão: “Olá! Temos novidades no catálogo
   de atacado da Tock Fatal. Quer receber o link para conhecer as peças
   disponíveis? Se preferir não receber novidades, é só avisar.” A campanha
   depende de template aprovado da persona, preview de contatos e decisão
   individual; não há draft ou template publicado por esta auditoria.

Os 1.933 arquivos que apareciam modificados apenas por fim de linha já estavam
assim no início da sessão. `git diff --ignore-space-at-eol --stat` foi usado
para manter a revisão focada.
