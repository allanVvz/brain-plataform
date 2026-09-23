# Reconciliação visual — Utzig Garage

Status: candidato GraphBundle, aguardando revisão e stage/CAS. Não altera runtime, transport, binding, WhatsApp ou envio de mídia pelo agente.

## Regra pública

O resolvedor público opt-in usa somente posição explícita e a ordem `produto direto → capa do grupo → campanha`.

Cada resultado traz `origin`, `owner_node_id`, `representative` e `dedupe_key`. `assets` continua sendo somente evidência direta, por compatibilidade. Uma capa de grupo é apresentada uma vez no card do grupo; o detalhe do serviço a recebe em `media.primary` como representativa, sem alegar prova específica.

## Inventário e classificação

As evidências aprovadas vêm da pasta Utzig autorizada. A relação canônica é sempre `Asset → Gallery`; a relação `publishes_to → Gallery` continua apenas como compatibilidade do projetor público.

| Grupo | Serviços | Capa representativa | Evidência direta aprovada |
| --- | --- | --- | --- |
| Avaliação e orientação | Avaliação | processo | — |
| Limpeza e higienização | lavagem detalhada, cofre, higienização interna | extratora | cofre, higienização interna |
| Correção e acabamento | polimentos comercial/técnico/de vidros e faróis | farol antes | técnico, vidros, faróis |
| Reparo e pintura | funilaria, pintura | processo | — |
| Proteção e conservação | PPF, vitrificação, cristalização de para-brisa | vidro antes | cristalização de para-brisa |

PPF, vitrificação, funilaria e pintura não recebem evidência direta. O retrato do especialista não é imagem de PPF, e a foto de cofre não é imagem de pintura. Hero e retrato editorial permanecem em marca/campanha/especialista.

Materiais da pasta `EDIÇÃO`, se apresentados depois, entram como `pending_validation`; não são publicados nem entram no RAG antes de aprovação. Referências da Aura servem somente à estrutura: nenhum preço, garantia, promessa ou fato comercial dela é importado.

## Próximo gate

Exportar a publicação Utzig ativa por fonte autenticada e executar `compile_graph_bundle.py --against <export-confiavel>`. Depois da revisão do diff, stage candidato e CAS são autorizações separadas. Não há cenário WA Validator nesta alteração: ela não muda pergunta, jornada ou resposta do agente.
