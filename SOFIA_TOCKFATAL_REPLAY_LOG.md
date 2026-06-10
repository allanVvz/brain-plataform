# Sofia Criar - Tock Fatal replay log

Data de referÃªncia: 2026-06-01
Fonte: https://tockfatal.com
Persona: `tock-fatal`

## O que o usuÃ¡rio pediu
- Extrair 2 produtos do site.
- Criar 1 grupo de produtos chamado `Modais`.
- Conectar a audiÃªncia padrÃ£o.
- Montar a campanha de inverno `Tock Fatal`.
- Gerar preview da Ã¡rvore.
- Remover o grupo vazio quando ele aparecesse sem sentido.

## O que a Sofia executou
1. Recebeu a mensagem de retomada automÃ¡tica com o resumo do plano.
2. Reinterpretou a solicitaÃ§Ã£o como um plano hierÃ¡rquico de marketing.
3. Voltou a perguntar sobre audiÃªncia e campanha, mesmo depois de jÃ¡ haver contexto suficiente.
4. Gerou o mesmo plano mais de uma vez, sem avanÃ§ar para o preview Ãºtil.
5. O save falhou com `Erro: 500 /kb-intake/save`.
6. Depois da remoÃ§Ã£o do grupo vazio, o plano voltou com 1 grupo e ainda assim bloqueou por falta de cadeia completa.
7. Ao pedir `crie o grafo de preview`, o sistema mostrou pendÃªncias de caminho e nÃ£o entregou a Ã¡rvore esperada.

## Funcoes que entram nesse fluxo
- `api/services/kb_intake_service.py::validate_sofia_knowledge_plan`
  - valida a arvore antes de permitir preview ou save.
- `api/services/kb_intake_service.py::_normalize_sofia_knowledge_plan`
  - normaliza entries, parents e links.
- `api/services/kb_intake_service.py::_rewrite_visible_plan_summary`
  - monta o texto exibido no chat com o resumo do plano.
- `api/services/kb_intake_service.py::apply_plan_hierarchy`
  - materializa os links do plano em edges da arvore.
- `api/services/kb_intake_service.py::repair_primary_tree_connections`
  - repara conexoes da arvore principal quando alguma edge primaria falta.
- `api/services/knowledge_graph.py::ensure_main_tree_connection`
  - cria a edge principal com `metadata.primary_tree=true`.
- `api/routes/graph.py::get_graph_data`
  - renderiza o grafo em `layered` / `semantic_tree`.
- `dashboard/app/knowledge/capture/page.tsx`
  - abre o diagnostico e bloqueia o preview quando existem violacoes.

## O que significa `entry[4]`
`entry[4]` nao e um node do grafo.

`entry[n]` e o indice zero-based do array `entries` do plano da Sofia.

Exemplo:
- `entry[0]` = primeiro bloco do plano
- `entry[1]` = segundo bloco
- `entry[4]` = quinto bloco

No caso dessa conversa, `entry[4]` era um bloco `product` ou `product_group` dependendo da versao do plano gerado. O erro `entry[4] has no complete path to persona` significa:
- o validador nao encontrou uma cadeia pai -> filho completa ate a persona;
- ou o parent do bloco nao foi resolvido;
- ou a edge principal nao foi marcada/gravada como `primary_tree=true`;
- ou o preview estava olhando apenas a arvore principal e ignorando uma relacao semantica que nao foi promovida para a edge estrutural.

## Por que o erro pareceu sem sentido
O texto mistura duas camadas diferentes:
- camada de plano: `entries`, `links`, `entry[4]`
- camada de grafo: nodes, edges, `primary_tree`, renderizacao

Quando a Sofia imprime:
`entry[4] has no complete path to persona`
ela esta falando do plano ainda nao validado, nao do grafo publicado.

Se o plano esta incoerente, o preview quebra antes de virar grafo.
Se o grafo publica relation semantica sem marcar `primary_tree=true`, o preview pode parecer certo no texto, mas a arvore some no render.

## Inconsistencias observadas
- A Sofia repetiu o mesmo resumo de plano varias vezes sem sair do estado de coleta.
- O preview bloqueou por depender de caminho completo ate a persona.
- Um grupo vazio apareceu no plano e precisou ser removido manualmente.
- O validador continuou pedindo parent para produtos que ja tinham contexto suficiente.
- `has no complete path to persona` foi mostrado como se fosse uma falha de node isolado, mas na pratica e uma falha de encadeamento do plano.
- `entry[4]` aparece porque o plano e avaliado por posicao no array, nao por slug.
- Quando a edge estrutural nao e marcada como `primary_tree=true`, a camada `/knowledge/graph` em `layered/semantic_tree` nao enxerga a arvore completa.

## Leitura correta do fluxo
1. O usuario pede a criacao.
2. A Sofia monta `plan_json`.
3. `validate_sofia_knowledge_plan` decide se o preview pode abrir.
4. Se houver pendencia de caminho, o preview trava e abre o diagnostico.
5. Ao confirmar o grafo, `apply_plan_hierarchy` deve publicar edges principais.
6. Essas edges precisam carregar `metadata.primary_tree=true`.
7. O `/knowledge/graph` renderiza a arvore com base nessa marca.

## Ponto de correcao principal
O problema relatado nao e a existencia de `entry[4]`.
O problema e que o plano estava sendo validado e publicado de forma inconsistente entre:
- relacao semantica
- relacao estrutural principal
- renderizacao do grafo

Quando isso acontece, a Sofia fala como se faltasse um parent, mas o que faltou foi a promocao da aresta principal ou a resolucao do parent no plano.

## Estado atual do que foi ajustado
- A publicacao da arvore principal passou a tratar `metadata.primary_tree=true` como fonte de verdade.
- A relacao semantica pode ficar como metadata complementar.
- O repair da arvore principal nao depende mais apenas do `relation_type`.
- Um teste de contrato foi adicionado para cobrir save + graph render da Tock Fatal com 1 grupo `Modais` e 2 produtos.

## Como continuar o ajuste
1. Tratar o diagnostico como erro de plano, nao como node isolado.
2. Quando houver `product_group` vazio, perguntar explicitamente se o usuario quer 1 ou 2 grupos.
3. Garantir que o preview mostre a arvore inteira antes do save.
4. Manter a aresta principal sempre com `primary_tree=true`.
5. Usar `entry[n]` apenas como referencia de posicao do plano.
