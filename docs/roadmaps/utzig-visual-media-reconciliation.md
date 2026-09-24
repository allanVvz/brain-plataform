# Reconciliação visual — Utzig Garage

Status: reconciliação visual ativa na publicação v8. O incremento editorial seguinte parte exatamente dessa fonte comprovada e aguarda stage/CAS; não altera runtime, transport, binding, WhatsApp ou envio de mídia pelo agente.

## Enriquecimento editorial aprovado

- A primeira dobra do linktree e da landing usa “Estética Automotiva Premium” e “Mais de 20 serviços que valorizam e deixam o seu carro na melhor versão”, com a linha de apoio “Tudo o que seu carro precisa, em um só lugar.” A afirmação foi aprovada diretamente a partir do feedback comercial de 2026-09-23.
- O catálogo continua destacando os 13 serviços graph-backed em cinco jornadas; o contador do frontend é calculado pelo payload e deixa explícito que são serviços em destaque, não a totalidade da oferta.
- Os 13 produtos recebem descrições editoriais próprias. A Aura Detail é referência autorizada de conteúdo comercial, mas identidade, telefone, endereço, avaliações e depoimentos da concorrente não são fatos da Utzig.
- Cinco preços iniciais aprovados são nós `Offer`: lavagem detalhada R$ 259,90; higienização interna R$ 600; polimento técnico R$ 700; PPF R$ 499,90; vitrificação R$ 999,90. A interface sempre apresenta “A partir de”, e avaliação continua definindo o valor final.
- O especialista passa a ser identificado como “Wilian”, com o subtítulo “O Alemão da Utzig”. O apelido permanece nos CTAs compactos já reconhecidos pelo público.
- O resumo de produto exibe texto e preço, sem ícone de fotografia. Mídia direta continua visível somente ao expandir o serviço, e capas representativas preservam sua identificação de fallback.

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
