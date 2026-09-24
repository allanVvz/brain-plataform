# Reconciliação visual — Utzig Garage

Status: reconciliação principal ativa na publicação v6. A capa representativa exclusiva de Reparo e pintura segue como incremento v7, aguardando stage/CAS. Não altera runtime, transport, binding, WhatsApp ou envio de mídia pelo agente.

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
| Reparo e pintura | funilaria, pintura | editorial gerada e marcada como representativa | — |
| Proteção e conservação | PPF, vitrificação, cristalização de para-brisa | vidro antes | cristalização de para-brisa |

PPF, vitrificação, funilaria e pintura não recebem evidência direta. O retrato do especialista não é imagem de PPF, e a foto de cofre não é imagem de pintura. Hero e retrato editorial permanecem em marca/campanha/especialista.

A capa de Reparo e pintura foi gerada especificamente para preencher a lacuna visual do grupo. O asset declara `synthetic=true`, `representative=true` e `not_direct_evidence=true`; ele não é reutilizado como prova de funilaria ou pintura e permanece ligado canonicamente à Gallery.

Materiais da pasta `EDIÇÃO`, se apresentados depois, entram como `pending_validation`; não são publicados nem entram no RAG antes de aprovação. Referências da Aura servem somente à estrutura: nenhum preço, garantia, promessa ou fato comercial dela é importado.

## Próximo gate

O incremento v7 foi compilado contra a v6: adiciona um asset, três edges, altera uma associação de capa, reutiliza todos os chunks e não cria embeddings. Após revisão do diff, executar stage e CAS. Não há cenário WA Validator nesta alteração: ela não muda pergunta, jornada ou resposta do agente.
