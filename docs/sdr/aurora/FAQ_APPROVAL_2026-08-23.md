# Aprovação das FAQs Aurora — 2026-08-23

## Decisão

Por autorização explícita, foram aprovadas as 53 FAQs factuais que estavam em
`pending_validation` no grafo legado da Aurora. Todas possuem fonte declarada,
pai estrutural único e `branch_path` completo. A publicação conecta cada FAQ
aprovada ao Embedded da própria Aurora; não há alteração de persona, binding,
conteúdo ou publicação da Tock Fatal.

As cinco FAQs arquivadas permanecem arquivadas: elas descrevem subtipos de
polimento não publicados ou claims técnicos não sustentados pela fonte. Esta
aprovação não reativa conteúdo arquivado.

## Escopo publicado

- Fonte das 53 FAQs: `aurora_review_plan_2026_08_21`.
- Pais: ProductGroup, Rule ou Product da Aurora, um por FAQ.
- Destino: `aurora-embedded` / Golden Dataset SDR Aurora.
- Restrições preservadas: preço, agenda, disponibilidade, prazo e desconto
  continuam dependentes de confirmação humana quando o grafo assim determina.

## Dívida técnica registrada

Aurora continua no caminho legado `fixture + publish_aurora_graph.py +
compile_persona_publication`. A migração para GraphBundle permanece o item 6
do roadmap e deve ser feita somente por shadow compilation, comparação de
checksum materializado e ativação explícita.

Enquanto essa migração não ocorre, qualquer alteração de conteúdo da Aurora
exige a publicação legada com CAS e a recompilação GraphRAG; não deve haver
edição direta de conteúdo em produção. O checksum semântico de uma fixture não
substitui o checksum materializado de runtime, que incorpora identidades reais
da publicação.
