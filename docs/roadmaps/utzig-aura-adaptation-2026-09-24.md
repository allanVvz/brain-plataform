# Utzig Garage — adaptação editorial da referência Aura

## Atualização de 2026-09-24

O operador pediu a inversão das capas de Preservação e Revitalização e a retomada da edição dos campos do grafo. A inversão será uma publicação graph-only baseada na publicação ativa, com plan, stage e CAS. Os campos e perguntas de agendamento permanecem no node Persona e nos produtos do grafo; no modo agentic sua lista define cobertura e completude, sem impor ordem fixa. A publicação editorial v11 local tem baseline v10 e não deve ser reutilizada como fonte ativa sem novo export. Pendem o canário conversacional de qualidade, a promoção do contrato `media.primary` no control plane e fontes reais para depoimentos. A release de runtime do commit local `cabfded` ainda depende de candidate isolado e canário interno.

Estado: GraphBundle v10 ativo e frontend público promovido em 2026-09-24. Fonte observada em 2026-09-24: <https://auradetail.com.br/>. O repositório MIT `JCodesMore/ai-website-cloner-template` foi instalado em `.references/ai-website-cloner-template` e usado como roteiro de inspeção visual, sem copiar seus componentes para o produto.

## Decisões do operador

- Direção: arquitetura visual e ritmo comercial da Aura com identidade premium editorial da Utzig.
- Escopo: landing page completa e home/linktree na mesma entrega, com títulos distintos.
- Novos serviços aprovados: película de vidros/insulfilm, envelopamento, lavagem de chassis, hidratação dos couros e vitrificação dos bancos. Martelinho de ouro e oxi-sanitização foram excluídos explicitamente.
- Preços iniciais aprovados: lavagem detalhada R$ 259,90; higienização interna R$ 600; polimento técnico R$ 700; PPF R$ 499,90; vitrificação R$ 999,90; película de vidros R$ 999,90. Valores aparecem com “A partir de”.
- A frase “mais de 20 serviços” foi reafirmada pelo operador em 2026-09-24. O catálogo público lista 18 serviços em destaque; o inventário dos demais serviços foi explicitamente adiado para outra etapa.
- Nesta publicação os cinco novos produtos e as oito FAQs adicionais são exclusivos do site. Os produtos receberam grants `publishes_to` explícitos para Gallery e herdam somente a capa representativa do grupo ou da campanha, sem imagem direta inventada. O agente receberá esse conteúdo em outra publicação, depois de um canário WA interno.
- Não há avaliações de clientes da Utzig com fonte verificável no material recebido. O layout usa diferenciais e imagens da oficina; depoimentos atribuídos a clientes aguardam fonte real.

## Arquitetura de conteúdo no grafo

| Origem/assunto na referência | Destino Utzig | Nó ou campo autoral |
| --- | --- | --- |
| Hero com promessa, categorias e ação principal | Hero amplo da landing; entrada curta no linktree | `campaign:automotive-detailing.page`, `campaign:home.page`, `copy:hero`, `copy:home-hero` |
| Benefícios de proteção, brilho e valorização | Três objetivos no hero; três diferenciais junto ao especialista | `ribbon_terms`, `copy:benefit-*` |
| Seis serviços principais e preços | Descrições revistas dos serviços já existentes; seis nós Offer | `product:*`, `copy:*`, `offer:*` |
| Serviços complementares | Cinco novos produtos nos grupos existentes | `product:window-film`, `vehicle-wrap`, `chassis-wash`, `leather-conditioning`, `seat-vitrification` |
| Combinação de serviços | Orientação para montar um plano após avaliar o carro | `copy:benefit-choice`, `copy:process-step-diagnosis`, CTA final |
| Processo em três passos | Contato, avaliação, execução/entrega | `copy:process-step-*`, bloco `lp-process` |
| Galeria de trabalhos | Fotos aprovadas da Utzig, sem legendas com marcas/modelos de terceiros | `lp-gallery` e assets ligados à Gallery |
| Prova social e nota Google | Sem publicação até haver fonte Utzig | lacuna de conteúdo; nenhum nó testimonial aprovado |
| Por que escolher a oficina | Cuidado, escolha orientada e conservação | `copy:benefit-*`, bloco do Wilian |
| Localização e contato | Endereço/telefone próprios da Utzig; CTAs recorrentes | `campaign:physical-store`, contatos já ativos, `lp-location`, `lp-final` |
| Perguntas de PPF, vitrificação, película, durabilidade, cuidados, garantia, avaliação e orçamento | Oito FAQs reescritas com respostas próprias, além das quatro existentes | `faq:site:*`, sem edge ao Embedded nesta etapa |

