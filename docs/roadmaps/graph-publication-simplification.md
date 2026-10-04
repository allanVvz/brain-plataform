# Simplificar a publicação de GraphBundle

Pedido do usuário (02/10/2026): publicar um grafo novo deve ser descomplicado —
editar o arquivo, gerar o plano e ativar.

## Por que hoje é complicado

1. **O bundle precisa descrever o grafo inteiro.** O preflight de
   `apps/control-plane/api/services/graph_bundle_publisher.py` recusa qualquer nó
   ou aresta publicada no banco que o bundle não mencione
   (`source_graph_has_unplanned_nodes` / `_edges`).
2. **O grafo tem mais de um escritor.** Funções fora do bundle também criam nós e
   arestas — por exemplo o upload de imagens cria `gallery:gallery-default` e liga
   os assets a ele (`ensure_gallery_node`). A galeria é o destino final dos assets
   que vão para o site (no futuro, também para o agente enviar). Na publicação
   seguinte o bundle "não conhece" esses nós e a publicação trava.
3. **Arquivos defasados.** Os bundles do repositório deixam de refletir a
   produção (ex.: o arquivo v13 da Utzig ainda aponta o v12 como base).
4. **Não há remoção.** O publicador só cria e atualiza. Retirar um serviço exige
   arquivar o nó fora do fluxo.

## Direção

1. **Escopo de propriedade:** o preflight compara apenas o que o bundle criou
   (`source_table = 'graph_bundle'`). Nós e arestas criados por outras funções
   (galeria, assets enviados) pertencem a elas e passam intactos. O bundle pode
   referenciá-los por tipo e slug.
2. **Remoção nativa:** `metadata.retired_nodes` arquiva os nós no mesmo passo da
   publicação, com restauração no rollback
   (`api/scripts/apply_graph_node_retirements.py`, já escrito; falta entrar em
   `.github/workflows/publish-graphbundle.yml`). As arestas desses nós usam os
   tombstones que já existem.
3. **Base sempre atual:** o workflow exporta o grafo ativo e aplica o overlay
   sobre ele, em vez de depender de um arquivo completo no repositório.
4. Resultado esperado: um overlay pequeno (o que muda) → plan → activate.

## Estado

- Itens 1 e 2 mexem no publicador e no workflow de publicação e precisam de
  autorização explícita para alterar infraestrutura.
- Enquanto isso, a publicação da Utzig v15 inclui explicitamente os nós criados
  fora do bundle (galeria), lidos da produção.
