# Reconciliação visual — Utzig Garage

Status: reconciliação visual e enriquecimento editorial ativos na publicação v9 (`2f51e762-4d5d-452c-808d-1c9149fd466d`), checksum `sha256:5101c7565b789111e36fa5d80ad26b64d13efd57fe87536163041e378582c83b`. O frontend promovido em 2026-09-23 consome essa publicação sem alterar binding, WhatsApp ou envio de mídia pelo agente.

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

Materiais da pasta `EDIÇÃO`, se apresentados depois, entram como `pending_validation`; não são publicados nem entram no RAG antes de aprovação. A referência pública da Aura foi autorizada pelo operador para adaptação comercial dos 13 serviços existentes, incluindo os cinco preços iniciais listados acima. Identidade, contatos, endereço, avaliações e depoimentos da Aura continuam excluídos.

## Evidências da ativação

- GraphBundle compilado contra a publicação v8: cinco nodes `Offer`, dez edges e 25 nodes alterados; 145 chunks reutilizados, 27 embeddings e zero erro de validação.
- Plan, stage e ativação CAS concluídos pelos runs `35945661475`, `35945736002` e `35945855899`.
- O contrato público confirmou v9, 13 serviços, cinco grupos, cinco preços, seis imagens diretas, cinco capas de grupo e nenhuma chave pública de segredo.
- O deployment Vercel `dpl_6hvPwMCDZKqxkHRc1mB3vwCN8nR3` está ativo em `https://utzig.vercel.app`. A home e a landing usam a mesma hero aprovada; cada resumo de produto contém apenas o chevron, sem ícone de fotografia.
- O WA Validator interno confirmou `technical_pass=true`, Graph v9, proof válido, commit completo, uma decisão e um outbound interno por turno. O gate de qualidade reprovou porque a resposta “Onix” foi reconhecida na fala, mas não persistida como `modelo_veiculo`; sessão `635446f0-ee5c-435d-bb04-9e23b51b3e7e`. Não houve outbound ao WhatsApp real.

## Gate bloqueado do backend

O código do control plane e do `brain-contracts` já implementa `media.primary`, mas o control plane produtivo ainda usa o digest anterior e o payload público preserva somente `assets` e capas de grupo. A tentativa de renderizar uma release exclusiva do control plane foi bloqueada corretamente pelo validador: a alteração do checksum de `brain-contracts` também alcança runtime e transport, enquanto o escopo aprovado proíbe alterar esses serviços e o runtime possui um canário de qualidade pendente. Nenhum cutover de microsserviço foi executado. A interface pública já evita repetição visual pela estrutura grupo/produto; promover o contrato aditivo do backend exige uma release separada depois de corrigir e aprovar o canário do runtime.
