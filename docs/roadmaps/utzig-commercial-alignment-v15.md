# Utzig — alinhamento comercial v15 (grafo + LP)

Fonte: notas da Luiza Camargo (Utzig), WhatsApp, 28/09/2026. Base: publicação
ativa v13 (`6b85bf7a-ab87-4f3b-a1d1-4a6b4ae4c05f`, draft `sha256:b23cea31…`).

## Decisões do usuário (02/10)

- O SDR **não fala preço**: diz que o atendente confirma. O closer (humano hoje,
  agêntico depois) tem os preços. Controle por **recuperação**, sem proof/guarda.
- Funilaria, pintura, envelopamento e películas saem da LP **e** do SDR.
- **Nenhum valor na página nem no SDR.** Os preços da Luiza ficam só registrados
  no grafo (`offer.data.visibility: registered_only`) para serem religados
  depois. A lavagem detalhada fica sem valor (o R$ 259,90 veio da Aura).

## Regra de preço: produto × serviço

- **Produto (varejo/atacado, ex.: Tock Fatal):** a oferta tem `channel`
  (`varejo`/`atacado`); o SDR conhece o valor publicado e o closer pode dar
  desconto.
- **Serviço (ex.: Utzig):** não tem valor fixo nem canal. O SDR **nunca** conhece
  o valor; responde que o atendente confirma depois da avaliação. O valor de
  referência, quando o cliente informa, fica em `offer` com
  `price_kind: service_reference` e `visibility: registered_only`: não vai para
  a LP (o `menu.py` ignora essas ofertas) nem para o RAG do SDR (só FAQs viram
  chunk, e as FAQs de serviço não citam valor).
- A Tock não foi alterada por esta regra.

## Pronto (branch `feat/utzig-commercial-v15`, commit `f1205c1`)

- `data/graph_bundles/utzig-garage/build_commercial_alignment_v15.py` gera o
  overlay e o bundle `utzig-commercial-alignment-v15.json` (plano em `.PLAN.json`,
  `validation_errors: []`).
- Setores: Limpeza e higienização · Brilho e correção · Proteção · Avaliação e
  orientação. 22 nós retirados (`metadata.retired_nodes`) e 52 arestas em
  `soft_disabled_edges`.
- Preços da Luiza registrados nos `offer:` (`price_qualifier`
  `a_partir_de`/`valor_base`, `visibility: registered_only`, sem `channel`).
  As 40 FAQs recuperáveis pelo SDR não contêm valor. As FAQs de preço antigas
  (vindas da Aurora/Aura) foram reescritas.
- FAQs novas a partir do texto da Luiza: serviços, PPF (áreas, multimídia),
  tempos, avaliação/orçamento. `faq:utzig:services-not-offered` fica em
  `utzig-commercial-alignment-v15.pending-faqs.json` até confirmação.
- Veículo e nome são da lead (`carry_over`); veículo não depende do serviço.
- `menu.py` ignora ofertas `registered_only`; o compilador indexa `aliases` e
  `question_aliases`; o preview da LP projeta catálogo e FAQs do candidato.
- LP (`utzig-pages`, branch `feat/utzig-lp-v15`): 3 colunas **sem preços**, sem
  "Catálogo completo"/"Seu objetivo"/"Resultados" duplicado, CTA de WhatsApp nas
  FAQs e botão flutuante. Uma LP futura mais simples, sem preços, está prevista.
  Validado em build de preview (desktop e mobile, sem erros de página).

## Bloqueios para publicar

1. **Nó `gallery:gallery-default`** existe no banco e não está no bundle
   (criado por upload de asset). É preciso o `projection_node_id` real dele para
   incluí-lo no v15, senão o preflight recusa (`source_graph_has_unplanned_nodes`).
2. **Retirada de nós no workflow**: `api/scripts/apply_graph_node_retirements.py`
   está pronto (arquiva com status anterior e `--restore`), mas ainda não é
   chamado por `.github/workflows/publish-graphbundle.yml`. Precisa: copiar o
   script, rodar dry-run + `--apply` antes dos tombstones e `--restore` no trap
   de rollback.
3. Depois disso: `publish-graphbundle` plan → stage → activate com os checksums
   do `.PLAN.json` regenerado; deploy do control-plane (qualifier no menu);
   deploy da LP em `test.utziggarage.pages.dev` e depois `main`.

## Confirmar com a Luiza / o Alemão

1. Valor de referência da lavagem detalhada/tradicional, se houver (hoje sem
   valor).
2. Setor da hidratação de couros (hoje em Limpeza e higienização).
3. Quais valores sem "a partir de" são fixos (higienização, couros, polimento
   comercial, faróis, PPF kit básico).
4. Foto nova do hero ("ele operando").
5. Publicar a FAQ "não fazemos funilaria/pintura/envelopamento/película".
6. Garantia de 10 anos do PPF e FAQs vindas da Aura (vitrificação × cera,
   cuidados pós-serviço, PPF em carro usado).
7. Tempos de serviço que ainda não foram informados.

## Fase 2 (closer agêntico)

`data.retrieval_scope` (`sdr`/`closer`) no compilador e filtro por `agent_role`
no runtime; FAQs de preço com escopo `closer`.