Todos os textos publicados foram reescritos para a Utzig. Números de avaliações, depoimento e contato da Aura não foram atribuídos à Utzig. A seção de processo preserva a avaliação individual; nenhuma foto representativa de grupo se torna evidência direta de produto.

## Design system aplicado

Base visual da Utzig: grafite `#050505`, painel `#151310`, texto claro `#F5F5F5`, cobre `#FF5A00`, linha translúcida `#ffffff24`. Tipografia: Barlow Condensed 600/700 em títulos e Manrope 400/500/600 em corpo. A composição adota hero em duas colunas com retrato de Wilian, faixa de objetivos, capas amplas por grupo, listas expansíveis com preço, processo numerado, galeria real, especialista com diferenciais, FAQ e CTA final. No mobile, seções passam para uma coluna, a galeria vira trilho horizontal e os botões continuam visíveis.

O linktree tem outro H1: “Encontre o cuidado certo para o seu carro.” Sua função é encaminhar rapidamente para catálogo, atendimento e localização. A landing mantém o H1 aprovado: “Mais de 20 serviços que valorizam e deixam o seu carro na melhor versão.” Seu conteúdo permite comparar serviços e benefícios antes de entrar em contato.

## Fonte, limites e verificação

O inventário da Aura cobriu hero, serviços principais e complementares, benefícios, pacotes, galeria, processo, localização, diferenciais e nove perguntas. A implementação incorpora sua função comercial por meio de textos próprios e nós rastreáveis. Contatos, marcas de veículos citadas na galeria, nota Google, números de avaliações e depoimentos da referência ficaram fora do conteúdo público da Utzig.

Verificação: compilador GraphBundle e gate de publicação sem erros; 39 nós e 64 edges adicionados contra a v9 anterior. Os 13 branches do agente, `common_contract`, `branch_contracts` e o conjunto de 40 FAQs elegíveis ao RAG permaneceram iguais à baseline. Frontend build/lint passou; Playwright passou em desktop, dois tamanhos de celular e tablet. O plano, stage e CAS concluíram no workflow `Publish GraphBundle`; publicação ativa `5c5acf16-2e35-4f05-a0cf-2d0ea508a9f5`, v10, checksum `sha256:5745e4795ff78340ca8c87f077fa2dc33dfc30773735f2e4ef5f2186785abcd2`. O payload público confirmou 18 produtos, cinco grupos com capa, seis imagens diretas e seis ofertas iniciais. O frontend `c4eb70a` foi promovido no projeto Vercel `utzig`, deployment `dpl_HNWymF6Pr2YeknZTQaQPkcX8JJtJ`; home e landing foram abertas no navegador em produção.

Pendente de contrato público: a versão de control plane em produção ainda não expõe `media.primary`/`origin` no `/api/menu`, apesar do resolver estar no código-fonte. O frontend publicado usa `assets` diretos e a capa de grupo como fallback visual, sem repetir a imagem em cada serviço. A atualização isolada do control plane não passou na auditoria de release: o checksum local de `brain-contracts` difere do manifesto ativo, e o validador exige checksum idêntico nos três consumidores. Não forçar deploy de runtime/transport nem alterar manualmente a VPS para contornar o gate; resolver a compatibilidade do manifesto em uma release própria antes de declarar `media.primary` entregue.
