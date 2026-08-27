# Handoff — nova persona SDR B2B (tirzepatida), escopo restrito

Data do snapshot: 2026-08-21
Escopo: ler `C:\Users\allan\Downloads\Emagreça agora` e montar uma persona
completa pronta para o fluxo SDR, a partir do pedido do operador.
Estado: **GraphBundle de conteúdo pronto, plano local limpo. Nada criado em
produção** — sem linha em `personas`, sem `workflow_bindings`, sem ativação.

## 1. Por que o escopo mudou

Os documentos não descrevem uma marca de produto de emagrecimento de
varejo — descrevem venda/distribuição de **tirzepatida** (medicamento
injetável de prescrição) com envio transfronteiriço para o Brasil. Perguntei
diretamente ao operador sobre a base regulatória da venda direta a pessoa
física para uso pessoal; a resposta confirmou que essa via existe no negócio,
mas não trouxe a base regulatória pedida (telemedicina com prescrição real?
importação pessoal autorizada?).

**Decisão tomada, registrada em `rule:tirzeb2b-sem-pessoa-fisica` no próprio
grafo:** o segmento de pessoa física/interesse pessoal (`PES` na fonte) fica
**fora do funil de qualificação/venda**. Qualquer sinal desse tipo é
desviado por uma regra de handoff, nunca qualificado. Os outros 7 públicos
documentados na fonte — todos profissionais/empresariais, respondendo pela
própria licença — foram mantidos: médico, outro profissional de saúde,
dono/gestor de clínica, profissional de estética, farmácia, distribuidor e
parceiro/indicador.

Reabrir o segmento de pessoa física exige nova aprovação explícita do
operador, com a base regulatória documentada — gate separado desta rodada.

## 2. Fonte usada

`PERGUNTAS_RESPOSTAS_POR_PUBLICO_WHATSAPP.md` (v1.0, 2026-08-18) — lido na
íntegra. Perguntas de qualificação, FAQs e objeções vêm transcritas/adaptadas
diretamente desse documento, não inventadas.

**Não lido/usado:** `FLUXOS_SDR_TIRZEPATIDA.md` (79KB) está corrompido — 100%
bytes nulos, ilegível. Pode conter catálogo, política comercial ou nome da
empresa. Precisa ser reenviado antes desta persona virar "completa" de
verdade. `FLUXOS_WHATSAPP_OUTBOUND_SDR.md`,
`FLUXO_IA_WHATSAPP_AUDIENCIA_DESCONHECIDA.md` e
`MANUAL_FLUXOS_WHATSAPP_SDR_TIRZEPATIDA.md` não foram lidos nesta rodada —
provável material complementar (outbound, fluxo de audiência desconhecida,
manual) para uma próxima revisão.

## 3. O que está no GraphBundle

Arquivo: `data/graph_bundles/tirzepatida-b2b/sdr-qualification-v1-draft.json`
(+ `.PLAN.json` com o plano computado localmente — `disposition:
awaiting_approval`, `validation_errors: []`, 46 nodes / 45 edges, 7 branches).

- `persona:tirzepatida-b2b` — slug e nome **provisórios** (nenhum nome de
  empresa aparece nos documentos legíveis); `business_model: sales`.
- `brand:tirzeb2b-essencia` — tom consultivo documentado na fonte (humano,
  direto, sem pressão, uma pergunta por vez).
- `campaign:tirzeb2b-qualificacao` — container da qualificação B2B.
- **7 `audience` (branch anchors)**, cada uma com os campos de qualificação
  da "Matriz técnica de campos por público" da fonte: médico, profissional de
  saúde, clínica, estética, farmácia, distribuidor, parceiro.
- **FAQs de qualificação** — uma por pergunta de cada público (área de
  atuação, interesse principal, localização, etc.), mais **9 FAQs
  compartilhadas** ("quanto custa", "entregam no Brasil", "manda material",
  "não tenho interesse" etc.) transcritas da seção "Respostas comuns a todos
  os públicos".
- `rule:tirzeb2b-sem-preco-numerico` — nunca revelar preço/desconto/prazo
  fechado no chat, sempre encaminhar para ligação (política já documentada na
  fonte, formalizada como regra global).
- `rule:tirzeb2b-sem-pessoa-fisica` — a exclusão de compliance descrita acima.

**De propósito fora desta entrega:** nenhum node `product`/`offer` (não
existe catálogo real na fonte legível); nenhuma criação de persona real em
produção (`POST /personas`), nenhum `workflow_bindings`, nenhuma ativação.

## 4. Bloqueios antes de considerar isso pronto para produção

- Nome real da empresa (hoje só `[EMPRESA]` placeholder na fonte).
- `FLUXOS_SDR_TIRZEPATIDA.md` reenviado, sem corrupção.
- Confirmação do slug/nome final da persona.
- Se o operador quiser reabrir pessoa física: base regulatória documentada.
- Depois disso: criar a persona de verdade pela API administrativa
  (`POST /personas`), atualizar o UUID no bundle, recompilar e aprovar os dois
  checksums, e então rodar `api/scripts/publish_graph_bundle.py` — mesmo
  processo usado para a Tock Fatal, gate por gate. Número de WhatsApp, binding,
  workflow e retomada de transporte são etapas posteriores, independentes e
  com autorização própria; não são pré-requisito para publicar o conteúdo.
  Enquanto esses recursos não existirem, a nova persona permanece inerte sem
  exigir pausa de outras personas.
